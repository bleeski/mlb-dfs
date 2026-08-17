from __future__ import annotations

import csv
import inspect
import datetime as dtmod
import json
import math
import os
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[1]

from mlb_engine.optimize import optimizer_v3 as opt

from mlb_engine.pipeline import execution_pipeline as epi

from mlb_engine.pipeline.build_state_manager import (
    create_run, promote_run, register_artifact, sha256_file,
    slate_context_refresh_plan, update_run_certification,
)
from mlb_engine.allocate.contest_allocator import (
    ContestCard, _entry_candidate_compatible, candidate_reuse_cap_rungs,
    contest_cards_from_reserved_grid, default_candidate_reuse_cap,
    resolve_candidate_bank_plan, resolve_phase0_mode, select_and_assign_entries,
    select_and_assign_portfolio, uncovered_locked_team_players,
)
from mlb_engine.entries.dk_entries_manager import (
    ROSTER_SLOTS, fixed_portfolio_exposure, parse_dk_entry_rows,
    reconcile_entries_against_assignments,
    validate_dk_entries_file, validate_template_preservation,
    validate_upload_ready_gates,
)
from mlb_engine.pipeline.execution_pipeline import promote_deferred_run, run_initial_build, run_late_swap, run_slate, normalize_posture
from mlb_engine.intake import platoon_order_adapter as poa

from mlb_engine.swap.late_swap_manager import (
    PlayerLineupStatus, freeze_lineup_state, late_swap_certification,
    partial_rebuild_constraints,
)
from mlb_engine.projections.projection_builder import (
    apply_xwoba_correction, build_projections, build_xwoba_corrections,
    load_savant_expected_stats, refresh_confirmed_lineups,
)
from mlb_engine.intake.slate_intake_manager import material_weather_adjustments, validate_slate_context_packet
from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv, slate_clock
from mlb_engine.intake.live_data_adapters import build_status_map_from_lineups_feed
from mlb_engine.optimize import bank_cache
from mlb_engine.allocate.contest_allocator import ENTRY_ROSTER_SLOTS, _candidate_ordered_roster

NOW = datetime(2026, 6, 11, 17, 0, tzinfo=timezone.utc)
TS = NOW.isoformat()
HEADER = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", "P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "", "Instructions"]


def venue(roof_type="outdoor", weather_required=True, sensitivity="high", threshold=8):
    return {
        "venue": "Test Park", "roof_type": roof_type,
        "weather_required": weather_required, "wind_sensitivity": sensitivity,
        "wind_min_speed_mph": threshold,
    }


def game():
    return {"game_id": "AAA@BBB", "away_team": "AAA", "home_team": "BBB", "game_date": "2026-06-11"}


def salary_rows():
    rows = [
        ["P", "Pitcher A (10001)", "Pitcher A", "10001", "P", "9000", "AAA@BBB 06/11/2026 01:00PM ET", "AAA"],
        ["P", "Pitcher C (10002)", "Pitcher C", "10002", "P", "8800", "CCC@DDD 06/11/2026 01:00PM ET", "CCC"],
    ]
    ids = 11000
    for team, opp_game in [("AAA", "AAA@BBB 06/11/2026 01:00PM ET"), ("CCC", "CCC@DDD 06/11/2026 01:00PM ET")]:
        for pos, suffix in [("C", "C"), ("1B", "1B"), ("2B", "2B"), ("3B", "3B"), ("SS", "SS"), ("OF", "OF1"), ("OF", "OF2"), ("OF", "OF3")]:
            ids += 1
            rows.append([pos, f"{team} {suffix} ({ids})", f"{team} {suffix}", str(ids), pos, "3000", opp_game, team])
    return rows


def write_salary(path: Path) -> dict[str, str]:
    header = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary", "Game Info", "TeamAbbrev"]
    rows = salary_rows()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(header); writer.writerows(rows)
    lookup = {row[2]: row[3] for row in rows}
    return lookup


def legal_rosters(ids: dict[str, str]):
    r1 = [
        ids["Pitcher A"], ids["Pitcher C"], ids["AAA C"], ids["CCC 1B"],
        ids["AAA 2B"], ids["CCC 3B"], ids["AAA SS"], ids["AAA OF1"],
        ids["CCC OF1"], ids["CCC OF2"],
    ]
    r2 = [
        ids["Pitcher A"], ids["Pitcher C"], ids["CCC C"], ids["AAA 1B"],
        ids["CCC 2B"], ids["AAA 3B"], ids["CCC SS"], ids["CCC OF3"],
        ids["AAA OF2"], ids["AAA OF3"],
    ]
    return r1, r2


def write_entries(path: Path, rosters=None, contest_ids=None):
    rosters = rosters or [None, None]
    contest_ids = contest_ids or ["900", "900"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(HEADER)
        for i, roster in enumerate(rosters, start=1):
            writer.writerow([str(5000 + i), "Test WTA", contest_ids[i - 1], "$1", *((roster or [""] * 10)), "", ""])


def candidate(candidate_id, roster, score, primary="AAA"):
    return {
        "candidate_id": candidate_id,
        "lineup_ids": roster,
        "player_ids": roster,
        "sp_ids": roster[:2],
        "primary_stack": primary,
        "objective": score,
        "contest_fit_score": score,
    }


def projection_frame(ids: dict[str, str]) -> pd.DataFrame:
    rows = []
    salary_path_dummy = None
    for raw in salary_rows():
        position, _, name, pid, roster_pos, salary, game_info, team = raw
        away, home = game_info.split()[0].split("@")
        opponent = home if team == away else away
        rows.append({
            "Player_ID": pid, "Name": name, "Team": team, "Opponent": opponent,
            "Position": roster_pos, "Salary": float(salary), "Game_ID": f"{away}@{home}",
            "Floor": 5.0 if position != "P" else 12.0,
            "Ceiling": 12.0 if position != "P" else 25.0,
            "Excluded": False, "Locked": False,
        })
    return pd.DataFrame(rows)


def diverse_projection_frame() -> pd.DataFrame:
    """Four pitchers on four teams (six SP pairs) plus four eight-hitter teams.

    Rich enough to exercise SP-pair and stack coverage in the diverse candidate
    bank, unlike the two-pitcher default fixture which admits a single SP pair.
    """
    game = {"T1": "T1@T2", "T2": "T1@T2", "T3": "T3@T4", "T4": "T3@T4"}
    opp = {"T1": "T2", "T2": "T1", "T3": "T4", "T4": "T3"}
    rows = []
    pid = 20000
    for team in ("T1", "T2", "T3", "T4"):
        pid += 1
        rows.append({
            "Player_ID": str(pid), "Name": f"P_{team}", "Team": team, "Opponent": opp[team],
            "Position": "P", "Salary": 9000.0, "Game_ID": game[team],
            "Floor": 12.0, "Ceiling": 25.0 + (pid % 5), "Excluded": False, "Locked": False,
        })
    base = 21000
    for team in ("T1", "T2", "T3", "T4"):
        for pos in ("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"):
            base += 1
            rows.append({
                "Player_ID": str(base), "Name": f"{team}_{pos}_{base}", "Team": team,
                "Opponent": opp[team], "Position": pos, "Salary": 3000.0, "Game_ID": game[team],
                "Floor": 5.0, "Ceiling": 10.0 + (base % 7), "Excluded": False, "Locked": False,
            })
    return pd.DataFrame(rows)


def _entry_reqs(n, contest_id="900", shape="large_wta"):
    return [{"entry_id": str(i), "contest_id": contest_id, "contest_shape": shape} for i in range(n)]


def pool_salary_csv(path: Path, game_dt_et: str = "07/10/2026 07:05PM ET",
                    postponed_teams: tuple = ()) -> None:
    """Four-team salary file for pool-contract tests: per team, 9 lineup-caliber
    hitters, 4 bench bats, 1 probable SP, and 3 relievers (68 rows total).
    Teams named in ``postponed_teams`` get DK's literal 'Postponed' as their
    whole Game Info cell, the shape the 2026-07-28 incident arrived in (R26)."""
    header = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary",
              "Game Info", "AvgPointsPerGame", "TeamAbbrev"]
    games = {"T1": "T1@T2", "T2": "T1@T2", "T3": "T3@T4", "T4": "T3@T4"}
    hit_pos = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "1B"]
    rows = []
    pid = 30000
    for team in ("T1", "T2", "T3", "T4"):
        gi = "Postponed" if team in postponed_teams else f"{games[team]} {game_dt_et}"
        for i in range(9):
            pid += 1
            rows.append([hit_pos[i], f"{team} Hitter{i+1} ({pid})", f"{team} Hitter{i+1}",
                         pid, hit_pos[i], 3200 + i * 100, gi, 8.0 + i * 0.3, team])
        for i in range(4):
            pid += 1
            rows.append(["OF", f"{team} Bench{i+1} ({pid})", f"{team} Bench{i+1}",
                         pid, "OF", 2400, gi, 3.0, team])
        pid += 1
        rows.append(["P", f"{team} Ace ({pid})", f"{team} Ace", pid, "P", 9200, gi, 17.5, team])
        for i in range(3):
            pid += 1
            rows.append(["P", f"{team} Pen{i+1} ({pid})", f"{team} Pen{i+1}",
                         pid, "P", 4500, gi, 5.0, team])
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def pool_lineups_feed(lock_utc: str = "2026-07-10T23:05:00Z", *, t4_confirmed: bool = False,
                      drop_t4_probable: bool = False, postpone_game2: bool = False) -> dict:
    def side(team, confirmed=True, probable=True):
        entry = {"team_abbrev": team,
                 "lineup_status": "confirmed" if confirmed else "tbd",
                 "lineup": []}
        if probable:
            entry["probable_pitcher"] = {"name": f"{team} Ace", "hand": "R", "id": 600000}
        if confirmed:
            for i in range(9):
                entry["lineup"].append({"name": f"{team} Hitter{i+1}", "order": i + 1,
                                        "bat_side": "L" if i % 2 else "R"})
        return entry

    return {"date": "2026-07-10", "fetched_at": "2026-07-10T20:00:00Z", "games": [
        {"game_pk": 1, "venue": "Park A", "status": "Scheduled", "game_date_utc": lock_utc,
         "away": side("T1"), "home": side("T2")},
        {"game_pk": 2, "venue": "Park B",
         "status": "Postponed" if postpone_game2 else "Scheduled", "game_date_utc": lock_utc,
         "away": side("T3"),
         "home": side("T4", confirmed=t4_confirmed, probable=not drop_t4_probable)},
    ]}


def pool_platoon_json() -> dict:
    return {"collected_date": "2026-07-10", "teams": [
        {"abbrev": "T4", "page_updated": "2026-07-10",
         "vs_RHP": [{"player": f"T4 Hitter{i+1}", "slot": i + 1} for i in range(9)],
         "vs_LHP": [{"player": f"T4 Hitter{i+1}", "slot": i + 1} for i in range(9)]}]}


class ContextTests(unittest.TestCase):
    def test_medium_delay_is_pitcher_only(self):
        packet = {"games": [{"game_id": "AAA@BBB", "weather": {"delay_risk": "medium", "postponement_risk": "low"}}]}
        adjustment = material_weather_adjustments(packet)
        self.assertEqual(adjustment["pitcher_delay_factors"]["AAA@BBB"], 0.95)
        self.assertEqual(adjustment["game_exposure_caps"], {})

    def test_retractable_roof_unknown_blocks(self):
        packet = {"games": [{"game_id": "AAA@BBB", "weather": {}, "odds": {"total": 8.5, "source": "test", "fetched_at": TS}}]}
        result = validate_slate_context_packet(packet, [game()], {"BBB": venue("retractable", False, "none", 999)}, now=NOW)
        self.assertFalse(result["passed"])
        self.assertTrue(result["roof_gate"]["errors"])

    def test_context_refresh_reuses_clear_weather(self):
        packet = {"games": [{"game_id": "A@B", "weather_required": True, "roof_status_required": False, "weather": {"delay_risk": "low", "postponement_risk": "low", "fetched_at": TS}, "odds": {"fetched_at": TS}}]}
        self.assertIn("A@B", slate_context_refresh_plan(packet, now_iso=TS)["reuse_cached_weather_games"])


class ProjectionAndOptimizerTests(unittest.TestCase):
    def test_projection_formula_and_refresh(self):
        source = [{
            "Player_ID": "1", "Name": "A", "Team": "AAA", "Opponent": "BBB",
            "Position": "OF", "Salary": 4000, "Game_ID": "AAA@BBB",
            "Base": 10, "F1": 1.1, "F2": 1.0, "F3": 1.2, "F4": 0.9, "F5": 1.05,
        }]
        projections, audit = build_projections(source, "emergency_proxy")
        expected = 10 * 1.1 * 1.0 * 1.2 * 0.9 * 1.05
        self.assertAlmostEqual(projections.iloc[0]["Base_Projection"], expected)
        refreshed, delta = refresh_confirmed_lineups(projections, {"1": 1}, starter_player_ids={"1"})
        self.assertGreater(refreshed.iloc[0]["Ceiling"], projections.iloc[0]["Ceiling"])
        self.assertEqual(len(delta), 1)

    def test_exact_slot_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = write_salary(Path(tmp) / "salary.csv")
            lineup, _ = opt.build_single_lineup(projection_frame(ids), locked_slot_assignments={"C": ids["AAA C"]})
            self.assertIsNotNone(lineup)
            locked = lineup[lineup["Assigned_Slot"] == "C"].iloc[0]
            self.assertEqual(str(locked["Player_ID"]), ids["AAA C"])

    def test_optional_projection_fields_do_not_block(self):
        frame = projection_frame({})
        self.assertTrue(opt.validate_projection_schema(frame)["passed"])


class EntryAndAllocationTests(unittest.TestCase):
    def test_duplicate_headers_parse_positionally(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entries.csv"
            write_entries(path)
            rows = parse_dk_entry_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0].roster_cells), 10)

    def test_entry_level_locks_choose_compatible_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = write_salary(Path(tmp) / "salary.csv")
            r1, r2 = legal_rosters(ids)
            result = select_and_assign_entries(
                [candidate("A", r1, 100), candidate("B", r2, 99, "CCC")],
                [
                    {"entry_id": "1", "contest_id": "x", "contest_shape": "large_wta", "locked_slot_assignments": {"C": r1[2]}},
                    {"entry_id": "2", "contest_id": "x", "contest_shape": "large_wta", "locked_slot_assignments": {"C": r2[2]}},
                ],
                {"max_shared_players": 9},
            )
            self.assertTrue(result["passed"])
            chosen = {row["entry_id"]: row["candidate_id"] for row in result["assignments"]}
            self.assertEqual(chosen, {"1": "A", "2": "B"})

    def test_locked_team_cannot_be_introduced(self):
        roster_bad = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "X"]
        roster_good = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "B7"]
        team_map = {pid: "CCC" for pid in set(roster_bad + roster_good)}
        team_map.update({"L": "AAA", "X": "AAA"})
        result = select_and_assign_entries(
            [candidate("bad", roster_bad, 100), candidate("good", roster_good, 99)],
            [{
                "entry_id": "1", "contest_id": "x", "contest_shape": "large_wta",
                "locked_slot_assignments": {"P1": "L"}, "locked_player_ids": ["L"],
                "excluded_new_teams": ["AAA"], "player_team_by_id": team_map,
            }],
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["assignments"][0]["candidate_id"], "good")

    def test_a_pid_the_team_map_does_not_cover_is_excluded_not_admitted(self):
        """R72(i): per-player fail-open on the locked-game exclusion.

        `team_by_player.get(pid) in excluded_new_teams` is False for an UNMAPPED
        pid, because .get returns None, so every player the map did not cover
        walked through the one test that keeps a locked game closed. Partial
        coverage is the real case: a game absent from the lineups feed leaves its
        platoon-filled players with no PlayerLineupStatus, hence absent from
        player_team_by_id, and its team absent from locked_teams. F15's sibling
        guard only fails closed when the map is empty ENTIRELY, so this shape ran
        straight through it.
        """
        roster_bad = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "X"]
        roster_good = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "B7"]
        # X is the uncovered pid: present in a candidate, absent from the map.
        team_map = {pid: "CCC" for pid in set(roster_bad + roster_good)}
        team_map.update({"L": "AAA"})
        del team_map["X"]
        requirement = {
            "entry_id": "1", "contest_id": "x", "contest_shape": "large_wta",
            "locked_slot_assignments": {"P1": "L"}, "locked_player_ids": ["L"],
            "excluded_new_teams": ["AAA"], "player_team_by_id": team_map,
        }
        result = select_and_assign_entries(
            [candidate("bad", roster_bad, 100), candidate("good", roster_good, 99)],
            [dict(requirement)],
        )
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(result["assignments"][0]["candidate_id"], "good",
                         "the candidate carrying an unclassifiable pid must not "
                         "outrank the one that is fully covered")
        # The locked player himself stays admissible on his own locked team.
        self.assertTrue(_entry_candidate_compatible(
            candidate("good", roster_good, 99), dict(requirement)))
        self.assertFalse(_entry_candidate_compatible(
            candidate("bad", roster_bad, 100), dict(requirement)))

    def test_a_starved_entry_names_the_uncovered_players_as_the_cause(self):
        """R72(i)'s other half: fail-closed must not starve an entry silently.

        With every candidate carrying an uncovered pid, the entry has no
        compatible candidate — correct, but "no compatible candidate for Entry ID
        1" reads as a strategy dead end rather than the stale feed it is."""
        roster = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "X"]
        team_map = {pid: "CCC" for pid in roster}
        team_map.update({"L": "AAA"})
        del team_map["X"]
        requirement = {
            "entry_id": "1", "contest_id": "x", "contest_shape": "large_wta",
            "locked_slot_assignments": {"P1": "L"}, "locked_player_ids": ["L"],
            "excluded_new_teams": ["AAA"], "player_team_by_id": team_map,
        }
        result = select_and_assign_entries([candidate("only", roster, 100)],
                                           [dict(requirement)])
        self.assertFalse(result["passed"])
        message = result["errors"][0]
        self.assertIn("no compatible candidate for Entry ID 1", message)
        self.assertIn("player_team_by_id", message)
        self.assertIn("X", message)
        self.assertIn("Refresh the lineups feed", message)
        self.assertEqual(
            uncovered_locked_team_players([candidate("only", roster, 100)], requirement),
            ["X"])
        # No excluded_new_teams means no locked game, so nothing is uncovered.
        self.assertEqual(uncovered_locked_team_players(
            [candidate("only", roster, 100)],
            {k: v for k, v in requirement.items() if k != "excluded_new_teams"}), [])

    def test_exact_entry_reconciliation_catches_swapped_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = write_salary(root / "salary.csv")
            r1, r2 = legal_rosters(ids)
            actual = root / "entries.csv"
            write_entries(actual, [r1, r2])
            intended = [
                {"entry_id": "5001", "lineup_ids": r2},
                {"entry_id": "5002", "lineup_ids": r1},
            ]
            self.assertFalse(reconcile_entries_against_assignments(intended, actual)["passed"])

    def test_export_exposure_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            r1, _ = legal_rosters(ids)
            entries = root / "entries.csv"
            write_entries(entries, [r1, r1, r1], ["1", "2", "3"])
            result = validate_dk_entries_file(entries, salary_csv_path=salary, portfolio_controls={"max_player_exposure_pct": 0.45})
            self.assertFalse(result["portfolio_caps_passed"])
            self.assertFalse(result["passed"])

    def test_completed_template_row_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = write_salary(root / "salary.csv")
            r1, r2 = legal_rosters(ids)
            before = root / "before.csv"; after = root / "after.csv"
            write_entries(before, [r1, None]); write_entries(after, [r2, None])
            self.assertFalse(validate_template_preservation(before, after)["passed"])

    def test_joint_wrapper_applies_player_cap(self):
        cards = [ContestCard("1", "WTA 1", "wta", 100, 2, 1, 100, reserved_entries=2), ContestCard("2", "WTA 2", "wta", 100, 2, 1, 100, reserved_entries=2)]
        candidates = []
        for i in range(8):
            players = (["X"] if i < 3 else [f"U{i}"]) + [f"P{i}_{j}" for j in range(9)]
            candidates.append({"candidate_id": f"C{i}", "player_ids": players, "lineup_ids": players, "sp_ids": players[:2], "primary_stack": f"T{i}", "objective": 100 - i})
        result = select_and_assign_portfolio(candidates, cards, {"1": 2, "2": 2}, max_candidate_reuse=1)
        self.assertTrue(result["selection_certified"])
        self.assertEqual(result["allocation_method"], "scipy_milp_entry_level")


class RunProvenanceTests(unittest.TestCase):
    def test_same_timestamp_runs_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = create_run(tmp, "initial_build", now=NOW)
            second = create_run(tmp, "initial_build", now=NOW)
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertTrue(Path(first["run_dir"]).exists())
            self.assertTrue(Path(second["run_dir"]).exists())

    def test_stale_diagnostics_hash_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = create_run(tmp, "initial_build")
            run_dir = Path(run["run_dir"])
            export = run_dir / "final" / "DKEntries.csv"; export.write_text("x", encoding="utf-8")
            diagnostics = run_dir / "final" / "diagnostics.json"
            diagnostics.write_text(json.dumps({"diagnostic_source_file": "final/DKEntries.csv", "diagnostic_source_sha256": "wrong"}), encoding="utf-8")
            register_artifact(run_dir, export, "dk_export"); register_artifact(run_dir, diagnostics, "diagnostics")
            update_run_certification(run_dir, {"workflow_valid": True, "selection_certified": True, "allocation_certified": True})
            self.assertFalse(promote_run(run_dir)["passed"])

    def test_caller_cannot_assert_post_export_gates(self):
        gates = {name: True for name in [
            "salary_gate_passed", "entry_grid_gate_passed", "lineup_gate_passed",
            "pitcher_audit_gate_passed", "weather_gate_passed", "odds_gate_passed",
            "projection_schema_gate_passed", "optimizer_gate_passed", "selection_certified",
        ]}
        gates["workflow_valid"] = True
        self.assertFalse(validate_upload_ready_gates(gates)["passed"])

    def test_validate_only_never_certifies(self):
        result = late_swap_certification("validate_only")
        self.assertFalse(result["selection_certified"])
        self.assertFalse(result["allocation_certified"])
        self.assertFalse(result["late_swap_optimization_performed"])


class PipelineTests(unittest.TestCase):
    def workflow_gates(self):
        return {
            "salary_gate_passed": True, "entry_grid_gate_passed": True,
            "lineup_gate_passed": True, "pitcher_audit_gate_passed": True,
            "weather_gate_passed": True, "odds_gate_passed": True,
            "projection_schema_gate_passed": True, "optimizer_gate_passed": True,
        }

    def test_end_to_end_initial_and_late_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            r1, r2 = legal_rosters(ids)
            candidates = [candidate("A", r1, 100), candidate("B", r2, 99, "CCC")]
            requirements = [
                {"entry_id": "5001", "contest_id": "900", "contest_name": "Test WTA", "contest_shape": "large_wta"},
                {"entry_id": "5002", "contest_id": "900", "contest_name": "Test WTA", "contest_shape": "large_wta"},
            ]
            initial = run_initial_build(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections=projection_frame(ids), candidates=candidates,
                entry_requirements=requirements, workflow_gates=self.workflow_gates(),
                portfolio_controls={"max_player_exposure_pct": 1.0, "max_pitcher_exposure_pct": 1.0, "max_primary_stack_exposure_pct": 1.0, "max_sp_pair_repetition": 2, "max_shared_players": 9},
            )
            self.assertTrue(initial["passed"], initial.get("errors"))
            self.assertTrue(Path(initial["output_path"]).exists())
            diagnostics = json.loads(Path(initial["diagnostics_path"]).read_text())
            self.assertEqual(diagnostics["diagnostic_source_sha256"], sha256_file(initial["output_path"]))

            future = NOW + timedelta(hours=2)
            statuses = {}
            for pid in ids.values():
                statuses[pid] = PlayerLineupStatus(pid, pid, "AAA", "AAA@BBB", future, "Confirmed_Starter")
            late = run_late_swap(
                runs_root=root / "runs", current_entries_csv=initial["output_path"],
                status_by_player_id=statuses, as_of=NOW, salary_csv=salary,
                projections=projection_frame(ids), candidates=candidates,
                workflow_gates=self.workflow_gates(),
                portfolio_controls={"max_player_exposure_pct": 1.0, "max_pitcher_exposure_pct": 1.0, "max_primary_stack_exposure_pct": 1.0, "max_sp_pair_repetition": 2, "max_shared_players": 9},
            )
            self.assertTrue(late["passed"], late.get("errors"))
            self.assertTrue(late["late_swap_optimization_performed"])
            self.assertTrue(late["selection_certified"])

    def test_late_swap_locked_slot_contract(self):
        lock = NOW - timedelta(minutes=1)
        future = NOW + timedelta(hours=1)
        statuses = {
            "1": PlayerLineupStatus("1", "A", "AAA", "AAA@BBB", lock, "Confirmed_Starter"),
            "2": PlayerLineupStatus("2", "B", "CCC", "CCC@DDD", future, "Confirmed_Starter"),
        }
        state = freeze_lineup_state("c", "e", "l", ["1", "2"], statuses, NOW, roster_slots=["P1", "P2"])
        contract = partial_rebuild_constraints(state)
        self.assertEqual(contract["locked_slot_assignments"], {"P1": "1"})
        self.assertIn("immutable", contract["rule"])


class ExistingBehaviorTests(unittest.TestCase):
    def test_reserved_grid_bank_uses_unique_demand(self):
        plan = resolve_candidate_bank_plan(32, contest_entry_counts=[7, 7, 6, 5, 4, 3], contest_shapes=["wta_ticket_satellite"], max_candidate_reuse=3, runtime_context="chatgpt")
        self.assertLessEqual(plan["actual_bank_target"], 24)
        self.assertGreaterEqual(plan["unique_lineup_need"], 11)

    def test_declared_wta_suppresses_ticket_gaps(self):
        summary = {"contests": [{"contest_id": "1", "contest_name": "Satellite", "reserved_entries": 2, "entry_fee": 0.25, "inferred_type": "satellite", "decision_critical_gaps": ["ticket_count", "ticket_value"]}]}
        cards = contest_cards_from_reserved_grid(summary, declared_contest_type="wta")
        self.assertEqual(cards[0].contest_type, "wta")
        self.assertEqual(cards[0].decision_critical_gaps, [])
        self.assertEqual(resolve_phase0_mode(summary), "reserved_entry_execution")




# ---------------------------------------------------------------------------
# v2.16.0 regression and new-capability tests
# ---------------------------------------------------------------------------
import shutil

import numpy as np

from mlb_engine.entries.dk_entries_manager import populate_dk_entries_template
from mlb_engine.swap.late_swap_manager import build_entry_requirements
from mlb_engine.intake.slate_intake_manager import (
    compute_f5_factor, load_f5_park_factors, load_f5_weather_adjustments,
)
from mlb_engine.intake import live_data_adapters as lda
from mlb_engine.intake import slate_intake_manager as sim



def pipeline_controls():
    return {
        "max_player_exposure_pct": 1.0, "max_pitcher_exposure_pct": 1.0,
        "max_primary_stack_exposure_pct": 1.0, "max_sp_pair_repetition": 2,
        "max_candidate_reuse": 1,
    }


def build_promoted_initial(root: Path):
    salary = root / "salary.csv"; ids = write_salary(salary)
    entries = root / "DKEntries.csv"
    write_entries(entries, contest_ids=["900", "901"])
    r1, r2 = legal_rosters(ids)
    candidates = [candidate("A", r1, 100), candidate("B", r2, 99, "CCC")]
    requirements = [
        {"entry_id": "5001", "contest_id": "900", "contest_name": "Test WTA", "contest_shape": "large_wta"},
        {"entry_id": "5002", "contest_id": "901", "contest_name": "Test WTA", "contest_shape": "large_wta"},
    ]
    gates = {
        "salary_gate_passed": True, "entry_grid_gate_passed": True,
        "lineup_gate_passed": True, "pitcher_audit_gate_passed": True,
        "weather_gate_passed": True, "odds_gate_passed": True,
        "projection_schema_gate_passed": True, "optimizer_gate_passed": True,
    }
    initial = run_initial_build(
        runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
        projections=projection_frame(ids), candidates=candidates,
        entry_requirements=requirements, workflow_gates=gates,
        portfolio_controls=pipeline_controls(),
    )
    return salary, ids, entries, candidates, gates, initial


def future_statuses(ids):
    future = NOW + timedelta(hours=2)
    return {
        pid: PlayerLineupStatus(pid, pid, "AAA", "AAA@BBB", future, "Confirmed_Starter")
        for pid in ids.values()
    }


class FailClosedLateSwapTests(unittest.TestCase):
    def test_missing_lock_status_errors_by_default(self):
        statuses = {"1": PlayerLineupStatus("1", "A", "AAA", "AAA@BBB", NOW + timedelta(hours=1), "Confirmed_Starter")}
        with self.assertRaises(ValueError):
            freeze_lineup_state("c", "e", "l", ["1", "2"], statuses, NOW, roster_slots=["P1", "P2"])

    def test_missing_lock_status_can_freeze_instead(self):
        statuses = {"1": PlayerLineupStatus("1", "A", "AAA", "AAA@BBB", NOW + timedelta(hours=1), "Confirmed_Starter")}
        state = freeze_lineup_state(
            "c", "e", "l", ["1", "2"], statuses, NOW, roster_slots=["P1", "P2"],
            missing_status_policy="treat_as_locked",
        )
        self.assertEqual(state.locked_slot_assignments, {"P2": "2"})
        self.assertEqual(state.unlocked_player_ids, ["1"])

    def test_authorized_entry_ids_scope_and_unknown_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = write_salary(root / "salary.csv")
            r1, r2 = legal_rosters(ids)
            entries = root / "entries.csv"
            write_entries(entries, [r1, r2])
            statuses = future_statuses(ids)
            requirements = build_entry_requirements(entries, statuses, NOW, authorized_entry_ids=["5002"])
            self.assertEqual([req["entry_id"] for req in requirements], ["5002"])
            with self.assertRaises(ValueError):
                build_entry_requirements(entries, statuses, NOW, authorized_entry_ids=["9999"])
            with self.assertRaises(ValueError):
                build_entry_requirements(entries, statuses, NOW, authorized_entry_ids=[])

    def test_fully_locked_entry_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = write_salary(root / "salary.csv")
            r1, _ = legal_rosters(ids)
            entries = root / "entries.csv"
            write_entries(entries, [r1, None])
            past = NOW - timedelta(hours=1)
            statuses = {pid: PlayerLineupStatus(pid, pid, "AAA", "AAA@BBB", past, "Confirmed_Starter") for pid in ids.values()}
            requirements = build_entry_requirements(entries, statuses, NOW)
            self.assertEqual([req["entry_id"] for req in requirements], ["5002"])


class ProvenanceHardeningTests(unittest.TestCase):
    def test_tampered_parent_blocks_late_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, ids, entries, candidates, gates, initial = build_promoted_initial(root)
            self.assertTrue(initial["passed"], initial.get("errors"))
            with open(initial["output_path"], "a", encoding="utf-8") as handle:
                handle.write("tamper")
            with self.assertRaises(RuntimeError):
                run_late_swap(
                    runs_root=root / "runs", current_entries_csv=initial["output_path"],
                    status_by_player_id=future_statuses(ids), as_of=NOW, salary_csv=salary,
                    projections=projection_frame(ids), candidates=candidates,
                    workflow_gates=gates, portfolio_controls=pipeline_controls(),
                )

    def test_validate_only_creates_diagnostic_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, ids, _, _, _, initial = build_promoted_initial(root)
            self.assertTrue(initial["passed"], initial.get("errors"))
            result = run_late_swap(
                runs_root=root / "runs", current_entries_csv=initial["output_path"],
                status_by_player_id=future_statuses(ids), as_of=NOW,
                late_swap_mode="validate_only",
            )
            self.assertTrue(result["passed"])
            self.assertTrue(result["run_id"])
            self.assertFalse(result["selection_certified"])
            manifest = json.loads((Path(result["run_dir"]) / "manifest.json").read_text())
            self.assertEqual(manifest["mode"], "validate_only")
            self.assertEqual(manifest["status"], "diagnostic")
            self.assertFalse(manifest["certification"]["workflow_valid"])
            self.assertTrue(Path(result["requirements_path"]).exists())

    def test_blocked_allocation_marks_run_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            gates = {name: True for name in (
                "salary_gate_passed", "entry_grid_gate_passed", "lineup_gate_passed",
                "pitcher_audit_gate_passed", "weather_gate_passed", "odds_gate_passed",
                "projection_schema_gate_passed", "optimizer_gate_passed",
            )}
            result = run_initial_build(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections=projection_frame(ids), candidates=[],
                entry_requirements=[{"entry_id": "5001", "contest_id": "900", "contest_name": "Test WTA", "contest_shape": "large_wta"}],
                workflow_gates=gates, portfolio_controls=pipeline_controls(),
            )
            self.assertFalse(result["passed"])
            manifest = json.loads((Path(result["run_dir"]) / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "blocked")

    def test_unauthorized_entry_preserved_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, ids, entries, candidates, gates, initial = build_promoted_initial(root)
            self.assertTrue(initial["passed"], initial.get("errors"))
            before = {row.entry_id: row.raw_row for row in parse_dk_entry_rows(initial["output_path"])}
            r1, _ = legal_rosters(ids)
            r3 = list(r1[:-1]) + [ids["CCC OF3"]]
            late = run_late_swap(
                runs_root=root / "runs", current_entries_csv=initial["output_path"],
                status_by_player_id=future_statuses(ids), as_of=NOW, salary_csv=salary,
                projections=projection_frame(ids), candidates=[candidate("N", r3, 200)],
                workflow_gates=gates, portfolio_controls=pipeline_controls(),
                authorized_entry_ids=["5002"],
            )
            self.assertTrue(late["passed"], late.get("errors"))
            after = {row.entry_id: row.raw_row for row in parse_dk_entry_rows(late["output_path"])}
            self.assertEqual(before["5001"], after["5001"])
            self.assertNotEqual(before["5002"], after["5002"])
            self.assertIn(ids["CCC OF3"], after["5002"])
            self.assertIn("parent_export_sha256", late)
            self.assertTrue(late["current_matches_parent_export"])

    def test_populate_wrapper_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = write_salary(root / "salary.csv")
            template = root / "template.csv"; write_entries(template)
            output = root / "out.csv"; output.write_text("SENTINEL", encoding="utf-8")
            result = populate_dk_entries_template(template, [], output, {})
            self.assertFalse(result["passed"])
            self.assertIn("already exists", result["errors"][0])
            self.assertEqual(output.read_text(encoding="utf-8"), "SENTINEL")


class StrictProjectionTests(unittest.TestCase):
    def test_ceiling_below_floor_raises(self):
        source = [{
            "Player_ID": "1", "Name": "A", "Team": "AAA", "Opponent": "BBB",
            "Position": "OF", "Salary": 4000, "Game_ID": "AAA@BBB",
            "Base": 10, "F1": 1.0, "F2": 1.0, "F3": 1.0, "F4": 1.0, "F5": 1.0,
            "Floor": 10.0, "Ceiling": 5.0,
        }]
        with self.assertRaises(ValueError):
            build_projections(source, "emergency_proxy")

    def test_per_team_confirmed_refresh_and_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            source = []
            for name in ("AAA C", "AAA 1B", "CCC 1B"):
                team = name.split()[0]
                source.append({
                    "Player_ID": ids[name], "Name": name, "Team": team,
                    "Opponent": "BBB" if team == "AAA" else "DDD",
                    "Position": name.split()[1], "Salary": 3000,
                    "Game_ID": "AAA@BBB" if team == "AAA" else "CCC@DDD",
                    "Base": 8, "F1": 1.0, "F2": 1.0, "F3": 1.0, "F4": 1.0, "F5": 1.0,
                })
            frame, _ = build_projections(source, "emergency_proxy")
            starters = {ids["AAA C"]}
            refreshed, _ = refresh_confirmed_lineups(
                frame, {ids["AAA C"]: 1}, starter_player_ids=starters, confirmed_teams=["AAA"],
            )
            by_id = refreshed.set_index("Player_ID")
            self.assertTrue(bool(by_id.loc[ids["AAA 1B"], "Excluded"]))
            self.assertFalse(bool(by_id.loc[ids["CCC 1B"], "Excluded"]))
            r1, _ = legal_rosters(ids)
            entries = root / "entries.csv"
            write_entries(entries, [r1])
            result = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                confirmed_hitter_ids={pid for name, pid in ids.items() if name.startswith("AAA") and "Pitcher" not in name},
                confirmed_teams=["AAA"],
            )
            self.assertTrue(result["passed"], result["errors"])
            strict = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                confirmed_hitter_ids={pid for name, pid in ids.items() if name.startswith("AAA") and "Pitcher" not in name},
            )
            self.assertFalse(strict["passed"])


class DeterministicF5Tests(unittest.TestCase):
    def test_wind_band_delay_and_postponement(self):
        parks = load_f5_park_factors("data/reference/f5_park_factors.csv")
        adjustments = load_f5_weather_adjustments("data/reference/f5_weather_adjustments.csv")
        result = compute_f5_factor(
            "Great American Ball Park",
            {"wind_status": "out", "wind_speed_mph": 15, "delay_risk": "medium", "postponement_risk": "medium"},
            parks, adjustments, wind_threshold_mph=8,
        )
        self.assertAlmostEqual(result["hitter_f5"], 1.02 * 1.030, places=6)
        self.assertAlmostEqual(result["pitcher_f5"], 0.970 * 0.950, places=6)
        self.assertEqual(result["game_exposure_cap"], 0.25)
        self.assertFalse(result["exclude_game"])

    def test_wind_below_threshold_or_cross_is_neutral(self):
        parks = load_f5_park_factors("data/reference/f5_park_factors.csv")
        adjustments = load_f5_weather_adjustments("data/reference/f5_weather_adjustments.csv")
        below = compute_f5_factor(
            "Great American Ball Park",
            {"wind_status": "out", "wind_speed_mph": 5, "delay_risk": "none", "postponement_risk": "none"},
            parks, adjustments, wind_threshold_mph=8,
        )
        self.assertAlmostEqual(below["hitter_f5"], 1.02, places=6)
        self.assertAlmostEqual(below["pitcher_f5"], 1.0, places=6)
        cross = compute_f5_factor(
            "Great American Ball Park",
            {"wind_status": "cross", "wind_speed_mph": 20, "delay_risk": "none", "postponement_risk": "none"},
            parks, adjustments, wind_threshold_mph=8,
        )
        self.assertAlmostEqual(cross["hitter_f5"], 1.02, places=6)
        roof = compute_f5_factor(
            "Great American Ball Park",
            {"wind_status": "out", "wind_speed_mph": 20, "delay_risk": "none", "postponement_risk": "none"},
            parks, adjustments, wind_threshold_mph=8, roof_closed=True,
        )
        self.assertAlmostEqual(roof["hitter_f5"], 1.02, places=6)


class LiveDataAdapterTests(unittest.TestCase):
    def lineups_feed(self):
        lock = (NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
        hitters = [
            {"order": i + 1, "id": 600000 + i, "name": f"AAA {suffix}", "position": pos, "bat_side": "R"}
            for i, (pos, suffix) in enumerate([
                ("C", "C"), ("1B", "1B"), ("2B", "2B"), ("3B", "3B"),
                ("SS", "SS"), ("OF", "OF1"), ("OF", "OF2"), ("OF", "OF3"),
            ])
        ]
        return {
            "date": "2026-06-11", "fetched_at": TS,
            "games": [{
                "game_pk": 1, "game_date_utc": lock, "status": "Pre-Game", "venue": "Test Park",
                "away": {
                    "team_abbrev": "AAA", "lineup_status": "confirmed",
                    "probable_pitcher": {"id": 1, "name": "Pitcher A", "hand": "R"},
                    "lineup": hitters,
                },
                "home": {
                    "team_abbrev": "BBB", "lineup_status": "tbd",
                    "probable_pitcher": None, "lineup": [],
                },
            }],
        }

    def test_lineups_feed_builds_dk_status_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            ids = write_salary(salary)
            result = lda.build_status_map_from_lineups_feed(self.lineups_feed(), str(salary))
            statuses = result["status_by_player_id"]
            self.assertEqual(statuses[ids["AAA C"]].status, "Confirmed_Starter")
            self.assertEqual(statuses[ids["AAA C"]].batting_order, 1)
            self.assertEqual(statuses[ids["Pitcher A"]].status, "Projected_Starter")
            self.assertEqual(result["confirmed_teams"], ["AAA"])
            self.assertEqual(result["confirmed_order_by_player_id"][ids["AAA 2B"]], 3)
            self.assertIn(ids["CCC 1B"], result["uncovered_salary_player_ids"])
            self.assertNotIn(ids["CCC 1B"], statuses)
            lock_iso = result["lock_time_by_game_id"]["AAA@BBB"]
            self.assertEqual(lock_iso, (NOW + timedelta(hours=3)).isoformat())
            r1, _ = legal_rosters(ids)
            with tempfile.TemporaryDirectory() as tmp2:
                entries = Path(tmp2) / "entries.csv"
                write_entries(entries, [r1])
                with self.assertRaises(ValueError):
                    build_entry_requirements(entries, statuses, NOW)

    def test_normalize_name_folds_diacritics_and_suffixes(self):
        # Regression for the 2026-07-19 bug: the old regex deleted an accented
        # character instead of folding it, so "José" and "Jose" normalized
        # to different keys and a confirmed starter's salary row went unmatched.
        from mlb_engine.intake.slate_intake_manager import normalize_name
        self.assertEqual(normalize_name("José Fermín"), normalize_name("Jose Fermin"))
        self.assertEqual(normalize_name("Nasim Nuñez"), normalize_name("Nasim Nunez"))
        self.assertEqual(normalize_name("Andrés Chaparro"), normalize_name("Andres Chaparro"))
        self.assertEqual(normalize_name("Julio Rodríguez Jr."), normalize_name("Julio Rodriguez"))
        self.assertEqual(normalize_name("O'Hoppe"), normalize_name("O'Hoppe"))  # unchanged/self-consistent
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name(None), "")

    def test_accented_feed_name_matches_ascii_salary_row(self):
        # Same bug, exercised through the real matching path: a confirmed-lineup
        # hitter with an accented name (as the MLB Stats API returns it) must
        # still resolve against the plain-ASCII DK salary row for that player,
        # not fall into unmatched_feed_players / uncovered_salary_player_ids.
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            with salary.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary", "Game Info", "TeamAbbrev"])
                writer.writerow(["C", "Jose Fermin (77001)", "Jose Fermin", "77001", "C", "4000",
                                  "AAA@BBB 06/11/2026 01:00PM ET", "AAA"])
            feed = {
                "date": "2026-06-11", "fetched_at": TS,
                "games": [{
                    "game_pk": 1, "game_date_utc": TS, "status": "Pre-Game", "venue": "Test Park",
                    "away": {
                        "team_abbrev": "AAA", "lineup_status": "confirmed", "probable_pitcher": None,
                        "lineup": [{"order": 1, "id": 900, "name": "José Fermín", "position": "C", "bat_side": "R"}],
                    },
                    "home": {"team_abbrev": "BBB", "lineup_status": "tbd", "probable_pitcher": None, "lineup": []},
                }],
            }
            result = lda.build_status_map_from_lineups_feed(feed, str(salary))
            self.assertEqual(result["unmatched_feed_players"], [])
            self.assertIn("77001", result["confirmed_hitter_ids"])
            self.assertEqual(result["status_by_player_id"]["77001"].status, "Confirmed_Starter")

    def test_totals_raw_to_odds_packet(self):
        raw = [{
            "id": "ev1", "commence_time": "2026-06-11T17:05:00Z",
            "home_team": "Cincinnati Reds", "away_team": "Houston Astros",
            "bookmakers": [
                {"key": "draftkings", "markets": [{"key": "totals", "last_update": TS, "outcomes": [
                    {"name": "Over", "point": 9.5, "price": -110}, {"name": "Under", "point": 9.5, "price": -110},
                ]}]},
                {"key": "fanduel", "markets": [{"key": "totals", "outcomes": [
                    {"name": "Over", "point": 9.0, "price": -115},
                ]}]},
            ],
        }]
        packet = lda.parse_the_odds_api_totals(raw)
        entry = packet["odds_by_game_id"]["HOU@CIN"]
        self.assertAlmostEqual(entry["total"], 9.25)
        self.assertEqual(entry["fetched_at"], TS)
        self.assertEqual(entry["books"], {"draftkings": 9.5, "fanduel": 9.0})
        for field in ("total", "source", "fetched_at"):
            self.assertIn(field, entry)
        self.assertEqual(packet["unmapped_teams"], [])

    def test_implied_probability_math_and_props_table(self):
        self.assertAlmostEqual(lda.american_to_implied_prob(150), 0.4)
        self.assertAlmostEqual(lda.american_to_implied_prob(-200), 2.0 / 3.0)
        self.assertAlmostEqual(lda.decimal_to_implied_prob(2.5), 0.4)
        over, under = lda.vig_free_probabilities(0.45, 0.65)
        self.assertAlmostEqual(over + under, 1.0)
        self.assertAlmostEqual(over, 0.45 / 1.10)
        event = {
            "id": "ev1", "home_team": "Cincinnati Reds", "away_team": "Houston Astros",
            "bookmakers": [{"key": "draftkings", "markets": [{"key": "batter_home_runs", "outcomes": [
                {"name": "Over", "description": "Aaron Judge", "point": 0.5, "price": 250},
                {"name": "Under", "description": "Aaron Judge", "point": 0.5, "price": -350},
            ]}]}],
        }
        rows = lda.parse_the_odds_api_event_props(event)
        self.assertEqual(len(rows), 2)
        table = lda.build_props_implied_table(rows)
        self.assertEqual(len(table), 1)
        p_over = lda.american_to_implied_prob(250)
        p_under = lda.american_to_implied_prob(-350)
        self.assertAlmostEqual(table[0]["vig_free_prob"], p_over / (p_over + p_under), places=5)
        self.assertEqual(lda.estimate_the_odds_api_props_cost(12, 1, 1), 12)
        hr_rows = lda.parse_odds_api_io_hr_props([{
            "id": "e9", "bookmakers": [{"name": "Bet365", "markets": [{
                "name": "Player Home Runs", "label": "Juan Soto",
                "odds": [{"label": "Under", "price": 1.30, "point": 0.5}],
            }]}],
        }])
        self.assertEqual(len(hr_rows), 1)
        self.assertAlmostEqual(hr_rows[0]["implied_prob"], 1.0 / 1.30, places=6)




class FixedExposureOffsetTests(unittest.TestCase):
    """R61. The solve and the export validator resolve one cap, one denominator.

    `select_and_assign_entries` resolved every exposure cap against the entries
    it was HANDED; `validate_dk_entries_file` resolves them against every
    complete row in the file. On a late swap those differ, and a feasible swap
    died at the gate closest to lock while the operator was pointed at
    --controls-override. `fixed_exposure` closes it. Seven controls shared the
    asymmetry, so these tests cover all seven, not the one the item was filed on.
    """

    ENTRIES = [{"entry_id": str(i), "contest_id": "c1",
                "contest_shape": "large_wta"} for i in range(1, 5)]

    def _bank(self, hot="HOT"):
        """Six candidates for four entries: two hold the hot player and four do
        not, every signature distinct. The slack matters -- with exactly four
        candidates the same-contest duplicate rule forces all four into the
        solve, and every headroom assertion below would be testing that
        compulsion instead of the headroom."""
        return [
            candidate("h1", [hot, "p1", *[f"a{i}" for i in range(8)]], 100),
            candidate("h2", [hot, "p2", *[f"b{i}" for i in range(8)]], 99),
            candidate("c1", ["p3", "p4", *[f"c{i}" for i in range(8)]], 10, "QQQ"),
            candidate("c2", ["p5", "p6", *[f"d{i}" for i in range(8)]], 9, "ZZZ"),
            candidate("c3", ["p7", "p8", *[f"e{i}" for i in range(8)]], 8, "WWW"),
            candidate("c4", ["p9", "p0", *[f"g{i}" for i in range(8)]], 7, "VVV"),
        ]

    def test_absent_offsets_leave_the_result_untouched(self):
        """The R28 precedent: an initial build must not move because a swap fix
        landed. Absent means the v1.12 key set and the v1.12 assignments."""
        controls = {"max_player_exposure_pct": 0.5}
        plain = select_and_assign_entries(self._bank(), self.ENTRIES, controls)
        explicit_none = select_and_assign_entries(
            self._bank(), self.ENTRIES, controls, fixed_exposure=None)
        empty = select_and_assign_entries(
            self._bank(), self.ENTRIES, controls, fixed_exposure={})
        zero_rows = select_and_assign_entries(
            self._bank(), self.ENTRIES, controls,
            fixed_exposure={"row_count": 0, "player_counts": {"HOT": 99}})
        self.assertTrue(plain["passed"], plain.get("errors"))
        for label, other in (("explicit None", explicit_none), ("empty", empty),
                             ("row_count 0", zero_rows)):
            with self.subTest(offsets=label):
                self.assertEqual(sorted(plain), sorted(other))
                self.assertNotIn("fixed_exposure_report", other)
                self.assertEqual(plain["assignments"], other["assignments"])
                self.assertEqual(plain["direct_constraints"],
                                 other["direct_constraints"])
        # `row_count: 0` carrying counts is a contradiction no derivation can
        # produce, and it must read as "no untouchable rows", not as a cap the
        # counts quietly spend. Before this was one gate it did the latter: the
        # conflict check was skipped while HOT's headroom went to zero, dropping
        # both hot candidates with nothing in the output saying so.
        self.assertEqual(zero_rows["direct_constraints"]["max_player_count"],
                         plain["direct_constraints"]["max_player_count"])

    def test_denominator_widens_by_the_untouchable_rows(self):
        result = select_and_assign_entries(
            self._bank(), self.ENTRIES, {"max_player_exposure_pct": 0.5},
            fixed_exposure={"row_count": 4})
        self.assertTrue(result["passed"], result.get("errors"))
        report = result["fixed_exposure_report"]
        self.assertEqual(report["solve_entry_count"], 4)
        self.assertEqual(report["untouchable_row_count"], 4)
        self.assertEqual(report["entry_denominator"], 8)
        # floor(8*0.5)=4 where the old denominator gave floor(4*0.5)=2.
        self.assertEqual(result["direct_constraints"]["max_player_count"], 4)

    def test_headroom_is_the_cap_minus_what_is_already_fixed(self):
        """Two untouchable rows already hold HOT, cap 3 over six rows, so the
        solve may add exactly one -- not three."""
        result = select_and_assign_entries(
            self._bank(), self.ENTRIES, {"max_player_exposure_pct": 0.5},
            fixed_exposure={"row_count": 2, "player_counts": {"HOT": 2}})
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(result["direct_constraints"]["max_player_count"], 3)
        chosen = {row["candidate_id"] for row in result["assignments"]}
        self.assertEqual(len(chosen & {"h1", "h2"}), 1)
        self.assertIn("HOT", result["fixed_exposure_report"]
                      ["headroom_reduced_keys"]["max_player_exposure_pct"])

    def test_untouchable_rows_over_cap_refuse_and_never_say_infeasible(self):
        """The cap is already blown by rows nobody asked the solver to touch.
        Decidable from the file, so it is decided before the MILP, and it does
        not wear the reserved 'proven infeasible' label."""
        result = select_and_assign_entries(
            self._bank(), self.ENTRIES, {"max_player_exposure_pct": 0.5},
            fixed_exposure={"row_count": 4, "player_counts": {"HOT": 5}})
        self.assertFalse(result["passed"])
        self.assertEqual(result["refusal"], "untouchable_rows_exceed_cap")
        self.assertFalse(result["selection_certified"])
        self.assertFalse(result["allocation_certified"])
        blob = " ".join(result["errors"])
        self.assertIn("max_player_exposure_pct", blob)
        self.assertIn("already appears in 5", blob)
        self.assertIn("cannot change", blob)
        self.assertIn("whole-file cap of 4", blob)
        self.assertNotIn("infeasible", blob.lower())
        # Remedies in R98(2)'s order: scope first, the parent's own cap second,
        # a strategy decision last, and NEVER bank growth -- the bank has
        # nothing to do with a count the untouchable rows carry alone.
        self.assertIn("--entry-ids", blob)
        self.assertIn("SCOPE change", blob)
        self.assertIn("strategy decision", blob)
        self.assertNotIn("grow the bank", blob.lower())
        self.assertNotIn("job list", blob.lower())

    def test_fixed_equal_to_cap_is_zero_headroom_not_a_refusal(self):
        """The boundary. Meeting the cap exactly is an ordinary constraint the
        solve satisfies by taking none of that key; only EXCEEDING it refuses."""
        at_cap = select_and_assign_entries(
            self._bank(), self.ENTRIES, {"max_player_exposure_pct": 0.5},
            fixed_exposure={"row_count": 4, "player_counts": {"HOT": 4}})
        self.assertNotIn("refusal", at_cap)
        self.assertTrue(at_cap["passed"], at_cap.get("errors"))
        chosen = {row["candidate_id"] for row in at_cap["assignments"]}
        self.assertEqual(chosen & {"h1", "h2"}, set())
        over_by_one = select_and_assign_entries(
            self._bank(), self.ENTRIES, {"max_player_exposure_pct": 0.5},
            fixed_exposure={"row_count": 4, "player_counts": {"HOT": 5}})
        self.assertEqual(over_by_one.get("refusal"), "untouchable_rows_exceed_cap")

    def test_every_count_control_refuses_on_its_own_key(self):
        cases = [
            ({"max_pitcher_exposure_pct": 0.5},
             {"pitcher_counts": {"p1": 5}}, "max_pitcher_exposure_pct"),
            ({"max_primary_stack_exposure_pct": 0.5},
             {"primary_stack_counts": {"AAA": 5}},
             "max_primary_stack_exposure_pct"),
            ({"max_sp_pair_repetition": 2},
             {"sp_pair_counts": {"HOT|p1": 3}}, "max_sp_pair_repetition"),
            ({"max_game_exposure_pct_by_game": {"G1": 0.5},
              "player_game_by_id": {"HOT": "G1"}},
             {"game_counts": {"G1": 5}}, "max_game_exposure_pct_by_game"),
        ]
        for controls, fixed, control in cases:
            with self.subTest(control=control):
                result = select_and_assign_entries(
                    self._bank(), self.ENTRIES, controls,
                    fixed_exposure={"row_count": 4, **fixed})
                self.assertFalse(result["passed"])
                self.assertEqual(result["refusal"], "untouchable_rows_exceed_cap")
                self.assertIn(control, " ".join(result["errors"]))

    def test_untouchable_signature_is_a_same_contest_duplicate(self):
        """A candidate identical to an untouched row of the SAME contest is a
        duplicate in the exported file; the solve's own duplicate rows never
        formed that pair because the row was not in the solve."""
        roster = ["HOT", "p1", *[f"a{i}" for i in range(8)]]
        bank = [candidate("dup", list(roster), 100),
                candidate("other", ["p3", "p4", *[f"c{i}" for i in range(8)]],
                          10, "QQQ")]
        entries = [{"entry_id": "1", "contest_id": "c1",
                    "contest_shape": "large_wta"}]
        offsets = {"row_count": 1,
                   "signatures_by_contest": {"c1": [sorted(roster)]}}
        blocked = select_and_assign_entries(bank, entries, {},
                                            fixed_exposure=offsets)
        self.assertTrue(blocked["passed"], blocked.get("errors"))
        self.assertEqual([r["candidate_id"] for r in blocked["assignments"]],
                         ["other"])
        self.assertEqual(blocked["fixed_exposure_report"]
                         ["entry_candidate_pairs_blocked_by_untouchable_signature"], 1)
        # A DIFFERENT contest is approved cross-contest reuse, not a duplicate.
        elsewhere = select_and_assign_entries(
            bank, entries, {},
            fixed_exposure={"row_count": 1,
                            "signatures_by_contest": {"c9": [sorted(roster)]}})
        self.assertEqual([r["candidate_id"] for r in elsewhere["assignments"]],
                         ["dup"])

    def test_untouchable_overlap_blocks_the_candidate_with_the_same_exemption(self):
        shared = [f"s{i}" for i in range(6)]
        untouchable = [*shared, "u1", "u2", "u3", "u4"]
        near = [*shared, "n1", "n2", "n3", "n4"]
        far = [f"f{i}" for i in range(10)]
        bank = [candidate("near", near, 100), candidate("far", far, 10, "QQQ")]
        entries = [{"entry_id": "1", "contest_id": "c1",
                    "contest_shape": "large_wta"}]
        result = select_and_assign_entries(
            bank, entries, {"max_shared_players": 5},
            fixed_exposure={"row_count": 1, "rosters": [untouchable]})
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual([r["candidate_id"] for r in result["assignments"]], ["far"])
        self.assertEqual(result["fixed_exposure_report"]
                         ["candidates_blocked_by_untouchable_overlap"], ["near"])
        # Five shared is at the limit, not over it.
        at_limit = select_and_assign_entries(
            [candidate("near", [*shared[:5], "x1", "x2", "x3", "x4", "x5"], 100)],
            entries, {"max_shared_players": 5},
            fixed_exposure={"row_count": 1, "rosters": [untouchable]})
        self.assertTrue(at_limit["passed"], at_limit.get("errors"))
        # An IDENTICAL roster is approved reuse of one candidate, which is the
        # exemption validate_dk_entries_file applies; the duplicate rule owns it.
        identical = select_and_assign_entries(
            [candidate("same", list(untouchable), 100)], entries,
            {"max_shared_players": 5},
            fixed_exposure={"row_count": 1, "rosters": [untouchable]})
        self.assertTrue(identical["passed"], identical.get("errors"))

    def test_starved_entry_names_the_untouchable_rows_not_the_bank(self):
        roster = ["HOT", "p1", *[f"a{i}" for i in range(8)]]
        result = select_and_assign_entries(
            [candidate("dup", list(roster), 100)],
            [{"entry_id": "1", "contest_id": "c1", "contest_shape": "large_wta"}],
            {"max_shared_players": 5},
            fixed_exposure={"row_count": 1,
                            "signatures_by_contest": {"c1": [sorted(roster)]}})
        self.assertFalse(result["passed"])
        self.assertEqual(result["refusal"], "untouchable_rows_starve_entry")
        blob = " ".join(result["errors"])
        self.assertIn("Entry ID 1", blob)
        self.assertIn("cannot change", blob)
        self.assertIn("NOT", blob)
        self.assertIn("--entry-ids", blob)

    def test_derivation_matches_the_validator_on_the_whole_file(self):
        """The two definitions cannot drift, because there is one of them.

        With nothing solved, `fixed_portfolio_exposure` is measuring exactly the
        set `validate_dk_entries_file` measures, so every count must agree. This
        is the same guard the _cap_count contract gets, applied to the counts.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            r1, r2 = legal_rosters(ids)
            entries = root / "entries.csv"
            write_entries(entries, [r1, r2, r1], ["1", "2", "2"])
            whole = fixed_portfolio_exposure(entries, [], salary_csv_path=salary)
            report = validate_dk_entries_file(entries, salary_csv_path=salary)
            self.assertEqual(whole["row_count"], report["complete_entry_count"])
            self.assertEqual(whole["player_counts"],
                             report["exposures"]["player_counts"])
            self.assertEqual(whole["pitcher_counts"],
                             report["exposures"]["pitcher_counts"])
            self.assertEqual(whole["primary_stack_counts"],
                             report["exposures"]["primary_stack_counts"])
            self.assertEqual(whole["sp_pair_counts"],
                             report["exposures"]["sp_pair_counts"])
            # Naming a row as solved removes it and only it. These are ENTRY
            # IDs, which write_entries assigns as 5001..500N; the third argument
            # above is the contest column.
            self.assertEqual(whole["entry_ids"], ["5001", "5002", "5003"])
            partial = fixed_portfolio_exposure(entries, ["5001"],
                                               salary_csv_path=salary)
            self.assertEqual(partial["row_count"], 2)
            self.assertEqual(partial["entry_ids"], ["5002", "5003"])

    def test_derivation_skips_blank_rows_and_groups_signatures_by_contest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            r1, r2 = legal_rosters(ids)
            entries = root / "entries.csv"
            # Numeric contest IDs: parse_dk_entry_rows skips any row whose Entry
            # ID or Contest ID is not all digits.
            write_entries(entries, [r1, None, r2], ["901", "901", "902"])
            offsets = fixed_portfolio_exposure(entries, [], salary_csv_path=salary)
            # The blank reserved row is not a legal roster, so it is not a row.
            self.assertEqual(offsets["row_count"], 2)
            self.assertEqual(sorted(offsets["signatures_by_contest"]), ["901", "902"])
            self.assertEqual(offsets["signatures_by_contest"]["901"], [sorted(r1)])
            self.assertEqual(offsets["rosters"], [list(r1), list(r2)])
            # Without a salary file there is no team map, so stacks and games are
            # not invented; the flag says so rather than the caller guessing.
            no_salary = fixed_portfolio_exposure(entries, [])
            self.assertFalse(no_salary["stacks_derived"])
            self.assertEqual(no_salary["primary_stack_counts"], {})
            self.assertEqual(no_salary["game_counts"], {})
            self.assertEqual(no_salary["player_counts"], offsets["player_counts"])


class ControlAlignmentTests(unittest.TestCase):
    def test_candidate_reuse_cap_is_signature_keyed(self):
        roster = [f"P{i}" for i in range(10)]
        other = [f"Q{i}" for i in range(10)]
        result = select_and_assign_entries(
            [candidate("A", roster, 100), candidate("B", list(roster), 100), candidate("C", other, 1, "QQQ")],
            [
                {"entry_id": "1", "contest_id": "x", "contest_shape": "large_wta"},
                {"entry_id": "2", "contest_id": "y", "contest_shape": "large_wta"},
            ],
            {"max_candidate_reuse": 1},
        )
        self.assertTrue(result["passed"], result.get("errors"))
        chosen = sorted(row["candidate_id"] for row in result["assignments"])
        self.assertIn("C", chosen)
        self.assertEqual(len([cid for cid in chosen if cid in {"A", "B"}]), 1)

    def test_game_exposure_cap_solver_and_validator(self):
        g1 = [f"a{i}" for i in range(10)]
        g2 = [f"b{i}" for i in range(10)]
        game_map = {pid: "G1" for pid in g1}
        game_map.update({pid: "G2" for pid in g2})
        capped = select_and_assign_entries(
            [candidate("X", g1, 100), candidate("Y", g2, 90, "YYY")],
            [
                {"entry_id": "1", "contest_id": "c1", "contest_shape": "large_wta"},
                {"entry_id": "2", "contest_id": "c2", "contest_shape": "large_wta"},
            ],
            {"max_game_exposure_pct_by_game": {"G1": 0.5}, "player_game_by_id": game_map},
        )
        self.assertTrue(capped["passed"], capped.get("errors"))
        chosen = sorted(row["candidate_id"] for row in capped["assignments"])
        self.assertEqual(chosen, ["X", "Y"])
        missing_map = select_and_assign_entries(
            [candidate("X", g1, 100)],
            [{"entry_id": "1", "contest_id": "c1", "contest_shape": "large_wta"}],
            {"max_game_exposure_pct_by_game": {"G1": 0.5}},
        )
        self.assertFalse(missing_map["passed"])
        self.assertIn("player_game_by_id", missing_map["errors"][0])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            r1, _ = legal_rosters(ids)
            entries = root / "entries.csv"
            write_entries(entries, [r1, r1, r1], ["1", "2", "3"])
            result = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                portfolio_controls={"max_game_exposure_pct_by_game": {"AAA@BBB": 0.5}},
            )
            self.assertFalse(result["portfolio_caps_passed"])
            self.assertTrue(any(error.startswith("game AAA@BBB") for error in result["errors"]))


class BankCoverageTests(unittest.TestCase):
    def test_bank_coverage_reports_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = write_salary(Path(tmp) / "salary.csv")
            frame = projection_frame(ids)
            r1, r2 = legal_rosters(ids)
            report = opt.bank_coverage_report(frame, [candidate("A", r1, 100), candidate("B", r2, 99)])
            self.assertTrue(report["passed"])
            self.assertGreaterEqual(report["gap_points"], 0.0)
            self.assertEqual(report["candidate_count"], 2)
            self.assertIsNotNone(report["best_candidate_id"])
            empty = opt.bank_coverage_report(frame, [])
            self.assertIsNone(empty["passed"])


def _shaped_candidate(cid, roster, by_shape, primary="AAA"):
    """A candidate whose score is pinned per contest shape.

    `_candidate_shape_score` reads `contest_fit_by_shape[shape]` ahead of every
    proxy, so this is the only way to set the two entries' scores independently
    and put two candidates a known distance apart.
    """
    best = max(by_shape.values())
    return {
        "candidate_id": cid, "lineup_ids": roster, "player_ids": roster,
        "sp_ids": roster[:2], "primary_stack": primary,
        "objective": best, "contest_fit_score": best,
        "contest_fit_by_shape": dict(by_shape),
    }


class JointObjectiveNoReuseTermTests(unittest.TestCase):
    """R36 Finding 11. The joint objective carries no reuse term.

    `reuse_penalty * 0.01` used to sit on the used-candidate indicators as a
    POSITIVE minimization cost, so it rewarded concentration rather than
    penalising it. These tests pin the vector it left behind and the behaviour
    the term used to distort.
    """

    SHAPES = ("large_wta", "mid_wta")

    def _entries(self, count):
        return [
            {"entry_id": str(i + 1), "contest_id": f"c{i + 1}",
             "contest_shape": self.SHAPES[i % len(self.SHAPES)]}
            for i in range(count)
        ]

    def _near_tie_bank(self, delta):
        """Two candidates each better for one shape by `delta`, plus an anchor.

        The anchor holds the normalization range at a full 0-100 span, which is
        what makes `delta` a distance on that scale rather than on the raw
        scores. Rosters are disjoint, so no overlap row fires and reuse stays
        legal on the constraints.
        """
        a = [f"a{i}" for i in range(10)]
        b = [f"b{i}" for i in range(10)]
        c = [f"c{i}" for i in range(10)]
        return [
            _shaped_candidate("A", a, {"large_wta": 100.0, "mid_wta": 100.0 - delta}, "AAA"),
            _shaped_candidate("B", b, {"large_wta": 100.0 - delta, "mid_wta": 100.0}, "BBB"),
            _shaped_candidate("ANCHOR", c, {"large_wta": 0.0, "mid_wta": 0.0}, "CCC"),
        ]

    def _capture_objective(self, candidates, entries, controls):
        """Snapshot the `c` vector handed to `milp`, and solve for real."""
        import numpy as np
        import scipy.optimize as so
        real_milp = so.milp
        seen = {}

        def spy(*args, **kwargs):
            seen["c"] = np.array(kwargs["c"], dtype=float)
            return real_milp(*args, **kwargs)

        with unittest.mock.patch.object(so, "milp", spy):
            result = select_and_assign_entries(candidates, entries, controls)
        self.assertIn("c", seen, "milp was never reached")
        return seen["c"], result

    def test_objective_names_signs_and_bounds_every_term(self):
        candidates = self._near_tie_bank(0.01)
        entries = self._entries(2)
        E, K = len(entries), len(candidates)
        objective, result = self._capture_objective(
            candidates, entries, {"max_shared_players": 4})
        self.assertTrue(result["passed"], result.get("errors"))

        # Two variable blocks and no others: E*K assignment vars, then K
        # used-candidate indicators because max_shared_players is set.
        self.assertEqual(objective.size, E * K + K)

        # The y block is the R36 F11 pin. Every indicator coefficient is
        # exactly zero; y_k exists only to carry the hard overlap rows.
        y_block = objective[E * K:]
        self.assertEqual(y_block.size, K)
        self.assertTrue((y_block == 0.0).all(), list(y_block))

        # The x block is bounded and signed: negated shape scores normalized
        # onto [-100, 0], so nothing in the whole vector is ever positive.
        x_block = objective[:E * K]
        self.assertLessEqual(float(x_block.max()), 0.0)
        self.assertGreaterEqual(float(x_block.min()), -100.0)
        self.assertLessEqual(float(objective.max()), 0.0)
        for e in range(E):
            row = x_block[e * K:(e + 1) * K]
            self.assertAlmostEqual(float(row.min()), -100.0, places=9)
            self.assertAlmostEqual(float(row.max()), 0.0, places=9)

    def test_no_indicator_block_without_max_shared_players(self):
        candidates = self._near_tie_bank(0.01)
        entries = self._entries(2)
        objective, result = self._capture_objective(candidates, entries, {})
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(objective.size, len(entries) * len(candidates))

    def test_near_tie_entries_do_not_collapse_onto_one_reused_lineup(self):
        """The behavioural half. Two candidates 0.01 apart on a 100-point scale
        sit inside the removed term's 0.02 tiebreaker band. Each is the better
        fit for one of the two entries by that margin, and the entries are in
        different contests so reuse is legal on the constraints. Taking both is
        worth -200.00 and reusing either one is worth -199.99, so the distinct
        pair is the unique optimum. Under the old term reuse won: it saved 0.02
        by keeping one indicator down and gave up only 0.01 of fit.
        """
        candidates = self._near_tie_bank(0.01)
        entries = self._entries(2)
        result = select_and_assign_entries(
            candidates, entries, {"max_shared_players": 4})
        self.assertTrue(result["passed"], result.get("errors"))
        chosen = [row["candidate_id"] for row in result["assignments"]]
        self.assertEqual(sorted(chosen), ["A", "B"], chosen)
        self.assertFalse(
            any(row["reused_across_contests"] for row in result["assignments"]))
        by_entry = {row["entry_id"]: row["candidate_id"] for row in result["assignments"]}
        self.assertEqual(by_entry["1"], "A")
        self.assertEqual(by_entry["2"], "B")

    def test_reuse_penalty_control_is_named_and_changes_nothing(self):
        """The key is no longer a joint control. It is reported, not obeyed, and
        not fatal: the checkpoint renders an allocator refusal as
        `proven_infeasible`, and a dead control key is not an infeasible
        constraint system.
        """
        candidates = self._near_tie_bank(0.01)
        entries = self._entries(2)
        clean_obj, clean = self._capture_objective(
            candidates, entries, {"max_shared_players": 4})
        stale_obj, stale = self._capture_objective(
            candidates, entries, {"max_shared_players": 4, "reuse_penalty": 2.0})

        self.assertTrue(stale["passed"], stale.get("errors"))
        self.assertTrue((clean_obj == stale_obj).all())
        self.assertEqual(
            [row["candidate_id"] for row in clean["assignments"]],
            [row["candidate_id"] for row in stale["assignments"]],
        )
        self.assertEqual(clean.get("warnings"), [])
        named = [w for w in stale["warnings"] if "reuse_penalty" in w]
        self.assertEqual(len(named), 1, stale["warnings"])
        self.assertIn("IGNORED", named[0])


class TestXwobaBaselineCorrection(unittest.TestCase):
    def _bat(self, woba, est, pa, pid="100"):
        return pd.DataFrame([{"player_id": pid, "pa": pa, "woba": woba, "est_woba": est}])

    def test_batter_overperformer_pulled_down(self):
        corr = build_xwoba_corrections(self._bat(0.350, 0.315, 200), role="batter")
        self.assertAlmostEqual(corr["100"], 0.9, places=4)

    def test_pitcher_ratio_inverted_unlucky_arm_pulled_up(self):
        # low wOBA-against expected vs higher actual => skill better than results
        table = pd.DataFrame([{"player_id": "200", "pa": 200, "woba": 0.320, "est_woba": 0.300}])
        corr = build_xwoba_corrections(table, role="pitcher")
        self.assertGreater(corr["200"], 1.0)
        self.assertAlmostEqual(corr["200"], 0.320 / 0.300, places=4)

    def test_extreme_ratio_is_clipped_to_band(self):
        corr = build_xwoba_corrections(self._bat(0.200, 0.400, 300), role="batter")
        self.assertEqual(corr["100"], 1.15)  # 2.0 ratio clipped to batter ceiling

    def test_sub_floor_pa_is_neutral(self):
        corr = build_xwoba_corrections(self._bat(0.200, 0.400, 30), role="batter")
        self.assertEqual(corr["100"], 1.0)

    def test_partial_sample_shrinks_toward_one(self):
        # pa 75 is halfway between 50 and 100 => weight 0.5; ratio 1.2 -> 1.10
        corr = build_xwoba_corrections(self._bat(0.300, 0.360, 75), role="batter")
        self.assertAlmostEqual(corr["100"], 1.10, places=4)

    def test_zero_or_missing_woba_is_neutral(self):
        zero = build_xwoba_corrections(self._bat(0.0, 0.300, 300), role="batter")
        self.assertEqual(zero["100"], 1.0)
        nan = build_xwoba_corrections(
            pd.DataFrame([{"player_id": "100", "pa": 300, "woba": 0.300, "est_woba": float("nan")}]),
            role="batter",
        )
        self.assertEqual(nan["100"], 1.0)

    def test_apply_sets_base_and_falls_back_for_unmatched(self):
        rows = pd.DataFrame([
            {"Player_ID": "100", "Name": "Matched", "AvgPointsPerGame": 10.0},
            {"Player_ID": "999", "Name": "Unmatched", "AvgPointsPerGame": 8.0},
        ])
        out, audit = apply_xwoba_correction(rows, {"100": 1.1})
        by_id = {str(r["Player_ID"]): r for r in out.to_dict("records")}
        self.assertAlmostEqual(by_id["100"]["Base"], 11.0, places=6)
        self.assertAlmostEqual(by_id["999"]["Base"], 8.0, places=6)  # fallback factor 1.0
        matched = {str(r["Player_ID"]): r["matched"] for r in audit.to_dict("records")}
        self.assertTrue(matched["100"])
        self.assertFalse(matched["999"])

    def test_null_base_in_is_never_corrected_to_nan(self):
        # R57(b) at the helper: base_in null * factor is NaN, and a NaN Base is
        # a crash in validate_projection_factors, not a correction. The row
        # keeps the base_out it arrived with.
        rows = pd.DataFrame([
            {"Player_ID": "100", "Name": "HasAppg", "AvgPointsPerGame": 10.0, "Base": 10.0},
            {"Player_ID": "100", "Name": "NoAppg", "AvgPointsPerGame": None, "Base": 12.0},
        ])
        out, audit = apply_xwoba_correction(rows, {"100": 1.1})
        self.assertAlmostEqual(float(out.iloc[0]["Base"]), 11.0, places=6)
        self.assertAlmostEqual(float(out.iloc[1]["Base"]), 12.0, places=6)
        self.assertFalse(pd.isna(out["Base"]).any())
        self.assertEqual([True, False], list(audit["applied"]))
        # the audit reports what actually multiplied Base, not what would have
        self.assertAlmostEqual(float(audit.iloc[1]["xwoba_correction"]), 1.0, places=6)

    def test_apply_mask_false_rows_keep_their_base(self):
        # R57(a) at the helper: the mask is how a caller says "this base_out
        # came from a source the correction may not overwrite."
        rows = pd.DataFrame([
            {"Player_ID": "100", "Name": "FromAppg", "AvgPointsPerGame": 10.0, "Base": 10.0},
            {"Player_ID": "100", "Name": "Operator", "AvgPointsPerGame": 10.0, "Base": 12.0},
        ])
        out, audit = apply_xwoba_correction(rows, {"100": 1.1}, apply_mask=[True, False])
        self.assertAlmostEqual(float(out.iloc[0]["Base"]), 11.0, places=6)
        self.assertAlmostEqual(float(out.iloc[1]["Base"]), 12.0, places=6)
        self.assertEqual([True, False], list(audit["applied"]))

    def test_misaligned_apply_mask_raises(self):
        rows = pd.DataFrame([{"Player_ID": "100", "AvgPointsPerGame": 10.0, "Base": 10.0}])
        with self.assertRaisesRegex(ValueError, "aligned"):
            apply_xwoba_correction(rows, {"100": 1.1}, apply_mask=[True, True])

    def test_loader_handles_bom_and_normalizes_player_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            p.write_bytes(
                b"\xef\xbb\xbf\"last_name, first_name\",\"player_id\",\"pa\",\"woba\",\"est_woba\"\n"
                b"\"Wood, James\",\"695578\",\"349\",0.408,0.43\n"
            )
            frame = load_savant_expected_stats(p)
            self.assertIn("player_id", frame.columns)
            self.assertEqual(frame.iloc[0]["player_id"], "695578")
            self.assertAlmostEqual(float(frame.iloc[0]["est_woba"]), 0.43, places=4)


class RunSlateFrontDoorTests(unittest.TestCase):
    LOOSE = {
        "max_player_exposure_pct": 1.0, "max_pitcher_exposure_pct": 1.0,
        "max_primary_stack_exposure_pct": 1.0, "max_sp_pair_repetition": 2,
        "max_shared_players": 9,
    }

    def _inputs(self, root: Path):
        salary = root / "salary.csv"; ids = write_salary(salary)
        entries = root / "DKEntries.csv"; write_entries(entries)
        r1, r2 = legal_rosters(ids)
        cands = [candidate("A", r1, 100), candidate("B", r2, 99, "CCC")]
        return salary, entries, cands, projection_frame(ids)

    def test_plan_only_creates_no_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, cands, proj = self._inputs(root)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj, candidates_override=cands, approve=False,
            )
            self.assertEqual(plan["status"], "plan_pending_approval")
            self.assertTrue(plan["passed"])
            self.assertFalse(plan["approved"])
            self.assertTrue(plan["checkpoint_plan"]["contests"])
            self.assertFalse(plan["checkpoint_plan"]["calibrated"])
            self.assertTrue(plan["checkpoint_plan"]["defaults_are_priors"])
            # the two gates run_slate computes are not in the caller-asserted set
            self.assertNotIn("projection_schema_gate_passed", plan["caller_asserted_gates"])
            self.assertNotIn("optimizer_gate_passed", plan["caller_asserted_gates"])
            # no expensive build happened
            self.assertFalse((root / "runs").exists())

    # The gates this fixture cannot evidence: it supplies no odds map, no
    # weather map, no pitcher_roles, and (R53) no batting orders or pool report.
    # Before F4 the first three defaulted to True and the certification read
    # clean; now they are absent, and absent blocks.
    #
    # lineup_gate_passed joined the list on 2026-08-04. `projection_frame` has no
    # Batting_Order column and this call passes no pool_report, so nothing here
    # states that the lineups behind the build were reviewed. It nevertheless
    # certified until R53, because the gate read the truthiness of a summary dict
    # that is always truthy. A fixture that cannot evidence a gate has to say so
    # out loud through assume_gates, which is recorded on the artifact -- that is
    # the whole mechanism, and this test was silently outside it.
    UNEVIDENCED = ["odds_gate_passed", "weather_gate_passed",
                   "pitcher_audit_gate_passed", "lineup_gate_passed"]

    def test_approved_promotes_with_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, cands, proj = self._inputs(root)
            built = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj, candidates_override=cands,
                portfolio_controls_override=self.LOOSE, approve=True,
                assume_gates=self.UNEVIDENCED,
            )
            self.assertTrue(built["passed"], built.get("errors"))
            self.assertTrue(built["approved"])
            self.assertTrue(built["selection_certified"])
            self.assertTrue(built["allocation_certified"])
            self.assertTrue(Path(built["output_path"]).exists())
            self.assertEqual(built["candidate_bank"]["source"], "candidates_override")
            # the artifact states which checks were skipped rather than implying
            # they ran
            self.assertEqual(sorted(built["assumed_gates"]), sorted(self.UNEVIDENCED))

    def test_unevidenced_gates_block_and_are_named(self):
        """F4: six gates used to be hardcoded True, so workflow_valid was a constant."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, cands, proj = self._inputs(root)
            built = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj, candidates_override=cands,
                portfolio_controls_override=self.LOOSE, approve=True,
            )
            self.assertFalse(built["passed"])
            errors = " ".join(built.get("errors") or [])
            for gate in self.UNEVIDENCED:
                self.assertIn(gate, errors)
            # and every gate says why it reads the way it does
            evidence = built["workflow_gate_evidence"]
            self.assertIn("salary CSV schema validation", evidence["salary_gate_passed"])
            self.assertIn("no map supplied", evidence["odds_gate_passed"])

    def test_blocks_on_bad_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, cands, proj = self._inputs(root)
            broken = proj.drop(columns=["Ceiling"])
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=broken, candidates_override=cands,
                portfolio_controls_override=self.LOOSE, approve=True,
            )
            self.assertFalse(result["passed"])
            self.assertEqual(result["status"], "blocked")
            self.assertFalse((root / "runs").exists())

    def test_posture_mapping(self):
        self.assertEqual(normalize_posture("wta", None, None), "wta_satellite")
        self.assertEqual(normalize_posture(None, None, 1), "single_entry")
        self.assertEqual(normalize_posture("cash", "flat_cash", None), "cash")
        self.assertEqual(normalize_posture("portfolio", "broad_micro_gpp", None), "large_gpp")


class ContestShapeVocabularyTests(unittest.TestCase):
    """R1a: one canonical shape vocabulary, and satellites reach their own profile.

    Teeth: before this, `normalize_posture` folded inferred_type='satellite' and
    payout_shape_default='ticket_line' into the wta_satellite posture, which
    `_posture_to_shape` mapped to `large_wta`. The optimizer's `satellite`
    profile (ticket_line, 0.58/0.42) and the allocator's floor-aware satellite
    branch were both unreachable from a production build, and `mme` mapped to
    `mme_top_heavy`, which is not a profile key at all.
    """

    def test_profile_table_covers_the_canonical_vocabulary_exactly(self):
        from mlb_engine.contest_shapes import CONTEST_SHAPES, OBJECTIVE_CLASS_BY_SHAPE
        self.assertEqual(set(opt.CONTEST_SHAPE_PROFILE_WEIGHTS), set(CONTEST_SHAPES))
        self.assertEqual(set(OBJECTIVE_CLASS_BY_SHAPE), set(CONTEST_SHAPES))
        for shape, profile in opt.CONTEST_SHAPE_PROFILE_WEIGHTS.items():
            self.assertEqual(profile["mode_family"], OBJECTIVE_CLASS_BY_SHAPE[shape], shape)

    def test_curated_ticket_count_reaches_the_shape_and_closes_the_gap(self):
        """R1c: the one satellite fact no title inference can recover.

        Teeth: resolve_contest_shape has read info['ticket_count'] since R1a and
        infer_contest_archetype never returned one, so a single-ticket qualifier
        could not reach the wta_ticket_satellite profile from a curated row no
        matter what the row said.
        """
        from mlb_engine.entries.dk_entries_manager import (
            ContestArchetype, infer_contest_archetype)

        one = ContestArchetype("Qualifier", None, "satellite", None, "ticket_line",
                               "inferred_high", ticket_count=1)
        many = ContestArchetype("Qualifier", None, "satellite", None, "ticket_line",
                                "inferred_high", ticket_count=6)
        unknown = ContestArchetype("Qualifier", None, "satellite", None, "ticket_line",
                                   "inferred_high")

        single = infer_contest_archetype("MLB $5 Qualifier", archetypes=[one])
        self.assertEqual(single["ticket_count"], 1)
        self.assertEqual(epi.resolve_contest_shape("wta_satellite", single),
                         "wta_ticket_satellite")
        self.assertNotIn("ticket_count", single["decision_critical_gaps"])

        multi = infer_contest_archetype("MLB $5 Qualifier", archetypes=[many])
        self.assertEqual(epi.resolve_contest_shape("wta_satellite", multi), "satellite")

        blank = infer_contest_archetype("MLB $5 Qualifier", archetypes=[unknown])
        self.assertIsNone(blank["ticket_count"])
        self.assertIn("ticket_count", blank["decision_critical_gaps"])
        self.assertEqual(epi.resolve_contest_shape("wta_satellite", blank), "satellite")

    def test_a_curated_objective_class_that_contradicts_its_row_fails_the_load(self):
        """R1c: the column is a cross-check, never a router. Two copies of one
        fact that can disagree is this project's named failure class, so the
        disagreement is fatal at load instead of silent at build time."""
        from mlb_engine.entries.dk_entries_manager import load_archetypes

        header = ("pattern,inferred_buy_in,inferred_type,inferred_max_entries,"
                  "payout_shape_default,confidence,notes,objective_class,ticket_count\n")
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.csv"
            good.write_text(header + "Qualifier,,satellite,,ticket_line,inferred_high,,ticket_line,4\n",
                            encoding="utf-8")
            row = load_archetypes(str(good))[0]
            self.assertEqual(row.objective_class, "ticket_line")
            self.assertEqual(row.ticket_count, 4)

            for bad_line, needle in (
                ("Qualifier,,satellite,,ticket_line,inferred_high,,wta,4\n", "contradicts"),
                ("Qualifier,,satellite,,ticket_line,inferred_high,,not_a_class,4\n", "not one of"),
                ("Qualifier,,satellite,,ticket_line,inferred_high,,,many\n", "not a number"),
                ("Qualifier,,satellite,,ticket_line,inferred_high,,,0\n", "not a count"),
            ):
                bad = Path(tmp) / "bad.csv"
                bad.write_text(header + bad_line, encoding="utf-8")
                with self.assertRaises(ValueError) as ctx:
                    load_archetypes(str(bad))
                self.assertIn(needle, str(ctx.exception))

    def test_the_shipped_archetype_csv_carries_both_columns_and_loads(self):
        """The curated file is the deliverable, not just the parser."""
        from mlb_engine.entries.dk_entries_manager import (
            DEFAULT_ARCHETYPES_CSV, load_archetypes)
        from mlb_engine.contest_shapes import objective_class_for_payout_token

        path = Path(DEFAULT_ARCHETYPES_CSV)
        if not path.exists():  # pragma: no cover - repo-root dependent
            self.skipTest(f"{DEFAULT_ARCHETYPES_CSV} not reachable from cwd")
        rows = load_archetypes(str(path))
        self.assertGreater(len(rows), 15)
        for row in rows:
            implied = objective_class_for_payout_token(row.payout_shape_default)
            if implied is not None:
                self.assertEqual(row.objective_class, implied, row.pattern)

    def test_du_reports_that_it_was_not_enforced_instead_of_passing(self):
        """R15, decision 2026-07-27: delete the dead stage, keep the primitive,
        and stop recording an all-clear for a control that did not run.

        Teeth: production reaches build_multi_lineup through
        build_candidate_lineup_bank with bank_constraint_scope='selection',
        which passes du_threshold_row=None. That used to return
        du_validation={'pass': True}, and execution_pipeline carries the dict
        into every run payload, so every certified build recorded a DU pass for
        a check that never ran.
        """
        row = opt._resolve_du_threshold_row(8, "wta", None)
        self.assertIsNone(row, "explicit None is the production value and means disabled")

        with tempfile.TemporaryDirectory() as tmp:
            frame = projection_frame(write_salary(Path(tmp) / "s.csv"))
        result = opt.build_multi_lineup(frame, n_lineups=2, mode="wta",
                                        target="ceiling", du_threshold_row=None)
        validation = result["du_validation"]
        self.assertFalse(validation["enforced"])
        self.assertIsNone(validation["pass"], "a check that did not run cannot pass")
        self.assertIn("not enforced", validation["pairwise_summary"])

    def test_the_zero_caller_selection_stage_is_gone(self):
        """R15: 327 lines with no caller since they were written, built on the
        subset-then-allocate shape MLB_Classic section 8's opening rule rejects.
        Production selects through contest_allocator.select_and_assign_entries.
        """
        for name in ("select_final_portfolio_from_candidate_bank",
                     "_solve_candidate_subset_milp",
                     "_selection_pairwise_incompatible",
                     "_candidate_explicit_right_tail",
                     # Orphaned by the same delete and missed on the first pass:
                     # its only caller was _solve_candidate_subset_milp.
                     "_candidate_selection_score"):
            self.assertFalse(hasattr(opt, name), f"{name} came back")

    def test_the_bank_stops_reporting_a_handoff_to_the_deleted_stage(self):
        """R15 follow-up. build_candidate_lineup_bank stamped
        selection_du_threshold_row, selection_max_sp_exposure,
        selection_max_sp_pair_repetition and
        bank_constraints_deferred_to_selection=True onto every result. With the
        selection stage deleted, those four described a handoff nothing
        performs, which is the same false label R15 removed from du_validation.
        """
        with tempfile.TemporaryDirectory() as tmp:
            frame = projection_frame(write_salary(Path(tmp) / "s.csv"))
        bank = opt.build_candidate_lineup_bank(frame, requested_n=1,
                                               candidate_bank_size=2, mode="wta")
        for gone in ("selection_du_threshold_row", "selection_max_sp_exposure",
                     "selection_max_sp_pair_repetition",
                     "bank_constraints_deferred_to_selection"):
            self.assertNotIn(gone, bank, gone)
        self.assertEqual(bank["bank_constraint_scope"], "selection")
        self.assertFalse(bank["bank_portfolio_controls_enforced"])

    def test_satellite_family_caps_are_section_8s_numbers(self):
        """R5, dated decision 2026-07-27 (ledger 3.11).

        Teeth: the caps a satellite portfolio is actually built under. These
        reached the solver as 0.60 / 0.70 / 0.60 / 7 while MLB_Classic section 8
        published 0.45 / 0.43 / 0.35 / 5, and duplication is the main enemy in a
        satellite-heavy portfolio. The posture was NOT split, so a true WTA rides
        the same row; the WTA-versus-cut-line difference is carried by
        resolve_contest_shape and asserted separately above.
        """
        controls = epi.STRATEGY_DEFAULTS["wta_satellite"]["controls"]
        self.assertEqual(controls["max_player_exposure_pct"], 0.45)
        self.assertEqual(controls["max_pitcher_exposure_pct"], 0.43)
        self.assertEqual(controls["max_primary_stack_exposure_pct"], 0.35)
        self.assertEqual(controls["max_shared_players"], 5)
        self.assertEqual(controls["max_sp_pair_repetition"], 2)

    def test_the_tightened_caps_reach_a_merged_build(self):
        """The dict is not the contract; what run_slate merges is."""
        merged = epi._merged_controls_for_build(
            {"c1": {"posture": "wta_satellite"}}, None)
        self.assertEqual(merged["max_pitcher_exposure_pct"], 0.43)
        self.assertEqual(merged["max_shared_players"], 5)
        # Tightest cap wins across contests, so a satellite beside a large_gpp
        # cannot loosen the satellite row.
        both = epi._merged_controls_for_build(
            {"c1": {"posture": "wta_satellite"}, "c2": {"posture": "large_gpp"}}, None)
        self.assertEqual(both["max_pitcher_exposure_pct"], 0.43)
        self.assertEqual(both["max_primary_stack_exposure_pct"], 0.35)
        # An explicit override still wins over the tightened default, and a
        # feasibility floor still relaxes it, both unchanged by R5.
        self.assertEqual(
            epi._merged_controls_for_build(
                {"c1": {"posture": "wta_satellite"}},
                {"max_pitcher_exposure_pct": 1.0})["max_pitcher_exposure_pct"], 1.0)
        self.assertEqual(
            epi._merged_controls_for_build(
                {"c1": {"posture": "wta_satellite"}}, None,
                {"max_shared_players": 8})["max_shared_players"], 8)

    def test_every_posture_resolves_to_a_real_profile_key(self):
        from mlb_engine.contest_shapes import CONTEST_SHAPE_SET
        postures = list(epi.STRATEGY_DEFAULTS) + ["not_a_posture"]
        for posture in postures:
            shape = epi._posture_to_shape(posture)
            self.assertIn(shape, CONTEST_SHAPE_SET, posture)
            # The real regression: this raised for mme before R1a.
            self.assertEqual(
                opt.resolve_contest_shape_profile(contest_shape=shape)["contest_shape"], shape)

    def test_satellite_reaches_the_ticket_line_profile_not_large_wta(self):
        inferred = {"inferred_type": "satellite", "payout_shape_default": "ticket_line"}
        shape = epi.resolve_contest_shape("wta_satellite", inferred)
        self.assertEqual(shape, "satellite")
        profile = opt.resolve_contest_shape_profile(contest_shape=shape)
        self.assertEqual(profile["mode_family"], "ticket_line")
        self.assertGreater(profile["floor_weight"], 0.0)

    def test_single_ticket_satellite_routes_to_the_wta_ticket_profile(self):
        inferred = {"inferred_type": "satellite", "payout_shape_default": "ticket_line",
                    "ticket_count": 1}
        self.assertEqual(epi.resolve_contest_shape("wta_satellite", inferred),
                         "wta_ticket_satellite")

    def test_true_wta_and_operator_override_are_untouched(self):
        self.assertEqual(
            epi.resolve_contest_shape("wta_satellite",
                                      {"inferred_type": "wta",
                                       "payout_shape_default": "winner_take_all"}),
            "large_wta")
        self.assertEqual(
            epi.resolve_contest_shape("wta_satellite",
                                      {"inferred_type": "satellite",
                                       "contest_shape": "large_wta"}),
            "large_wta")
        with self.assertRaises(ValueError):
            epi.resolve_contest_shape("cash", {"contest_shape": "invented_shape"})

    def test_satellite_keeps_its_caps_posture_and_its_construction_mode(self):
        """R1 moves the ranking objective only. The posture (caps) and the MILP
        construction mode both stay put; the caps divergence is backlog R5."""
        from mlb_engine.contest_shapes import WTA_CONSTRUCTION_SHAPES
        self.assertEqual(normalize_posture("satellite", "ticket_line", None), "wta_satellite")
        for shape in ("satellite", "wta_ticket_satellite", "large_wta"):
            self.assertIn(shape, WTA_CONSTRUCTION_SHAPES)

    def test_a_satellite_named_contest_routes_end_to_end(self):
        from mlb_engine.entries.dk_entries_manager import (
            infer_contest_archetype, load_archetypes,
        )
        archetypes = load_archetypes(None)
        cases = {
            "MLB $5 Satellite to the $2 Pocket Cup MEGA Qualifier": "satellite",
            "MLB $10 Winner Take All": "large_wta",
            "MLB $5 Double Up": "cash",
        }
        for name, expected in cases.items():
            inferred = infer_contest_archetype(name, 5.0, archetypes)
            posture = normalize_posture(inferred.get("inferred_type"),
                                        inferred.get("payout_shape_default"),
                                        inferred.get("inferred_max_entries"))
            self.assertEqual(epi.resolve_contest_shape(posture, inferred), expected, name)

    def test_payout_breadth_fallback_covers_every_canonical_shape(self):
        from mlb_engine.contest_shapes import CONTEST_SHAPES
        for shape in CONTEST_SHAPES:
            self.assertIn(shape, epi.PAYOUT_BREADTH_BY_SHAPE, shape)
        satellite = epi._resolve_payout_breadth(
            {"contest_shape": "satellite", "inferred": {}}, epi.PAYOUT_BREADTH_BY_SHAPE)
        wta = epi._resolve_payout_breadth(
            {"contest_shape": "large_wta", "inferred": {}}, epi.PAYOUT_BREADTH_BY_SHAPE)
        self.assertGreater(satellite, wta)

    def test_archetype_csv_parses_with_every_breadth_a_number(self):
        """The ' SE' row carried unquoted commas in notes, so csv.DictReader put
        ' POSE' in payout_breadth and the rest of the line in the restkey. It
        fell back to the in-code prior silently; any new column would have
        landed in the wrong field."""
        from mlb_engine.entries.dk_entries_manager import find_archetypes_csv
        path = find_archetypes_csv()
        self.assertIsNotNone(path)
        with Path(path).open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(row.get(None), row.get("pattern"))
            float(row["payout_breadth"])


class TicketLineScoringTests(unittest.TestCase):
    """R1b/R1d: a ticket contest is ranked on the cut line, and no profile key
    is decoration.

    Teeth: score_lineup_candidate blended ceiling and floor for the `cash` mode
    family only, so the satellite profile advertised floor_weight 0.42 and took
    pure ceiling. `leverage_bonus_weight` and `right_tail_weight` were defined on
    all twelve profiles and read by nothing.
    """

    POSITIONS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]

    def _lineup(self, ceilings, floors):
        n = len(ceilings)
        return pd.DataFrame({
            "Player_ID": [f"p{i}" for i in range(n)],
            "Name": [f"P{i}" for i in range(n)],
            "Position": self.POSITIONS[:n],
            "Team": ["AAA"] * n,
            "Opponent": ["ZZZ"] * n,
            "Salary": [4000] * n,
            "Ceiling": ceilings,
            "Floor": floors,
        })

    def test_ticket_line_blends_floor_where_wta_takes_pure_ceiling(self):
        lineup = self._lineup([12.0] * 10, [7.0] * 10)
        sat = opt.score_lineup_candidate(lineup, contest_shape="satellite")
        wta = opt.score_lineup_candidate(lineup, mode="wta", contest_shape="large_wta")
        self.assertEqual(wta["score_components"]["projection"], wta["ceiling_sum"])
        expected = 0.58 * sat["ceiling_sum"] + 0.42 * sat["floor_sum"]
        self.assertAlmostEqual(sat["score_components"]["projection"], expected, places=6)
        self.assertNotEqual(sat["score_components"]["projection"], sat["ceiling_sum"])

    def test_floor_changes_a_ticket_ranking_and_leaves_wta_ranking_alone(self):
        """The observable consequence: on one bank, two lineups with the same
        ceiling and different floors tie under WTA and separate under a ticket
        line. That is the objective actually changing, not a relabel."""
        high_floor = self._lineup([12.0] * 10, [9.0] * 10)
        low_floor = self._lineup([12.0] * 10, [4.0] * 10)
        wta_scores = [opt.score_lineup_candidate(x, mode="wta", contest_shape="large_wta")
                      ["contest_fit_score"] for x in (high_floor, low_floor)]
        sat_scores = [opt.score_lineup_candidate(x, contest_shape="satellite")
                      ["contest_fit_score"] for x in (high_floor, low_floor)]
        self.assertAlmostEqual(wta_scores[0], wta_scores[1], places=6)
        self.assertGreater(sat_scores[0], sat_scores[1])

    def test_the_gpp_family_advertises_no_split_it_does_not_apply(self):
        """Ledger 3.12, 2026-07-27. Teeth: six gpp profiles carried a
        ceiling/floor pair that projection_component never read, and the ladder
        ran backwards, giving more floor weight as the field grew. Deleting the
        keys is the decision; this asserts the table cannot re-grow them without
        someone also wiring the branch that would consume them.
        """
        for shape, profile in opt.CONTEST_SHAPE_PROFILE_WEIGHTS.items():
            if profile["mode_family"] != "gpp":
                continue
            self.assertNotIn("ceiling_weight", profile, shape)
            self.assertNotIn("floor_weight", profile, shape)
        # And the score still takes raw ceiling for a gpp shape, unchanged.
        lineup = self._lineup([12.0] * 10, [7.0] * 10)
        gpp = opt.score_lineup_candidate(lineup, contest_shape="large_field_gpp")
        self.assertEqual(gpp["score_components"]["projection"], gpp["ceiling_sum"])
        # The two families whose objective IS floor-ish keep their blend.
        for shape in ("cash", "satellite"):
            self.assertIn("floor_weight", opt.CONTEST_SHAPE_PROFILE_WEIGHTS[shape])

    def test_the_metric_is_labelled_a_proxy_and_names_the_right_objective(self):
        lineup = self._lineup([12.0] * 10, [7.0] * 10)
        sat = opt.score_lineup_candidate(lineup, contest_shape="satellite")
        self.assertEqual(sat["contest_fit_metric"], "Ticket_Line_Advance_Proxy")
        self.assertIn("Ticket_Line_Advance_Proxy", sat)
        # Never a probability, a cash rate, or an ROI claim.
        for key in sat:
            lowered = str(key).lower()
            for banned in ("roi", "win_rate", "cash_rate", "probability", "p_win"):
                self.assertNotIn(banned, lowered)
        self.assertEqual(opt._mode_for_contest_shape("satellite", "wta"), "ticket_line")
        self.assertEqual(opt._mode_for_contest_shape("large_wta", "wta"), "wta")

    def test_no_profile_weight_is_decoration_outside_one_named_exception(self):
        """RC 1.2's contract test, cheap form: perturb each weight on each shape
        against a fixed lineup and require the score to move.

        One exception survives and it is in the name so it cannot hide. On the
        `wta` family ceiling/floor are 1.00/0.00, so the blend equals raw ceiling
        and skipping it is a no-op. The `gpp` family used to be the second
        exception and it was a live contradiction: six profiles advertised splits
        from 0.80/0.20 to 0.70/0.30 while projection_component took pure ceiling.
        Decided 2026-07-27 (ledger 3.12): the pair is deleted from the gpp
        profiles, so there is nothing left to exempt. The rule is back to one
        line: a weight in the table is consumed, or it is not in the table.
        """
        known_inert = {"wta": {"ceiling_weight", "floor_weight"}}
        lineup = self._lineup([12.0, 11.0, 10.5, 10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0],
                              [6.0, 5.5, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5])
        lineup.loc[:4, "Team"] = "BBB"
        lineup["Batting_Order"] = [1, 2, 3, 4, 5, 1, 2, 3, 4, 0]
        lineup["Projected_Ownership_Pct"] = [20.0] * 10
        lineup.loc[:4, "Salary"] = 5200
        for shape, profile in sorted(opt.CONTEST_SHAPE_PROFILE_WEIGHTS.items()):
            family = profile["mode_family"]
            base = opt.score_lineup_candidate(lineup, contest_shape=shape)["contest_fit_score"]
            for key, value in sorted(profile.items()):
                if key == "mode_family":
                    continue
                if key in known_inert.get(family, set()):
                    continue
                patched = dict(opt.CONTEST_SHAPE_PROFILE_WEIGHTS)
                patched[shape] = dict(profile, **{key: float(value) + 1.5})
                with unittest.mock.patch.object(
                        opt, "CONTEST_SHAPE_PROFILE_WEIGHTS", patched):
                    moved = opt.score_lineup_candidate(
                        lineup, contest_shape=shape)["contest_fit_score"]
                self.assertNotAlmostEqual(
                    moved, base, places=6,
                    msg=f"{shape}.{key} is defined and never reaches the score")

    def test_the_blend_is_inert_on_uniform_proxy_projections(self):
        """Stated so it is not rediscovered as a bug. Under the emergency-proxy
        path every Floor is 0.58*Base and every Ceiling is 1.42*Base, so the
        0.58/0.42 blend is a fixed 0.7515 multiple of ceiling and cannot reorder
        anything. That is why the golden replay did not move on R1b, and it is
        why the ticket objective only bites once Floor carries information
        independent of Ceiling (the enriched path)."""
        ratios = []
        for bases in ([10, 9, 9, 8, 8, 7, 7, 6, 6, 5],
                      [12, 8, 8, 8, 8, 7, 7, 6, 6, 4]):
            lineup = self._lineup([b * 1.42 for b in bases], [b * 0.58 for b in bases])
            scored = opt.score_lineup_candidate(lineup, contest_shape="satellite")
            ratios.append(scored["score_components"]["projection"] / scored["ceiling_sum"])
        self.assertAlmostEqual(ratios[0], ratios[1], places=9)
        self.assertAlmostEqual(ratios[0], 0.58 * 1.42 / 1.42 + 0.42 * 0.58 / 1.42, places=9)

    def test_the_deleted_knobs_are_gone_from_every_profile(self):
        for shape, profile in opt.CONTEST_SHAPE_PROFILE_WEIGHTS.items():
            self.assertNotIn("leverage_bonus_weight", profile, shape)
            self.assertNotIn("right_tail_weight", profile, shape)
        # The signal itself still ships; only the unread weight is gone.
        payload = opt.score_lineup_candidate(
            self._lineup([12.0] * 10, [7.0] * 10), contest_shape="satellite")
        self.assertIn("right_tail_bonus", payload)
        self.assertIn("right_tail_volatility_counts", payload)


class TailCandidateScannerTests(unittest.TestCase):
    """Tests for tail_candidate_scanner.scan_tail_candidates."""

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------

    def _write_park_factors(self, path: Path, rows=None):
        default = [
            {"Venue": "Hitter Park", "Run_Factor_Raw": "1.10", "HR_Factor_Raw": "1.10",
             "Run_Factor_Applied": "1.08", "HR_Factor_Applied": "1.08", "Wind_Sensitivity": "Medium", "Last_Updated": "2026-01-01"},
            {"Venue": "Pitcher Park", "Run_Factor_Raw": "0.90", "HR_Factor_Raw": "0.90",
             "Run_Factor_Applied": "0.94", "HR_Factor_Applied": "0.94", "Wind_Sensitivity": "Medium", "Last_Updated": "2026-01-01"},
        ]
        rows = rows or default
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)

    def _write_team_venues(self, path: Path, rows=None):
        default = [
            {"Home_Team": "AAA", "Venue": "Hitter Park", "Roof_Type": "outdoor",
             "CF_Azimuth_Degrees": "45", "Default_Wind_Direction": "cross",
             "Latitude": "40.0", "Longitude": "-75.0", "Timezone": "America/New_York",
             "Weather_Required": "true", "Wind_Sensitivity": "moderate",
             "Wind_Min_Speed_MPH": "13", "Roof_Status_Source": "default", "Last_Verified": "2026-01-01"},
            {"Home_Team": "BBB", "Venue": "Pitcher Park", "Roof_Type": "outdoor",
             "CF_Azimuth_Degrees": "45", "Default_Wind_Direction": "cross",
             "Latitude": "41.0", "Longitude": "-76.0", "Timezone": "America/New_York",
             "Weather_Required": "true", "Wind_Sensitivity": "moderate",
             "Wind_Min_Speed_MPH": "13", "Roof_Status_Source": "default", "Last_Verified": "2026-01-01"},
        ]
        rows = rows or default
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)

    def _write_statcast_pitching(self, path: Path, rows=None):
        default = [
            {"last_name": "Lucky", "first_name": "Sam", "player_id": "1001", "year": "2026",
             "pa": "450", "bip": "200", "ba": "0.250", "est_ba": "0.270",
             "est_ba_minus_ba_diff": "0.020", "slg": "0.400", "est_slg": "0.430",
             "est_slg_minus_slg_diff": "0.030", "woba": "0.310", "est_woba": "0.340",
             "est_woba_minus_woba_diff": "0.030", "era": "3.00", "xera": "3.50",
             "era_minus_xera_diff": "-0.50"},
            {"last_name": "Solid", "first_name": "Tom", "player_id": "1002", "year": "2026",
             "pa": "420", "bip": "180", "ba": "0.255", "est_ba": "0.255",
             "est_ba_minus_ba_diff": "0.000", "slg": "0.410", "est_slg": "0.410",
             "est_slg_minus_slg_diff": "0.000", "woba": "0.315", "est_woba": "0.315",
             "est_woba_minus_woba_diff": "0.000", "era": "3.80", "xera": "3.85",
             "era_minus_xera_diff": "-0.05"},
            {"last_name": "Bulk", "first_name": "Joe", "player_id": "1003", "year": "2026",
             "pa": "120", "bip": "50", "ba": "0.270", "est_ba": "0.270",
             "est_ba_minus_ba_diff": "0.000", "slg": "0.430", "est_slg": "0.430",
             "est_slg_minus_slg_diff": "0.000", "woba": "0.330", "est_woba": "0.330",
             "est_woba_minus_woba_diff": "0.000", "era": "4.50", "xera": "4.55",
             "era_minus_xera_diff": "-0.05"},
        ]
        rows = rows or default
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)

    def _odds_json(self, away="CCC", home="AAA", dk=7.0, fd=7.5):
        # Passes abbreviations directly; _odds_by_game falls back to raw string
        # for names not in the full-team-name map, which is fine for test fixtures.
        return {
            "games": [{
                "away_team": away,
                "home_team": home,
                "books": {
                    "draftkings": {"total": {"line": dk, "over": -110, "under": -110}},
                    "fanduel": {"total": {"line": fd, "over": -108, "under": -112}},
                },
            }]
        }

    def _lineups_json(self, away="CCC", home="AAA", away_pid=1002, home_pid=1001,
                      away_name="Tom Solid", home_name="Sam Lucky"):
        return {
            "games": [{
                "away": {"team_abbrev": away, "probable_pitcher": {"id": away_pid, "name": away_name, "hand": "R"}},
                "home": {"team_abbrev": home, "probable_pitcher": {"id": home_pid, "name": home_name, "hand": "R"}},
            }]
        }

    def _slate(self, away="CCC", home="AAA"):
        return [{"away_team": away, "home_team": home, "game_id": f"{away}@{home}"}]

    def _run(self, tmp, away="CCC", home="AAA", odds=None, lineups=None, thresholds=None, statcast=True):
        from mlb_engine.optimize.tail_candidate_scanner import scan_tail_candidates
        park = Path(tmp) / "pf.csv"; self._write_park_factors(park)
        venues = Path(tmp) / "tv.csv"; self._write_team_venues(venues)
        sc_path = None
        if statcast:
            sc_path = Path(tmp) / "sc.csv"; self._write_statcast_pitching(sc_path)
        return scan_tail_candidates(
            game_slate=self._slate(away, home),
            park_factors_path=park,
            team_to_venue_path=venues,
            savant_pitching_path=sc_path,
            odds_json=odds,
            lineups_json=lineups,
            thresholds=thresholds,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_tail_scanner_full_coverage_flags_game(self):
        # Lucky SP (gap 0.50 >= 0.30) + book spread (0.50 >= 0.50) => score 2 => flagged
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp,
                odds=self._odds_json(dk=7.0, fd=7.5),
                lineups=self._lineups_json(home_pid=1001, home_name="Sam Lucky"),
            )
            self.assertEqual(result["coverage_tier"], "full")
            self.assertGreaterEqual(len(result["flagged_games"]), 1)
            game = result["all_games"][0]
            self.assertGreaterEqual(game["tail_score"], 2.0)
            self.assertEqual(game["signals"]["era_xera_gap"]["status"], "triggered")
            self.assertEqual(game["signals"]["book_spread"]["status"], "triggered")

    def test_tail_scanner_no_signals_no_flag(self):
        # Solid SP (gap 0.05 < 0.30) + books agree (spread 0) + pitcher park => score 0
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp, home="BBB",  # Pitcher Park, run_factor 0.94
                odds=self._odds_json(home="BBB", dk=8.5, fd=8.5),
                lineups=self._lineups_json(home="BBB", home_pid=1002, home_name="Tom Solid"),
            )
            self.assertEqual(result["flagged_games"], [])
            game = result["all_games"][0]
            self.assertEqual(game["tail_score"], 0.0)

    def test_tail_scanner_park_only_fallback(self):
        # No statcast, no odds => park_only tier; park_total_div is partial for hitter park
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, statcast=False)
            self.assertEqual(result["coverage_tier"], "park_only")
            self.assertIn("era_xera_gap", result["signals_unavailable"])
            self.assertIn("book_spread", result["signals_unavailable"])
            game = result["all_games"][0]
            # Hitter Park (1.08 >= 1.04) with no implied total => partial
            self.assertEqual(game["signals"]["park_total_div"]["status"], "partial")

    def test_tail_scanner_statcast_park_tier(self):
        # Statcast + lineups but no odds => statcast_park tier
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp,
                lineups=self._lineups_json(home_pid=1001, home_name="Sam Lucky"),
            )
            self.assertEqual(result["coverage_tier"], "statcast_park")
            self.assertIn("book_spread", result["signals_unavailable"])
            # ERA/xERA still computable
            game = result["all_games"][0]
            self.assertIn(game["signals"]["era_xera_gap"]["status"], ("triggered", "not_triggered"))

    def test_tail_scanner_era_xera_gap_threshold(self):
        # Gap 0.50 (xERA 3.50, ERA 3.00) triggers at default 0.30; just-below gap does not
        with tempfile.TemporaryDirectory() as tmp:
            from mlb_engine.optimize.tail_candidate_scanner import _era_xera_signal, _load_statcast_pitching
            sc = Path(tmp) / "sc.csv"; self._write_statcast_pitching(sc)
            statcast = _load_statcast_pitching(sc)
            # Player 1001: gap = 3.50 - 3.00 = 0.50
            sig = _era_xera_signal(None, 1001, statcast, threshold=0.30)
            self.assertEqual(sig["status"], "triggered")
            self.assertAlmostEqual(sig["value"], 0.50, places=3)
            # Player 1002: gap = 3.85 - 3.80 = 0.05 => not triggered
            sig2 = _era_xera_signal(None, 1002, statcast, threshold=0.30)
            self.assertEqual(sig2["status"], "not_triggered")

    def test_tail_scanner_book_spread_threshold(self):
        # Spread 0.50 triggers; spread 0.25 does not
        from mlb_engine.optimize.tail_candidate_scanner import _book_spread_signal
        self.assertEqual(_book_spread_signal(7.0, 7.5, 0.50)["status"], "triggered")
        self.assertEqual(_book_spread_signal(7.0, 7.25, 0.50)["status"], "not_triggered")
        self.assertEqual(_book_spread_signal(None, 7.5, 0.50)["status"], "unavailable")

    def test_tail_scanner_park_total_divergence_threshold(self):
        # run_factor 1.08, baseline 8.5 => expected 9.18; implied 7.5
        # divergence = (9.18 - 7.5) / 9.18 = 0.183 => triggers at 0.06
        from mlb_engine.optimize.tail_candidate_scanner import _park_total_signal
        sig = _park_total_signal(1.08, 7.5, park_factor_min=1.04, div_min=0.06)
        self.assertEqual(sig["status"], "triggered")
        self.assertGreater(sig["value"], 0.06)
        # Implied total close to expected => not triggered
        sig2 = _park_total_signal(1.04, 8.8, park_factor_min=1.04, div_min=0.06)
        self.assertEqual(sig2["status"], "not_triggered")

    def test_tail_scanner_pitcher_role_bulk_flag(self):
        # Player 1003 has PA=120 <= default 200 => triggered; player 1001 has PA=450 => not
        with tempfile.TemporaryDirectory() as tmp:
            from mlb_engine.optimize.tail_candidate_scanner import _pitcher_role_signal, _load_statcast_pitching
            sc = Path(tmp) / "sc.csv"; self._write_statcast_pitching(sc)
            statcast = _load_statcast_pitching(sc)
            sig = _pitcher_role_signal(None, 1003, None, "Joe Bulk", statcast, pa_max=200)
            self.assertEqual(sig["status"], "triggered")
            self.assertEqual(sig["flagged_pitchers"][0]["pa"], 120)
            # High-PA pitcher not flagged
            sig2 = _pitcher_role_signal(None, 1001, None, "Sam Lucky", statcast, pa_max=200)
            self.assertEqual(sig2["status"], "not_triggered")

    def test_tail_scanner_threshold_override(self):
        # Raise era_xera_gap_min to 0.60 => gap 0.50 should NOT trigger
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp,
                odds=self._odds_json(dk=7.0, fd=7.5),
                lineups=self._lineups_json(home_pid=1001, home_name="Sam Lucky"),
                thresholds={"era_xera_gap_min": 0.60},
            )
            game = result["all_games"][0]
            self.assertEqual(game["signals"]["era_xera_gap"]["status"], "not_triggered")
            self.assertIn("era_xera_gap_min", result["thresholds_applied"])
            self.assertAlmostEqual(result["thresholds_applied"]["era_xera_gap_min"], 0.60)

    def test_tail_scanner_partial_park_no_odds(self):
        # Hitter-friendly park + no odds => park_total_div partial, score 0.5
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp,
                lineups=self._lineups_json(home_pid=1002, home_name="Tom Solid"),
                # home=AAA => Hitter Park (1.08); no odds supplied
            )
            game = result["all_games"][0]
            self.assertEqual(game["signals"]["park_total_div"]["status"], "partial")
            self.assertAlmostEqual(game["tail_score"], 0.5, places=2)


class FillDepthPlanTests(unittest.TestCase):
    """v1.3 game-script fill-depth determination, contest routing, and coverage."""

    def _ranking(self):
        return [
            {"script": "BOS", "game": "BOS@COL", "stack_ceiling": 87.3, "ceiling_ratio": 1.0},
            {"script": "LAA", "game": "BAL@LAA", "stack_ceiling": 71.6, "ceiling_ratio": 0.82},
            {"script": "BAL", "game": "BAL@LAA", "stack_ceiling": 54.4, "ceiling_ratio": 0.62},
            {"script": "COL", "game": "BOS@COL", "stack_ceiling": 54.3, "ceiling_ratio": 0.62},
            {"script": "CHC", "game": "CHC@NYM", "stack_ceiling": 52.2, "ceiling_ratio": 0.60},
        ]

    def test_single_entry_fill_depth_is_one(self):
        self.assertEqual(epi.compute_contest_fill_depth(1, 0.01, "single_entry")["fill_depth"], 1)

    def test_high_volume_satellite_fills_deep(self):
        d = epi.compute_contest_fill_depth(20, 0.22)  # broad ticket payout -> low saturation
        self.assertEqual(d["lineups_per_script_prior"], 4)
        self.assertEqual(d["fill_depth"], 5)
        self.assertEqual(epi.compute_contest_fill_depth(20, 0.22, n_viable_scripts=3)["fill_depth"], 3)

    def test_small_satellite_stays_shallow(self):
        self.assertEqual(epi.compute_contest_fill_depth(5, 0.22)["fill_depth"], 2)

    def test_script_saturation_is_inverse_to_breadth(self):
        self.assertGreater(epi._script_saturation(0.01), epi._script_saturation(0.22))
        self.assertEqual(epi._script_saturation(0.0, "cash"), 9)

    def test_rank_game_scripts_orders_by_ceiling_and_excludes_pitchers(self):
        frame = pd.DataFrame([
            {"Player_ID": "1", "Stack_Group": "BOS", "Position": "OF", "Ceiling": 20.0, "Game_ID": "BOS@COL"},
            {"Player_ID": "2", "Stack_Group": "BOS", "Position": "1B", "Ceiling": 18.0, "Game_ID": "BOS@COL"},
            {"Player_ID": "3", "Stack_Group": "BOS", "Position": "P", "Ceiling": 40.0, "Game_ID": "BOS@COL"},
            {"Player_ID": "4", "Stack_Group": "COL", "Position": "OF", "Ceiling": 9.0, "Game_ID": "BOS@COL"},
        ])
        ranked = epi.rank_game_scripts(frame)
        self.assertEqual([r["script"] for r in ranked], ["BOS", "COL"])
        self.assertEqual(ranked[0]["stack_ceiling"], 38.0)  # pitcher ceiling excluded
        self.assertEqual(ranked[0]["game"], "BOS@COL")

    def test_rank_game_scripts_defensive_on_missing_columns(self):
        self.assertEqual(epi.rank_game_scripts(pd.DataFrame([{"x": 1}])), [])
        self.assertEqual(epi.rank_game_scripts(None), [])

    def test_fill_depth_plan_marks_contrarian_slots(self):
        contest_rows = [{"contest_id": "SE"}] + [{"contest_id": "BIG"}] * 20
        postures = {
            "SE": {"contest_id": "SE", "contest_name": "Daily Dollar", "posture": "single_entry",
                   "contest_shape": "single_entry_gpp", "inferred": {"payout_shape_default": "single_entry_gpp"}},
            "BIG": {"contest_id": "BIG", "contest_name": "SuperSat", "posture": "wta_satellite",
                    "contest_shape": "ticket_line", "inferred": {"payout_shape_default": "ticket_line"}},
        }
        plan = epi.build_fill_depth_plan(contest_rows, postures, game_script_ranking=self._ranking(),
                                         scanner_flagged_games=["BAL@LAA"])
        by = {c["contest_id"]: c for c in plan["contests"]}
        self.assertEqual(by["SE"]["fill_depth"], 1)
        self.assertEqual(by["SE"]["contrarian_slots"], 0)
        self.assertEqual(by["BIG"]["fill_depth"], 5)
        self.assertGreaterEqual(by["BIG"]["contrarian_slots"], 1)
        self.assertIn("BAL", by["BIG"]["contrarian_scripts_recommended"])
        self.assertIn("BAL", by["BIG"]["scanner_flagged_contrarian_scripts"])
        self.assertEqual(plan["primary_scripts"], ["BOS", "LAA"])

    def test_emit_routing_pins_single_entry_and_guards(self):
        cands = [candidate("L1", [], 165.9, "BOS"), candidate("L2", [], 150.0, "LAA"),
                 candidate("L3", [], 120.0, "BAL")]
        plan = {"contests": [
            {"contest_id": "SE", "posture": "single_entry",
             "primary_scripts_covered": ["BOS"], "contrarian_scripts_recommended": []},
            {"contest_id": "BIG", "posture": "wta_satellite",
             "primary_scripts_covered": ["BOS", "LAA"], "contrarian_scripts_recommended": ["BAL"]},
        ]}
        reqs = [{"entry_id": "e0", "contest_id": "SE"}] + \
               [{"entry_id": f"e{i}", "contest_id": "BIG"} for i in range(1, 3)]
        routing = epi.emit_contest_routing(plan, cands, reqs)
        amap = routing["allowed_candidate_ids_by_entry"]
        self.assertEqual(amap["e0"], ["L1"])  # highest-ceiling lineup pinned to single-entry
        self.assertEqual(set(amap["e1"]), {"L1", "L2", "L3"})
        plan2 = {"contests": [{"contest_id": "TINY", "posture": "wta_satellite",
                               "primary_scripts_covered": ["BOS"], "contrarian_scripts_recommended": []}]}
        reqs2 = [{"entry_id": "t1", "contest_id": "TINY"}, {"entry_id": "t2", "contest_id": "TINY"}]
        r2 = epi.emit_contest_routing(plan2, cands, reqs2)
        self.assertEqual(r2["allowed_candidate_ids_by_entry"], {})
        self.assertTrue(r2["warnings"])

    def test_game_script_coverage_counts_distinct(self):
        frame = pd.DataFrame([
            {"Player_ID": "1", "Stack_Group": "BOS", "Position": "OF", "Ceiling": 20.0, "Game_ID": "BOS@COL"},
            {"Player_ID": "2", "Stack_Group": "LAA", "Position": "OF", "Ceiling": 18.0, "Game_ID": "BAL@LAA"},
            {"Player_ID": "3", "Stack_Group": "BAL", "Position": "OF", "Ceiling": 9.0, "Game_ID": "BAL@LAA"},
        ])
        cands = [candidate("L1", [], 100, "BOS"), candidate("L2", [], 99, "LAA"),
                 candidate("L3", [], 98, "BOS")]
        cov = epi.compute_game_script_coverage(frame, cands)
        self.assertEqual(cov["n_scripts_covered"], 2)
        self.assertEqual(set(cov["scripts_covered"]), {"BOS", "LAA"})
        self.assertEqual(cov["n_viable_scripts"], 3)


class BankDiversificationGuardrailTests(unittest.TestCase):
    """v2.21.0 contested-slot guardrail and bank player-coverage net."""

    def _frame(self):
        return pd.DataFrame([
            {"Player_ID": "Y", "Name": "Flex Bat", "Team": "TB", "Position": "1B/3B", "Ceiling": 12.5},
            {"Player_ID": "C", "Name": "Pure Third", "Team": "TB", "Position": "3B", "Ceiling": 11.9},
            {"Player_ID": "A", "Name": "Pure First", "Team": "TB", "Position": "1B", "Ceiling": 11.7},
            {"Player_ID": "O", "Name": "Out Fielder", "Team": "SEA", "Position": "OF", "Ceiling": 10.0},
            {"Player_ID": "P", "Name": "Some Arm", "Team": "SEA", "Position": "P", "Ceiling": 30.0},
        ])

    def test_contested_slot_audit_flags_crowded_out_single_position_hitter(self):
        res = epi.contested_slot_audit(self._frame())
        flagged = {r["displaceable_player_id"]: r for r in res["contested_slots"]}
        self.assertIn("C", flagged)  # pure 3B crowded by flex 1B/3B of higher ceiling
        self.assertEqual(flagged["C"]["slot"], "3B")
        self.assertIn("Y", [c["player_id"] for c in flagged["C"]["covered_by"]])
        self.assertNotIn("Y", flagged)  # the multi-eligible bat is never the displaceable one

    def test_contested_slot_audit_no_flag_when_single_position_hitter_is_top(self):
        frame = pd.DataFrame([
            {"Player_ID": "C", "Name": "Pure Third", "Team": "TB", "Position": "3B", "Ceiling": 13.0},
            {"Player_ID": "Y", "Name": "Flex Bat", "Team": "TB", "Position": "1B/3B", "Ceiling": 12.0},
        ])
        res = epi.contested_slot_audit(frame)
        self.assertEqual(res["contested_slots"], [])  # nobody outranks the pure 3B at 3B

    def test_audit_bank_player_coverage_flags_absent_top_hitter(self):
        cands = [{"candidate_id": "L1", "player_ids": ["Y", "A", "O"]}]  # no "C"
        res = epi.audit_bank_player_coverage(cands, self._frame())
        self.assertFalse(res["passed"])
        self.assertIn("C", [a["player_id"] for a in res["absent_players"]])

    def test_audit_bank_player_coverage_passes_when_all_top_present(self):
        cands = [{"candidate_id": "L1", "player_ids": ["Y", "C", "A", "O"]}]
        res = epi.audit_bank_player_coverage(cands, self._frame())
        self.assertTrue(res["passed"])
        self.assertEqual(res["absent_players"], [])

    def test_generate_positional_variant_candidates_locks_focus_player(self):
        def fake_builder(projections, target="ceiling", locks=None, stack_constraints=None,
                         bringback_constraint=None):
            self.assertIn("C", locks or [])  # focus appended to locks
            lu = pd.DataFrame([
                {"Assigned_Slot": "P1", "Player_ID": "P", "Team": "SEA", "Ceiling": 30.0, "Floor": 12.0},
                {"Assigned_Slot": "3B", "Player_ID": "C", "Team": "TB", "Ceiling": 11.9, "Floor": 4.9},
            ])
            return lu, 41.9

        out = epi.generate_positional_variant_candidates(
            self._frame(), "C", [{"locks": ["P"], "stack_constraints": {"team": "TB"}}],
            builder=fake_builder)
        self.assertEqual(len(out), 1)
        self.assertIn("C", out[0]["player_ids"])
        self.assertTrue(out[0]["candidate_id"].startswith("VAR"))


class PlatoonOrderAdapterTests(unittest.TestCase):
    """v2.22.0: FanGraphs platoon-order adapter -- TBD fallback and mispricing screen."""

    def _platoon(self):
        # Team AAA, names matching the salary fixture. SS jumps 5 (vs R) -> 1 (vs L);
        # C drops 1 -> 2; OF3 appears only vs L (a strict-platoon bat in the L view).
        return {"collected_date": "2026-06-30", "teams": [{
            "abbrev": "AAA",
            "vs_RHP": [
                {"slot": 1, "position": "C", "player": "AAA C", "bats": "R"},
                {"slot": 2, "position": "1B", "player": "AAA 1B", "bats": "L"},
                {"slot": 3, "position": "2B", "player": "AAA 2B", "bats": "R"},
                {"slot": 4, "position": "3B", "player": "AAA 3B", "bats": "L"},
                {"slot": 5, "position": "SS", "player": "AAA SS", "bats": "R"},
                {"slot": 6, "position": "OF", "player": "AAA OF1", "bats": "L"},
                {"slot": 7, "position": "OF", "player": "AAA OF2", "bats": "R"},
            ],
            "vs_LHP": [
                {"slot": 1, "position": "SS", "player": "AAA SS", "bats": "R"},
                {"slot": 2, "position": "C", "player": "AAA C", "bats": "R"},
                {"slot": 3, "position": "1B", "player": "AAA 1B", "bats": "L"},
                {"slot": 4, "position": "2B", "player": "AAA 2B", "bats": "R"},
                {"slot": 5, "position": "3B", "player": "AAA 3B", "bats": "L"},
                {"slot": 6, "position": "OF", "player": "AAA OF1", "bats": "L"},
                {"slot": 7, "position": "OF", "player": "AAA OF2", "bats": "R"},
                {"slot": 8, "position": "OF", "player": "AAA OF3", "bats": "L"},
            ],
        }]}

    def test_extract_opp_throws_maps_to_opposing_hand(self):
        feed = {"games": [{
            "away": {"team_abbrev": "AAA", "probable_pitcher": {"name": "Pitcher A", "hand": "R"}},
            "home": {"team_abbrev": "BBB", "probable_pitcher": {"name": "Pitcher B", "hand": "L"}},
        }]}
        out = poa.extract_opp_throws_from_lineups(feed)
        self.assertEqual(out["AAA"], "L")  # AAA faces the home LHP
        self.assertEqual(out["BBB"], "R")

    def test_build_projected_order_selects_handedness_view_and_crosswalks(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"; ids = write_salary(salary)
            order, report = poa.build_projected_order(self._platoon(), salary, {"AAA": "L"})
            self.assertEqual(report["n_matched"], 8)         # all eight vs_LHP names matched
            self.assertEqual(report["hand_assumed_teams"], [])
            self.assertEqual(order[ids["AAA SS"]], 1)        # vs_LHP slot, not the vs_RHP 5
            self.assertEqual(order[ids["AAA C"]], 2)

    def test_build_projected_order_unknown_hand_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"; ids = write_salary(salary)
            order, report = poa.build_projected_order(self._platoon(), salary, {}, default_hand="R")
            self.assertIn("AAA", report["hand_assumed_teams"])
            self.assertEqual(order[ids["AAA SS"]], 5)        # vs_RHP default view
            self.assertNotIn(ids["AAA OF3"], order)          # OF3 is not in the vs_RHP view

    def test_build_projected_order_never_emits_confirmed_teams(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"; write_salary(salary)
            _order, report = poa.build_projected_order(self._platoon(), salary, {"AAA": "R"})
            self.assertNotIn("confirmed_teams", report)
            self.assertIn("Do NOT pass these teams as", report["note"])

    def test_mispricing_screen_flags_move_up_and_down(self):
        rows = {r["player"]: r for r in poa.mispricing_screen(self._platoon(), {"AAA": "L"})}
        self.assertGreater(rows["AAA SS"]["lift_pct"], 0)    # 5 -> 1 vs L
        self.assertGreater(rows["AAA SS"]["slot_delta"], 0)
        self.assertLess(rows["AAA C"]["lift_pct"], 0)        # 1 -> 2 vs L

    def test_mispricing_screen_flags_platoon_only_bat(self):
        rows = {r["player"]: r for r in poa.mispricing_screen(self._platoon(), {"AAA": "L"})}
        self.assertEqual(rows["AAA OF3"]["platoon_only"], "vs_L only")
        self.assertEqual(rows["AAA OF3"]["lift_pct"], 0.0)   # no cross-view baseline to move against

    def test_mispricing_screen_external_typical_override(self):
        # Override AAA SS's typical slot to 9; tonight (vs L) is 1, so lift is large and positive.
        rows = {r["player"]: r for r in poa.mispricing_screen(
            self._platoon(), {"AAA": "L"}, typical_order_map={"AAA|aaa ss": 9.0})}
        self.assertEqual(rows["AAA SS"]["typical_source"], "external")
        self.assertEqual(rows["AAA SS"]["typical_slot"], 9.0)
        self.assertEqual(rows["AAA C"]["typical_source"], "within_file_blend")

    def test_apply_projected_order_to_rows_sets_f2_and_preserves_existing(self):
        from mlb_engine.projections.projection_builder import batting_order_factor
        rows = [
            {"Player_ID": "p1", "Base": 9.0},                       # no order -> enriched
            {"Player_ID": "p2", "Base": 9.0, "Batting_Order": 7},   # has order -> preserved
        ]
        out, applied = poa.apply_projected_order_to_rows(rows, {"p1": 2, "p2": 1})
        self.assertEqual(applied, ["p1"])
        by_id = {r["Player_ID"]: r for r in out}
        self.assertEqual(by_id["p1"]["Batting_Order"], 2)
        self.assertAlmostEqual(by_id["p1"]["F2"], batting_order_factor(2))
        self.assertEqual(by_id["p2"]["Batting_Order"], 7)           # untouched
        self.assertNotIn("F2", by_id["p2"])

    def test_assemble_frame_applies_projected_order_f2(self):
        from mlb_engine.projections.projection_builder import batting_order_factor
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"; ids = write_salary(salary)
            rows = [{"Player_ID": raw[3], "Base": 10.0} for raw in salary_rows()]
            frame, _enrich = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                projected_order_by_player_id={ids["AAA SS"]: 1})
            r = frame[frame["Player_ID"] == ids["AAA SS"]].iloc[0]
            self.assertAlmostEqual(float(r["F2"]), batting_order_factor(1))
            self.assertEqual(int(r["Batting_Order"]), 1)
            self.assertIn("platoon_order", str(r["Notes"]))

    def test_run_slate_surfaces_projected_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            rows = [{"Player_ID": raw[3], "Base": 10.0} for raw in salary_rows()]
            order, _ = poa.build_projected_order(self._platoon(), salary, {"AAA": "L"})
            res = run_slate(runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                            projection_rows=rows, platoon_order_by_player_id=order, approve=False)
            self.assertEqual(res["status"], "plan_pending_approval")
            self.assertEqual(res["projected_order"]["applied_count"], len(order))
            self.assertIn(ids["AAA SS"], res["projected_order"]["applied_player_ids"])




def write_savant_batting(path: Path, rows):
    """rows: (savant_name, mlbam, pa, woba, est_woba, est_ba, est_slg)."""
    header = ["last_name, first_name", "player_id", "pa", "woba", "est_woba", "est_ba", "est_slg"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle); w.writerow(header)
        for r in rows:
            w.writerow(list(r))


def write_savant_pitching(path: Path, rows):
    """rows: (savant_name, mlbam, pa, woba, est_woba)."""
    header = ["last_name, first_name", "player_id", "pa", "woba", "est_woba"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle); w.writerow(header)
        for r in rows:
            w.writerow(list(r))


def write_fangraphs_pitching(path: Path, rows, header=None):
    """rows: (name, gs, ip, k9) tuples for the default header."""
    header = header or ["#", "Name", "Team", "GS", "IP", "K/9"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle); w.writerow(header)
        for i, r in enumerate(rows, 1):
            if header[-1] == "K/9" and len(r) == 4:
                name, gs, ip, k9 = r
                w.writerow([i, name, "XXX", gs, ip, k9])
            else:
                w.writerow(list(r))


class ProjectionEnrichmentWiringTests(unittest.TestCase):
    """v2.23.0 wiring tests: enrichments must demonstrably reach the frame.

    These exist because 86 unit tests passed while the front door's xwOBA
    correction was a silent no-op (MLBAM-keyed map applied to DK-keyed rows).
    Each test drives synthetic fixtures through the real join and asserts a
    non-neutral value arrived, so an untested integration path cannot recur.
    """

    def _rows(self, avg=10.0, overrides=None):
        overrides = overrides or {}
        return [{"Player_ID": raw[3], "AvgPointsPerGame": overrides.get(raw[2], avg)}
                for raw in salary_rows()]

    def test_xwoba_dk_keyed_correction_reaches_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            bat = root / "bat.csv"
            write_savant_batting(bat, [
                ("SS, AAA", 700001, 200, 0.300, 0.360, 0.250, 0.450),  # 1.2 -> clip 1.15
                ("C, AAA", 700002, 200, 0.360, 0.300, 0.260, 0.380),   # .833 -> clip 0.85
            ])
            pit = root / "pit.csv"
            write_savant_pitching(pit, [("A, Pitcher", 800001, 300, 0.320, 0.300)])  # 1.0667
            frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", str(bat), str(pit), None,
                apply_value_sanity_guard=False)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            self.assertAlmostEqual(float(by_id[ids["AAA SS"]]["Base"]), 11.5, places=4)
            self.assertAlmostEqual(float(by_id[ids["AAA C"]]["Base"]), 8.5, places=4)
            self.assertAlmostEqual(float(by_id[ids["Pitcher A"]]["Base"]), 10.0 * 0.320 / 0.300, places=4)
            self.assertAlmostEqual(float(by_id[ids["CCC SS"]]["Base"]), 10.0, places=6)  # unmatched fallback
            x = enrich["xwoba"]
            self.assertTrue(x["applied"])
            self.assertEqual(x["matched"], 3)
            self.assertGreater(x["match_rate"], 0.0)
            self.assertEqual(x["non_neutral_applied"], 3)

    def _r57_fixture(self, root, base_overrides=None, drop_appg=()):
        """The R57 reproduction: a matched-and-corrected pool where selected rows
        carry an explicit operator Base and/or no AvgPointsPerGame."""
        salary = root / "salary.csv"; ids = write_salary(salary)
        bat = root / "bat.csv"
        write_savant_batting(bat, [
            ("SS, AAA", 700001, 200, 0.300, 0.360, 0.250, 0.450),  # ratio 1.2 -> clip 1.15
            ("C, AAA", 700002, 200, 0.360, 0.300, 0.260, 0.380),   # .833 -> clip 0.85
        ])
        base_overrides = base_overrides or {}
        rows = []
        for raw in salary_rows():
            key, pid = raw[2], raw[3]
            r = {"Player_ID": pid}
            if key not in drop_appg:
                r["AvgPointsPerGame"] = 10.0
            if key in base_overrides:
                r["Base"] = base_overrides[key]
            rows.append(r)
        return salary, bat, ids, rows

    def test_operator_supplied_base_survives_the_xwoba_correction(self):
        # R57(a): the correction restates Base from APPG, so it may only touch
        # rows whose Base came from APPG. AAA SS is matched at factor 1.15; an
        # operator Base of 12.0 must not become 10.0 * 1.15 = 11.5.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, bat, ids, rows = self._r57_fixture(root, base_overrides={"AAA SS": 12.0})
            frame, enrich = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            self.assertAlmostEqual(float(by_id[ids["AAA SS"]]["Base"]), 12.0, places=6)
            # the rest of the pool still gets corrected, so this is a mask and
            # not a disabled correction
            self.assertAlmostEqual(float(by_id[ids["AAA C"]]["Base"]), 8.5, places=6)
            x = enrich["xwoba"]
            self.assertTrue(x["applied"])
            self.assertEqual(x["rows_skipped_operator_base"], 1)
            self.assertEqual(x["rows_corrected"], len(frame) - 1)

    def test_explicit_base_without_appg_does_not_crash_the_front_door(self):
        # R57(b): live_data_adapters tells the operator to "supply Base before
        # run_slate". That row has no APPG, so APPG * factor is NaN and
        # build_projections rejected it as nonnumeric — an uncaught crash at
        # both approve legs, triggered by following the documented remedy.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, bat, ids, rows = self._r57_fixture(
                root, base_overrides={"AAA SS": 12.0}, drop_appg=("AAA SS",))
            frame, enrich = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            self.assertAlmostEqual(float(by_id[ids["AAA SS"]]["Base"]), 12.0, places=6)
            self.assertFalse(frame["Base"].isna().any())
            self.assertTrue(enrich["xwoba"]["applied"])

    def test_blank_base_cell_still_falls_back_to_appg(self):
        # The mask is "did the operator supply Base", and a blank cell in a
        # projections_override CSV arrives as NaN, not "". Treating NaN as
        # supplied would skip the APPG fallback and leave a NaN Base for
        # validate_projection_factors to reject — with or without Savant CSVs.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, bat, ids, rows = self._r57_fixture(
                root, base_overrides={"AAA SS": float("nan")})
            frame, _ = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            self.assertAlmostEqual(float(by_id[ids["AAA SS"]]["Base"]), 11.5, places=6)
            frame2, _ = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                apply_value_sanity_guard=False)
            by_id2 = {str(r["Player_ID"]): r for r in frame2.to_dict("records")}
            self.assertAlmostEqual(float(by_id2[ids["AAA SS"]]["Base"]), 10.0, places=6)

    def test_row_with_neither_base_nor_appg_still_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, bat, ids, rows = self._r57_fixture(root, drop_appg=("AAA SS",))
            with self.assertRaisesRegex(ValueError, "missing Base/AvgPointsPerGame"):
                epi._assemble_projection_frame(
                    str(salary), rows, "emergency_proxy", str(bat), None, None,
                    apply_value_sanity_guard=False)

    def test_xwoba_zero_match_raises_wiring_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; write_salary(salary)
            bat = root / "bat.csv"
            write_savant_batting(bat, [("Nobody, Zed", 700099, 300, 0.300, 0.360, 0.250, 0.450)])
            with self.assertRaisesRegex(ValueError, "wiring"):
                epi._assemble_projection_frame(
                    str(salary), self._rows(), "emergency_proxy", str(bat), None, None)

    def test_value_guard_caps_hitter_and_never_pitcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            rows = self._rows(avg=8.0, overrides={"AAA SS": 60.0, "Pitcher A": 50.0})
            frame, enrich = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            # 15 hitters at 8/3k=2.667 pts/$k, one at 20; p90 = 2.667 -> cap 2.88/$k -> 8.64
            self.assertAlmostEqual(float(by_id[ids["AAA SS"]]["Base"]), 8.64, places=2)
            self.assertIn("value_guard", str(by_id[ids["AAA SS"]]["Notes"]))
            self.assertAlmostEqual(float(by_id[ids["Pitcher A"]]["Base"]), 50.0, places=6)
            self.assertEqual(enrich["value_guard"]["clipped_count"], 1)
            frame2, enrich2 = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                apply_value_sanity_guard=False)
            by_id2 = {str(r["Player_ID"]): r for r in frame2.to_dict("records")}
            self.assertAlmostEqual(float(by_id2[ids["AAA SS"]]["Base"]), 60.0, places=6)
            self.assertFalse(enrich2["value_guard"]["applied"])

    def test_per_player_ceiling_multiplier_flows_to_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            bat = root / "bat.csv"
            neutral = (0.320, 0.320)  # woba == est_woba so Base is untouched
            write_savant_batting(bat, [
                ("SS, AAA", 700001, 200, *neutral, 0.240, 0.470),  # xISO .230 high
                ("1B, AAA", 700002, 200, *neutral, 0.260, 0.400),  # .140 mid
                ("C, AAA", 700003, 200, *neutral, 0.270, 0.340),   # .070 low
            ])
            frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            def ratio(key):
                r = by_id[ids[key]]
                return float(r["Ceiling"]) / float(r["Base_Projection"])
            self.assertAlmostEqual(ratio("AAA SS"), 1.57, places=4)
            self.assertAlmostEqual(ratio("AAA 1B"), 1.47, places=4)
            self.assertAlmostEqual(ratio("AAA C"), 1.37, places=4)
            self.assertAlmostEqual(ratio("CCC SS"), 1.42, places=4)  # unmatched -> neutral
            self.assertEqual(enrich["ceiling"]["differentiated_rows"], 3)
            self.assertIn("xiso_ceiling", str(by_id[ids["AAA SS"]]["Notes"]))

    def test_f4_map_applied_and_explicit_row_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            rows = self._rows()
            for r in rows:
                if r["Player_ID"] == ids["AAA C"]:
                    r["F4"] = 1.05
            frame, enrich = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                f4_by_player_id={ids["AAA SS"]: 1.10, ids["AAA C"]: 0.95},
                apply_value_sanity_guard=False)
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            self.assertAlmostEqual(float(by_id[ids["AAA SS"]]["F4"]), 1.10, places=6)
            self.assertAlmostEqual(float(by_id[ids["AAA C"]]["F4"]), 1.05, places=6)  # explicit wins
            self.assertIn("f4_matchup", str(by_id[ids["AAA SS"]]["Notes"]))
            self.assertEqual(enrich["f4"]["applied_count"], 1)
            self.assertEqual(enrich["f4"]["applied_player_ids"], [ids["AAA SS"]])

    def test_compute_f4_factors_quality_and_platoon_math(self):
        from mlb_engine.projections import projection_builder as pb

        pitching = pd.DataFrame([
            {"player_id": "900", "pa": 300, "woba": 0.30, "est_woba": 0.360},
            {"player_id": "901", "pa": 300, "woba": 0.30, "est_woba": 0.320},
            {"player_id": "902", "pa": 300, "woba": 0.30, "est_woba": 0.280},
        ])
        f4, report = pb.compute_f4_factors(
            {"h1": "AAA", "h2": "AAA", "h3": "CCC", "h4": "EEE"},
            {"AAA": {"id": "900", "name": "Loud Contact", "hand": "R"},
             "CCC": {"id": "902", "name": "Ace", "hand": "L"}},
            pitching_table=pitching,
            bat_side_by_player_id={"h1": "L", "h3": "R"},
        )
        # league mean est_woba = .320; AAA quality 1.125 -> clip 1.10; CCC .875 -> clip 0.90
        self.assertAlmostEqual(f4["h1"], 1.10 * 1.04, places=6)  # L vs R platoon prior
        self.assertAlmostEqual(f4["h2"], 1.10, places=6)          # no hand -> quality only
        self.assertAlmostEqual(f4["h3"], 0.90 * 1.03, places=6)   # R vs L
        self.assertAlmostEqual(f4["h4"], 1.0, places=6)           # no opposing probable -> neutral
        self.assertIn("EEE", report["teams_without_opposing_probable"])
        self.assertAlmostEqual(report["league_mean_est_woba"], 0.320, places=6)

    def test_run_slate_surfaces_projection_enrichment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            bat = root / "bat.csv"
            write_savant_batting(bat, [("SS, AAA", 700001, 200, 0.300, 0.360, 0.240, 0.470)])
            fgp = root / "fg_pitching.csv"
            write_fangraphs_pitching(fgp, [("Pitcher A", 18, 100.0, 11.0), ("Pitcher C", 18, 100.0, 7.0)])
            res = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projection_rows=self._rows(), savant_batting_csv=bat,
                fangraphs_pitching_csv=fgp,
                f4_by_player_id={ids["AAA SS"]: 1.08}, approve=False)
            self.assertEqual(res["status"], "plan_pending_approval")
            pe = res["projection_enrichment"]
            self.assertTrue(pe["xwoba"]["applied"])
            self.assertEqual(pe["xwoba"]["matched"], 1)
            self.assertEqual(pe["f4"]["applied_count"], 1)
            self.assertTrue(pe["value_guard"]["applied"])
            self.assertEqual(pe["ceiling"]["differentiated_rows"], 1)
            self.assertEqual(pe["pitcher_ceiling"]["differentiated_rows"], 2)
            self.assertEqual(pe["pitcher_ceiling"]["rate_column"], "K/9")

    # --- v2.24.0: per-pitcher Ceiling multipliers from a K-rate input --------

    def test_load_fangraphs_pitching_requires_k_rate_column(self):
        from mlb_engine.projections.projection_builder import load_fangraphs_pitching
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok = root / "ok.csv"
            write_fangraphs_pitching(ok, [("Pitcher A", 18, 100.0, 9.0)])
            table = load_fangraphs_pitching(ok)
            self.assertIn("Name", table.columns)
            bad = root / "bad.csv"
            write_fangraphs_pitching(bad, [(1, "Pitcher A", "XXX", 100.0)],
                                     header=["#", "Name", "Team", "IP"])
            with self.assertRaisesRegex(ValueError, "K-rate"):
                load_fangraphs_pitching(bad)

    def test_k_rate_ceiling_scale_reliever_shrink_and_floor(self):
        from mlb_engine.projections.projection_builder import build_k_rate_ceiling_multipliers, load_fangraphs_pitching
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fgp = root / "fg.csv"
            write_fangraphs_pitching(fgp, [
                ("Low K SP", 18, 100.0, 6.0),      # pct 1/3 -> 1.37
                ("Mid K SP", 18, 100.0, 8.0),      # pct 2/3 -> 1.47
                ("High K SP", 18, 100.0, 10.0),    # pct 3/3 -> 1.57
                ("Monster RP", 0, 60.0, 14.0),     # GS 0 -> excluded, neutral
            ])
            mults = build_k_rate_ceiling_multipliers(load_fangraphs_pitching(fgp))
            self.assertAlmostEqual(mults["Low K SP"], 1.37, places=4)
            self.assertAlmostEqual(mults["Mid K SP"], 1.47, places=4)
            self.assertAlmostEqual(mults["High K SP"], 1.57, places=4)
            self.assertAlmostEqual(mults["Monster RP"], 1.42, places=4)
            shr = root / "shrink.csv"
            write_fangraphs_pitching(shr, [
                ("Short SP", 3, 15.0, 12.0),       # tbf 63.75, weight .275, pct 1.0
                ("Tiny SP", 1, 10.0, 12.0),        # tbf 42.5 < 50 -> neutral
            ])
            m2 = build_k_rate_ceiling_multipliers(load_fangraphs_pitching(shr))
            self.assertAlmostEqual(m2["Short SP"], 1.42 + 0.15 * 0.275, places=4)
            self.assertAlmostEqual(m2["Tiny SP"], 1.42, places=4)

    def test_k_rate_prefers_k_percent_over_k9(self):
        from mlb_engine.projections.projection_builder import (
            build_k_rate_ceiling_multipliers, k_rate_column, load_fangraphs_pitching,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fgp = root / "fg.csv"
            # K% and K/9 disagree on ordering; K% must win the rank.
            write_fangraphs_pitching(fgp, [
                (1, "Whiff SP", "XXX", 18, 100.0, 7.0, "31.0%"),
                (2, "Contact SP", "XXX", 18, 100.0, 10.0, "18.0%"),
            ], header=["#", "Name", "Team", "GS", "IP", "K/9", "K%"])
            table = load_fangraphs_pitching(fgp)
            self.assertEqual(k_rate_column(table), "K%")
            mults = build_k_rate_ceiling_multipliers(table)
            # K% ordering wins: pct ranks in a two-row universe are 0.5 and 1.0.
            # Under K/9 ordering Contact SP would take the 1.57; under K% it is Whiff SP.
            self.assertGreater(mults["Whiff SP"], mults["Contact SP"])
            self.assertAlmostEqual(mults["Whiff SP"], 1.57, places=4)
            self.assertAlmostEqual(mults["Contact SP"], 1.42, places=4)

    def test_dk_keyed_pitcher_ceiling_pitchers_only_and_collision(self):
        from mlb_engine.projections.xwoba_base_correction import build_dk_keyed_pitcher_ceiling_multipliers
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            fgp = root / "fg.csv"
            write_fangraphs_pitching(fgp, [
                ("Pitcher A", 18, 100.0, 12.0),     # collision winner (higher TBF)
                ("Pitcher A Jr.", 5, 30.0, 4.0),    # normalizes to the same key
                ("Pitcher C", 18, 100.0, 6.0),
                ("AAA SS", 18, 100.0, 9.0),         # hitter-named row must never map
            ])
            mults, report = build_dk_keyed_pitcher_ceiling_multipliers(salary, fgp)
            self.assertEqual(set(mults), {ids["Pitcher A"], ids["Pitcher C"]})
            self.assertEqual(report["considered_pitchers"], 2)
            self.assertEqual(report["matched"], 2)
            # universe K/9 ranks: 4 -> .25, 6 -> .50, 9 -> .75, 12 -> 1.0
            self.assertAlmostEqual(mults[ids["Pitcher A"]], 1.57, places=4)
            self.assertAlmostEqual(mults[ids["Pitcher C"]], 1.42, places=4)
            self.assertIn("pitcher a", report["name_collisions"])

    def test_pitcher_ceiling_reaches_frame_and_hitters_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            fgp = root / "fg.csv"
            write_fangraphs_pitching(fgp, [
                ("Pitcher A", 18, 100.0, 11.0),     # pct 1.0 -> 1.57
                ("Pitcher C", 18, 100.0, 7.0),      # pct 0.5 -> 1.42, still applied
            ])
            frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", None, None, None,
                apply_value_sanity_guard=False, fangraphs_pitching_csv=str(fgp))
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            def ratio(key):
                r = by_id[ids[key]]
                return float(r["Ceiling"]) / float(r["Base_Projection"])
            self.assertAlmostEqual(ratio("Pitcher A"), 1.57, places=4)
            self.assertAlmostEqual(ratio("Pitcher C"), 1.42, places=4)
            self.assertIn("k_rate_ceiling", str(by_id[ids["Pitcher A"]]["Notes"]))
            self.assertIn("k_rate_ceiling", str(by_id[ids["Pitcher C"]]["Notes"]))
            self.assertAlmostEqual(ratio("AAA SS"), 1.42, places=4)
            self.assertNotIn("k_rate_ceiling", str(by_id[ids["AAA SS"]]["Notes"]))
            pc = enrich["pitcher_ceiling"]
            self.assertEqual(pc["differentiated_rows"], 2)
            self.assertEqual(pc["matched"], 2)
            self.assertEqual(pc["rate_column"], "K/9")

    def test_pitcher_ceiling_combines_with_xiso_in_one_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            bat = root / "bat.csv"
            write_savant_batting(bat, [("SS, AAA", 700001, 200, 0.320, 0.320, 0.240, 0.470)])
            fgp = root / "fg.csv"
            write_fangraphs_pitching(fgp, [
                ("Pitcher A", 18, 100.0, 11.0),
                ("Pitcher C", 18, 100.0, 7.0),
            ])
            frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False, fangraphs_pitching_csv=str(fgp))
            by_id = {str(r["Player_ID"]): r for r in frame.to_dict("records")}
            def ratio(key):
                r = by_id[ids[key]]
                return float(r["Ceiling"]) / float(r["Base_Projection"])
            self.assertAlmostEqual(ratio("AAA SS"), 1.57, places=4)      # xISO, sole qualifier
            self.assertAlmostEqual(ratio("Pitcher A"), 1.57, places=4)   # K-rate
            self.assertIn("xiso_ceiling", str(by_id[ids["AAA SS"]]["Notes"]))
            self.assertIn("k_rate_ceiling", str(by_id[ids["Pitcher A"]]["Notes"]))
            self.assertEqual(enrich["ceiling"]["differentiated_rows"], 1)
            self.assertEqual(enrich["pitcher_ceiling"]["differentiated_rows"], 2)

    def test_fangraphs_zero_match_raises_wiring_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            header = ["Position", "Name + ID", "Name", "ID", "Roster Position",
                      "Salary", "Game Info", "TeamAbbrev"]
            rows = []
            for i in range(1, 11):
                rows.append(["P", f"Px {i} (2000{i})", f"Px {i}", f"2000{i}", "P",
                             "8000", "AAA@BBB 06/11/2026 01:00PM ET", "AAA"])
            with salary.open("w", newline="", encoding="utf-8") as handle:
                w = csv.writer(handle); w.writerow(header); w.writerows(rows)
            fgp = root / "fg.csv"
            write_fangraphs_pitching(fgp, [("Nobody Zed", 18, 100.0, 9.0)])
            proj = [{"Player_ID": f"2000{i}", "AvgPointsPerGame": 15.0} for i in range(1, 11)]
            with self.assertRaisesRegex(ValueError, "wiring"):
                epi._assemble_projection_frame(
                    str(salary), proj, "emergency_proxy", None, None, None,
                    apply_value_sanity_guard=False, fangraphs_pitching_csv=str(fgp))


class NeutralDefaultVisibilityTests(unittest.TestCase):
    """R127(a). A factor that fell back to its neutral default must be NAMED.

    The reproduction is the 2026-08-15 2138_2g slate: an arm absent from the
    FanGraphs season pitching file kept the neutral 1.42 ceiling multiplier,
    outranked a better strikeout arm that WAS in the file, and took 9 of 19
    lineups. The only signal in the brief was a count, and a count names no
    player, no reason, and no consequence. Every assertion below pins a VALUE
    rather than the presence of a key (R91).
    """

    # Four filler arms so the pool clears XWOBA_WIRING_MIN_POOL bookkeeping and
    # the K-rate percentile has a population; only Pitcher A and Pitcher C are
    # in the salary file.
    FILLERS = [("Filler One", 18, 100.0, 7.0), ("Filler Two", 18, 100.0, 8.0),
               ("Filler Three", 18, 100.0, 9.0), ("Filler Four", 18, 100.0, 6.0)]

    def _rows(self):
        return [{"Player_ID": raw[3], "AvgPointsPerGame": 10.0} for raw in salary_rows()]

    def _assemble(self, root, fg_rows, drop_pitcher_ids=()):
        salary = root / "salary.csv"
        write_salary(salary)
        rows = [r for r in self._rows() if r["Player_ID"] not in set(drop_pitcher_ids)]
        kwargs = {}
        if fg_rows is not None:
            fgp = root / "fg.csv"
            write_fangraphs_pitching(fgp, fg_rows)
            kwargs["fangraphs_pitching_csv"] = str(fgp)
        return epi._assemble_projection_frame(
            str(salary), rows, "emergency_proxy", None, None, None,
            apply_value_sanity_guard=False, **kwargs)

    def test_a_declared_starter_missing_from_the_reference_is_named_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            _frame, enrich = self._assemble(
                Path(tmp), [("Pitcher A", 18, 100.0, 11.0)] + self.FILLERS)
            block = enrich["neutral_default"]["pitcher_ceiling"]
            self.assertTrue(block["applied"])
            self.assertEqual(block["in_pool"], 2)
            self.assertEqual(block["at_neutral"], 1)
            self.assertEqual(
                [(p["name"], p["player_id"], p["reason"]) for p in block["players"]],
                [("Pitcher C", "10002", "absent_from_fangraphs_season_pitching")])
            self.assertEqual(block["neutral"], 1.42)

    def test_the_named_miss_reaches_the_warnings_with_the_player_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            _frame, enrich = self._assemble(
                Path(tmp), [("Pitcher A", 18, 100.0, 11.0)] + self.FILLERS)
            # Carried twice on purpose: the brief merges enrichment["warnings"],
            # a caller echoes neutral_default["warnings"] to stderr without
            # string-matching the merged pile.
            nd_warnings = enrich["neutral_default"]["warnings"]
            self.assertEqual(len(nd_warnings), 1)
            self.assertIn("Pitcher C", nd_warnings[0])
            self.assertIn("absent_from_fangraphs_season_pitching", nd_warnings[0])
            self.assertIn("1 of 2 declared starter(s)", nd_warnings[0])
            self.assertIn("can change selection", nd_warnings[0])
            self.assertIn(nd_warnings[0], enrich["warnings"])

    def test_full_coverage_names_nobody_and_raises_nothing(self):
        """The falsifier: same fixture with the missing arm added to the file."""
        with tempfile.TemporaryDirectory() as tmp:
            _frame, enrich = self._assemble(
                Path(tmp),
                [("Pitcher A", 18, 100.0, 11.0), ("Pitcher C", 18, 100.0, 7.0)]
                + self.FILLERS)
            block = enrich["neutral_default"]["pitcher_ceiling"]
            self.assertEqual(block["at_neutral"], 0)
            self.assertEqual(block["players"], [])
            self.assertEqual(enrich["neutral_default"]["warnings"], [])

    def test_the_list_is_this_builds_pool_not_the_salary_file(self):
        """The crosswalk's own `unmatched_rows` is computed over the whole salary
        file, so it cannot be the operator's list: most of those arms are absent
        from the pool and unrosterable. Dropping Pitcher C from the projection
        rows must drop him from the named list too, even though he is still an
        unmatched row in the salary file."""
        with tempfile.TemporaryDirectory() as tmp:
            _frame, enrich = self._assemble(
                Path(tmp), [("Pitcher A", 18, 100.0, 11.0)] + self.FILLERS,
                drop_pitcher_ids=("10002",))
            block = enrich["neutral_default"]["pitcher_ceiling"]
            self.assertEqual(block["in_pool"], 1)
            self.assertEqual(block["at_neutral"], 0)
            self.assertEqual(block["players"], [])

    def test_an_absent_input_is_one_fact_with_a_count_never_a_roster_of_names(self):
        """"The file is missing" is one fact about the build, not N facts about
        N players. Listing the pool under it buries the case the list exists for:
        the factor RAN and skipped somebody."""
        with tempfile.TemporaryDirectory() as tmp:
            _frame, enrich = self._assemble(Path(tmp), None)
            block = enrich["neutral_default"]["pitcher_ceiling"]
            self.assertFalse(block["applied"])
            self.assertEqual(block["players"], [])
            self.assertEqual(block["in_pool"], 2)
            self.assertEqual(block["at_neutral"], 2)
            self.assertEqual(block["unavailable_reason"],
                             "no_fangraphs_pitching_csv_supplied")
            self.assertEqual(len(enrich["neutral_default"]["warnings"]), 1)
            self.assertIn("no FanGraphs pitching CSV supplied",
                          enrich["neutral_default"]["warnings"][0])

    def test_matched_but_unmeasurable_carries_its_own_reason(self):
        """A pitcher IN the file whose sample is under the floor also lands on
        the neutral, and that is a different data condition with a different
        remedy than being absent. Same value, different reason."""
        with tempfile.TemporaryDirectory() as tmp:
            _frame, enrich = self._assemble(
                Path(tmp),
                # Pitcher C at 1.0 IP is far under XWOBA_PA_MIN batters faced.
                [("Pitcher A", 18, 100.0, 11.0), ("Pitcher C", 1, 1.0, 7.0)]
                + self.FILLERS)
            block = enrich["neutral_default"]["pitcher_ceiling"]
            self.assertEqual(
                [(p["name"], p["reason"]) for p in block["players"]],
                [("Pitcher C", "matched_but_sub_floor_sample_or_non_starter")])

    def test_hitter_ceiling_and_base_correction_report_the_same_way(self):
        """The treatment generalizes to the other per-player file joins rather
        than being a special case for one factor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            bat = root / "bat.csv"
            write_savant_batting(bat, [
                ("SS, AAA", 700001, 200, 0.300, 0.360, 0.250, 0.450)])
            _frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False)
            hit = enrich["neutral_default"]["hitter_ceiling"]
            self.assertTrue(hit["applied"])
            self.assertEqual(hit["in_pool"], 16)
            # One of sixteen hitters is in the Savant export; the other fifteen
            # are named as absent rather than counted.
            self.assertEqual(hit["at_neutral"], 15)
            self.assertNotIn(ids["AAA SS"], [p["player_id"] for p in hit["players"]])
            self.assertEqual(
                {p["reason"] for p in hit["players"]},
                {"absent_from_expected_stats_batting"})
            base = enrich["neutral_default"]["xwoba_base"]
            self.assertTrue(base["applied"])
            self.assertEqual(base["neutral"], 1.0)
            self.assertEqual(base["at_neutral"], 17)  # 18 pool rows, one corrected

    def test_the_side_split_answers_for_each_side_separately(self):
        """R127(b). The 2138_2g shape: hitter-side signal, pitcher side entirely
        at neutral. One boolean over both sides answered for the side that had
        signal and spoke for the side that did not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; write_salary(salary)
            bat = root / "bat.csv"
            write_savant_batting(bat, [
                ("SS, AAA", 700001, 200, 0.300, 0.360, 0.250, 0.450)])
            _frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", str(bat), None, None,
                apply_value_sanity_guard=False)
            self.assertTrue(enrich["by_side"]["hitters"]["signal_applied"])
            self.assertFalse(enrich["by_side"]["pitchers"]["signal_applied"])
            self.assertEqual(enrich["by_side"]["pitchers"]["rows"], 2)
            self.assertEqual(enrich["by_side"]["pitchers"]["ceiling_multiplier_moved"], 0)
            self.assertEqual(enrich["by_side"]["hitters"]["rows"], 16)
            self.assertEqual(enrich["by_side"]["hitters"]["ceiling_multiplier_moved"], 1)

    def test_the_side_split_is_measured_per_row_not_from_the_input_map(self):
        """A stale-id map is requested-but-unapplied. An F4 map keyed to ids that
        are not on this slate must leave both sides dark."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; write_salary(salary)
            _frame, enrich = epi._assemble_projection_frame(
                str(salary), self._rows(), "emergency_proxy", None, None, None,
                apply_value_sanity_guard=False,
                f4_by_player_id={"999999": 1.25, "999998": 0.80})
            self.assertEqual(enrich["f4"]["requested"], 2)
            self.assertEqual(enrich["f4"]["applied_count"], 0)
            self.assertFalse(enrich["by_side"]["hitters"]["signal_applied"])
            self.assertFalse(enrich["by_side"]["pitchers"]["signal_applied"])
            self.assertEqual(enrich["by_side"]["hitters"]["factor_cells_moved"], 0)


class FeasibilityAndDiverseBankTests(unittest.TestCase):
    """v2.25.0: coverage-guaranteed bank and feasibility-aware control resolution."""

    def _legal_lineup(self, ldf):
        self.assertEqual(len(ldf), 10)
        self.assertLessEqual(float(ldf["Salary"].sum()), 50000.0)
        pitchers = ldf[ldf["Position"].astype(str).str.contains("P", na=False)]
        self.assertEqual(len(pitchers), 2)

    def test_diverse_bank_covers_all_viable_sp_pairs(self):
        frame = diverse_projection_frame()
        n_pairs = len(opt.enumerate_sp_pairs(opt._eligible_sp_ids_for_anchor_caps(frame)))
        self.assertEqual(n_pairs, 6)
        bank = opt.build_diverse_candidate_bank(
            frame, requested_n=6, mode="gpp", target="ceiling",
            contest_shapes=["large_field_gpp"],
        )
        cands = bank["candidate_lineups"]
        self.assertGreaterEqual(len(cands), 6)
        pairs = {opt._sp_pair_from_lineup(c["lineup"]) for c in cands}
        pairs.discard(None)
        self.assertEqual(len(pairs), n_pairs)
        for c in cands:
            self._legal_lineup(c["lineup"])
        self.assertTrue(bank["diversity_augmentation"]["attempted"])

    def test_diverse_bank_has_no_duplicate_lineups(self):
        frame = diverse_projection_frame()
        bank = opt.build_diverse_candidate_bank(
            frame, requested_n=6, mode="gpp", target="ceiling",
            contest_shapes=["large_field_gpp"],
        )
        sigs = [frozenset(c["player_ids"]) for c in bank["candidate_lineups"]]
        self.assertEqual(len(sigs), len(set(sigs)))

    def test_diverse_bank_not_worse_than_base(self):
        frame = diverse_projection_frame()
        base = opt.build_candidate_lineup_bank(
            frame, requested_n=6, mode="gpp", target="ceiling",
            contest_shapes=["large_field_gpp"],
        )
        diverse = opt.build_diverse_candidate_bank(
            frame, requested_n=6, mode="gpp", target="ceiling",
            contest_shapes=["large_field_gpp"],
        )

        def distinct_pairs(bank):
            pairs = {opt._sp_pair_from_lineup(c["lineup"]) for c in bank["candidate_lineups"]}
            pairs.discard(None)
            return len(pairs)

        self.assertGreaterEqual(distinct_pairs(diverse), distinct_pairs(base))
        self.assertGreaterEqual(len(diverse["candidate_lineups"]), len(base["candidate_lineups"]))

    def test_feasibility_floor_raises_repetition_caps(self):
        pbc = {"900": {"posture": "single_entry"}, "901": {"posture": "wta_satellite"}}
        base = epi._merged_controls_for_build(pbc, None)
        self.assertEqual(base["max_sp_pair_repetition"], 1)  # single_entry drags the min to 1
        floored = epi._merged_controls_for_build(
            pbc, None, feasibility_floors={"max_sp_pair_repetition": 3, "max_shared_players": 8},
        )
        self.assertEqual(floored["max_sp_pair_repetition"], 3)
        self.assertEqual(floored["max_shared_players"], 8)
        overridden = epi._merged_controls_for_build(
            pbc, {"max_sp_pair_repetition": 2},
            feasibility_floors={"max_sp_pair_repetition": 3, "max_shared_players": 8},
        )
        self.assertEqual(overridden["max_sp_pair_repetition"], 2)  # explicit override wins over floor

    def test_slate_feasibility_derives_floors(self):
        frame = diverse_projection_frame()
        feas = epi._slate_feasibility(
            {"900": {"posture": "wta_satellite"}}, _entry_reqs(16), frame, None,
        )
        self.assertTrue(feas["available"])
        # 4 SPs across 2 games is 6 combinations, but 2 of them are the opposing
        # starters of one game. Those are anti-correlated and were never real
        # capacity, so counting them understated the repetition floor: the same
        # 16 entries now correctly floor at 4 per pair instead of 3.
        self.assertEqual(feas["viable_sp_pairs"], 4)
        self.assertEqual(feas["floor_sp_pair_repetition"], 4)  # ceil(16 / 4)
        self.assertEqual(feas["max_stack_size"], 5)
        self.assertEqual(feas["floor_shared_players"], 8)  # 5-stack + shared SP pair + 1

    def test_run_slate_checkpoint_surfaces_feasibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            proj = projection_frame(ids)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                approve=False,
            )
            feas = plan["checkpoint_plan"]["feasibility"]
            self.assertIn("inputs", feas)
            self.assertEqual(feas["inputs"]["viable_sp_pairs"], 1)
            self.assertIn(feas["passed"], (True, None))
            self.assertFalse((root / "runs").exists())

    def test_run_slate_flags_infeasible_override_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            proj = projection_frame(ids)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                portfolio_controls_override={"max_sp_pair_repetition": 1},
                approve=False,
            )
            feas = plan["checkpoint_plan"]["feasibility"]
            self.assertFalse(feas["passed"])
            self.assertTrue(feas["binding_constraints"])
            self.assertTrue(any("SP-pair capacity" in b for b in feas["binding_constraints"]))
            self.assertEqual(plan["status"], "plan_pending_approval")  # advisory, never a hard block
            self.assertFalse((root / "runs").exists())


class PlanJointAllocationTests(unittest.TestCase):
    """R28(1): the approve=False checkpoint solves the build's joint MILP.

    The golden replay pins that the plan and the build AGREE on the archived
    06-03 grid. These pin the contract around that agreement: the verdict is
    always emitted, it never creates a run directory, it distinguishes an exact
    solve from a plan-bank proxy, and it never reports a clock as a proof.
    """

    def _plan(self, root, **kw):
        salary = root / "salary.csv"; ids = write_salary(salary)
        entries = root / "DKEntries.csv"; write_entries(entries)
        proj = projection_frame(ids)
        plan = run_slate(
            runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
            projections_override=proj, approve=False, **kw)
        return plan, ids

    def test_the_verdict_is_always_present_and_never_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, _ = self._plan(root)
            joint = plan["checkpoint_plan"]["joint_allocation"]
            self.assertIn(joint["verdict"], ("would_certify", "proven_infeasible", "unchecked"))
            self.assertTrue(joint["summary"], "an empty summary is the silence the item forbids")
            self.assertEqual(joint, plan["joint_allocation"])

    def test_an_exact_solve_on_supplied_candidates_says_it_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            proj = projection_frame(ids)
            rosters = legal_rosters(ids)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", rosters[0], 100),
                                     candidate("B", rosters[1], 99)],
                approve=False)
            joint = plan["checkpoint_plan"]["joint_allocation"]
            self.assertEqual(joint["bank_source"], "candidates_override")
            self.assertTrue(joint["exact_for_this_build"])
            self.assertEqual(joint["candidate_count"], 2)
            self.assertFalse((root / "runs").exists())

    def test_the_sliced_plan_bank_never_claims_to_be_the_builds_bank(self):
        """Without candidates_override the plan builds its own sliced bank, and
        the build would build a different one through build_diverse_candidate_bank.
        Reporting that verdict as exact would be a claim the engine cannot make."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, _ = self._plan(root)
            joint = plan["checkpoint_plan"]["joint_allocation"]
            self.assertEqual(joint["bank_source"], "sliced_plan_bank")
            self.assertFalse(joint["exact_for_this_build"])
            self.assertIn("not the build's", joint["summary"])
            self.assertFalse((root / "runs").exists())

    def test_a_zero_budget_is_unchecked_and_names_the_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, _ = self._plan(root, plan_solve_budget_s=0)
            joint = plan["checkpoint_plan"]["joint_allocation"]
            self.assertEqual(joint["verdict"], "unchecked")
            self.assertFalse(joint["available"])
            self.assertIn("unchecked", joint["summary"])
            self.assertIn("0s", joint["summary"])
            self.assertIn("joint_allocation:", " ".join(plan["checkpoint_plan"]["warnings"]))

    def test_a_non_certifying_verdict_warns_but_never_blocks_the_checkpoint(self):
        """The checkpoint is the review, not a gate. A predicted refusal is a
        warning the operator reads, not a refusal to let them run the build."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, _ = self._plan(root, plan_solve_budget_s=0)
            self.assertTrue(plan["passed"])
            self.assertEqual(plan["status"], "plan_pending_approval")
            self.assertFalse((root / "runs").exists())

    def test_an_allocator_time_limit_is_unchecked_not_proven_infeasible(self):
        """The allocator distinguishes the clock from a proof and says which in
        its own error text. Collapsing the two here would reintroduce exactly
        the mislabel R28 exists to remove."""
        from mlb_engine.pipeline import execution_pipeline as ep

        def fake_alloc(candidates, entries, controls):
            return {"passed": False, "errors": ["entry-level joint MILP hit the 30s time limit"],
                    "allocation_solver_report": {"status": "time_limit"}}

        original = ep.select_and_assign_entries
        ep.select_and_assign_entries = fake_alloc
        try:
            verdict = ep._plan_joint_allocation(
                None, [{"entry_id": "1", "contest_id": "900", "contest_shape": "large_field_gpp"}],
                {}, budget_s=25.0, candidates_override=[{"candidate_id": "A"}])
        finally:
            ep.select_and_assign_entries = original
        self.assertEqual(verdict["verdict"], "unchecked")
        self.assertIn("the clock, not a proven infeasibility", verdict["summary"])

    def test_no_entries_is_trivially_satisfiable_rather_than_unchecked(self):
        from mlb_engine.pipeline import execution_pipeline as ep
        verdict = ep._plan_joint_allocation(None, [], {}, budget_s=25.0)
        self.assertEqual(verdict["verdict"], "would_certify")
        self.assertEqual(verdict["candidate_count"], 0)

    def test_a_raising_plan_solve_degrades_to_unchecked_and_never_propagates(self):
        """The checkpoint may never be the thing that breaks a build path."""
        from mlb_engine.pipeline import execution_pipeline as ep

        def boom(*a, **k):
            raise RuntimeError("solver exploded")

        original = ep.select_and_assign_entries
        ep.select_and_assign_entries = boom
        try:
            verdict = ep._plan_joint_allocation(
                None, [{"entry_id": "1", "contest_id": "900", "contest_shape": "large_field_gpp"}],
                {}, budget_s=25.0, candidates_override=[{"candidate_id": "A"}])
        finally:
            ep.select_and_assign_entries = original
        self.assertEqual(verdict["verdict"], "unchecked")
        self.assertIn("RuntimeError", verdict["summary"])


class SlateClockTests(unittest.TestCase):
    def test_parse_game_info_datetime_et(self):
        from mlb_engine.intake.slate_intake_manager import parse_game_info_datetime
        dt = parse_game_info_datetime("COL@LAD 07/08/2026 10:10PM ET")
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.astimezone(timezone.utc).isoformat(), "2026-07-09T02:10:00+00:00")
        self.assertIsNone(parse_game_info_datetime("Final"))
        self.assertIsNone(parse_game_info_datetime(""))

    def test_slate_clock_from_lock_map_deadline_math(self):
        from mlb_engine.intake.slate_intake_manager import slate_clock
        lock_map = {"COL@LAD": "2026-07-09T02:10:00Z", "ARI@SD": "2026-07-09T02:40:00Z"}
        now = datetime(2026, 7, 9, 1, 30, tzinfo=timezone.utc)
        clock = slate_clock(lock_time_by_game_id=lock_map, now=now)
        self.assertTrue(clock["available"])
        self.assertEqual(clock["source"], "lock_time_map")
        self.assertEqual(clock["first_lock_game_id"], "COL@LAD")
        self.assertEqual(clock["deadline_utc"], "2026-07-09T02:05:00+00:00")
        self.assertEqual(clock["minutes_to_lock"], 40.0)
        self.assertEqual(clock["minutes_to_deadline"], 35.0)
        self.assertFalse(clock["past_deadline"])
        late = slate_clock(lock_time_by_game_id=lock_map,
                           now=datetime(2026, 7, 9, 2, 7, tzinfo=timezone.utc))
        self.assertTrue(late["past_deadline"])
        self.assertEqual(late["minutes_to_deadline"], -2.0)

    def test_slate_clock_from_salary_game_info(self):
        from mlb_engine.intake.slate_intake_manager import slate_clock
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            pool_salary_csv(salary)
            now = datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc)
            clock = slate_clock(salary_csv=str(salary), now=now)
            self.assertTrue(clock["available"])
            self.assertEqual(clock["source"], "salary_game_info")
            self.assertEqual(clock["first_lock_utc"], "2026-07-10T23:05:00+00:00")
            self.assertEqual(clock["minutes_to_deadline"], 60.0)

    def test_slate_clock_unavailable_without_datetimes(self):
        from mlb_engine.intake.slate_intake_manager import slate_clock
        clock = slate_clock()
        self.assertFalse(clock["available"])
        self.assertIn("note", clock)


class BuildSlatePoolTests(unittest.TestCase):
    def _pool(self, tmp: str, feed=None, platoon="default", postponed_teams=(), **kwargs):
        salary = Path(tmp) / "salary.csv"
        pool_salary_csv(salary, postponed_teams=postponed_teams)
        if platoon == "default":
            platoon = pool_platoon_json()
        return lda.build_slate_pool(
            salary, feed if feed is not None else pool_lineups_feed(),
            platoon_json=platoon, **kwargs,
        )

    def test_pool_keeps_only_field_players(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp)
            report = pool["pool_report"]
            self.assertEqual(report["salary_rows_total"], 68)
            self.assertEqual(report["kept"], 40)
            self.assertEqual(report["dropped"], 28)
            self.assertEqual(report["hitters_kept"], 36)
            self.assertEqual(report["pitchers_kept"], 4)
            names = [r["Name"] for r in pool["projection_rows"]]
            self.assertFalse(any("Bench" in n or "Pen" in n for n in names))
            self.assertEqual(set(pool["pitcher_roles"].values()), {"declared_probable_sp"})
            statuses = {t: v["status"] for t, v in report["teams"].items()}
            self.assertEqual(statuses, {"T1": "confirmed", "T2": "confirmed",
                                        "T3": "confirmed", "T4": "platoon"})
            self.assertEqual(report["blockers"], [])

    def test_pool_confirmed_orders_and_platoon_slots(self):
        from mlb_engine.projections.projection_builder import batting_order_factor
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp)
            rows = pool["projection_rows"]
            confirmed = [r for r in rows if r["Team"] == "T1" and "Ace" not in r["Name"]]
            self.assertEqual(len(confirmed), 9)
            for row in confirmed:
                self.assertIn("Batting_Order", row)
                self.assertAlmostEqual(row["F2"], batting_order_factor(row["Batting_Order"]))
                self.assertIn("confirmed_order", row.get("Notes", ""))
            t4_hitters = [r for r in rows if r["Team"] == "T4" and "Ace" not in r["Name"]]
            self.assertEqual(len(t4_hitters), 9)
            self.assertFalse(any("Batting_Order" in r for r in t4_hitters))
            platoon_map = pool["platoon_order_by_player_id"]
            self.assertEqual(len(platoon_map), 9)
            t4_ids = {r["Player_ID"] for r in t4_hitters}
            self.assertEqual(set(platoon_map), t4_ids)
            kwargs = pool["run_slate_kwargs"]
            self.assertEqual(kwargs["confirmed_teams"], ["T1", "T2", "T3"])
            self.assertEqual(len(kwargs["confirmed_hitter_ids"]), 27)
            self.assertIs(kwargs["projection_rows"], pool["projection_rows"])

    def test_pool_tbd_fallback_top9_appg(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp, platoon=None)
            report = pool["pool_report"]
            self.assertEqual(report["teams"]["T4"]["status"], "fallback_top9_appg")
            self.assertEqual(report["teams"]["T4"]["hitters"], 9)
            self.assertEqual(report["kept"], 40)
            self.assertTrue(any("T4" in w and "fallback" in w for w in report["warnings"]))
            self.assertIsNone(pool["run_slate_kwargs"]["platoon_order_by_player_id"])
            t4 = [r for r in pool["projection_rows"]
                  if r["Team"] == "T4" and "Ace" not in r["Name"]]
            self.assertTrue(all("Hitter" in r["Name"] for r in t4))  # APPG picks lineup bats over bench

    def test_pool_missing_probable_is_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp, feed=pool_lineups_feed(drop_t4_probable=True))
            report = pool["pool_report"]
            self.assertEqual(report["pitchers_kept"], 3)
            self.assertTrue(any("T4" in b for b in report["blockers"]))
            self.assertEqual(report["teams"]["T4"]["hitters"], 9)  # hitters still pooled

    def test_pool_postponed_game_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp, feed=pool_lineups_feed(postpone_game2=True))
            report = pool["pool_report"]
            self.assertEqual(report["teams"]["T3"]["status"], "excluded_postponed")
            self.assertEqual(report["teams"]["T4"]["status"], "excluded_postponed")
            self.assertEqual(report["kept"], 20)
            self.assertEqual(report["pitchers_kept"], 2)
            teams_kept = {r["Team"] for r in pool["projection_rows"]}
            self.assertEqual(teams_kept, {"T1", "T2"})
            self.assertTrue(any("postponed" in w for w in report["warnings"]))
            self.assertEqual(report["blockers"], [])

    def test_pool_postponed_literal_game_info_excluded(self):
        """R26: DK marks a postponed game's Game Info with the literal string
        'Postponed', so the parsed game_id is empty and id-to-id matching can
        never exclude the team. Regression for 2026-07-28 (ATL@NYM): both
        teams fell into tbd_teams, took platoon-projected orders, and the
        postponed game's probable reached the bank as P1."""
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp, feed=pool_lineups_feed(postpone_game2=True),
                              postponed_teams=("T3", "T4"))
            report = pool["pool_report"]
            self.assertEqual(report["teams"]["T3"]["status"], "excluded_postponed")
            self.assertEqual(report["teams"]["T4"]["status"], "excluded_postponed")
            self.assertEqual(report["excluded_postponed_teams"], ["T3", "T4"])
            teams_kept = {r["Team"] for r in pool["projection_rows"]}
            self.assertEqual(teams_kept, {"T1", "T2"})  # never reach keep
            self.assertEqual(report["kept"], 20)
            self.assertEqual(report["pitchers_kept"], 2)
            self.assertEqual(pool["run_slate_kwargs"]["confirmed_teams"], ["T1", "T2"])
            self.assertTrue(any("not a matchup" in w for w in report["warnings"]))
            self.assertEqual(report["blockers"], [])

    def test_pool_salary_postponed_literal_alone_excludes(self):
        """R26 Signal 1: the salary file can know before the feed does. A
        stale feed still says Scheduled with confirmed lineups; DK's literal
        wins, because the salary CSV is authoritative for eligibility."""
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp, postponed_teams=("T3", "T4"))
            report = pool["pool_report"]
            self.assertEqual(report["teams"]["T3"]["status"], "excluded_postponed")
            self.assertEqual(report["teams"]["T4"]["status"], "excluded_postponed")
            teams_kept = {r["Team"] for r in pool["projection_rows"]}
            self.assertEqual(teams_kept, {"T1", "T2"})
            self.assertTrue(any("salary Game Info reads 'Postponed'" in w
                                for w in report["warnings"]))

    def test_pool_declared_pitcher_on_postponed_team_excluded(self):
        """R26: an explicit declaration is not a back door into a postponed
        game. T4 Ace is pid 30065 by fixture construction."""
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            pool_salary_csv(salary, postponed_teams=("T3", "T4"))
            pool = lda.build_slate_pool(
                salary, pool_lineups_feed(postpone_game2=True),
                platoon_json=pool_platoon_json(),
                declared_pitchers={"30065": "declared_probable_sp"},
            )
            self.assertNotIn("30065", pool["pitcher_roles"])
            kept_ids = {r["Player_ID"] for r in pool["projection_rows"]}
            self.assertNotIn("30065", kept_ids)
            self.assertTrue(any("declared, but the game is" in w
                                for w in pool["pool_report"]["warnings"]))

    def test_pool_all_game_info_unparsed_is_blocker_not_exclusion(self):
        """R26: every Game Info failing at once is a DK format change or the
        wrong file, not a slate of postponements. The pool blocks loudly
        instead of relabeling a parser failure as weather."""
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(tmp, postponed_teams=("T1", "T2", "T3", "T4"))
            report = pool["pool_report"]
            self.assertTrue(any("format change" in b for b in report["blockers"]))
            statuses = {v["status"] for v in report["teams"].values()}
            self.assertNotIn("excluded_postponed", statuses)
            self.assertEqual(report["excluded_postponed_teams"], [])
            self.assertEqual(report["kept"], 40)  # nothing silently dropped

    def test_pool_ignores_feed_teams_outside_the_draftgroup(self):
        """The feed covers the whole day; the salary file defines the slate.

        Regression for 2026-07-24, when a 15-game feed against a 4-game
        draftgroup produced 22 "0/9 salary hitters" warnings about teams that
        could never have been in the pool, burying the real ones.
        """
        feed = pool_lineups_feed()
        extra = dict(feed["games"][0])
        extra["game_pk"] = 3
        extra["away"] = {"team_abbrev": "T7", "lineup_status": "confirmed",
                         "probable_pitcher": {"name": "T7 Ace", "hand": "R", "id": 600007},
                         "lineup": [{"name": f"T7 Hitter{i+1}", "order": i + 1}
                                    for i in range(9)]}
        extra["home"] = {"team_abbrev": "T8", "lineup_status": "confirmed",
                         "probable_pitcher": {"name": "T8 Ace", "hand": "R", "id": 600008},
                         "lineup": [{"name": f"T8 Hitter{i+1}", "order": i + 1}
                                    for i in range(9)]}
        feed["games"] = feed["games"] + [extra]
        with tempfile.TemporaryDirectory() as tmp:
            report = self._pool(tmp, feed=feed)["pool_report"]
            noise = [w for w in report["warnings"] if "T7" in w or "T8" in w]
            self.assertEqual(noise, [])
            self.assertNotIn("T7", report["teams"])
            self.assertNotIn("T8", report["teams"])
            self.assertEqual(report["blockers"], [])

    def test_pool_confirmed_team_crosswalk_failure_is_blocker(self):
        """A posted lineup that matches almost no salary rows is a join failure.

        Building anyway substitutes a projected or APPG order while the real
        lineup sits unused, and the certified file cannot show that happened.
        """
        ghosted = pool_lineups_feed()
        ghosted["games"][0]["away"]["lineup"] = [
            {"name": f"T1 Ghost{i+1}", "order": i + 1} for i in range(9)]
        with tempfile.TemporaryDirectory() as tmp:
            report = self._pool(tmp, feed=ghosted)["pool_report"]
            self.assertTrue(any("T1" in b and "crosswalk" in b
                                for b in report["blockers"]), report["blockers"])

        # Boundary: 5 of 9 matched is thin data, not a join failure. Warning only.
        partial = pool_lineups_feed()
        for i in range(4):
            partial["games"][0]["away"]["lineup"][i]["name"] = f"T1 Ghost{i+1}"
        with tempfile.TemporaryDirectory() as tmp:
            report = self._pool(tmp, feed=partial)["pool_report"]
            self.assertTrue(any("T1: confirmed lineup matched 5/9" in w
                                for w in report["warnings"]), report["warnings"])
            self.assertFalse(any("T1" in b for b in report["blockers"]))

    def test_pool_blocks_when_feed_does_not_cover_the_draftgroup(self):
        """Keyed on game coverage, never on how many lineups have posted.

        An early build legitimately has zero confirmed teams and must not be
        blocked for it; a feed missing the slate's games entirely is a different
        thing and means the wrong feed was passed.
        """
        half = pool_lineups_feed()
        half["games"] = half["games"][:1]          # slate has T3@T4, feed does not
        with tempfile.TemporaryDirectory() as tmp:
            report = self._pool(tmp, feed=half)["pool_report"]
            self.assertTrue(any("does not match this draftgroup" in b
                                for b in report["blockers"]), report["blockers"])

        # One missing team out of four is a warning, not a blocker.
        mostly = pool_lineups_feed()
        mostly["games"][1]["home"]["team_abbrev"] = "T9"
        with tempfile.TemporaryDirectory() as tmp:
            report = self._pool(tmp, feed=mostly)["pool_report"]
            self.assertFalse(any("does not match this draftgroup" in b
                                 for b in report["blockers"]), report["blockers"])
            self.assertTrue(any("absent from the lineups feed" in w and "T4" in w
                                for w in report["warnings"]), report["warnings"])

        # Nothing posted yet: all teams tbd, feed still covers the games.
        unposted = pool_lineups_feed()
        for game in unposted["games"]:
            for team_side in ("away", "home"):
                game[team_side]["lineup_status"] = "tbd"
                game[team_side]["lineup"] = []
        with tempfile.TemporaryDirectory() as tmp:
            report = self._pool(tmp, feed=unposted)["pool_report"]
            self.assertFalse(any("does not match this draftgroup" in b
                                 for b in report["blockers"]), report["blockers"])


class EasternCalendarAuthorityTests(unittest.TestCase):
    """R65. Baseball's day is an ET day; this container's day is a UTC day.

    Three callers computed slate dates from `date.today()` or a hardcoded UTC-4,
    so between 8pm ET and midnight ET they were answering about a different
    calendar day than the one the schedule runs on. `repo_env` is now the single
    authority and takes an injected instant so the boundary is pinnable.
    """

    ET = ZoneInfo("America/New_York")

    def setUp(self):
        from mlb_engine import repo_env
        self.env = repo_env

    def test_the_8pm_et_rollover_is_the_case_that_broke(self):
        # 00:15 UTC on Aug 6 is 8:15pm ET on Aug 5: a live build for TONIGHT's
        # slate, at the hour the container's calendar has already moved on.
        now = datetime(2026, 8, 6, 0, 15, tzinfo=timezone.utc)
        self.assertEqual(now.date().isoformat(), "2026-08-06")  # what today() said
        self.assertEqual(self.env.today_et(now), "2026-08-05")
        self.assertEqual(self.env.et_day_offsets(now=now), ("2026-08-05", "2026-08-06"))

    def test_est_months_are_utc_minus_five(self):
        # The retired approximation was a hardcoded UTC-4 commented "EDT covers
        # the MLB season". Any instant in the 04:00-05:00 UTC window returned
        # tomorrow's ET date in EST months, which is when archive work runs.
        now = datetime(2026, 12, 1, 4, 30, tzinfo=timezone.utc)
        self.assertEqual((now - timedelta(hours=4)).date().isoformat(), "2026-12-01")
        self.assertEqual(self.env.today_et(now), "2026-11-30")
        self.assertEqual(self.env.now_et(now).utcoffset(), timedelta(hours=-5))

    def test_offsets_come_from_one_reading(self):
        # Two date.today() calls can straddle midnight and return a
        # non-adjacent pair. One reading cannot, at any instant.
        for hour in (3, 4, 5, 23):
            with self.subTest(hour=hour):
                now = datetime(2026, 8, 6, hour, 59, 59, tzinfo=timezone.utc)
                today, tomorrow = self.env.et_day_offsets(now=now)
                self.assertEqual(
                    (datetime.strptime(tomorrow, "%Y-%m-%d")
                     - datetime.strptime(today, "%Y-%m-%d")), timedelta(days=1))

    def test_a_naive_datetime_is_refused_not_guessed(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.env.now_et(datetime(2026, 8, 6, 0, 15))

    def test_fetch_slate_bundle_defaults_through_the_authority(self):
        from tools.fetch_slate_bundle import _today_et
        self.assertEqual(_today_et(), self.env.today_et())


class RotoWireParseFloorTests(unittest.TestCase):
    """R65, second half. A regex parser over live third-party HTML fails EMPTY.

    An empty platoon file is worse than no file: the next build merges it, counts
    zero lineups, and reports a successful fetch. The floor refuses to emit one.
    """

    def setUp(self):
        from tools import fetch_rotowire_lineups as frl
        self.frl = frl

    def test_regex_drift_on_a_real_page_is_refused(self):
        # Substantial HTML, zero game containers: the split/anchor regexes no
        # longer match the page. Unambiguous, and independent of whether any
        # lineup has posted.
        report = {"page_bytes": 480_000, "blocks": 0, "games": 0,
                  "teams_with_order": 0, "teams_without_order": 0}
        # Assert on wording unique to the drift branch. Both branches can fire on
        # this input (0 games implies 0 orders), so what is being pinned is WHICH
        # diagnosis the operator gets -- "the layout moved" sends them to the
        # regexes, "nothing to merge" sends them to the slate.
        with self.assertRaisesRegex(self.frl.RotoWireParseFloor, "layout moved"):
            self.frl.check_parse_floor(report)
        with self.assertRaisesRegex(self.frl.RotoWireParseFloor, "480000 bytes"):
            self.frl.check_parse_floor(report)

    def test_games_found_but_nothing_to_merge_is_refused(self):
        report = {"page_bytes": 480_000, "blocks": 15, "games": 15,
                  "teams_with_order": 0, "teams_without_order": 30}
        with self.assertRaisesRegex(self.frl.RotoWireParseFloor, "nothing to merge"):
            self.frl.check_parse_floor(report)

    def test_an_early_fetch_before_lineups_post_is_not_a_failure(self):
        # 9am ET on a full slate: the game containers are up, two clubs have
        # posted. This is the case an absolute >=24-team floor would have
        # refused, which is why the floor is structural instead.
        report = {"page_bytes": 480_000, "blocks": 15, "games": 15,
                  "teams_with_order": 2, "teams_without_order": 28}
        self.assertIsNone(self.frl.check_parse_floor(report))

    def test_a_light_schedule_day_is_not_a_failure(self):
        # A 9-game day is 18 teams even with every lineup posted.
        report = {"page_bytes": 300_000, "blocks": 9, "games": 9,
                  "teams_with_order": 18, "teams_without_order": 0}
        self.assertIsNone(self.frl.check_parse_floor(report))

    def test_min_teams_is_the_knob_for_a_caller_that_knows_better(self):
        report = {"page_bytes": 300_000, "blocks": 15, "games": 15,
                  "teams_with_order": 18, "teams_without_order": 12}
        self.assertIsNone(self.frl.check_parse_floor(report, min_teams=18))
        with self.assertRaisesRegex(self.frl.RotoWireParseFloor, r"floor 24"):
            self.frl.check_parse_floor(report, min_teams=24)

    def test_an_empty_response_is_not_diagnosed_as_regex_drift(self):
        # A truncated or empty body has no game containers either, but calling
        # that "the layout moved" would send the operator to the wrong place.
        report = {"page_bytes": 12, "blocks": 0, "games": 0,
                  "teams_with_order": 0, "teams_without_order": 0}
        with self.assertRaisesRegex(self.frl.RotoWireParseFloor, "nothing to merge"):
            self.frl.check_parse_floor(report)

    def test_the_parser_reports_the_counts_the_floor_reads(self):
        # Built from the module's own regex constants rather than a hand-typed
        # page, so this pins the report wiring without pretending to be a
        # fixture of the real page (see R90).
        frl = self.frl

        def team_block(abbr, anchor, players):
            rows = "".join(
                f'<div class="lineup__pos">{pos}</div>'
                f'<a href="/x" title="{name}">{name}</a>'
                f'<span class="lineup__bats">{bats}</span>'
                for pos, name, bats in players)
            return f'<div class="{anchor}"><div class="lineup__abbr">{abbr}</div>{rows}</div>'

        def game(away, home, away_players, home_players):
            return ('<div class="lineup is-mlb">'
                    f'<div class="lineup__abbr">{away}</div>'
                    f'<div class="lineup__abbr">{home}</div>'
                    + team_block(away, "lineup__list is-visit", away_players)
                    + team_block(home, "lineup__list is-home", home_players)
                    + "</div>")

        nine = [("C", "A B", "R")] * 9
        page = ("<html>" + " " * 3000
                + game("NYY", "BOS", nine, nine)
                + game("LAD", "SF", nine, [])          # SF has not posted
                + '<div class="lineup is-mlb">template only</div>'
                + "</html>")
        report = {}
        teams = frl.parse_lineups(page, report=report)
        self.assertEqual(report["games"], 2, "the template block must not count")
        self.assertEqual(report["blocks"], 3)
        self.assertEqual(report["teams_with_order"], 3)
        self.assertEqual(report["teams_without_order"], 1)
        self.assertEqual(report["page_bytes"], len(page))
        self.assertEqual([t["abbrev"] for t in teams], ["NYY", "BOS", "LAD"])
        self.assertIsNone(frl.check_parse_floor(report))
        # and the report travels on the emitted document
        doc = frl.to_platoon_schema(teams, "2026-08-05")
        self.assertEqual(doc["team_count"], 3)

    def test_collected_date_defaults_to_et(self):
        import inspect
        src = inspect.getsource(self.frl.fetch_rotowire_platoon)
        self.assertIn("today_et()", src)
        self.assertNotIn("dt.date.today()", src)


class BuildSlateScriptTests(unittest.TestCase):
    """Covers the two pure helpers in the generate-lineups build script.

    The script is the production front door but had no test harness; its
    top-level imports are stdlib only, so it loads without the engine.
    """

    def test_rotowire_window_reads_the_et_calendar(self):
        # R65. The window logic was always right; the two dates handed to it
        # came from the container's UTC calendar. With ET dates, a build started
        # at 8:15pm ET resolves tonight's slate to "today" (it used to fall out
        # of the window entirely and skip the merge in silence) and tomorrow's
        # to "tomorrow" (it used to resolve to "today" and fetch the wrong ET
        # day under a fresh collected_date).
        mod = self._module()
        from mlb_engine.repo_env import et_day_offsets
        now = datetime(2026, 8, 6, 0, 15, tzinfo=timezone.utc)  # 8:15pm ET Aug 5
        today, tomorrow = et_day_offsets(now=now)
        self.assertEqual(mod.rotowire_window("2026-08-05", today, tomorrow), "today")
        self.assertEqual(mod.rotowire_window("2026-08-06", today, tomorrow), "tomorrow")
        # a backfill is still out of range, which is the branch that must stay
        self.assertIsNone(mod.rotowire_window("2026-08-04", today, tomorrow))
        self.assertIsNone(mod.rotowire_window("2026-08-07", today, tomorrow))
        # and the pre-fix UTC dates prove the failure this pins
        utc_today = now.date().isoformat()
        utc_tomorrow = (now.date() + dtmod.timedelta(days=1)).isoformat()
        self.assertIsNone(mod.rotowire_window("2026-08-05", utc_today, utc_tomorrow))
        self.assertEqual(mod.rotowire_window("2026-08-06", utc_today, utc_tomorrow),
                         "today")

    def test_the_rotowire_gate_asks_the_et_authority_not_the_container(self):
        """R65 at the call site, behaviorally.

        `rotowire_window` and `repo_env` are each pinned on their own, and that
        left the join between them unpinned: reverting this call site to
        `date.today()` kept both green. So this drives the real function with an
        injected ET clock and a stubbed fetch, and asserts which RotoWire page it
        asked for.
        """
        mod = self._module()
        from mlb_engine import repo_env
        from tools import fetch_rotowire_lineups as frl

        # 00:15 UTC == 8:15pm ET the previous day, which is the rollover window.
        # The date is deliberately in the PAST and far from any run date: if the
        # frozen instant sat near today, a call site reading the container clock
        # would produce the same answers and this test would pass under the very
        # mutation it exists to catch. Asserted, not assumed.
        frozen = datetime(2026, 6, 10, 0, 15, tzinfo=timezone.utc)
        self.assertNotEqual(frozen.date(), dtmod.date.today(),
                            "the frozen instant must not be able to coincide with "
                            "the container's calendar, or this pins nothing")
        asked = []

        def fake_fetch(date, **kwargs):
            asked.append(date)
            return {"teams": [], "collected_date": kwargs.get("collected_date")}

        real_now, real_fetch = repo_env.now_et, frl.fetch_rotowire_platoon
        repo_env.now_et = lambda now=None: real_now(frozen if now is None else now)
        frl.fetch_rotowire_platoon = fake_fetch
        try:
            args = types.SimpleNamespace(date="2026-06-09", rotowire=True)
            self.assertIsNotNone(mod.resolve_platoon_json(args))
            self.assertEqual(asked, ["today"],
                             "the gate fell out of the ET window for tonight's slate")
            args = types.SimpleNamespace(date="2026-06-10", rotowire=True)
            mod.resolve_platoon_json(args)
            self.assertEqual(asked[-1], "tomorrow",
                             "tomorrow's ET slate asked for the wrong RotoWire page")
            # a real backfill still declines, and now says so out loud
            args = types.SimpleNamespace(date="2026-06-01", rotowire=True)
            self.assertIsNone(mod.resolve_platoon_json(args))
            self.assertEqual(len(asked), 2, "a backfill fetched anyway")
        finally:
            repo_env.now_et, frl.fetch_rotowire_platoon = real_now, real_fetch

    def test_the_script_still_loads_without_the_engine_on_the_path(self):
        # The ET authority is imported inside the functions that need it, so the
        # class docstring's stdlib-only top-level property survives R65.
        import ast
        path = (Path(__file__).resolve().parents[1] / "skills" / "generate-lineups"
                / "scripts" / "build_slate.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        engine = [n for n in top_level
                  if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("mlb_engine")]
        self.assertEqual(engine, [], "build_slate grew a top-level engine import")

    @staticmethod
    def _module():
        import importlib.util
        path = (Path(__file__).resolve().parents[1] / "skills" / "generate-lineups"
                / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location("build_slate_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_brief_records_the_objective_each_contest_resolved_to(self):
        """R40. The build's objective per contest used to print to stderr and
        stop there, which is how 'which profile scored this build' became
        archaeology for two rank-1 finishes. The weights ride along with the
        shape name because a name only means something against the version of
        the profile table that was current when the build ran."""
        mod = self._module()
        rows = mod._contest_objective_block({
            "9": {"contest_name": "MLB Satellite to $15 Relay Throw",
                  "posture": "wta_satellite", "contest_shape": "satellite",
                  "posture_source": "name_inference", "matched_pattern": "satellite"},
            "1": {"contest_name": "MLB $5 FFM", "posture": "wta_satellite",
                  "contest_shape": "large_wta", "posture_source": "curated"},
        })
        self.assertEqual([r["contest_id"] for r in rows], ["1", "9"],
                         "contests are recorded in a stable order")
        by_id = {r["contest_id"]: r for r in rows}
        self.assertEqual(by_id["9"]["posture"], "wta_satellite")
        self.assertEqual(by_id["9"]["posture_source"], "name_inference")
        self.assertEqual(by_id["9"]["profile"]["contest_shape"], "satellite")
        self.assertAlmostEqual(by_id["9"]["profile"]["floor_weight"], 0.42)
        self.assertEqual(by_id["1"]["profile"]["mode_family"], "wta")
        self.assertAlmostEqual(by_id["1"]["profile"]["floor_weight"], 0.00)
        self.assertEqual(mod._contest_objective_block(None), [])

    def test_an_unknown_contest_shape_is_recorded_as_an_error_not_dropped(self):
        """Bookkeeping must never break a delivery, and must never quietly
        report a shape it could not resolve as having no profile."""
        mod = self._module()
        row = mod._contest_objective_block(
            {"7": {"contest_shape": "not_a_shape", "posture": "large_gpp"}})[0]
        self.assertIn("error", row["profile"])

    def test_gate_failure_detail_collects_cause(self):
        """R27 open half: a failed pre-export gate names itself, its evidence
        line, and the pool blockers, so the not_certified payload carries the
        cause instead of leaving it to a by-hand pool rebuild."""
        mod = self._module()
        result = {
            "errors": [
                "Failed pre-export gate: lineup_gate_passed",
                "Missing pre-export gate: odds_gate_passed",
                "Failed pre-export gate: lineup_gate_passed",  # dupe collapses
                "allocation failed",  # non-gate error stays out
            ],
            "workflow_gate_evidence": {
                "lineup_gate_passed":
                    "pool report: 1 blockers, 0 team(s) under nine hitters",
            },
        }
        report = {"blockers": ["platoon reference is 27 days old against slate"]}
        detail = mod.gate_failure_detail(result, report)
        self.assertEqual(detail["failed_gates"],
                         ["lineup_gate_passed", "odds_gate_passed"])
        self.assertEqual(detail["gate_evidence"]["lineup_gate_passed"],
                         "pool report: 1 blockers, 0 team(s) under nine hitters")
        self.assertEqual(detail["gate_evidence"]["odds_gate_passed"],
                         "no evidence recorded")
        self.assertEqual(detail["pool_blockers"],
                         ["platoon reference is 27 days old against slate"])
        # Empty inputs produce an empty dict, so the payload merge is a no-op.
        self.assertEqual(mod.gate_failure_detail({}, {}), {})
        self.assertEqual(mod.gate_failure_detail({"errors": ["x"]}, None), {})

    def test_feed_age_minutes_reads_fetched_at(self):
        import datetime as dt
        mod = self._module()
        self.assertIsNone(mod.feed_age_minutes({}))
        self.assertIsNone(mod.feed_age_minutes({"fetched_at": "not a time"}))
        recent = (dt.datetime.now(dt.timezone.utc)
                  - dt.timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        self.assertAlmostEqual(mod.feed_age_minutes({"fetched_at": recent}), 30.0, delta=1.0)

    def test_verify_classic_enforces_dk_team_and_game_rules(self):
        mod = self._module()
        header = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary",
                  "Game Info", "AvgPointsPerGame", "TeamAbbrev"]
        slots = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]

        def write(tmp, teams, games):
            salary = Path(tmp) / "s.csv"
            with salary.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                for i, slot in enumerate(slots):
                    w.writerow([slot, f"P{i} ({i})", f"P{i}", i, slot, 4000,
                                f"{games[i]} 07/10/2026 07:05PM ET", 8.0, teams[i]])
            entries = Path(tmp) / "e.csv"
            with entries.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee"] + slots)
                w.writerow(["1", "c", "2", "$1"] + [str(i) for i in range(10)])
            return salary, entries

        # Six hitters from one team: over the DK cap of five.
        stacked = ["A", "B"] + ["H"] * 6 + ["Z", "Z"]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = write(tmp, stacked, ["A@B"] * 2 + ["H@Z"] * 8)
            result = mod.verify_classic(salary, entries)
            self.assertFalse(result["passed"])
            self.assertTrue(any("more than 5 hitters" in f for f in result["failures"]),
                            result["failures"])

        # Every player from a single game: DK requires at least two.
        with tempfile.TemporaryDirectory() as tmp:
            teams = ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"]
            salary, entries = write(tmp, teams, ["A@B"] * 10)
            result = mod.verify_classic(salary, entries)
            self.assertTrue(any("DK requires 2" in f for f in result["failures"]),
                            result["failures"])

        # A legal lineup across two games passes both new checks.
        with tempfile.TemporaryDirectory() as tmp:
            teams = ["A", "C", "A", "A", "A", "A", "C", "C", "C", "C"]
            salary, entries = write(tmp, teams, ["A@B"] * 6 + ["C@D"] * 4)
            result = mod.verify_classic(salary, entries)
            self.assertEqual([f for f in result["failures"]
                              if "hitters" in f or "game(s)" in f], [])


class BankBudgetFloorTests(unittest.TestCase):
    """R98(1): a bank budget bounded by a constant instead of by --max-seconds
    must say so, because the thin bank that follows is otherwise indistinguishable
    from a deliberately small search. The 1910_9g brief recorded
    ``time_budget_s: 5.0`` and the operator read it as a choice."""

    _module = staticmethod(BuildSlateScriptTests._module)

    @staticmethod
    def _capture():
        import contextlib
        import io
        return contextlib.redirect_stderr(io.StringIO())

    def test_a_computed_budget_above_the_floor_is_silent_and_unfloored(self):
        mod = self._module()
        with self._capture() as err:
            budget, floored = mod.resolve_bank_budget(21.5, label="sliced bank")
        self.assertEqual(budget, 21.5)
        self.assertFalse(floored)
        self.assertEqual(err.getvalue(), "")

    def test_a_budget_below_the_floor_is_raised_flagged_and_announced(self):
        mod = self._module()
        # The live shape: --max-seconds 11, most of it already spent on imports
        # and pool construction, so the subtraction goes negative.
        with self._capture() as err:
            budget, floored = mod.resolve_bank_budget(-3.0, label="sliced bank")
        self.assertEqual(budget, mod.BANK_BUDGET_FLOOR_S)
        self.assertTrue(floored)
        printed = err.getvalue()
        self.assertIn("BANK BUDGET FLOORED", printed)
        self.assertIn("sliced bank", printed)
        # The announcement must name the remedy, not merely the condition.
        self.assertIn("exits 10 and resumes", printed)
        self.assertIn("do not relax", printed.lower())

    def test_the_floor_boundary_itself_does_not_report_as_floored(self):
        mod = self._module()
        with self._capture() as err:
            budget, floored = mod.resolve_bank_budget(
                mod.BANK_BUDGET_FLOOR_S, label="sliced bank")
        self.assertEqual(budget, mod.BANK_BUDGET_FLOOR_S)
        self.assertFalse(floored, "equal to the floor is not bounded BY the floor")
        self.assertEqual(err.getvalue(), "")


class InfeasibilityRemedyOrderTests(unittest.TestCase):
    """R98(2), both halves of the same lesson.

    The 1910_9g build proved infeasible against a bank explored to 1.8% and every
    message it printed was true. The operator raised three exposure caps from
    0.35/0.43 to 0.56 and certified, because nothing distinguished a control that
    was genuinely binding from a search that had not run.
    """

    # --- allocator half -------------------------------------------------- #

    @staticmethod
    def _roster(seed):
        return [f"{seed}-{i}" for i in range(10)]

    def _infeasible(self, **kwargs):
        """The live shape: far fewer distinct stacks than the cap needs."""
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary="AAA")
                 for i in range(3)]
        return select_and_assign_entries(
            cands, _entry_reqs(6), {"max_primary_stack_exposure_pct": 0.34},
            **kwargs)

    def test_an_unexhausted_job_list_makes_bank_growth_the_first_remedy(self):
        result = self._infeasible(bank_report={
            "job_list_exhausted": False, "jobs_attempted": 47,
            "jobs_total": 2592, "budget_floored": True,
        })
        self.assertFalse(result["passed"])
        errors = result["errors"]
        # The solver's own arithmetic still leads: what it PROVED is unchanged.
        self.assertIn("proven infeasible", errors[0])
        remedies = [e for e in errors if "REMEDY" in e]
        self.assertTrue(remedies, errors)
        self.assertIn("grow the bank", remedies[0])
        self.assertIn("47 of 2592", remedies[0])
        self.assertIn("1.8%", remedies[0])
        self.assertIn("exits 10 and resumes", remedies[0])
        self.assertIn("engine floor", remedies[0])
        # --controls-override never precedes it.
        self.assertLess(errors.index(remedies[0]),
                        min(i for i, e in enumerate(errors)
                            if "--controls-override" in e))

    def test_an_exhausted_job_list_never_claims_the_bank_is_the_problem(self):
        result = self._infeasible(bank_report={"job_list_exhausted": True})
        joined = " ".join(result["errors"])
        self.assertNotIn("grow the bank", joined)
        self.assertIn("--controls-override", joined)

    def test_a_missing_bank_report_asserts_nothing_about_the_bank(self):
        """Absence of evidence is not evidence the search completed.

        The floor-versus-cap classification is true of the controls whatever the
        bank did, so it survives; the bank sentence is the one claim that needs
        evidence, and without a report it is simply not made.
        """
        silent = self._infeasible()
        joined = " ".join(silent["errors"])
        self.assertIn("proven infeasible", joined)
        self.assertNotIn("grow the bank", joined)
        self.assertNotIn("job list", joined)
        self.assertIn("--controls-override", joined)
        # With no bank line there is no earlier remedy to be "NEXT" after.
        self.assertNotIn("NEXT REMEDY", joined)

    def test_a_structural_floor_and_an_exposure_cap_are_named_differently(self):
        result = self._infeasible(bank_report={"job_list_exhausted": True})
        line = next(e for e in result["errors"] if "--controls-override" in e)
        # The failing control here is an exposure cap, which has no floor.
        self.assertIn("max_primary_stack_exposure_pct", line)
        self.assertIn("NO engine-named floor", line)
        self.assertIn("strategy decision", line)
        self.assertNotIn("is arithmetic", line)

    def test_a_time_limit_gets_no_remedies_because_it_proved_nothing(self):
        """CLAUDE.md: the allocator says time limit OR proven infeasible, never
        both. A remedy list attached to a clock would be the same conflation."""
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary=f"T{i}")
                 for i in range(8)]
        with _patch_milp(lambda real, *a, **k: _FakeMilpResult(None, mip_gap=0.01)):
            result = select_and_assign_entries(
                cands, _entry_reqs(4),
                bank_report={"job_list_exhausted": False, "jobs_attempted": 47,
                             "jobs_total": 2592})
        joined = " ".join(result["errors"])
        self.assertIn("clock, not a proven infeasibility", joined)
        self.assertNotIn("REMEDY", joined)

    # --- build_slate half ------------------------------------------------ #

    @staticmethod
    def _hint(feasibility, bank_report):
        return BuildSlateScriptTests._module().infeasibility_hint(
            feasibility, bank_report)

    def test_the_hint_leads_with_the_bank_then_splits_floor_from_cap(self):
        """The exact 1910_9g composite: a starved bank AND a max_shared_players
        floor failure AND an exposure cap that could be raised to fit."""
        hint = self._hint(
            {"passed": False, "checks": [
                {"name": "shared_players_floor", "passed": False,
                 "detail": "max_shared_players 6 vs inherent overlap floor 7",
                 "remedy": "raise max_shared_players to >= 7"},
                {"name": "pitcher_exposure_capacity", "passed": False,
                 "detail": "cap 3 x 5 viable SPs = 15 vs 18 pitcher slots",
                 "remedy": "raise max_pitcher_exposure_pct to >= 0.560 (cap 5)"},
                {"name": "sp_pair_capacity", "passed": True, "detail": "fine"},
            ]},
            {"job_list_exhausted": False, "jobs_attempted": 47,
             "jobs_total": 2592, "budget_floored": True, "total_candidates": 38})
        self.assertIsNotNone(hint)
        self.assertTrue(hint.startswith("GROW THE BANK FIRST"), hint)
        self.assertIn("47 of 2592", hint)
        self.assertIn("engine floor", hint)
        # Order: bank, then the arithmetic floor, then the strategy decision.
        self.assertLess(hint.index("GROW THE BANK"), hint.index("ARITHMETIC"))
        self.assertLess(hint.index("ARITHMETIC"), hint.index("STRATEGY DECISION"))
        self.assertIn("max_shared_players to >= 7", hint)
        self.assertIn("NO engine-named floor", hint)
        self.assertIn("not a recommendation", hint)

    def test_an_exhausted_bank_with_only_a_structural_failure_omits_growth(self):
        hint = self._hint(
            {"passed": False, "checks": [
                {"name": "shared_players_floor", "passed": False, "detail": "d",
                 "remedy": "raise max_shared_players to >= 7"},
            ]},
            {"job_list_exhausted": True, "jobs_attempted": 2592,
             "jobs_total": 2592})
        self.assertNotIn("GROW THE BANK", hint)
        self.assertTrue(hint.startswith("ARITHMETIC"), hint)
        self.assertNotIn("STRATEGY DECISION", hint)

    def test_nothing_true_to_say_produces_no_hint_rather_than_a_guess(self):
        self.assertIsNone(self._hint({"passed": True, "checks": []},
                                     {"job_list_exhausted": True}))
        self.assertIsNone(self._hint(None, None))
        # A passing check with a remedy string is not a failure.
        self.assertIsNone(self._hint(
            {"passed": True, "checks": [
                {"name": "shared_players_floor", "passed": True,
                 "detail": "d", "remedy": None}]},
            {"job_list_exhausted": True}))


class BuildContractCheckpointTests(unittest.TestCase):
    """R63, decided 2026-08-08: build_slate reviews on its own approve=True call
    and does NOT run a plan leg first. These pin the two halves of that decision
    so a later session re-reading CLAUDE.md item 3 cannot quietly reopen it."""

    def test_build_slate_makes_exactly_one_run_slate_call_and_it_approves(self):
        """Behavioural intent stated structurally, because the alternative -- a
        second run_slate(approve=False) call -- is exactly a call-graph fact."""
        import ast
        path = (Path(__file__).resolve().parents[1] / "skills" / "generate-lineups"
                / "scripts" / "build_slate.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "run_slate"]
        self.assertEqual(len(calls), 1, "build_slate grew a second run_slate call")
        approve = [kw.value for kw in calls[0].keywords if kw.arg == "approve"]
        self.assertEqual(len(approve), 1)
        self.assertIs(approve[0].value, True)

    def test_the_engine_api_checkpoint_still_carries_the_plan_verdict(self):
        """The other half of the decision: approve=False keeps R28's bank
        verdict, so the contract's engine-API leg is not hollowed out by
        build_slate's exemption."""
        import inspect
        source = inspect.getsource(epi.run_slate)
        self.assertIn("_plan_joint_allocation", source)
        self.assertIn("if not approve:", source)


class BuildSlateEnrichmentWiringTests(unittest.TestCase):
    """The I-1 gap: enrichment that exists, is tested, and reaches no build.

    Distinct from ProjectionEnrichmentWiringTests above, which covers the engine
    layer. These cover the SCRIPT layer, which is where the gap actually was.

    Production builds ranked players on AvgPointsPerGame times a batting-order
    factor because the script that builds slates never passed the Savant CSVs,
    the FanGraphs CSV, or an F4 map to the engine. Nothing downstream could
    detect that, because a certified file built on bare APPG is indistinguishable
    at certification time from one built on real signal. These tests drive the
    script path specifically, so the wiring cannot silently come undone again.
    """

    @staticmethod
    def _module():
        return BuildSlateScriptTests._module()

    @staticmethod
    def _args(**overrides):
        import types
        base = dict(enrichment=True, reference_dir=None, reference_max_age_days=14.0)
        base.update(overrides)
        return types.SimpleNamespace(**base)

    def _reference_dir(self, tmp, ages=None, missing=()):
        """A reference directory whose files carry controlled fetch stamps."""
        import datetime as dt
        root = Path(tmp) / "reference"
        root.mkdir(parents=True, exist_ok=True)
        names = ["expected_stats_batting.csv", "expected_stats_pitching.csv",
                 "fangraphs_season_pitching.csv"]
        files = {}
        now = dt.datetime.now(dt.timezone.utc)
        for name in names:
            if name in missing:
                continue
            (root / name).write_text("placeholder\n", encoding="utf-8")
            age = (ages or {}).get(name, 0.0)
            files[name] = {"fetched_at": (now - dt.timedelta(days=age)).isoformat()}
        (root / "reference_manifest.json").write_text(
            json.dumps({"files": files}), encoding="utf-8")
        # F17: the platoon reference joined the tracked set. Its age comes from
        # the payload's own collected_date, not from the manifest, because a
        # checkout resets mtime and that file's failure mode is reading fresh.
        from tools.refresh_reference_data import TRACKED_JSON
        for name, spec in TRACKED_JSON.items():
            if name in missing:
                continue
            age = (ages or {}).get(name, 0.0)
            stamp = (now - dt.timedelta(days=age)).date().isoformat()
            (root / name).write_text(
                json.dumps({str(spec["date_key"]): stamp, "teams": []}),
                encoding="utf-8")
        return root

    def test_resolve_reference_data_reports_ages_and_returns_paths(self):
        mod = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = self._reference_dir(tmp)
            ref = mod.resolve_reference_data(self._args(reference_dir=str(root)))
            self.assertTrue(ref["savant_batting"])
            self.assertTrue(ref["savant_pitching"])
            self.assertTrue(ref["fangraphs_pitching"])
            self.assertTrue(ref["status"]["enabled"])
            self.assertFalse(ref["status"]["any_stale"])
            self.assertEqual(ref["status"]["warnings"], [])

    def test_stale_and_missing_reference_data_warn_without_blocking(self):
        """Degraded signal beats no lineups at T-10, but it is never silent."""
        mod = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            root = self._reference_dir(
                tmp, ages={"expected_stats_batting.csv": 40.0},
                missing=("fangraphs_season_pitching.csv",))
            ref = mod.resolve_reference_data(self._args(reference_dir=str(root)))
            self.assertTrue(ref["savant_batting"])          # stale is still used
            self.assertIsNone(ref["fangraphs_pitching"])    # missing is not
            self.assertTrue(ref["status"]["any_stale"])
            joined = " ".join(ref["status"]["warnings"])
            self.assertIn("expected_stats_batting.csv", joined)
            self.assertIn("fangraphs_season_pitching.csv", joined)

    def test_no_enrichment_flag_returns_no_paths(self):
        mod = self._module()
        ref = mod.resolve_reference_data(self._args(enrichment=False))
        self.assertFalse(ref["status"]["enabled"])
        self.assertIsNone(ref["savant_batting"])
        self.assertIsNone(ref["savant_pitching"])
        self.assertIsNone(ref["fangraphs_pitching"])

    def test_build_f4_map_applies_sp_quality_and_platoon(self):
        """A tough opposing SP must discount hitters relative to a soft one."""
        mod = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            pitching = Path(tmp) / "pitching.csv"
            # est_woba against: 0.360 is hittable, 0.260 is not. Both well over
            # the PA-shrinkage threshold so neither is pulled back to neutral.
            pitching.write_text(
                "player_id,pa,woba,est_woba\n"
                "1001,600,0.360,0.360\n"
                "1002,600,0.260,0.260\n",
                encoding="utf-8")
            pool = {
                "team_by_player_id": {"h1": "AAA", "h2": "BBB"},
                "opposing_probables": {
                    "AAA": {"id": "1001", "name": "Soft Tosser", "hand": "R"},
                    "BBB": {"id": "1002", "name": "Ace", "hand": "R"},
                },
                "batter_hands": {"h1": "L", "h2": "L"},
            }
            f4, report = mod.build_f4_map(pool, str(pitching))
            self.assertGreater(f4["h1"], f4["h2"])
            self.assertEqual(report["hitters_scored"], 2)
            self.assertEqual(report["non_neutral_f4"], 2)
            # Both hitters are L vs R, so the platoon component must be live.
            self.assertEqual(report["platoon_component_applied"], 2)

    def test_build_f4_map_stays_neutral_without_an_opposing_probable(self):
        mod = self._module()
        f4, report = mod.build_f4_map(
            {"team_by_player_id": {"h1": "AAA"}, "opposing_probables": {},
             "batter_hands": {}}, None)
        self.assertEqual(f4, {"h1": 1.0})
        self.assertIn("AAA", report["teams_without_opposing_probable"])
        self.assertIn("neutral", report["warning"])

    def test_summarize_enrichment_answers_whether_the_build_had_signal(self):
        mod = self._module()
        bare = mod.summarize_enrichment({"enabled": True}, {}, {}, None)
        self.assertFalse(bare["signal_applied"])
        self.assertEqual(bare["counts"]["f4_non_neutral"], 0)

        enriched = mod.summarize_enrichment(
            {"enabled": True, "warnings": []},
            {"xwoba": {"non_neutral_applied": 40, "match_rate": 0.9},
             "ceiling": {"differentiated_rows": 38},
             "pitcher_ceiling": {"differentiated_rows": 6},
             "warnings": []},
            {"hitters_scored": 40, "non_neutral_f4": 40,
             "platoon_component_applied": 40},
            None,
        )
        self.assertTrue(enriched["signal_applied"])
        self.assertEqual(enriched["counts"]["xwoba_non_neutral"], 40)
        self.assertEqual(enriched["counts"]["f4_platoon_applied"], 40)
        # F1 and F5 are not wired yet; they must report zero, never absent.
        self.assertEqual(enriched["counts"]["f1_non_neutral"], 0)
        self.assertEqual(enriched["counts"]["f5_non_neutral"], 0)

    def test_summarize_enrichment_surfaces_a_degraded_build(self):
        mod = self._module()
        summary = mod.summarize_enrichment(
            {"enabled": True}, {}, {}, "xwOBA wiring failure: matched 0 of 60")
        self.assertTrue(summary["degraded"])
        self.assertFalse(summary["signal_applied"])
        self.assertTrue(any("DEGRADED" in w for w in summary["warnings"]))

    # --- R127(b): one boolean covered two sides with different answers -------

    @staticmethod
    def _two_sided(hitters_signal: bool, pitchers_signal: bool) -> dict:
        """The engine's by_side block for a 40-hitter / 4-pitcher slate."""
        return {
            "hitters": {"rows": 40, "ceiling_multiplier_moved": 38,
                        "factor_cells_moved": 80, "base_corrected": 40,
                        "signal_applied": hitters_signal},
            "pitchers": {"rows": 4, "ceiling_multiplier_moved": 3,
                         "factor_cells_moved": 0, "base_corrected": 0,
                         "signal_applied": pitchers_signal},
        }

    def test_the_brief_reports_signal_per_side_not_as_one_boolean(self):
        """The 2138_2g reproduction: signal_applied was True on hitter-side
        signal while all four pitchers sat at F1 = F4 = F5 = 1.0, and BUILD read
        the single True and reported the build fully enriched."""
        mod = self._module()
        summary = mod.summarize_enrichment(
            {"enabled": True, "warnings": []},
            {"xwoba": {"non_neutral_applied": 40, "match_rate": 0.9},
             "ceiling": {"differentiated_rows": 38},
             "by_side": self._two_sided(True, False),
             "warnings": []},
            {"hitters_scored": 40, "non_neutral_f4": 40}, None,
        )
        self.assertTrue(summary["signal_applied"])
        self.assertEqual(summary["signal_applied_by_side"],
                         {"hitters": True, "pitchers": False})

    def test_a_side_disagreement_raises_a_warning_naming_the_dark_side(self):
        mod = self._module()
        summary = mod.summarize_enrichment(
            {"enabled": True, "warnings": []},
            {"xwoba": {"non_neutral_applied": 40, "match_rate": 0.9},
             "by_side": self._two_sided(True, False), "warnings": []},
            {"hitters_scored": 40, "non_neutral_f4": 40}, None,
        )
        hits = [w for w in summary["warnings"]
                if "reached hitters but NOT pitchers" in w]
        self.assertEqual(len(hits), 1)
        self.assertIn("all 4 pitchers in the pool", hits[0])
        self.assertIn("signal_applied_by_side", hits[0])

    def test_both_sides_enriched_raises_no_disagreement_warning(self):
        """The falsifier: the warning is about the DISAGREEMENT, not about a
        pitcher count being small."""
        mod = self._module()
        summary = mod.summarize_enrichment(
            {"enabled": True, "warnings": []},
            {"xwoba": {"non_neutral_applied": 40, "match_rate": 0.9},
             "by_side": self._two_sided(True, True), "warnings": []},
            {"hitters_scored": 40, "non_neutral_f4": 40}, None,
        )
        self.assertEqual(summary["signal_applied_by_side"],
                         {"hitters": True, "pitchers": True})
        self.assertEqual([w for w in summary["warnings"] if "but NOT" in w], [])

    def test_a_missing_side_split_reports_none_rather_than_guessing(self):
        """An older caller or a degraded unenriched frame carries no by_side.
        None means the engine did not report it; False would claim both sides
        were measured and found dark, which is a different statement."""
        mod = self._module()
        summary = mod.summarize_enrichment({"enabled": True}, {}, {}, None)
        self.assertIsNone(summary["signal_applied_by_side"])

    def test_the_brief_carries_the_engines_named_neutral_default_list(self):
        mod = self._module()
        block = {"pitcher_ceiling": {"applied": True, "in_pool": 4, "at_neutral": 1,
                                     "neutral": 1.42,
                                     "players": [{"player_id": "30065",
                                                  "name": "Randy Dobnak",
                                                  "team": "MIN", "position": "P",
                                                  "reason": "absent_from_fangraphs_season_pitching"}]}}
        summary = mod.summarize_enrichment(
            {"enabled": True, "warnings": []},
            {"neutral_default": block, "warnings": []}, {}, None)
        named = summary["neutral_default"]["pitcher_ceiling"]["players"]
        self.assertEqual([p["name"] for p in named], ["Randy Dobnak"])
        self.assertEqual(named[0]["reason"], "absent_from_fangraphs_season_pitching")

    def test_the_brief_states_the_projection_mode_distribution(self):
        """`Projection_Mode = emergency_proxy` on every row is a fact about what
        the build was standing on, and it was visible nowhere but
        projections.csv."""
        import pandas as _pd
        mod = self._module()
        frame = _pd.DataFrame({"Projection_Mode": ["emergency_proxy"] * 38 + ["full"] * 2})
        summary = mod.summarize_enrichment(
            {"enabled": True, "warnings": []}, {"warnings": []}, {}, None,
            projections=frame)
        self.assertEqual(summary["projection_mode"],
                         {"rows": 40, "distribution": {"emergency_proxy": 38, "full": 2}})

    def test_projection_mode_is_none_when_no_frame_is_supplied(self):
        mod = self._module()
        summary = mod.summarize_enrichment({"enabled": True}, {}, {}, None)
        self.assertIsNone(summary["projection_mode"])

    def test_a_stale_reference_warning_names_what_it_feeds(self):
        """R127(b). "season rates are drifting" names a property of the file and
        nothing about the build, and it led BUILD to report that a 30-day-old
        file had not touched a build the file's own factor decided. The warning
        now names the factor and points at the per-player list."""
        import tools.refresh_reference_data as rrd
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("expected_stats_batting.csv", "expected_stats_pitching.csv",
                         "fangraphs_season_pitching.csv"):
                (root / name).write_text("x\n", encoding="utf-8")
            old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            (root / "reference_manifest.json").write_text(json.dumps(
                {"files": {n: {"fetched_at": old} for n in rrd.REQUIRED_COLUMNS}}),
                encoding="utf-8")
            warnings = rrd.reference_status(reference_dir=root)["warnings"]
            fg = [w for w in warnings if w.startswith("fangraphs_season_pitching.csv")]
            self.assertEqual(len(fg), 1)
            self.assertIn("it feeds the K-rate pitcher ceiling multipliers", fg[0])
            self.assertIn("enrichment['neutral_default']", fg[0])
            self.assertNotIn("season rates are drifting", fg[0])

    def test_a_missing_reference_warning_names_the_factor_that_is_off(self):
        import tools.refresh_reference_data as rrd
        with tempfile.TemporaryDirectory() as tmp:
            warnings = rrd.reference_status(reference_dir=Path(tmp))["warnings"]
            fg = [w for w in warnings if w.startswith("fangraphs_season_pitching.csv")]
            self.assertEqual(len(fg), 1)
            self.assertIn("it feeds the K-rate pitcher ceiling multipliers", fg[0])
            self.assertIn("which is OFF for this build", fg[0])

    def test_fetch_lineups_feed_shape_carries_handedness_fields(self):
        """extract_batter_hands and extract_opposing_probables both read fields
        the schedule hydrate does not return, so the fetcher must fill them."""
        mod = self._module()
        captured = {}

        def fake_handedness(ids):
            captured["ids"] = sorted(str(i) for i in ids)
            return {"11": {"bat": "L"}, "12": {"bat": "R"},
                    "99": {"pitch": "L"}}

        raw = {"dates": [{"games": [{
            "gamePk": 5, "gameDate": "2026-07-25T23:05:00Z",
            "status": {"detailedState": "Scheduled"},
            "teams": {
                "away": {"team": {"abbreviation": "AAA"},
                         "probablePitcher": {"id": 99, "fullName": "Arm"}},
                "home": {"team": {"abbreviation": "BBB"}},
            },
            "lineups": {"awayPlayers": [{"id": 11, "fullName": "One"},
                                        {"id": 12, "fullName": "Two"}]},
        }]}]}

        class FakeResponse:
            def read(self_inner):
                return json.dumps(raw).encode("utf-8")

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            original_open, original_hand = mod.urllib.request.urlopen, mod.fetch_handedness
            mod.urllib.request.urlopen = lambda *a, **k: FakeResponse()
            mod.fetch_handedness = fake_handedness
            try:
                feed = mod.fetch_lineups("2026-07-25", Path(tmp) / "feed.json")
            finally:
                mod.urllib.request.urlopen = original_open
                mod.fetch_handedness = original_hand

        away = feed["games"][0]["away"]
        self.assertEqual([h.get("bat_side") for h in away["lineup"]], ["L", "R"])
        self.assertEqual(away["probable_pitcher"]["hand"], "L")
        self.assertIn("99", captured["ids"])   # the probable was requested too


class F1GameEnvironmentTests(unittest.TestCase):
    """I-2: Vegas totals were fetched and discarded, so F1 was 1.0 for everyone.

    The engine priced an 11.5-total Coors game and a 7-total pitcher's park
    identically. The acceptance criterion from the 07-19 review is the first
    test here: a high-total game's hitters must carry a higher F1 than a
    low-total game's.
    """

    @staticmethod
    def _pb():
        from mlb_engine.projections import projection_builder as pb
        return pb

    def test_high_total_game_outranks_low_total_game(self):
        pb = self._pb()
        odds = {"COL@LAD": {"total": 11.5}, "SEA@SF": {"total": 7.0}}
        teams = {"h_col": "COL", "h_lad": "LAD", "h_sea": "SEA", "h_sf": "SF"}
        f1, report = pb.build_f1_factors(odds, teams)
        self.assertGreater(f1["h_col"], f1["h_sea"])
        self.assertGreater(f1["h_lad"], f1["h_sf"])
        self.assertEqual(report["games_priced"], 2)
        self.assertEqual(report["non_neutral_f1"], 4)

    def test_factors_stay_inside_the_clip(self):
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 20.0}, "CCC@DDD": {"total": 2.0}}
        teams = {"a": "AAA", "b": "BBB", "c": "CCC", "d": "DDD"}
        f1, _ = pb.build_f1_factors(odds, teams)
        low, high = pb.F1_HITTER_CLIP
        for value in f1.values():
            self.assertGreaterEqual(value, low)
            self.assertLessEqual(value, high)

    def test_moneyline_splits_the_total_toward_the_favorite(self):
        pb = self._pb()
        away, home = pb.implied_team_totals(8.5, away_price=200, home_price=-240)
        self.assertGreater(home, away)
        self.assertAlmostEqual(away + home, 8.5, places=6)
        # Without a moneyline the split is even rather than invented.
        self.assertEqual(pb.implied_team_totals(8.5), (4.25, 4.25))

    def test_pitchers_stay_neutral_in_v1(self):
        """The opposing-team total already feeds a pitcher's matchup elsewhere;
        applying it here too would double count it."""
        pb = self._pb()
        odds = {"COL@LAD": {"total": 12.0}, "SEA@SF": {"total": 6.5}}
        # Both games on the slate, so there is a real spread to normalize
        # against; a single-team slate is its own mean and correctly yields 1.0.
        teams = {"h": "COL", "h2": "SEA", "p": "COL"}
        f1, _ = pb.build_f1_factors(odds, teams, pitcher_ids=["p"])
        self.assertEqual(f1["p"], 1.0)
        self.assertNotEqual(f1["h"], 1.0)
        self.assertGreater(f1["h"], f1["h2"])

    def test_mean_is_taken_over_slate_teams_not_every_priced_game(self):
        """The odds feed covers the whole day; a draftgroup covers part of it.
        Normalizing against games nobody on the slate competes with shifts the
        whole slate and wastes the clip range."""
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 8.0}, "CCC@DDD": {"total": 8.0},
                "EEE@FFF": {"total": 14.0}}   # not on the slate
        teams = {"a": "AAA", "b": "BBB", "c": "CCC", "d": "DDD"}
        _, report = pb.build_f1_factors(odds, teams)
        self.assertEqual(report["mean_basis"], "slate_teams")
        self.assertEqual(report["mean_basis_team_count"], 4)
        self.assertAlmostEqual(report["league_mean_implied_total"], 4.0)

    def test_teams_without_a_game_line_stay_neutral(self):
        pb = self._pb()
        f1, report = pb.build_f1_factors(
            {"AAA@BBB": {"total": 9.0}}, {"a": "AAA", "z": "ZZZ"})
        self.assertEqual(f1["z"], 1.0)
        self.assertIn("ZZZ", report["teams_without_odds"])

    def test_no_odds_yields_an_empty_map_and_says_so(self):
        pb = self._pb()
        f1, report = pb.build_f1_factors({}, {"a": "AAA"})
        self.assertEqual(f1, {})
        self.assertIn("skipped", report)
        self.assertEqual(report["non_neutral_f1"], 0)

    def test_f1_map_reaches_the_projection_frame(self):
        """The whole point of I-2: the factor has to arrive in the frame the
        optimizer ranks on, not just exist in a helper."""
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            with salary.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Position", "Name + ID", "Name", "ID",
                                 "Roster Position", "Salary", "Game Info",
                                 "TeamAbbrev", "AvgPointsPerGame"])
                writer.writerow(["OF", "A (1)", "A", "1", "OF", 4000,
                                 "COL@LAD 07/25/2026 07:05PM ET", "COL", 9.0])
            rows = [{"Player_ID": "1", "AvgPointsPerGame": 9.0}]
            frame, enrichment = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                f1_by_player_id={"1": 1.12},
            )
            self.assertEqual(enrichment["f1"]["applied_count"], 1)
            self.assertAlmostEqual(float(frame.loc[0, "F1"]), 1.12)
            self.assertIn("f1_environment", str(frame.loc[0, "Notes"]))

    def test_explicit_f1_always_wins_over_the_prior(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            with salary.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Position", "Name + ID", "Name", "ID",
                                 "Roster Position", "Salary", "Game Info",
                                 "TeamAbbrev", "AvgPointsPerGame"])
                writer.writerow(["OF", "A (1)", "A", "1", "OF", 4000,
                                 "COL@LAD 07/25/2026 07:05PM ET", "COL", 9.0])
            rows = [{"Player_ID": "1", "AvgPointsPerGame": 9.0, "F1": 1.30}]
            frame, enrichment = epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                f1_by_player_id={"1": 1.12},
            )
            self.assertEqual(enrichment["f1"]["applied_count"], 0)
            self.assertAlmostEqual(float(frame.loc[0, "F1"]), 1.30)


class BankConsolidationTests(unittest.TestCase):
    """I-4, I-6, I-7: the bank was building the wrong pairs in the wrong order
    and handing the allocator candidates it could not score."""

    def test_same_game_sp_pairs_are_not_capacity(self):
        """Two opposing starters are anti-correlated at the win and
        quality-start level, so they were never real pair capacity."""
        from mlb_engine.optimize.optimizer_v3 import enumerate_sp_pairs
        frame = diverse_projection_frame()
        sp_ids = [str(p) for p in frame[frame["Position"] == "P"]["Player_ID"]]
        self.assertEqual(len(enumerate_sp_pairs(sp_ids, cross_game_only=False)), 6)
        cross = enumerate_sp_pairs(sp_ids, frame)
        self.assertEqual(len(cross), 4)
        game_of = {str(r.Player_ID): str(r.Game_ID) for r in frame.itertuples()}
        for a, b in cross:
            self.assertNotEqual(game_of[str(a)], game_of[str(b)])

    def test_pairs_are_ordered_by_combined_ceiling(self):
        """Coverage loops stop on budget exhaustion, so truncation must degrade
        from the weak end rather than from an alphabetical prefix."""
        from mlb_engine.optimize.optimizer_v3 import enumerate_sp_pairs
        frame = diverse_projection_frame()
        sp_ids = [str(p) for p in frame[frame["Position"] == "P"]["Player_ID"]]
        pairs = enumerate_sp_pairs(sp_ids, frame)
        ceiling = {str(r.Player_ID): float(r.Ceiling) for r in frame.itertuples()}
        totals = [ceiling[str(a)] + ceiling[str(b)] for a, b in pairs]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_unknown_games_do_not_shrink_the_pair_set(self):
        """An unknown game is not evidence of a same-game pair."""
        from mlb_engine.optimize.optimizer_v3 import enumerate_sp_pairs
        self.assertEqual(len(enumerate_sp_pairs(["a", "b", "c"])), 3)

    def test_cached_candidates_carry_shape_scores(self):
        """Without this the allocator falls back to raw objective on every big
        slate: no correlation bonus, no floor logic, floor_sum reads 0.0."""
        from mlb_engine.optimize.bank_cache import BankCache, extend_bank
        frame = diverse_projection_frame()
        with tempfile.TemporaryDirectory() as tmp:
            cache = BankCache(Path(tmp) / "bank.json")
            extend_bank(cache, frame, time_budget_s=12.0, max_candidates=6)
            self.assertTrue(len(cache) >= 2)

            plain = cache.as_candidates()
            self.assertNotIn("contest_fit", plain[0])

            scored = cache.as_candidates(frame, requested_n=6)
            self.assertEqual(len(scored), len(plain))
            for candidate in scored:
                self.assertIn("contest_fit", candidate)
                self.assertIsNotNone(candidate["contest_fit"]["contest_fit_score"])
                self.assertGreater(float(candidate["floor_sum"]), 0.0)

    def test_cash_shape_score_reads_the_floor_once_scored(self):
        """The cash branch reads floor_sum; unscored candidates made it 0.0 for
        everyone, so a high-floor lineup was indistinguishable from any other."""
        from mlb_engine.allocate.contest_allocator import _candidate_shape_score
        unscored = {"objective": 100.0}
        high_floor = {"objective": 100.0,
                      "contest_fit": {"contest_fit_score": 100.0, "floor_sum": 80.0}}
        low_floor = {"objective": 100.0,
                     "contest_fit": {"contest_fit_score": 100.0, "floor_sum": 40.0}}
        self.assertGreater(_candidate_shape_score(high_floor, "cash"),
                           _candidate_shape_score(low_floor, "cash"))
        # The unscored fallback cannot tell them apart at all.
        self.assertEqual(_candidate_shape_score(unscored, "cash"),
                         _candidate_shape_score(dict(unscored), "cash"))


class F5ParkWeatherWiringTests(unittest.TestCase):
    """F5 closes E-1. Park factors were computable all along and reached nothing.

    F5 is the one enrichment with a human step that cannot be automated: a
    retractable roof's open/closed state is in no forecast, and a closed roof
    cancels the wind adjustment entirely, so a wrong guess moves every hitter in
    that game the wrong way.
    """

    def _frame_with_f5(self, f5_map):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            with salary.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Position", "Name + ID", "Name", "ID",
                                 "Roster Position", "Salary", "Game Info",
                                 "TeamAbbrev", "AvgPointsPerGame"])
                writer.writerow(["OF", "A (1)", "A", "1", "OF", 4000,
                                 "COL@LAD 07/25/2026 07:05PM ET", "COL", 9.0])
            rows = [{"Player_ID": "1", "AvgPointsPerGame": 9.0}]
            return epi._assemble_projection_frame(
                str(salary), rows, "emergency_proxy", None, None, None,
                f5_by_player_id=f5_map)

    def test_f5_map_reaches_the_projection_frame(self):
        frame, enrichment = self._frame_with_f5({"1": 1.06})
        self.assertEqual(enrichment["f5"]["applied_count"], 1)
        self.assertAlmostEqual(float(frame.loc[0, "F5"]), 1.06)
        self.assertIn("f5_park_weather", str(frame.loc[0, "Notes"]))

    def test_no_f5_map_leaves_the_neutral_default(self):
        frame, enrichment = self._frame_with_f5(None)
        self.assertEqual(enrichment["f5"]["applied_count"], 0)
        self.assertAlmostEqual(float(frame.loc[0, "F5"]), 1.0)

    def test_closed_roof_cancels_wind_but_keeps_the_park_factor(self):
        from mlb_engine.intake.slate_intake_manager import compute_f5_factor
        park = {"Test Park": {"run_factor_applied": 1.06, "hr_factor_applied": 1.10}}
        adjustments = [{"adjustment_type": "wind", "level": "13-17", "direction": "out",
                        "hitter_factor": 1.03, "pitcher_factor": 0.97,
                        "game_exposure_cap": None, "exclude_game": False}]
        weather = {"wind_status": "out", "wind_speed_mph": 15.0,
                   "delay_risk": "none", "postponement_risk": "none"}
        open_roof = compute_f5_factor("Test Park", weather, park, adjustments,
                                      wind_threshold_mph=10.0, roof_closed=False)
        closed = compute_f5_factor("Test Park", weather, park, adjustments,
                                   wind_threshold_mph=10.0, roof_closed=True)
        self.assertGreater(open_roof["hitter_f5"], closed["hitter_f5"])
        # Closed still carries the park factor; only wind is cancelled.
        self.assertAlmostEqual(closed["hitter_f5"], 1.06)
        self.assertIsNone(closed["components"]["wind_row"])

    def test_wind_below_the_venue_threshold_does_not_apply(self):
        from mlb_engine.intake.slate_intake_manager import compute_f5_factor
        park = {"Test Park": {"run_factor_applied": 1.0, "hr_factor_applied": 1.0}}
        adjustments = [{"adjustment_type": "wind", "level": "8-12", "direction": "out",
                        "hitter_factor": 1.015, "pitcher_factor": 0.985,
                        "game_exposure_cap": None, "exclude_game": False}]
        weather = {"wind_status": "out", "wind_speed_mph": 9.0,
                   "delay_risk": "none", "postponement_risk": "none"}
        result = compute_f5_factor("Test Park", weather, park, adjustments,
                                   wind_threshold_mph=13.0)
        self.assertAlmostEqual(result["hitter_f5"], 1.0)
        self.assertIsNone(result["components"]["wind_row"])


class FieldMinerContractTests(unittest.TestCase):
    """field_miner v0.5: the structural gate must be able to fail.

    Before v0.5 the gate was `observed_slots == expected_slots`. On a file where
    nothing parsed, both sides were 0, so a total parse failure certified itself
    as structurally sound and emitted an empty archive block. A Showdown export
    did exactly that, because CPT/UTIL are not Classic slot tokens.
    """

    HEADER = ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup",
              "", "Player", "Roster Position", "%Drafted", "FPTS"]
    CLASSIC = ("P Gerrit Cole P Tarik Skubal C Cal Raleigh 1B Matt Olson "
               "2B Ketel Marte 3B Jose Ramirez SS Bobby Witt Jr. OF Aaron Judge "
               "OF Juan Soto OF Kyle Tucker")
    SHOWDOWN = ("CPT Aaron Judge UTIL Juan Soto UTIL Gerrit Cole UTIL Anthony Volpe "
                "UTIL Cody Bellinger UTIL Jose Ramirez")

    def _standings(self, tmp, lineups):
        path = Path(tmp) / "contest-standings-1.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(self.HEADER)
            for i, lineup in enumerate(lineups):
                writer.writerow([str(i + 1), str(9000 + i), f"u{i}", "0", "120.5",
                                 lineup, "", "Aaron Judge", "OF", "41.2%", "18.5"])
        from mlb_engine.field import field_miner as fm
        return fm.parse_standings_export(str(path))

    def test_detects_and_parses_showdown_lineups(self):
        from mlb_engine.field import field_miner as fm
        self.assertEqual(fm.detect_contest_type([self.SHOWDOWN]), "showdown")
        self.assertEqual(fm.detect_contest_type([self.CLASSIC]), "classic")
        self.assertEqual(fm.detect_contest_type([]), "classic")
        players, complete = fm.parse_lineup_string(self.SHOWDOWN, "showdown")
        self.assertTrue(complete)
        self.assertEqual(len(players), 6)
        self.assertEqual(players[0], ("CPT", "Aaron Judge"))

    def test_showdown_under_the_classic_contract_yields_nothing(self):
        """Disjoint token vocabularies, so a mismatch is empty, never wrong."""
        from mlb_engine.field import field_miner as fm
        players, complete = fm.parse_lineup_string(self.SHOWDOWN, "classic")
        self.assertEqual(players, [])
        self.assertFalse(complete)

    def test_zero_parse_fails_the_structural_gate(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            standings = self._standings(tmp, ["FLEX Aaron Judge FLEX Juan Soto"] * 3)
            result = fm.mine_contest(standings, None, contest_id="1")
            diagnostics = result["diagnostics"]
            self.assertFalse(diagnostics["parse_structural_ok"])
            self.assertIn("PARSE FAILURE", diagnostics["verification_note"])
            self.assertEqual(result["meta"]["entries_complete_lineups"], 0)

    def test_mostly_unparsed_fails_the_structural_gate(self):
        """A few withdrawn entries are normal; most of the field is not."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            standings = self._standings(tmp, [self.CLASSIC] + [""] * 4)
            result = fm.mine_contest(standings, None, contest_id="1")
            self.assertFalse(result["diagnostics"]["parse_structural_ok"])
            self.assertIn("PARSE FAILURE",
                          result["diagnostics"]["verification_note"])

    def test_clean_classic_field_still_passes(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            standings = self._standings(tmp, [self.CLASSIC] * 5)
            result = fm.mine_contest(standings, None, contest_id="1")
            self.assertTrue(result["diagnostics"]["parse_structural_ok"])
            self.assertEqual(result["contest_type"], "classic")
            self.assertEqual(result["meta"]["roster_size"], 10)

    def _salary_csv(self, tmp, showdown: bool):
        """A DK salary CSV. Showdown lists every player twice, CPT at 1.5x."""
        path = Path(tmp) / "sal.csv"
        names = ["Aaron Judge", "Juan Soto", "Gerrit Cole", "Anthony Volpe",
                 "Cody Bellinger", "Jose Ramirez"]
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Position", "Name + ID", "Name", "ID",
                             "Roster Position", "Salary", "Game Info",
                             "TeamAbbrev", "AvgPointsPerGame"])
            for i, name in enumerate(names):
                base = 8000 + i * 100
                if showdown:
                    writer.writerow(["OF", f"{name} ({i})", name, i, "CPT",
                                     int(base * 1.5), "A@B", "AAA", 9.0])
                    writer.writerow(["OF", f"{name} ({i})", name, i, "UTIL",
                                     base, "A@B", "AAA", 9.0])
                else:
                    writer.writerow(["OF", f"{name} ({i})", name, i, "OF",
                                     base, "A@B", "AAA", 9.0])
        return path

    def test_showdown_salary_map_keeps_cpt_and_util_prices_apart(self):
        """DK ships each Showdown player twice; collapsing them by name charged
        captain prices for all six slots and inflated every entry by ~36%."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            smap = fm.load_salary_map(str(self._salary_csv(tmp, showdown=True)))
            self.assertEqual(smap["__contest_type__"]["value"], "showdown")
            self.assertEqual(smap["__collisions__"]["names"], [])
            self.assertEqual(smap["aaron judge|CPT"]["salary"], 12000)
            self.assertEqual(smap["aaron judge|UTIL"]["salary"], 8000)
            # The flat key must be the base price, never the captain price.
            self.assertEqual(smap["aaron judge"]["salary"], 8000)

    def test_showdown_entry_is_charged_one_captain_and_five_util(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            smap = fm.load_salary_map(str(self._salary_csv(tmp, showdown=True)))
            standings = self._standings(tmp, [self.SHOWDOWN] * 3)
            result = fm.mine_contest(standings, smap, contest_id="1")
            # CPT Judge at 12000 plus the other five at base.
            expected = 12000 + sum(8000 + i * 100 for i in range(1, 6))
            self.assertEqual(result["entries"][0]["salary_used"], expected)
            self.assertTrue(result["diagnostics"]["parse_structural_ok"])

    def test_classic_salary_map_is_unchanged(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            smap = fm.load_salary_map(str(self._salary_csv(tmp, showdown=False)))
            self.assertEqual(smap["__contest_type__"]["value"], "classic")
            self.assertEqual(smap["aaron judge"]["salary"], 8000)
            self.assertNotIn("aaron judge|OF", smap)

    def test_wrong_contest_type_salary_file_fails_the_gate(self):
        """Joining across contest types matches on name and misprices silently."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            smap = fm.load_salary_map(str(self._salary_csv(tmp, showdown=False)))
            standings = self._standings(tmp, [self.SHOWDOWN] * 3)
            result = fm.mine_contest(standings, smap, contest_id="1")
            self.assertFalse(result["diagnostics"]["parse_structural_ok"])
            self.assertIn("WRONG SALARY FILE",
                          result["diagnostics"]["verification_note"])

    def _slate_salary(self, path, teams, extra_names=()):
        """A Classic salary file covering the given teams, 10 players each."""
        with Path(path).open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Position", "Name + ID", "Name", "ID",
                             "Roster Position", "Salary", "Game Info",
                             "TeamAbbrev", "AvgPointsPerGame"])
            pid = 0
            for team in teams:
                for j in range(10):
                    pid += 1
                    writer.writerow(["OF", f"{team}{j} ({pid})", f"{team} Player{j}",
                                     pid, "OF", 4000, "A@B", team, 8.0])
            for name in extra_names:
                pid += 1
                writer.writerow(["OF", f"{name} ({pid})", name, pid, "OF",
                                 4000, "A@B", "ZZZ", 8.0])
        return str(path)

    def _lineup_from(self, teams):
        slots = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
        names = [f"{teams[i % len(teams)]} Player{i}" for i in range(10)]
        return " ".join(f"{s} {n}" for s, n in zip(slots, names))

    def test_auto_salary_rejects_a_superset_draftgroup(self):
        """The real 2026-07-24 case: the night slate's games sat inside the main
        slate's, so a night contest joined 100% against both files."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            night_teams = ["AAA", "BBB", "CCC", "DDD"]
            night = self._slate_salary(Path(tmp) / "DKSalaries_night.csv", night_teams)
            main = self._slate_salary(Path(tmp) / "DKSalaries_main.csv",
                                      night_teams + ["EEE", "FFF", "GGG", "HHH"])
            standings = self._standings(tmp, [self._lineup_from(night_teams)] * 5)
            resolved = fm.resolve_salary_file(standings, [main, night])
            self.assertEqual(resolved["path"], night, resolved["reason"])
            by_path = {s["path"]: s for s in resolved["scored"]}
            # Both price every player; only team coverage separates them.
            self.assertEqual(by_path[main]["join_rate"], 1.0)
            self.assertEqual(by_path[night]["join_rate"], 1.0)
            self.assertLess(by_path[main]["team_coverage"],
                            by_path[night]["team_coverage"])

    def test_auto_salary_treats_identical_copies_as_one_answer(self):
        """The same slate is on disk as a staged copy, a run input, and an
        archived copy. That is not a decision to escalate."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            teams = ["AAA", "BBB", "CCC", "DDD"]
            a = self._slate_salary(Path(tmp) / "DKSalaries.csv", teams)
            b = self._slate_salary(Path(tmp) / "DKSalaries_archived.csv", teams)
            standings = self._standings(tmp, [self._lineup_from(teams)] * 5)
            resolved = fm.resolve_salary_file(standings, [a, b])
            self.assertIn(resolved["path"], (a, b))
            self.assertNotIn("ambiguous", resolved["reason"])

    def test_auto_salary_declines_when_two_real_slates_tie(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            teams = ["AAA", "BBB", "CCC", "DDD"]
            a = self._slate_salary(Path(tmp) / "DKSalaries_a.csv", teams)
            b = self._slate_salary(Path(tmp) / "DKSalaries_b.csv", teams,
                                   extra_names=("Someone Else",))
            standings = self._standings(tmp, [self._lineup_from(teams)] * 5)
            resolved = fm.resolve_salary_file(standings, [a, b])
            self.assertIsNone(resolved["path"])
            self.assertIn("ambiguous", resolved["reason"])

    def test_auto_salary_declines_rather_than_joining_a_foreign_slate(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            other = self._slate_salary(Path(tmp) / "DKSalaries_other.csv",
                                       ["XXX", "YYY"])
            standings = self._standings(
                tmp, [self._lineup_from(["AAA", "BBB", "CCC", "DDD"])] * 5)
            resolved = fm.resolve_salary_file(standings, [other])
            self.assertIsNone(resolved["path"])
            self.assertIn("standings_only", resolved["reason"])

    def test_showdown_field_carries_its_own_roster_size(self):
        """Showdown must never be scored against the Classic contract."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            standings = self._standings(tmp, [self.SHOWDOWN] * 5)
            result = fm.mine_contest(standings, None, contest_id="1")
            self.assertEqual(result["contest_type"], "showdown")
            self.assertEqual(result["meta"]["roster_size"], 6)
            self.assertTrue(result["diagnostics"]["parse_structural_ok"])


class PctFloorAndClockPipelineTests(unittest.TestCase):
    def test_slate_feasibility_emits_pct_floors(self):
        frame = diverse_projection_frame()
        feas = epi._slate_feasibility(
            {"900": {"posture": "wta_satellite"}}, _entry_reqs(16), frame, None,
        )
        self.assertTrue(feas["available"])
        self.assertEqual(feas["viable_sp_count"], 4)
        self.assertEqual(feas["stackable_team_count"], 4)
        self.assertEqual(feas["floor_pitcher_exposure_count"], 8)   # ceil(32 / 4)
        self.assertAlmostEqual(feas["floor_pitcher_exposure_pct"], 0.5)
        self.assertEqual(feas["floor_stack_exposure_count"], 4)     # ceil(16 / 4)
        self.assertAlmostEqual(feas["floor_stack_exposure_pct"], 0.25)
        self.assertEqual(feas["floor_player_exposure_count"], 8)
        self.assertAlmostEqual(feas["floor_player_exposure_pct"], 0.5)

    def test_merge_pct_floor_only_when_present_and_override_wins(self):
        pbc = {"900": {"posture": "wta_satellite"}}
        floored = epi._merged_controls_for_build(
            pbc, None, feasibility_floors={"max_pitcher_exposure_pct": 0.9},
        )
        self.assertAlmostEqual(floored["max_pitcher_exposure_pct"], 0.9)
        clamped = epi._merged_controls_for_build(
            pbc, None, feasibility_floors={"max_pitcher_exposure_pct": 1.5},
        )
        self.assertAlmostEqual(clamped["max_pitcher_exposure_pct"], 1.0)
        overridden = epi._merged_controls_for_build(
            pbc, {"max_pitcher_exposure_pct": 0.75},
            feasibility_floors={"max_pitcher_exposure_pct": 0.9},
        )
        self.assertAlmostEqual(overridden["max_pitcher_exposure_pct"], 0.75)
        empty = epi._merged_controls_for_build(
            {}, None, feasibility_floors={"max_pitcher_exposure_pct": 0.9,
                                          "max_sp_pair_repetition": 3},
        )
        self.assertNotIn("max_pitcher_exposure_pct", empty)  # floor never adds a cap
        self.assertNotIn("max_sp_pair_repetition", empty)

    def test_run_slate_pct_floor_and_clock_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            with entries.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(HEADER)
                for i in range(6):
                    writer.writerow([str(7000 + i), "WTA Sat", "900", "$5",
                                     *([""] * 10), "", ""])
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=projection_frame(ids),
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                contest_postures={"900": "wta_satellite"},
                approve=False,
            )
            controls = plan["merged_controls"]
            # Fixture slate: 2 SPs (1 pair), 2 stackable teams, 6 entries.
            self.assertEqual(controls["max_sp_pair_repetition"], 6)
            self.assertAlmostEqual(controls["max_pitcher_exposure_pct"], 1.0)  # ceil(12/2)=6 of 6
            self.assertAlmostEqual(controls["max_player_exposure_pct"], 1.0)
            # R5 moved the wta_satellite stack cap from 0.60 to 0.35. Two
            # stackable teams over six entries need ceil(6/2)=3, so the
            # feasibility floor now lifts 0.35 to 0.50 and says it did. Before
            # R5 the 0.60 cap cleared that minimum on its own and no floor was
            # recorded. The floor relaxing a tightened cap on a thin fixture is
            # the designed behavior, visible in floors_applied.
            self.assertAlmostEqual(controls["max_primary_stack_exposure_pct"], 0.5)
            applied = plan["checkpoint_plan"]["feasibility"]["controls_feasibility"]["floors_applied"]
            self.assertIn("max_pitcher_exposure_pct", applied)
            self.assertIn("max_player_exposure_pct", applied)
            self.assertIn("max_primary_stack_exposure_pct", applied)
            clock = plan["checkpoint_plan"]["slate_clock"]
            self.assertTrue(clock["available"])
            self.assertEqual(clock["source"], "salary_game_info")
            self.assertTrue(clock["past_deadline"])  # fixture slate date is in the past
            warnings = plan["checkpoint_plan"].get("warnings") or []
            self.assertTrue(any(str(w).startswith("slate_clock:") for w in warnings))


class WaterfallCheckpointTests(unittest.TestCase):
    """v1.10: posture_allocator rendered as a first-class, review-only checkpoint
    block, plus a DISPLAY-ONLY tier-derived coverage target. Nothing here auto-applies
    to the certified build; every value stays a deterministic review proxy."""

    @staticmethod
    def _menu():
        # contest_ids match the entries fixture; shapes land one A, one F, one V.
        return [
            {"contest_id": "900", "name": "MLB WTA Satellite", "entry_fee": 5,
             "field_size": 30, "paid_places": 1, "my_entries": 1},
            {"contest_id": "901", "name": "MLB Double Up", "entry_fee": 5,
             "field_size": 100, "paid_places": 30, "my_entries": 1},
            {"contest_id": "902", "name": "MLB Small Shootout", "entry_fee": 2,
             "field_size": 50, "paid_places": 5, "my_entries": 1},
        ]

    def test_waterfall_block_absent_when_not_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"; write_entries(entries)
            proj = projection_frame(ids)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                approve=False,
            )
            wf = plan["checkpoint_plan"]["waterfall"]
            self.assertFalse(wf["available"])
            self.assertIn("posture defaults", wf["note"])
            self.assertEqual(plan["status"], "plan_pending_approval")

    def test_waterfall_block_present_and_labeled(self):
        from mlb_engine.allocate import posture_allocator as pa
        result = pa.allocate(self._menu())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            write_entries(entries, rosters=[None, None, None],
                          contest_ids=["900", "901", "902"])
            proj = projection_frame(ids)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                waterfall=result, approve=False,
            )
            wf = plan["checkpoint_plan"]["waterfall"]
            self.assertTrue(wf["available"])
            self.assertEqual({r["tier"] for r in wf["tiers"]}, {"A", "F", "V"})
            self.assertEqual(set(wf["tier_entry_counts"]), {"A", "F", "V"})
            # Truthful-labels guard: the block disclaims win-rate/ROI/probability.
            for banned in ("win rate", "ROI", "probability"):
                self.assertIn(banned, wf["label"])
            self.assertIsNotNone(wf["fee_shares"])
            self.assertIsInstance(wf["coverage_target"], dict)
            self.assertTrue(wf["coverage_target"]["applies"])
            # run_slate also surfaces the block at the top level for convenience.
            self.assertEqual(plan["waterfall"], wf)

    def test_derive_coverage_target_apex_scales_sp_pairs(self):
        wf = {"rows": [{"contest_id": "900", "tier": "A"}]}
        reqs = _entry_reqs(16, contest_id="900")
        cov = epi.derive_coverage_target(wf, reqs, {"available": True, "viable_sp_pairs": 6})
        self.assertEqual(cov["sp_pair_spread_demand"], 6)   # min(16, 6), floored to min(3, 6)
        self.assertGreaterEqual(cov["coverage_target"], 6)
        self.assertEqual(cov["tier_entry_counts"], {"A": 16})
        self.assertTrue(cov["applies"])

    def test_derive_coverage_target_floor_heavy_is_compact(self):
        wf = {"rows": [{"contest_id": "900", "tier": "F"}]}
        reqs = _entry_reqs(20, contest_id="900")
        cov = epi.derive_coverage_target(wf, reqs, {"available": True, "viable_sp_pairs": 6})
        # Floor tolerates a shared chalk core, so the bank target stays small (efficiency).
        self.assertEqual(cov["coverage_target"], 2)
        self.assertIsNone(cov["sp_pair_spread_demand"])

    def test_derive_coverage_target_none_when_unresolved(self):
        wf = {"rows": [{"contest_id": "900", "tier": "UNRESOLVED"}]}
        reqs = _entry_reqs(5, contest_id="900")
        self.assertIsNone(epi.derive_coverage_target(wf, reqs, None))

    def test_coverage_target_wired_to_bank_matches_checkpoint(self):
        # Ledger 3.6 wiring test: the tier-derived coverage target shown in the
        # approve=False checkpoint is exactly the value that reaches
        # build_diverse_candidate_bank on approve=True. Real path, synthetic fixtures.
        from unittest import mock
        from mlb_engine.allocate import posture_allocator as pa
        result = pa.allocate(self._menu())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            write_entries(entries, rosters=[None, None, None],
                          contest_ids=["900", "901", "902"])
            proj = projection_frame(ids)

            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                waterfall=result, requested_n=4, approve=False,
            )
            cov = plan["checkpoint_plan"]["waterfall"]["coverage_target"]
            self.assertTrue(cov["applies"])
            shown = cov["coverage_target"]

            class _Stop(Exception):
                pass

            captured = {}

            def _spy(*args, **kwargs):
                captured["kwargs"] = kwargs
                raise _Stop()

            with mock.patch.object(opt, "build_diverse_candidate_bank", _spy):
                with self.assertRaises(_Stop):
                    run_slate(
                        runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                        projections_override=proj, waterfall=result,
                        requested_n=4, approve=True,
                    )
        self.assertEqual(captured["kwargs"].get("coverage_target"), shown)


class ContestLibraryTests(unittest.TestCase):
    """contest_library: review-only resolver turning reserved contests into a
    posture_allocator waterfall in trust order (provided > library > name > unresolved).
    Companion outside the audited engine; nothing auto-applies."""

    ARCH = str(Path(__file__).resolve().parents[1] / "data" / "reference" / "dk_contest_archetypes.csv")

    @staticmethod
    def _reserved():
        return [
            {"contest_id": "900", "name": "MLB $5 Winner Take All", "entry_fee": 5, "my_entries": 2},
            {"contest_id": "901", "name": "MLB $10 Double Up", "entry_fee": 10, "my_entries": 1},
            {"contest_id": "902", "name": "MLB $3 Relay Throw", "entry_fee": 3, "my_entries": 4},
            {"contest_id": "903", "name": "MLB Totally Novel Contest", "entry_fee": 3, "my_entries": 1},
        ]

    def test_name_archetype_resolution_and_tiers(self):
        from mlb_engine.field import contest_library as cl
        menu = {c["contest_id"]: c for c in cl.resolve_menu(self._reserved(), archetypes_path=self.ARCH)}
        self.assertEqual(menu["900"]["resolution"], "name_archetype")
        self.assertLessEqual(menu["900"]["breadth"], 0.05)     # WTA -> Apex
        self.assertGreaterEqual(menu["901"]["breadth"], 0.20)  # Double Up -> Floor
        self.assertEqual(menu["903"]["resolution"], "unresolved")

    def test_library_history_beats_name(self):
        from mlb_engine.field import contest_library as cl
        reg = cl.empty_registry()
        cl.record_observation(reg, "MLB Totally Novel Contest", 3,
                              field_size=200, paid_places=40, date_str="2026-07-18")
        menu = {c["contest_id"]: c for c in cl.resolve_menu(self._reserved(), reg, archetypes_path=self.ARCH)}
        self.assertEqual(menu["903"]["resolution"], "library")
        self.assertEqual(menu["903"]["field_size"], 200)
        self.assertEqual(menu["903"]["paid_places"], 40)

    def test_provided_beats_everything(self):
        from mlb_engine.field import contest_library as cl
        menu = {c["contest_id"]: c for c in cl.resolve_menu(
            self._reserved(), archetypes_path=self.ARCH,
            provided_menu=[{"contest_id": "900", "field_size": 50, "paid_places": 1}])}
        self.assertEqual(menu["900"]["resolution"], "provided")
        self.assertEqual(menu["900"]["paid_places"], 1)

    def test_build_waterfall_end_to_end_through_run_slate(self):
        from mlb_engine.field import contest_library as cl
        reserved = self._reserved()[:3]  # A, F, V, all name-resolved
        wf = cl.build_waterfall(reserved_contests=reserved, archetypes_path=self.ARCH)
        self.assertEqual({r["tier"] for r in wf["rows"]}, {"A", "F", "V"})
        self.assertGreaterEqual(wf["resolution_summary"]["name_archetype"], 3)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"; ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            write_entries(entries, rosters=[None, None, None],
                          contest_ids=["900", "901", "902"])
            proj = projection_frame(ids)
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj,
                candidates_override=[candidate("A", legal_rosters(ids)[0], 100)],
                waterfall=wf, approve=False,
            )
            block = plan["checkpoint_plan"]["waterfall"]
            self.assertTrue(block["available"])
            self.assertEqual({t["tier"] for t in block["tiers"]}, {"A", "F", "V"})
            self.assertTrue(all(t["resolution"] == "name_archetype" for t in block["tiers"]))
            self.assertIsInstance(block["coverage_target"], dict)


class BankCacheTests(unittest.TestCase):
    """A resumable bank exists because an unbounded build inside a bounded
    execution environment is killed with no output and no diagnostic."""

    def _roster(self, n=10, swap=False):
        ids = [f"p{i}" for i in range(n)]
        if swap:  # same ten players, OF1 and OF2 exchanged
            ids[7], ids[8] = ids[8], ids[7]
        return ids

    def test_dedupe_keys_on_ordered_roster_not_player_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            self.assertTrue(cache.add(self._roster(), 100.0))
            # Identical player set, different slot order: a genuinely different
            # candidate for late swap, which pins players to exact DK slots.
            self.assertTrue(cache.add(self._roster(swap=True), 99.0))
            self.assertEqual(len(cache), 2)
            # An exact repeat is still rejected.
            self.assertFalse(cache.add(self._roster(), 100.0))
            self.assertEqual(len(cache), 2)

    def test_round_trips_and_resumes_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache = bank_cache.BankCache(path)
            cache.add(self._roster(), 100.0, job="j1")
            cache.attempted.add("j1")
            cache.attempted.add("j2-failed")
            cache.save()

            resumed = bank_cache.BankCache(path)
            self.assertEqual(len(resumed), 1)
            # Failed jobs are remembered too, so a resumed slice does not re-pay
            # for combinations already known to be infeasible.
            self.assertEqual(resumed.attempted, {"j1", "j2-failed"})
            self.assertFalse(resumed.add(self._roster(), 100.0))

    def test_as_candidates_matches_allocator_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            cache.add(self._roster(), 100.0)
            cand = cache.as_candidates()[0]
            self.assertEqual(len(cand["roster_slot_ids"]), len(ENTRY_ROSTER_SLOTS))
            self.assertEqual(_candidate_ordered_roster(cand), tuple(self._roster()))

    def test_ordered_roster_fills_dk_slots_in_order(self):
        lineup = pd.DataFrame([
            {"Player_ID": "sp1", "Assigned_Position": "P"},
            {"Player_ID": "sp2", "Assigned_Position": "P"},
            {"Player_ID": "c1", "Assigned_Position": "C"},
            {"Player_ID": "b1", "Assigned_Position": "1B"},
            {"Player_ID": "b2", "Assigned_Position": "2B"},
            {"Player_ID": "b3", "Assigned_Position": "3B"},
            {"Player_ID": "ss1", "Assigned_Position": "SS"},
            {"Player_ID": "of1", "Assigned_Position": "OF"},
            {"Player_ID": "of2", "Assigned_Position": "OF"},
            {"Player_ID": "of3", "Assigned_Position": "OF"},
        ])
        self.assertEqual(
            bank_cache.ordered_roster(lineup),
            ("sp1", "sp2", "c1", "b1", "b2", "b3", "ss1", "of1", "of2", "of3"),
        )
        self.assertIsNone(bank_cache.ordered_roster(lineup.head(9)))


class SolveBudgetTests(unittest.TestCase):
    """Default None must leave the prior unbounded behavior byte-identical."""

    def test_budget_absent_builds_everything(self):
        ids = write_salary(Path(tempfile.mkdtemp()) / "s.csv")
        result = opt.build_multi_lineup(projection_frame(ids), n_lineups=2, mode="wta")
        self.assertEqual(len(result["lineups"]), 2)
        self.assertIsNone(result["budget"]["time_budget_s"])
        self.assertFalse(result["budget"]["exhausted"])

    def test_zero_budget_returns_partial_with_diagnostic(self):
        ids = write_salary(Path(tempfile.mkdtemp()) / "s.csv")
        result = opt.build_multi_lineup(
            projection_frame(ids), n_lineups=2, mode="wta", time_budget_s=0.0)
        self.assertTrue(result["budget"]["exhausted"])
        self.assertEqual(result["budget"]["lineups_built"], 0)
        self.assertEqual(result["budget"]["lineups_requested"], 2)


class TeamAbbrevNormalizationTests(unittest.TestCase):
    """Three vocabularies reach this engine: MLB Stats API (AZ), FanGraphs
    RosterResource (WSN/TBR/CHW/KCR/SDP/SFG), and DraftKings. An un-normalized
    code raises nothing -- it matches no salary row and fills zero hitters while
    reporting success, which is how WSH once filled 0 of 9."""

    def _salary(self, path: Path, team: str):
        header = ["Position", "Name + ID", "Name", "ID", "Roster Position",
                  "Salary", "Game Info", "TeamAbbrev"]
        game = f"{team}@ZZZ 06/11/2026 01:00PM ET"
        rows = [[p, f"{n} (2000{i})", n, f"2000{i}", p, "3000", game, team]
                for i, (p, n) in enumerate([
                    ("C", "Bat One"), ("1B", "Bat Two"), ("2B", "Bat Three")])]
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(header); w.writerows(rows)

    def _platoon(self, abbrev: str):
        return {"collected_date": "2026-06-11", "teams": [{
            "team": "Washington Nationals", "abbrev": abbrev, "page_updated": "2026-06-11",
            "vs_RHP": [{"slot": 1, "position": "C", "player": "Bat One", "bats": "R"},
                       {"slot": 2, "position": "1B", "player": "Bat Two", "bats": "L"},
                       {"slot": 3, "position": "2B", "player": "Bat Three", "bats": "R"}],
            "vs_LHP": [{"slot": 1, "position": "1B", "player": "Bat Two", "bats": "L"},
                       {"slot": 2, "position": "C", "player": "Bat One", "bats": "R"},
                       {"slot": 3, "position": "2B", "player": "Bat Three", "bats": "R"}]}]}

    def test_fangraphs_abbrev_resolves_to_dk_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            self._salary(salary, "WSH")
            order, report = poa.build_projected_order(
                self._platoon("WSN"), str(salary), {"WSH": "R"}, only_teams=["WSH"])
            self.assertEqual(len(order), 3)
            self.assertEqual(report["filled_by_team"], {"WSH": 3})
            self.assertEqual(report["zero_fill_teams"], [])

    def test_az_resolves_to_ari_for_opponent_handedness(self):
        feed = {"games": [{
            "game_pk": 1, "game_date_utc": "2026-06-11T17:00:00Z",
            "away": {"team_abbrev": "ATH", "lineup": [],
                     "probable_pitcher": {"id": 1, "name": "Lefty", "hand": "L"}},
            "home": {"team_abbrev": "AZ", "lineup": [],
                     "probable_pitcher": {"id": 2, "name": "Righty", "hand": "R"}}}]}
        out = poa.extract_opp_throws_from_lineups(feed)
        self.assertNotIn("AZ", out)
        self.assertEqual(out["ARI"], "L")   # Arizona faces the away lefty
        self.assertEqual(out["ATH"], "R")

    def test_zero_fill_is_reported_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            self._salary(salary, "WSH")
            # Names that match nothing in the salary file: covered but unfillable.
            broken = self._platoon("WSN")
            for view in ("vs_RHP", "vs_LHP"):
                for row in broken["teams"][0][view]:
                    row["player"] = "Nobody " + row["player"]
            _order, report = poa.build_projected_order(
                broken, str(salary), {"WSH": "R"}, only_teams=["WSH"])
            self.assertEqual(report["zero_fill_teams"], ["WSH"])

    def test_requested_team_absent_from_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            self._salary(salary, "WSH")
            _order, report = poa.build_projected_order(
                self._platoon("WSN"), str(salary), {"COL": "R"}, only_teams=["COL"])
            self.assertEqual(report["teams_missing_from_file"], ["COL"])


class DoubleheaderLegTests(unittest.TestCase):
    """A feed keyed by matchup alone collapses both legs of a doubleheader onto one
    key. Last-write-wins then adopts the night game's lock time for a matinee
    draftgroup, moving the delivery deadline hours the wrong way. Leg selection is
    resolved against the salary file, which is authoritative for the slate."""

    def _feed(self):
        def side(team, status="tbd"):
            return {"team_abbrev": team, "lineup_status": status, "lineup": [],
                    "probable_pitcher": {"id": 1, "name": "Pitcher A", "hand": "R"}}
        return {"date": "2026-06-11", "games": [
            {"game_pk": 1, "game_date_utc": "2026-06-11T17:00:00Z", "status": "Scheduled",
             "away": side("AAA"), "home": side("BBB")},
            {"game_pk": 2, "game_date_utc": "2026-06-11T23:05:00Z", "status": "Scheduled",
             "away": side("AAA"), "home": side("BBB")},
            {"game_pk": 3, "game_date_utc": "2026-06-11T17:00:00Z", "status": "Scheduled",
             "away": side("CCC"), "home": side("DDD")},
        ]}

    def test_night_leg_dropped_and_matinee_lock_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            write_salary(salary)
            status = build_status_map_from_lineups_feed(self._feed(), str(salary))
            self.assertEqual(
                status["lock_time_by_game_id"]["AAA@BBB"], "2026-06-11T17:00:00+00:00"
            )
            dropped = status["doubleheader_legs_dropped"]
            self.assertEqual([d["game_pk"] for d in dropped], [2])

    def _dh_feed_with_distinct_arms(self):
        """Both legs of AAA@BBB, the leg the salary file does NOT price rendered
        LAST so last-write-wins picks the wrong one. That is the filed direction."""
        def side(team, prefix, hand, arm):
            return {"team_abbrev": team, "lineup_status": "confirmed",
                    "lineup": [{"order": i, "name": f"{prefix} bat {i}",
                                "bat_side": "R"} for i in range(1, 10)],
                    "probable_pitcher": {"id": 1, "name": arm, "hand": hand}}
        # write_salary prices AAA@BBB at 06/11/2026 01:00PM ET == 17:00Z, so the
        # MATINEE is the priced leg and the night leg is rendered last.
        return {"date": "2026-06-11", "games": [
            {"game_pk": 1, "game_date_utc": "2026-06-11T17:00:00Z", "status": "Scheduled",
             "away": side("AAA", "matinee", "L", "Matinee Away Arm"),
             "home": side("BBB", "matinee", "L", "Matinee Home Arm")},
            {"game_pk": 2, "game_date_utc": "2026-06-11T23:05:00Z", "status": "Scheduled",
             "away": side("AAA", "night", "R", "Night Away Arm"),
             "home": side("BBB", "night", "R", "Night Home Arm")},
        ]}

    def test_the_team_keyed_extractors_leg_select_like_the_status_map(self):
        """R58(b). All three write into a TEAM-keyed dict while iterating games,
        so a doubleheader was last-write-wins: the same feed produced a
        leg-correct status map and a leg-wrong platoon view, silently."""
        from mlb_engine.intake.live_data_adapters import (
            extract_opposing_probables, extract_batter_hands, _salary_game_times,
            _load_salary_players)
        from mlb_engine.intake.platoon_order_adapter import (
            extract_opp_throws_from_lineups)

        feed = self._dh_feed_with_distinct_arms()
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            write_salary(salary)
            players = _load_salary_players(str(salary))
            times = _salary_game_times(players)
            # The salary fixture prices AAA@BBB at one start; assert which, so a
            # fixture change cannot quietly invert this test.
            self.assertEqual(times["AAA@BBB"].astimezone(timezone.utc).isoformat(),
                             "2026-06-11T17:00:00+00:00")

            # Without the argument: previous behavior, the LAST game wins, so a
            # matinee draftgroup takes the night starter and his throw hand.
            self.assertEqual(
                extract_opposing_probables(feed)["AAA"]["name"], "Night Home Arm")
            self.assertEqual(extract_opp_throws_from_lineups(feed)["AAA"], "R")

            # With it: the leg the salary file prices, matching the status map.
            probs = extract_opposing_probables(feed, times)
            throws = extract_opp_throws_from_lineups(feed, times)
            self.assertEqual(probs["AAA"]["name"], "Matinee Home Arm")
            self.assertEqual(probs["BBB"]["name"], "Matinee Away Arm")
            self.assertEqual(throws["AAA"], "L")
            self.assertEqual(throws["BBB"], "L")

            # batter_hands is keyed per player, so the failure there is the two
            # legs' hitters merging into one pool rather than a flipped value.
            both = extract_batter_hands(feed, players)
            one = extract_batter_hands(feed, players, times)
            self.assertLessEqual(len(one), len(both))

    def test_every_team_keyed_extractor_routes_through_one_leg_selector(self):
        """R58(b), pinned on the call graph like F18's selector check above.

        Three functions had to leg-select and none did. Pinning the behavior alone
        would let a fourth extractor be written the old way, or one of these three
        grow a private copy of the selection.
        """
        import ast
        import textwrap
        from mlb_engine.intake import live_data_adapters as lda
        from mlb_engine.intake import platoon_order_adapter as poa

        def calls(fn):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            return {node.func.id for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

        for fn in (lda.extract_opposing_probables, lda.extract_batter_hands,
                   poa.extract_opp_throws_from_lineups):
            self.assertIn("_legs_for_extraction", calls(fn), fn.__name__)
        # and the one helper routes through the one selector
        self.assertIn("_select_slate_legs", calls(lda._legs_for_extraction))

    def test_a_dropped_leg_reason_describes_the_dropped_leg(self):
        """R58(a). The reason described why the KEPT leg won and was then stamped
        on every dropped record, so a matinee dropped in favour of a night leg
        read "matched salary start <night time>" -- true of another leg, false of
        the record carrying it. That text is quoted in R58 as evidence."""
        from mlb_engine.intake.live_data_adapters import _select_slate_legs
        feed = self._dh_feed_with_distinct_arms()
        target = {"AAA@BBB": datetime(2026, 6, 11, 23, 5, tzinfo=timezone.utc)}
        kept, dropped = _select_slate_legs(feed["games"], target)
        self.assertEqual([g["game_pk"] for g in kept], [2])
        self.assertEqual(len(dropped), 1)
        reason = dropped[0]["reason"]
        self.assertIn("another leg matched", reason)
        self.assertIn("this leg is", reason)
        self.assertNotIn("matched salary start", reason)

    def test_clock_prefers_salary_file_when_feed_disagrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            write_salary(salary)
            players = parse_dk_salary_csv(str(salary))
            # A feed map that kept the night leg: 6 hours late on the first lock.
            bad = {"AAA@BBB": "2026-06-11T23:05:00+00:00",
                   "CCC@DDD": "2026-06-11T17:00:00+00:00"}
            clock = slate_clock(players=players, lock_time_by_game_id=bad,
                                now=datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc))
            check = clock["salary_cross_check"]
            self.assertTrue(check["checked"])
            self.assertFalse(check["agrees"])
            self.assertEqual(clock["first_lock_utc"], "2026-06-11T17:00:00+00:00")
            self.assertEqual(clock["source"], "salary_game_info_after_cross_check")

    def test_agreeing_feed_leaves_clock_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            write_salary(salary)
            players = parse_dk_salary_csv(str(salary))
            good = {"AAA@BBB": "2026-06-11T17:00:00+00:00",
                    "CCC@DDD": "2026-06-11T17:00:00+00:00"}
            clock = slate_clock(players=players, lock_time_by_game_id=good,
                                now=datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc))
            self.assertTrue(clock["salary_cross_check"]["agrees"])
            self.assertEqual(clock["source"], "lock_time_map")


def _wide_projection_frame(teams=20, hitters_per_team=12) -> pd.DataFrame:
    """A pool big enough that a 1ms MILP finds no incumbent at all.

    The small fixtures solve in microseconds, so they exercise the accepted
    time-limited incumbent. This one exercises the other branch: time limit,
    nothing to accept, and the caller must not read that as an infeasible pool.
    """
    names = [f"W{i}" for i in range(1, teams + 1)]
    game = {t: f"{names[i // 2 * 2]}@{names[i // 2 * 2 + 1]}" for i, t in enumerate(names)}
    opp = {t: (names[i + 1] if i % 2 == 0 else names[i - 1]) for i, t in enumerate(names)}
    rows = []
    pid = 30000
    for team in names:
        pid += 1
        rows.append({
            "Player_ID": str(pid), "Name": f"P_{team}", "Team": team,
            "Opponent": opp[team], "Position": "P", "Salary": 9000.0,
            "Game_ID": game[team], "Floor": 12.0, "Ceiling": 25.0 + pid % 7,
            "Excluded": False, "Locked": False,
        })
    slots = ("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "1B", "OF", "2B", "SS")
    for team in names:
        for j in range(hitters_per_team):
            pid += 1
            rows.append({
                "Player_ID": str(pid), "Name": f"{team}_{pid}", "Team": team,
                "Opponent": opp[team], "Position": slots[j % len(slots)],
                "Salary": 3000.0 + (pid % 9) * 100, "Game_ID": game[team],
                "Floor": 5.0, "Ceiling": 8.0 + pid % 11, "Excluded": False, "Locked": False,
            })
    return pd.DataFrame(rows)


class _FakeMilpResult:
    """A scipy milp result reshaped to report a time limit.

    Timing-based tests are the wrong tool here: a faster machine turns them into
    skips, and the branch under test is the one that only fires when the clock
    runs out. Forcing the status makes the assertion deterministic while leaving
    the incumbent verification to run for real.
    """

    def __init__(self, x, status=1, message="Time limit reached", mip_gap=0.0125):
        self.x = x
        self.status = status
        self.success = status == 0
        self.message = message
        self.mip_gap = mip_gap
        self.fun = None


def _patch_milp(factory):
    """Context manager swapping scipy.optimize.milp for the duration."""
    import contextlib
    import scipy.optimize as sciopt

    @contextlib.contextmanager
    def _cm():
        real = sciopt.milp

        def fake(*args, **kwargs):
            return factory(real, *args, **kwargs)

        sciopt.milp = fake
        try:
            yield
        finally:
            sciopt.milp = real

    return _cm()


class SolverTimeoutSemanticsTests(unittest.TestCase):
    """F13. A clock is not an infeasible pool and never buys a relaxation."""

    def test_resolve_time_limit_bounds_by_remaining_budget(self):
        self.assertEqual(opt.resolve_solver_time_limit(), opt.SOLVER_TIME_LIMIT_S)
        self.assertEqual(opt.resolve_solver_time_limit(12.0), 12.0)
        # The remaining budget wins when it is tighter. Shrinking search effort
        # is the permitted response to a tight budget; trimming the pool is not.
        self.assertEqual(opt.resolve_solver_time_limit(30.0, 4.0), 4.0)
        self.assertEqual(opt.resolve_solver_time_limit(30.0, -5.0),
                         opt.MIN_SOLVER_TIME_LIMIT_S)

    def test_status_distinguishes_timeout_from_proven_infeasible(self):
        frame = _wide_projection_frame()
        timed = opt._new_solver_status()
        lineup, _ = opt.build_single_lineup(
            frame, target="ceiling", time_limit_s=0.001, status_out=timed)
        self.assertEqual(timed["status"], "time_limit")
        self.assertTrue(timed["timed_out"])
        self.assertFalse(timed["proven_infeasible"])
        self.assertIsNone(lineup)

        blocked = opt._new_solver_status()
        missing, _ = opt.build_single_lineup(
            diverse_projection_frame(), target="ceiling",
            locks=["does-not-exist"], status_out=blocked)
        self.assertIsNone(missing)
        self.assertTrue(blocked["proven_infeasible"])
        self.assertFalse(blocked["timed_out"])

    def test_time_limited_incumbent_is_accepted_and_tagged(self):
        frame = diverse_projection_frame()
        status = opt._new_solver_status()
        with _patch_milp(lambda real, *a, **k: _FakeMilpResult(real(*a, **k).x)):
            lineup, _ = opt.build_single_lineup(
                frame, target="ceiling", status_out=status)
        # A feasible incumbent is verified against the same constraint matrix
        # and kept, rather than thrown away because success is False.
        self.assertIsNotNone(lineup)
        self.assertEqual(len(lineup), opt.ROSTER_SIZE)
        self.assertTrue(status["timed_out"])
        self.assertEqual(status["optimality"], "time_limited")
        self.assertEqual(lineup.attrs.get("optimality"), "time_limited")

    def test_an_infeasible_incumbent_is_rejected_not_certified(self):
        """Accepting an unverified incumbent would be worse than the bug."""
        frame = diverse_projection_frame()
        status = opt._new_solver_status()

        def corrupt(real, *args, **kwargs):
            x = real(*args, **kwargs).x
            if x is not None:
                x = x.copy()
                x[:] = 1.0  # every assignment on at once: not a legal roster
            return _FakeMilpResult(x)

        with _patch_milp(corrupt):
            lineup, _ = opt.build_single_lineup(
                frame, target="ceiling", status_out=status)
        self.assertIsNone(lineup)
        self.assertTrue(status["incumbent_rejected"])

    def test_bank_timeout_populates_failed_indices_with_no_relaxation(self):
        result = opt.build_multi_lineup(
            _wide_projection_frame(), n_lineups=3, mode="wta",
            solver_time_limit_s=0.001,
        )
        self.assertEqual(result["lineups"], [])
        self.assertEqual(result["failed_indices"], [0, 1, 2])
        self.assertEqual(result["solver_report"]["timed_out_lineup_indices"], [0, 1, 2])
        relaxations = result["relaxations"]
        self.assertEqual(relaxations["overlap_relaxed_lineups"], 0)
        self.assertEqual(relaxations["du_relaxed_lineups"], 0)
        self.assertEqual(relaxations["du_relaxation_high_water"], -1)
        self.assertEqual(relaxations["timed_out_lineup_count"], 3)
        self.assertTrue(any("clock, not the pool" in w for w in relaxations["warnings"]))

    def test_timeout_never_climbs_the_overlap_ladder(self):
        """Deterministic: the solver is replaced, so nothing depends on speed."""
        frame = diverse_projection_frame()
        seen_overlaps = []
        real = opt.build_single_lineup

        def fake(projections_df, **kwargs):
            status = kwargs.get("status_out")
            seen_overlaps.append(kwargs.get("max_overlap"))
            if len(seen_overlaps) == 1:
                return real(projections_df, **kwargs)
            opt._record_solver_status(
                status, status="time_limit", timed_out=True,
                proven_infeasible=False, message="Time limit reached",
            )
            return None, None

        original = opt.build_single_lineup
        opt.build_single_lineup = fake
        try:
            result = opt.build_multi_lineup(frame, n_lineups=3, mode="wta")
        finally:
            opt.build_single_lineup = original

        # One solve per timed-out lineup: the ladder was never climbed and the
        # DU relaxation order was never stepped.
        self.assertEqual(len(seen_overlaps), 3)
        self.assertEqual(result["failed_indices"], [1, 2])
        self.assertEqual(result["relaxations"]["du_relaxation_high_water"], -1)
        self.assertEqual(result["relaxations"]["overlap_relaxed_lineups"], 0)

    def test_timed_out_cache_job_is_retried_on_a_later_slice(self):
        frame = diverse_projection_frame()

        def timing_out(projections_df, **kwargs):
            opt._record_solver_status(
                kwargs.get("status_out"), status="time_limit", timed_out=True,
                proven_infeasible=False, message="Time limit reached")
            return None, None

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache = bank_cache.BankCache(path)
            original = bank_cache.build_single_lineup
            bank_cache.build_single_lineup = timing_out
            try:
                report = bank_cache.extend_bank(
                    cache, frame, time_budget_s=2.0, max_candidates=3)
            finally:
                bank_cache.build_single_lineup = original
            self.assertGreater(report["jobs_timed_out"], 0)
            # A timeout is not an answer about the job, so it is not recorded and
            # the next slice picks it up. Recording it was how the sliced path
            # dropped exactly the jobs a second slice exists to finish.
            self.assertEqual(cache.attempted, set())
            self.assertEqual(bank_cache.BankCache(path).attempted, set())


class SolverIdDtypeBoundaryTests(unittest.TestCase):
    """R55(a). A control keyed on Player_ID must not depend on the column's dtype.

    stable_union returns sorted STRINGS by contract, and the solver looked the
    results up against df['Player_ID'] taken raw. A frame whose Player_ID arrives
    int64 -- runs/<id>/inputs/projections.csv reloaded with a plain read_csv, or
    any projections_override built from a numeric column -- matched none of them.
    Reproduced 2026-08-04 on all three controls; these drive the same frames.
    """

    @staticmethod
    def _frames():
        as_str = diverse_projection_frame()
        as_int = as_str.copy()
        as_int["Player_ID"] = as_int["Player_ID"].astype("int64")
        return as_str, as_int

    @staticmethod
    def _sp_ids(frame):
        return [str(p) for p in frame[frame["Position"] == "P"]["Player_ID"]]

    def test_a_lock_binds_on_an_int64_player_id_frame(self):
        # The headline: the lock is IN the pool, and the solver called it
        # unavailable and stamped the reserved proven_infeasible label on a
        # dtype artifact.
        _, as_int = self._frames()
        lock_id = self._sp_ids(as_int)[0]
        status = {}
        lineup, _ = opt.build_single_lineup(
            as_int, target="ceiling", locks=[lock_id], status_out=status)
        self.assertIsNotNone(
            lineup, f"lock no-opped into a refusal on an int64 frame: {status}")
        self.assertNotEqual(status.get("status"), "locked_player_unavailable")
        self.assertFalse(status.get("proven_infeasible"))
        self.assertIn(lock_id, {str(p) for p in lineup["Player_ID"]})

    def test_excludes_bind_on_an_int64_player_id_frame(self):
        # max_sp_exposure and the seed-pair excludes both arrive as id sets, and
        # both silently no-opped: cap=1 with an SP rostered three times, caught
        # only by post-hoc anchor_validation.
        _, as_int = self._frames()
        excluded = self._sp_ids(as_int)[:2]
        lineup, _ = opt.build_single_lineup(
            as_int, target="ceiling", excludes=excluded)
        self.assertIsNotNone(lineup)
        rostered = {str(p) for p in lineup["Player_ID"]}
        self.assertEqual(
            set(excluded) & rostered, set(),
            "an excluded player was rostered because the id types never matched")

    def test_a_locked_slot_assignment_binds_on_an_int64_frame(self):
        _, as_int = self._frames()
        catcher = str(as_int[as_int["Position"] == "C"].iloc[0]["Player_ID"])
        status = {}
        lineup, _ = opt.build_single_lineup(
            as_int, target="ceiling",
            locked_slot_assignments={"C": catcher}, status_out=status)
        self.assertIsNotNone(lineup, f"locked slot refused: {status}")
        by_slot = {str(r["Assigned_Slot"]): str(r["Player_ID"])
                   for _, r in lineup.iterrows()}
        self.assertEqual(by_slot["C"], catcher)

    def test_dtype_is_not_a_strategy_input(self):
        # Same pool, same controls, two dtypes: the lineup and the objective are
        # the same or the column is deciding strategy.
        as_str, as_int = self._frames()
        lock_id = self._sp_ids(as_str)[0]
        out = []
        for frame in (as_str, as_int):
            lineup, objective = opt.build_single_lineup(
                frame, target="ceiling", locks=[lock_id])
            self.assertIsNotNone(lineup)
            out.append(([str(p) for p in lineup["Player_ID"]], round(objective, 9)))
        self.assertEqual(out[0], out[1])
        # And the returned Player_ID is a string on both, so downstream joins
        # against DK ids do not have to care either.
        for frame in (as_str, as_int):
            lineup, _ = opt.build_single_lineup(frame, target="ceiling")
            self.assertTrue(all(isinstance(p, str) for p in lineup["Player_ID"]))

    def test_extend_bank_builds_the_same_jobs_on_either_dtype(self):
        # The filed case: extend_bank locks each SP pair, so on an int64 frame it
        # built 0 of 16 jobs while marking all 16 attempted-forever with
        # job_list_exhausted True -- a permanently poisoned, empty-looking-but-
        # "done" bank. The string control built 8 of 16.
        as_str, as_int = self._frames()
        results = []
        for frame in (as_str, as_int):
            with tempfile.TemporaryDirectory() as tmp:
                cache = bank_cache.BankCache(Path(tmp) / "bank.json")
                report = bank_cache.extend_bank(cache, frame, time_budget_s=30)
                results.append((report["built_this_slice"], report["jobs_total"],
                                report["job_list_exhausted"]))
        self.assertEqual(results[0], results[1],
                         f"the bank build depends on the Player_ID dtype: {results}")
        self.assertGreater(results[1][0], 0,
                           "an int64 frame still builds nothing")


class BankCacheAnsweredJobTests(unittest.TestCase):
    """R55(b). `attempted` holds ANSWERED jobs, and only two answers qualify.

    A lineup came back, or the solver proved infeasibility. A raised exception is
    neither: build_single_lineup returns (None, None) for infeasibility and never
    raises for it, so anything escaping the handler is a defect a later slice can
    retry. Recording those made a systematic error indistinguishable from a
    genuinely dry pool -- the misdiagnosis the module's own F13 note warns about.
    """

    @staticmethod
    def _stub(status_fields=None, raises=None):
        def fake(projections_df, **kwargs):
            if raises is not None:
                raise raises
            opt._record_solver_status(kwargs.get("status_out"), **(status_fields or {}))
            return None, None
        return fake

    def _run(self, stub, frame, path, **kw):
        cache = bank_cache.BankCache(path)
        original = bank_cache.build_single_lineup
        bank_cache.build_single_lineup = stub
        try:
            report = bank_cache.extend_bank(cache, frame, **kw)
        finally:
            bank_cache.build_single_lineup = original
        return cache, report

    def test_a_raised_exception_is_counted_and_stays_retryable(self):
        frame = diverse_projection_frame()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache, report = self._run(
                self._stub(raises=ValueError("Base contains nonnumeric values")),
                frame, path, time_budget_s=20)
            self.assertEqual(report["built_this_slice"], 0)
            self.assertEqual(report["jobs_raised"], report["jobs_total"])
            self.assertEqual(report["raised_by_reason"],
                             {"ValueError": report["jobs_total"]})
            self.assertTrue(report["raised_examples"])
            self.assertIn("nonnumeric", report["raised_examples"][0])
            self.assertEqual(cache.attempted, set(),
                             "a raised exception was recorded as an answered job")
            self.assertEqual(bank_cache.BankCache(path).attempted, set())
            # and once the cause is gone, the same cache builds
            follow = bank_cache.extend_bank(
                bank_cache.BankCache(path), frame, time_budget_s=30)
            self.assertGreater(follow["built_this_slice"], 0)

    def test_an_empty_return_that_proved_nothing_is_not_an_answer(self):
        frame = diverse_projection_frame()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache, report = self._run(
                self._stub({"status": "roster_size_mismatch",
                            "proven_infeasible": False,
                            "incumbent_rejected": True}),
                frame, path, time_budget_s=20)
            self.assertEqual(report["jobs_unanswered"], report["jobs_total"])
            self.assertEqual(report["unanswered_by_status"],
                             {"roster_size_mismatch": report["jobs_total"]})
            self.assertEqual(cache.attempted, set())

    def test_a_proven_infeasible_job_is_recorded_and_never_retried(self):
        frame = diverse_projection_frame()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache, report = self._run(
                self._stub({"status": "infeasible", "proven_infeasible": True}),
                frame, path, time_budget_s=20)
            self.assertEqual(len(cache.attempted), report["jobs_total"])
            self.assertEqual(report["jobs_unanswered"], 0)
            self.assertEqual(report["jobs_raised"], 0)
            second = bank_cache.extend_bank(
                bank_cache.BankCache(path), frame, time_budget_s=10)
            self.assertEqual(second["attempted_this_slice"], 0,
                             "a proven-infeasible job was re-paid for")

    def test_clear_attempted_survives_save_and_keeps_candidates(self):
        frame = diverse_projection_frame()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache = bank_cache.BankCache(path)
            report = bank_cache.extend_bank(cache, frame, time_budget_s=30)
            self.assertGreater(report["built_this_slice"], 0)
            reopened = bank_cache.BankCache(path)
            candidates_before = len(reopened.candidates)
            attempted_before = len(reopened.attempted)
            self.assertGreater(attempted_before, 0)
            cleared = reopened.clear_attempted(report["conditions_signature"])
            self.assertEqual(cleared, attempted_before)
            reopened.save()
            # save() unions memory with disk to protect concurrent writers, so a
            # clear that is not subtracted there is undone by the next save.
            after = bank_cache.BankCache(path)
            self.assertEqual(after.attempted, set())
            self.assertEqual(len(after.candidates), candidates_before,
                             "clearing the attempt record threw away real lineups")

    def test_clear_attempted_scopes_to_a_conditions_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            cache.attempted = {"a|b|SIG1", "c|d|SIG1", "e|f|SIG2"}
            self.assertEqual(cache.clear_attempted("SIG1"), 2)
            self.assertEqual(cache.attempted, {"e|f|SIG2"})
            self.assertEqual(cache.clear_attempted("SIG1"), 0)
            self.assertEqual(cache.clear_attempted(), 1)
            self.assertEqual(cache.attempted, set())


class AllocatorSolverStatusTests(unittest.TestCase):
    """F13/F15 at the allocator boundary."""

    @staticmethod
    def _roster(seed):
        return [f"{seed}-{i}" for i in range(10)]

    def test_proven_infeasible_names_the_binding_constraint(self):
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary="AAA")
                 for i in range(3)]
        result = select_and_assign_entries(
            cands, _entry_reqs(6),
            {"max_primary_stack_exposure_pct": 0.34},
        )
        self.assertFalse(result["passed"])
        joined = " ".join(result["errors"])
        self.assertIn("proven infeasible", joined)
        self.assertIn("max_primary_stack_exposure_pct", joined)
        self.assertNotIn("timed out", joined)

    def test_time_limit_reports_the_gap_not_an_infeasibility(self):
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary=f"T{i}")
                 for i in range(8)]
        with _patch_milp(lambda real, *a, **k: _FakeMilpResult(None, mip_gap=0.0125)):
            result = select_and_assign_entries(cands, _entry_reqs(4))
        self.assertFalse(result["passed"])
        joined = " ".join(result["errors"])
        self.assertIn("time limit", joined)
        self.assertIn("0.0125", joined)
        self.assertIn("clock, not a proven infeasibility", joined)
        report = result["allocation_solver_report"]
        self.assertEqual(report["status"], "time_limit")
        self.assertEqual(report["binding_constraints"], [])

    def test_time_limited_allocation_incumbent_is_accepted_and_named(self):
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary=f"T{i}")
                 for i in range(8)]
        with _patch_milp(lambda real, *a, **k: _FakeMilpResult(real(*a, **k).x)):
            result = select_and_assign_entries(cands, _entry_reqs(4))
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(result["allocation_optimality"], "time_limited")
        self.assertTrue(any("time-limited incumbent" in w
                            for w in result["warnings"]))

    def test_stackless_candidates_do_not_form_a_phantom_cap_bucket(self):
        # Every candidate carries the DU signature's no-stack sentinel. Read as
        # a team it becomes one bucket of eight against a cap of two entries.
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary="NONE")
                 for i in range(8)]
        result = select_and_assign_entries(
            cands, _entry_reqs(6), {"max_primary_stack_exposure_pct": 0.34},
        )
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(len(result["assignments"]), 6)
        self.assertTrue(all(a["primary_stack"] == "" for a in result["assignments"]))

    def test_stack_cap_binds_when_the_bank_is_concentrated(self):
        cands = []
        for slot, (team, base) in enumerate((("AAA", 100.0), ("BBB", 60.0), ("CCC", 30.0))):
            cands += [
                candidate(f"{team}{i}", self._roster(slot * 100 + i), base - i, primary=team)
                for i in range(4)
            ]
        result = select_and_assign_entries(
            cands, _entry_reqs(6),
            {"max_primary_stack_exposure_pct": 0.34, "max_candidate_reuse": 1},
        )
        self.assertTrue(result["passed"], result.get("errors"))
        used = [a["primary_stack"] for a in result["assignments"]]
        # floor(6 * 0.34) = 2. Without the emitted primary_stack the cap added no
        # MILP rows at all and all six would have come from the top-scoring AAA.
        self.assertEqual(result["direct_constraints"]["max_primary_stack_count"], 2)
        self.assertLessEqual(used.count("AAA"), 2)
        self.assertEqual(len(used), 6)

    def test_excluded_new_teams_without_a_team_map_fails_closed(self):
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i) for i in range(3)]
        reqs = _entry_reqs(1)
        reqs[0]["excluded_new_teams"] = ["AAA"]
        result = select_and_assign_entries(cands, reqs)
        self.assertFalse(result["passed"])
        self.assertIn("player_team_by_id", " ".join(result["errors"]))

    def test_prefilter_keeps_forced_coverage_and_shrinks_the_solve(self):
        cands = [candidate(f"c{i}", self._roster(i), 100.0 - i, primary=f"T{i % 4}")
                 for i in range(120)]
        reqs = _entry_reqs(2)
        # Entry 0 admits exactly one candidate, and it is the worst-scoring one.
        reqs[0]["allowed_candidate_ids"] = ["c119"]
        result = select_and_assign_entries(cands, reqs, {"max_candidate_reuse": 1})
        self.assertTrue(result["passed"], result.get("errors"))
        report = result["allocation_solver_report"]["candidate_prefilter"]
        self.assertTrue(report["applied"])
        self.assertEqual(report["candidates_in"], 120)
        self.assertLessEqual(report["candidates_kept"], 120)
        self.assertGreaterEqual(report["forced_coverage_kept"], 1)
        chosen = {a["candidate_id"] for a in result["assignments"]}
        self.assertIn("c119", chosen)


class BankPayloadSeamTests(unittest.TestCase):
    """F15. The fields the portfolio controls read must actually be emitted."""

    @staticmethod
    def _roster():
        return [f"p{i}" for i in range(10)]

    def test_candidate_primary_stack_maps_the_sentinel_to_blank(self):
        stackless = pd.DataFrame([
            {"Player_ID": f"h{i}", "Team": f"T{i}", "Position": "OF"} for i in range(10)
        ])
        self.assertEqual(opt._identify_primary_stack(stackless), "NONE")
        self.assertEqual(opt.candidate_primary_stack(stackless), "")

    def test_diverse_bank_records_carry_primary_stack_and_sp_ids(self):
        bank = opt.build_diverse_candidate_bank(
            diverse_projection_frame(), requested_n=4, mode="wta", target="ceiling",
        )
        records = bank["candidate_lineups"]
        self.assertTrue(records)
        for rec in records:
            self.assertIn("primary_stack", rec)
            self.assertIn("sp_ids", rec)
            self.assertNotEqual(rec["primary_stack"], "NONE")
            self.assertEqual(len(rec["sp_ids"]), 2)

    def test_as_candidates_emits_stack_pair_and_shape_scores(self):
        frame = diverse_projection_frame()
        lineup, _ = opt.build_single_lineup(frame, target="ceiling")
        roster = bank_cache.ordered_roster(lineup)
        with tempfile.TemporaryDirectory() as tmp:
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            cache.add(roster, 120.0, job="j")
            payload = cache.as_candidates(
                frame, requested_n=2, contest_shapes=["cash", "large_wta"])[0]
            self.assertEqual(payload["sp_ids"], list(roster[:2]))
            self.assertIn("primary_stack", payload)
            self.assertNotEqual(payload["primary_stack"], "NONE")
            # Cash used to rank on a ceiling-max score with a floor weight bolted
            # on afterwards. Each shape is now scored in its own mode.
            self.assertIn("cash", payload["contest_fit_by_shape"])
            self.assertIn("large_wta", payload["contest_fit_by_shape"])
            report = cache.last_payload_report
            self.assertEqual(report["scored"], 1)
            self.assertEqual(report["scoring_failed"], 0)
            self.assertEqual(report["shapes_scored"], ["cash", "large_wta"])

    def test_as_candidates_counts_scoring_failures_instead_of_swallowing_them(self):
        frame = diverse_projection_frame()
        with tempfile.TemporaryDirectory() as tmp:
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            cache.add([f"absent{i}" for i in range(10)], 100.0, job="j")
            payload = cache.as_candidates(frame, requested_n=1)
            # The candidate survives, because a short bank leaves a blank
            # reserved row and a blank row blocks certification.
            self.assertEqual(len(payload), 1)
            self.assertEqual(cache.last_payload_report["scoring_failed"], 1)
            self.assertTrue(cache.last_payload_report["scoring_failure_reasons"])


class RunSlateExclusionSeamTests(unittest.TestCase):
    """F15. Excludes reached validation and feasibility but never the bank."""

    def _inputs(self, root: Path):
        salary = root / "salary.csv"
        ids = write_salary(salary)
        entries = root / "DKEntries.csv"
        write_entries(entries)
        return salary, entries, projection_frame(ids)

    def test_excluded_players_never_enter_the_bank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, frame = self._inputs(root)
            dropped = str(frame[frame["Position"] != "P"]["Player_ID"].iloc[0])
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame, excluded_player_ids=[dropped],
                portfolio_controls_override=RunSlateFrontDoorTests.LOOSE,
                approve=True, assume_gates=RunSlateFrontDoorTests.UNEVIDENCED,
            )
            bank = result.get("candidate_bank") or {}
            self.assertEqual(bank.get("excluded_player_ids_applied"), [dropped])
            self.assertTrue(bank.get("candidate_count"))
            # The seam this closes: the bank used to be built without the
            # excludes and the mistake surfaced only at the export gate, after
            # the whole remaining budget had been spent building around them.
            for assignment in result.get("assignments") or []:
                self.assertNotIn(dropped, assignment["lineup_ids"])

    def test_unmatched_exclusion_blocks_at_the_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, frame = self._inputs(root)
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame,
                excluded_player_ids=["not-in-this-pool"], approve=False,
            )
            block = result["exclusions"]
            self.assertEqual(block["unmatched_player_ids"], ["not-in-this-pool"])
            self.assertTrue(block["blockers"])
            self.assertTrue(any("exclusions:" in w
                                for w in result["checkpoint_plan"]["warnings"]))

    def test_unmatched_exclusion_blocks_the_approve_path(self):
        """R69(c). The name of the test above, and the docstring on
        ``_exclusion_block``, both said "blocker" since F15 while the code only
        appended to warnings -- so approve=True built a portfolio around a player
        the operator had asked to drop.

        Same treatment as wrong-contest identity, on the same argument: decidable
        from disk, invisible in the certified output, and fixed by correcting one
        argument on the same command.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, frame = self._inputs(root)
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame,
                excluded_player_ids=["not-in-this-pool"],
                portfolio_controls_override=RunSlateFrontDoorTests.LOOSE,
                approve=True, assume_gates=RunSlateFrontDoorTests.UNEVIDENCED,
            )
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["passed"])
            self.assertTrue(any("match no row in this pool" in e
                                for e in result["errors"]), result["errors"])
            self.assertTrue(any("not-in-this-pool" in str(e)
                                for e in result["errors"]))
            # Nothing certified on the way out.
            self.assertFalse(result.get("workflow_valid"))

    def test_a_matched_exclusion_still_approves(self):
        """Over-reach guard: the gate is scoped to ids that match NOBODY."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, frame = self._inputs(root)
            dropped = str(frame["Player_ID"].iloc[0])
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame, excluded_player_ids=[dropped],
                portfolio_controls_override=RunSlateFrontDoorTests.LOOSE,
                approve=True, assume_gates=RunSlateFrontDoorTests.UNEVIDENCED,
            )
            self.assertNotEqual(result.get("status"), "blocked")
            self.assertEqual(result["exclusions"]["blockers"], [])

    def test_an_unrecognized_excluded_cell_does_not_block_approve(self):
        """The other half of the R69(c) split. Keeping a player whose Excluded
        cell holds an unrecognized value is the DOCUMENTED reading of that
        column, so it warns and the build ships; only the operator-typed id
        gates."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, frame = self._inputs(root)
            frame.loc[0, "Excluded"] = "probably not"
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame,
                portfolio_controls_override=RunSlateFrontDoorTests.LOOSE,
                approve=True, assume_gates=RunSlateFrontDoorTests.UNEVIDENCED,
            )
            self.assertNotEqual(result.get("status"), "blocked")
            self.assertTrue(any("does not recognize" in w
                                for w in result["exclusions"]["warnings"]))


class SalarySuppressionBoundedTiebreakerTests(unittest.TestCase):
    """R56. Suppression may bound the bonus it counts, never the feasible set.

    MLB_Classic: "Salary suppression is a bounded tiebreaker only." The lineup
    cap was a constraint row over sum(bonus * x), so four tagged players at the
    per-player cap summed to 1.0 and only three could be rostered -- a legal,
    projection-optimal lineup removed from the set and invisible in the
    certified output. Suppression had no test of any kind (R79f), so the
    reproduction from the 2026-08-04 audit is the test.
    """

    TAG = "SALARY_SUPPRESSION:role_elevation"

    @classmethod
    def _frame(cls, n_tagged=4, tag=None, suppression=1000.0, tagged_ceiling=40.0):
        """Two games, four arms, eight hitters each on T1 and T3.

        The tagged hitters are the highest-ceiling bats in the pool and sit at
        distinct T1 slots, so the unconstrained optimum rosters all of them:
        two arms at 25.0 + n_tagged bats at 40.0 + the rest at 10.0. Salary is
        2*9000 + 8*3000 = 42000 against a 50000 cap, so nothing here is a
        salary-driven refusal.
        """
        tag = cls.TAG if tag is None else tag
        game = {"T1": "T1@T2", "T2": "T1@T2", "T3": "T3@T4", "T4": "T3@T4"}
        opp = {"T1": "T2", "T2": "T1", "T3": "T4", "T4": "T3"}
        rows = []
        pid = 30000
        for team in ("T1", "T2", "T3", "T4"):
            pid += 1
            rows.append({"Player_ID": str(pid), "Name": f"P_{team}", "Team": team,
                         "Opponent": opp[team], "Position": "P", "Salary": 9000.0,
                         "Game_ID": game[team], "Floor": 12.0, "Ceiling": 25.0,
                         "Excluded": False, "Locked": False, "Notes": "",
                         "Salary_Suppression": 0.0})
        elevated = ["C", "1B", "2B", "3B"][:n_tagged]
        base = 31000
        for team in ("T1", "T3"):
            for pos in ("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"):
                base += 1
                tagged = team == "T1" and pos in elevated
                rows.append({
                    "Player_ID": str(base), "Name": f"{team}_{pos}_{base}",
                    "Team": team, "Opponent": opp[team], "Position": pos,
                    "Salary": 3000.0, "Game_ID": game[team],
                    "Floor": 5.0, "Ceiling": tagged_ceiling if tagged else 10.0,
                    "Excluded": False, "Locked": False,
                    "Notes": tag if tagged else "",
                    "Salary_Suppression": suppression if tagged else 0.0,
                })
                if tagged:
                    elevated.remove(pos)
        return pd.DataFrame(rows)

    def _solve(self, frame, apply_suppression=True):
        lineup, objective = opt.build_single_lineup(
            frame, target="ceiling", apply_suppression=apply_suppression)
        self.assertIsNotNone(lineup, "the reproduction pool must be feasible")
        return lineup, objective

    def _tagged_ids(self, frame):
        return set(frame[frame["Salary_Suppression"] > 0]["Player_ID"])

    def test_four_tagged_players_keep_the_legal_optimum(self):
        # The filed reproduction. Four tagged bats sum to 1.0 in bonus; before
        # R56 the solver could roster only three and the ceiling came back 220.0
        # against an identical legal pool's 250.0.
        frame = self._frame(n_tagged=4)
        on, _ = self._solve(frame, apply_suppression=True)
        off, _ = self._solve(frame, apply_suppression=False)
        self.assertAlmostEqual(float(off["Ceiling"].sum()), 250.0, places=6)
        self.assertAlmostEqual(
            float(on["Ceiling"].sum()), 250.0, places=6,
            msg="suppression removed a legal, projection-optimal lineup from the set")
        self.assertEqual(len(self._tagged_ids(frame) & set(on["Player_ID"])), 4)
        self.assertNotAlmostEqual(
            float(on["Ceiling"].sum()), 220.0, places=6,
            msg="220.0 is the pre-R56 suppressed ceiling; the cap is a "
                "feasibility constraint again")

    def test_counted_bonus_is_capped_not_the_feasible_set(self):
        # The other half: R56 is not "delete the cap". Four tagged players earn
        # 1.0 of raw bonus and the objective may count only 0.75 of it.
        frame = self._frame(n_tagged=4)
        lineup, objective = self._solve(frame, apply_suppression=True)
        self.assertAlmostEqual(
            objective, 250.0 + opt.SUPPRESSION_LINEUP_CAP, places=6,
            msg="the objective counted more than SUPPRESSION_LINEUP_CAP of bonus")
        self.assertAlmostEqual(
            float(lineup["Suppression_Objective_Bonus"].sum()), 1.0, places=6,
            msg="the per-player column reports what each player earned, uncapped")
        self.assertAlmostEqual(lineup.attrs["suppression_bonus_raw"], 1.0, places=6)
        self.assertAlmostEqual(
            lineup.attrs["suppression_bonus_counted"],
            opt.SUPPRESSION_LINEUP_CAP, places=6)
        self.assertTrue(lineup.attrs["suppression_bonus_capped"])

    def test_at_the_cap_exactly_the_full_bonus_still_counts(self):
        # Three tagged players sum to exactly 0.75. This case was always legal
        # and must stay bit-identical, which is what makes the boundary a
        # boundary rather than an off-by-one.
        frame = self._frame(n_tagged=3)
        lineup, objective = self._solve(frame, apply_suppression=True)
        self.assertEqual(len(self._tagged_ids(frame) & set(lineup["Player_ID"])), 3)
        self.assertAlmostEqual(objective, 220.0 + 0.75, places=6)
        self.assertFalse(lineup.attrs["suppression_bonus_capped"])

    def test_suppression_breaks_a_tie_without_moving_the_ceiling(self):
        # It is still a TIEBREAKER: one tagged bat priced and projected exactly
        # like its alternatives gets rostered, and the lineup's ceiling is
        # unchanged. All the tag bought was the tie.
        frame = self._frame(n_tagged=1, tagged_ceiling=10.0)
        tagged_id = next(iter(self._tagged_ids(frame)))
        on, obj_on = self._solve(frame, apply_suppression=True)
        off, obj_off = self._solve(frame, apply_suppression=False)
        self.assertIn(tagged_id, set(on["Player_ID"]),
                      "the tie went against the role-elevated bat")
        self.assertAlmostEqual(float(on["Ceiling"].sum()),
                               float(off["Ceiling"].sum()), places=6)
        self.assertAlmostEqual(
            obj_on - obj_off, opt.SUPPRESSION_PER_PLAYER_CAP, places=6)

    def test_only_role_elevation_activates_the_bonus(self):
        # MLB_Classic authorizes role_elevation alone. The other three triggers
        # parse and carry one-off labels; they never reach the objective, and
        # neither does the legacy DIVERGENCE_LEVERAGE:value tag. Before R56 two
        # docstrings claimed all four plus the legacy tag activate.
        for tag in ("SALARY_SUPPRESSION:metric_disconnect",
                    "SALARY_SUPPRESSION:late_news",
                    "SALARY_SUPPRESSION:environment",
                    opt.DIVERGENCE_VALUE_TAG):
            with self.subTest(tag=tag):
                frame = self._frame(n_tagged=4, tag=tag)
                bonus = opt._compute_suppression_bonus(frame)
                self.assertEqual(bonus, {}, f"{tag} activated the bonus")
                _, objective = self._solve(frame, apply_suppression=True)
                self.assertAlmostEqual(objective, 250.0, places=6)
        active = opt._compute_suppression_bonus(self._frame(n_tagged=4))
        self.assertEqual(len(active), 4)
        self.assertTrue(all(abs(v - opt.SUPPRESSION_PER_PLAYER_CAP) < 1e-9
                            for v in active.values()))

    def test_untagged_pool_adds_no_suppression_variable(self):
        # No tag anywhere means no auxiliary variable and no extra constraint
        # row, so a slate with no role elevation solves exactly as before.
        frame = self._frame(n_tagged=0)
        lineup, objective = self._solve(frame, apply_suppression=True)
        self.assertAlmostEqual(objective, float(lineup["Ceiling"].sum()), places=6)
        self.assertAlmostEqual(lineup.attrs["suppression_bonus_raw"], 0.0, places=6)
        self.assertFalse(lineup.attrs["suppression_bonus_capped"])


class ExcludedColumnCoercionTests(unittest.TestCase):
    """F21. A blank cell used to remove a player from the legal pool."""

    @staticmethod
    def _mixed_frame():
        frame = projection_frame(write_salary(Path(tempfile.mkdtemp()) / "s.csv"))
        # One of each shape a real frame arrives in: a genuine exclusion, the
        # string "False" that a CSV round-trip produces, an empty cell, a NaN,
        # and a token nobody in this engine has ever defined.
        frame.loc[0, "Excluded"] = True
        frame.loc[1, "Excluded"] = "False"
        frame.loc[2, "Excluded"] = ""
        frame.loc[3, "Excluded"] = float("nan")
        frame.loc[4, "Excluded"] = "maybe"
        frame.loc[5, "Excluded"] = "yes"
        return frame

    def test_only_affirmative_tokens_exclude(self):
        frame = self._mixed_frame()
        flags, report = opt.excluded_flags(frame)
        self.assertTrue(bool(flags.iloc[0]))
        self.assertTrue(bool(flags.iloc[5]))
        for idx in (1, 2, 3, 4):
            self.assertFalse(bool(flags.iloc[idx]), f"row {idx} was dropped")
        self.assertEqual(report["excluded_true"], 2)
        self.assertEqual(report["coerced_from_blank"], 2)   # "" and NaN
        self.assertEqual(report["coerced_from_text"], 2)    # "False" and "yes"
        self.assertEqual(report["unrecognized_kept"], 1)
        self.assertEqual(report["unrecognized_values"], ["maybe"])

    def test_blank_cell_no_longer_shrinks_the_pool(self):
        frame = self._mixed_frame()
        kept = opt._drop_excluded_rows(frame)
        # Two affirmative exclusions out of the frame, and nothing else.
        self.assertEqual(len(kept), len(frame) - 2)

    def test_blank_cell_no_longer_shrinks_the_sp_cap_denominator(self):
        frame = projection_frame(write_salary(Path(tempfile.mkdtemp()) / "s.csv"))
        baseline = len(opt._eligible_sp_ids_for_anchor_caps(frame))
        pitchers = frame.index[frame["Position"] == "P"].tolist()
        frame.loc[pitchers[0], "Excluded"] = float("nan")
        frame.loc[pitchers[1], "Excluded"] = "False"
        # Before F21 both of these dropped, halving the denominator the auto
        # anchor caps are computed against.
        self.assertEqual(len(opt._eligible_sp_ids_for_anchor_caps(frame)), baseline)

    def test_missing_column_excludes_nobody(self):
        frame = projection_frame(write_salary(Path(tempfile.mkdtemp()) / "s.csv"))
        frame = frame.drop(columns=["Excluded"])
        flags, report = opt.excluded_flags(frame)
        self.assertFalse(report["column_present"])
        self.assertEqual(len(opt._drop_excluded_rows(frame)), len(frame))

    def test_checkpoint_names_unrecognized_cells(self):
        """R69(c) moved this finding from ``blockers`` to ``warnings``.

        It still reaches the operator with the same text, and it still reaches
        the checkpoint's warnings line. What changed is the label: keeping a
        player whose Excluded cell holds an unrecognized value is the DOCUMENTED
        reading of that column (CLAUDE.md: "blank, NaN, 'False' and unrecognized
        cells keep them"), so filing it under a key that now hard-gates
        approve=True would refuse builds for behaving as specified. Its remedy is
        a file edit, not a flag correction, which is the line the split is drawn
        on.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            write_entries(entries)
            frame = projection_frame(ids)
            frame.loc[0, "Excluded"] = "probably not"
            plan = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame, approve=False,
            )
            column = plan["exclusions"]["excluded_column"]
            self.assertEqual(column["unrecognized_kept"], 1)
            self.assertTrue(any("does not recognize" in w
                                for w in plan["exclusions"]["warnings"]))
            self.assertEqual(plan["exclusions"]["blockers"], [])
            # It must still reach the line the operator actually reads.
            self.assertTrue(any("does not recognize" in w
                                for w in plan["checkpoint_plan"]["warnings"]))


_SOLVER_INPUT_PROBE = r"""
import hashlib, json, sys
sys.path.insert(0, ".")
from tests.test_core import diverse_projection_frame
from mlb_engine.optimize import optimizer_v3 as opt

calls = []
real = opt.build_single_lineup


def spy(projections_df, **kw):
    calls.append([
        list(kw.get("locks") or []),
        list(kw.get("excludes") or []),
        [list(c) for c in (kw.get("forbidden_player_combos") or [])],
        [list(c) for c in (kw.get("stack_core_blocklist") or [])],
    ])
    return real(projections_df, **kw)


opt.build_single_lineup = spy
opt.build_multi_lineup(
    diverse_projection_frame(), n_lineups=6, mode="wta", target="ceiling",
    max_sp_exposure=2, max_sp_pair_repetition=1,
)
print(hashlib.sha256(json.dumps(calls).encode()).hexdigest())
"""


_DETERMINISM_PROBE = r"""
import hashlib, sys, tempfile
from pathlib import Path
sys.path.insert(0, ".")
from tests.test_core import (
    write_salary, write_entries, projection_frame, RunSlateFrontDoorTests,
)
from mlb_engine.pipeline.execution_pipeline import run_slate

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    salary = root / "salary.csv"
    ids = write_salary(salary)
    entries = root / "DKEntries.csv"
    write_entries(entries)
    built = run_slate(
        runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
        projections_override=projection_frame(ids),
        portfolio_controls_override=RunSlateFrontDoorTests.LOOSE,
        approve=True, assume_gates=RunSlateFrontDoorTests.UNEVIDENCED,
    )
    if not built.get("passed"):
        print("BUILD_FAILED " + str(built.get("errors")))
        raise SystemExit(1)
    data = Path(built["output_path"]).read_bytes()
    print(hashlib.sha256(data).hexdigest())
"""


class DeterminismTests(unittest.TestCase):
    """F19. Same inputs, same file, across processes."""

    def test_stable_helpers_sort_and_dedupe(self):
        from mlb_engine import determinism

        self.assertEqual(determinism.stable_ids(["b", "a", "b", 3]), ["3", "a", "b"])
        self.assertEqual(determinism.stable_ids(None), [])
        self.assertEqual(
            determinism.stable_union(["c"], None, {"a", "b"}, ["a"]),
            ["a", "b", "c"],
        )

    def test_hash_seed_is_reported_in_optimizer_provenance(self):
        report = opt.runtime_preflight()["hash_seed"]
        self.assertIn("python_hash_seed", report)
        self.assertEqual(report["expected"], "0")
        # The audit runs the suite with the seed pinned, so a green suite under
        # an unpinned seed means the gate is not doing its job.
        self.assertTrue(report["pinned"] or report["python_hash_seed"] is None)

    @staticmethod
    def _probe_digests(source, seeds=("1", "2", "3")):
        import os
        import subprocess
        import sys

        digests = []
        for seed in seeds:
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            proc = subprocess.run(
                [sys.executable, "-c", source],
                cwd=str(Path(__file__).resolve().parents[1]),
                capture_output=True, text=True, env=env, timeout=300,
            )
            if proc.returncode != 0:
                raise AssertionError(
                    f"seed {seed} failed: {proc.stdout}\n{proc.stderr[-2000:]}")
            digests.append(proc.stdout.strip().splitlines()[-1])
        return digests

    def test_solver_inputs_are_identical_across_hash_seeds(self):
        """The assertion with teeth. Revert any sort and this goes red.

        Every locks, excludes, forbidden-combo and stack-core list handed to the
        solver is captured in order across three seeds. Verified by sabotage:
        with stable_union returning list(set(...)) this produces three different
        digests, and with the sort in place it produces one.
        """
        digests = self._probe_digests(_SOLVER_INPUT_PROBE)
        self.assertEqual(len(set(digests)), 1,
                         f"solver input order varied by hash seed: {digests}")

    def test_two_processes_with_different_seeds_produce_one_file(self):
        """End-to-end regression guard, stated honestly for what it is.

        The review predicted that an unpinned seed could certify two different
        files from one set of inputs. The mechanism was real (set order over
        player IDs does vary by seed, and those lists became constraint rows),
        but the divergence did NOT reproduce on any fixture available here:
        with the sorting removed, both this build and a tie-rich six-pair bank
        still produced byte-identical exports across seeds, because HiGHS
        presolve absorbs the row-order difference on pools this size.

        So this test is a guard against a future regression, not a reproduction
        of a caught bug. The test above is the one that fails when the fix is
        undone.
        """
        digests = self._probe_digests(_DETERMINISM_PROBE, seeds=("1", "2"))
        self.assertEqual(digests[0], digests[1],
                         "identical inputs certified two different files")


class IntakeTrustTests(unittest.TestCase):
    """F17. Three intake facts that were labelled instead of measured.

    A partial lineup was stamped Confirmed_Starter. The platoon reference's age
    was measured against its own collected_date, the one date it cannot be stale
    against. A DK probable opener entered as a plain declared starter.
    """

    def _salary(self, tmp, starting=None):
        path = Path(tmp) / "salary.csv"
        pool_salary_csv(path)
        if starting:
            with path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            header, body = rows[0], rows[1:]
            header.append("Starting")
            for row in body:
                row.append(starting.get(row[2], ""))
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                writer.writerows(body)
        return path

    @staticmethod
    def _partial_feed(hitters=4):
        feed = pool_lineups_feed()
        side = feed["games"][1]["home"]        # T4, TBD in the base fixture
        side["lineup_status"] = "partial"
        side["lineup"] = [{"name": f"T4 Hitter{i+1}", "order": i + 1, "bat_side": "R"}
                          for i in range(hitters)]
        return feed

    @staticmethod
    def _platoon(collected="2026-07-10", page_updated=None, teams=("T4",)):
        return {"collected_date": collected, "teams": [
            {"abbrev": t, "page_updated": page_updated or collected,
             "vs_RHP": [{"player": f"{t} Hitter{i+1}", "slot": i + 1} for i in range(9)],
             "vs_LHP": [{"player": f"{t} Hitter{i+1}", "slot": i + 1} for i in range(9)]}
            for t in teams]}

    def test_partial_lineup_is_projected_not_confirmed(self):
        """A side the feed calls 'partial' must not be stamped Confirmed_Starter.

        Teeth: reverting to the unconditional ``status=CONFIRMED_STARTER`` fails
        the first assertion. tools/fetch_slate_bundle.py emits 'partial' for any
        side with one to eight hitters posted, so this is reachable on any early
        build, not a synthetic state.
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp)
            result = lda.build_status_map_from_lineups_feed(
                self._partial_feed(), str(salary))
            posted = [p for p in result["status_by_player_id"].values()
                      if p.team == "T4" and p.batting_order is not None]
            self.assertEqual(len(posted), 4)
            for player in posted:
                self.assertEqual(player.status, "Projected_Starter")
            self.assertNotIn("T4", result["confirmed_teams"])
            for player in posted:
                self.assertNotIn(player.player_id, result["confirmed_hitter_ids"])
            self.assertEqual(
                [(r["team"], r["hitters_posted"], r["lineup_status"])
                 for r in result["partial_lineup_teams"]],
                [("T4", 4, "partial")])

    def test_partial_team_is_named_in_the_pool_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = lda.build_slate_pool(
                self._salary(tmp), self._partial_feed(),
                platoon_json=self._platoon(collected="2026-07-10"))
            report = pool["pool_report"]
            # R60 moved this word off "platoon" and it is load-bearing: four of
            # these nine seats were POSTED and five came from the projection, and
            # a report that calls the whole team "platoon" hides which is which.
            self.assertEqual(report["teams"]["T4"]["status"],
                             "posted_partial_plus_platoon")
            self.assertEqual(report["teams"]["T4"]["hitters"], 9)
            self.assertTrue(any("T4" in w and "partial" in w and "Projected_Starter" in w
                                for w in report["warnings"]),
                            report["warnings"])

    def test_stale_platoon_reference_blocks_a_tbd_dependent_build(self):
        """Age is measured against the slate, and only bites when relied upon.

        Teeth: before the fix nothing anywhere compared the file to the slate
        date, so this blocker did not exist in any form and the assertion fails
        on an empty blocker list. The 'warn' policy and the confirmed-slate case
        below are the over-blocking guards.
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp)
            old = self._platoon(collected="2026-06-01")   # 39 days before the slate
            pool = lda.build_slate_pool(salary, pool_lineups_feed(), platoon_json=old)
            report = pool["pool_report"]
            self.assertEqual(report["slate_date"], "2026-07-10")
            self.assertEqual(report["platoon_age_days"], 39)
            self.assertEqual(report["platoon_dependent_teams"], ["T4"])
            self.assertTrue(any("39 days old" in b and "T4" in b
                                for b in report["blockers"]), report["blockers"])

            warned = lda.build_slate_pool(salary, pool_lineups_feed(), platoon_json=old,
                                          stale_platoon_policy="warn")["pool_report"]
            self.assertEqual(warned["blockers"], [])
            self.assertTrue(any("39 days old" in w for w in warned["warnings"]))

    def test_stale_platoon_reference_is_silent_when_nothing_leans_on_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = lda.build_slate_pool(
                self._salary(tmp), pool_lineups_feed(t4_confirmed=True),
                platoon_json=self._platoon(collected="2026-06-01"))
            report = pool["pool_report"]
            self.assertEqual(report["platoon_dependent_teams"], [])
            self.assertEqual(report["blockers"], [])
            self.assertFalse(any("days old" in w for w in report["warnings"]))

    def test_all_four_platoon_report_keys_reach_the_operator(self):
        """stale_teams, teams_missing_from_file and hand_assumed_teams were
        computed by the adapter and read by nobody; only zero_fill_teams was
        forwarded. Teeth: dropping any of the three new forwarding loops fails
        the matching assertion."""
        with tempfile.TemporaryDirectory() as tmp:
            feed = pool_lineups_feed()
            # T4's opposing hand comes from T3's probable; blank it so the
            # platoon adapter has to assume a hand for T4.
            feed["games"][1]["away"]["probable_pitcher"]["hand"] = None
            feed["games"][1]["away"]["lineup_status"] = "tbd"       # T3 TBD, not in file
            feed["games"][1]["away"]["lineup"] = []
            platoon = self._platoon(collected="2026-07-10", page_updated="2026-05-01")
            report = lda.build_slate_pool(
                self._salary(tmp), feed, platoon_json=platoon)["pool_report"]
            warnings = report["warnings"]
            self.assertTrue(any("T3" in w and "absent from the platoon reference" in w
                                for w in warnings), warnings)
            self.assertTrue(any("T4" in w and "page last updated 2026-05-01" in w
                                for w in warnings), warnings)
            self.assertTrue(any("T4" in w and "opposing pitcher hand unknown" in w
                                for w in warnings), warnings)

    def test_dk_probable_opener_is_barred_from_pitcher_slots(self):
        """R104. DK's Starting=PO is a probable opener and is NOT rosterable.

        Supersedes the F17 pin, which asserted role viable_bulk_or_alt_sp and
        called the opener "still rosterable". That role is in
        ALLOWED_PITCHER_ROLES, OPTIONAL_SP_AUDIT_STATUSES and
        ALLOWED_PITCHER_ROLES_FOR_GATE, so the optimizer could put a
        one-or-two-inning arm in a P slot priced on a starter's workload and the
        build certified with nothing flagging it. Verified against a real file:
        SD's Randy Vasquez carries Starting=PO in
        data/slates/2026-07-25/DKSalaries.csv.

        Teeth: reinstating the old ``pitcher_roles[pid] = 'viable_bulk_or_alt_sp'``
        line fails the absence assertions AND the frame assertion, because the
        arm would be back in projection_rows where the solver can reach him.
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp, starting={"T4 Ace": "PO", "T1 Ace": "SP"})
            pool = lda.build_slate_pool(salary, pool_lineups_feed(),
                                        platoon_json=self._platoon())
            roles = pool["pitcher_roles"]
            report = pool["pool_report"]
            names = {r["Player_ID"]: r["Name"] for r in pool["projection_rows"]}
            # Absent from the rosterable set AND from the frame: "absent, not
            # excluded", the pool contract's own words.
            self.assertNotIn("T4 Ace", set(names.values()))
            self.assertEqual([p for p in roles if names.get(p) == "T4 Ace"], [])
            # The plain starter is untouched.
            self.assertEqual(roles[[p for p in roles if names[p] == "T1 Ace"][0]],
                             "declared_probable_sp")
            # Visible, not silent: the bar is an audit trail, not a disappearance.
            barred = report["non_rosterable_arms"]
            self.assertEqual([a["name"] for a in barred], ["T4 Ace"])
            self.assertEqual(barred[0]["role"], lda.BARRED_OPENER_ROLE)
            self.assertEqual(barred[0]["dk_starting"], "PO")
            self.assertTrue(any("Starting=PO" in w and "T4 Ace" in w
                                for w in report["warnings"]))
            # The barred role is in NO allowed-role set. This is the assertion
            # that makes 'non-rosterable' mean something.
            from mlb_engine.entries.dk_entries_manager import ALLOWED_PITCHER_ROLES
            from mlb_engine.optimize.optimizer_v3 import (
                OPTIONAL_SP_AUDIT_STATUSES, REQUIRED_SP_AUDIT_STATUSES)
            from mlb_engine.pipeline.execution_pipeline import (
                ALLOWED_PITCHER_ROLES_FOR_GATE)
            for allowed in (ALLOWED_PITCHER_ROLES, REQUIRED_SP_AUDIT_STATUSES,
                            OPTIONAL_SP_AUDIT_STATUSES,
                            ALLOWED_PITCHER_ROLES_FOR_GATE):
                self.assertNotIn(lda.BARRED_OPENER_ROLE, allowed)
            # viable_bulk_or_alt_sp survives; PO simply stopped producing it, so
            # it is now reachable only by explicit operator declaration.
            self.assertIn("viable_bulk_or_alt_sp", ALLOWED_PITCHER_ROLES)
            self.assertNotIn("viable_bulk_or_alt_sp", REQUIRED_SP_AUDIT_STATUSES)

    def test_a_side_whose_only_arm_is_an_opener_blocks_and_names_the_cause(self):
        """R104. The bar creates a decision point; it must not create a mystery.

        Teeth: the generic "no probable or declared starter" text passes a naive
        substring check, so this asserts the opener is NAMED in the blocker.
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp, starting={"T4 Ace": "PO"})
            pool = lda.build_slate_pool(salary, pool_lineups_feed(),
                                        platoon_json=self._platoon())
            blockers = pool["pool_report"]["blockers"]
            hit = [b for b in blockers if b.startswith("T4:")]
            self.assertEqual(len(hit), 1, blockers)
            self.assertIn("T4 Ace", hit[0])
            self.assertIn("opener", hit[0])
            self.assertIn("no ROSTERABLE starter", hit[0])

    def test_an_operator_declaration_lifts_the_opener_bar(self):
        """R104. declared_pitchers is the documented way past the PO bar, and the
        arm must then leave non_rosterable_arms rather than be in both places."""
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp, starting={"T4 Ace": "PO", "T1 Ace": "SP"})
            plain = lda.build_slate_pool(salary, pool_lineups_feed(),
                                         platoon_json=self._platoon())
            opener_id = plain["pool_report"]["non_rosterable_arms"][0]["player_id"]
            pool = lda.build_slate_pool(
                salary, pool_lineups_feed(), platoon_json=self._platoon(),
                declared_pitchers={opener_id: "viable_bulk_or_alt_sp"})
            self.assertEqual(pool["pitcher_roles"][opener_id],
                             "viable_bulk_or_alt_sp")
            self.assertEqual(pool["pool_report"]["non_rosterable_arms"], [])
            self.assertEqual(
                [b for b in pool["pool_report"]["blockers"] if b.startswith("T4:")],
                [])

    def test_a_plr_arm_outside_the_pool_is_surfaced_and_never_auto_resolved(self):
        """R104. PLR is a projected long reliever, a role claim DK is making.

        Classic intake documented PLR as meaningless, so a PLR arm who was not
        also the feed probable never entered the pool and nothing said so. Live
        case: DET Ty Madden, Starting=PLR, $5,800, DK 43755567, outside the
        2026-08-05 pool. The confirm step is a web search, so the engine
        surfaces and the operator decides.

        Teeth: the arm must NOT be auto-added. A fix that quietly rostered him
        would satisfy "no longer invisible" and fail this.
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp, starting={"T4 Ace": "SP", "T1 Ace": "SP",
                                                 "T4 Pen1": "PLR"})
            pool = lda.build_slate_pool(salary, pool_lineups_feed(),
                                        platoon_json=self._platoon())
            hit = [b for b in pool["pool_report"]["blockers"] if "T4 Pen1" in b]
            self.assertEqual(len(hit), 1, pool["pool_report"]["blockers"])
            self.assertIn("projected long reliever", hit[0])
            self.assertIn("--declare-pitcher", hit[0])
            names = {r["Name"] for r in pool["projection_rows"]}
            self.assertNotIn("T4 Pen1", names)
            # Soft by build_slate's tiering: a decision the operator owes, not a
            # statement that the pool is of the wrong slate. Asserted against the
            # real regex, because a blocker that reads soft and tiers hard would
            # stop every bullpen-game slate.
            import importlib.util
            path = (REPO / "skills" / "generate-lineups" / "scripts"
                    / "build_slate.py")
            spec = importlib.util.spec_from_file_location("_bs_r104", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(module.SOFT_POOL_BLOCKER_RE.search(hit[0]), hit[0])
            self.assertFalse(
                module.SOFT_POOL_BLOCKER_RE.search(
                    "T4: no probable or declared starter; declare one via "
                    "declared_pitchers or that side has no rosterable arm"),
                "the generic no-arm blocker must stay HARD")

    def test_the_dk_starting_vocabulary_is_pinned_in_sync_across_the_two_readers(self):
        """R104. The tokens are parsed in two modules. Full consolidation into one
        module is R108; until then a diverged copy is the defect itself, so the
        two are pinned. Teeth: changing either frozenset alone fails here."""
        from mlb_engine.optimize import showdown as sd
        self.assertEqual(sd.DK_STARTING_OPENER_TOKENS,
                         lda.DK_STARTING_OPENER_TOKENS)
        # PO is an opener in both and declared in NEITHER. PLR is a declared
        # bulk arm on the Showdown side, where every slot is a UTIL slot.
        self.assertNotIn("PO", sd.DK_STARTING_DECLARED_TOKENS)
        self.assertIn("PLR", sd.DK_STARTING_DECLARED_TOKENS)
        self.assertEqual(lda.DK_STARTING_LONG_RELIEVER_TOKENS, frozenset({"PLR"}))

    def test_platoon_reference_is_tracked_and_aged_from_its_own_payload(self):
        from tools.refresh_reference_data import TRACKED_JSON, reference_status
        self.assertIn("fangraphs_platoon_lineups.json", TRACKED_JSON)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fangraphs_platoon_lineups.json").write_text(
                json.dumps({"collected_date": "2000-01-01", "teams": []}),
                encoding="utf-8")
            status = reference_status(root)["files"]["fangraphs_platoon_lineups.json"]
            self.assertTrue(status["stale"])
            self.assertEqual(status["age_basis"], "collected_date")
            # mtime is minutes old here; reading it would have called this fresh.
            self.assertGreater(status["age_days"], 9000)


class PartialSidePoolTests(unittest.TestCase):
    """R60. A partial side's posted starters are observed fact, and the TBD fill
    never consulted them.

    The side is not confirmed, so it routes through the TBD path, where the fill
    ranked the whole roster by AvgPointsPerGame. A posted starter having a worse
    season than a bench bat therefore left the posted starter unrosterable while
    the bench bat entered the pool, and the team reported nine hitters filled.
    """

    @staticmethod
    def _salary(tmp, *, posted_appg=2.0, bench_appg=9.0, team="T4"):
        """T4's posted starters out-earned by its own bench bats on APPG.

        Not synthetic: a call-up or a defensive starter carries a low season
        average on the night he is in the lineup, and the bench bat he replaced
        carries the higher one.
        """
        path = Path(tmp) / "salary.csv"
        pool_salary_csv(path)
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        header, body = rows[0], rows[1:]
        appg, name, abbrev = (header.index("AvgPointsPerGame"),
                              header.index("Name"), header.index("TeamAbbrev"))
        for row in body:
            if row[abbrev] != team:
                continue
            if "Hitter" in row[name]:
                row[appg] = posted_appg
            elif "Bench" in row[name]:
                row[appg] = bench_appg
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(body)
        return path

    @staticmethod
    def _partial_feed(hitters=8):
        feed = pool_lineups_feed()
        side = feed["games"][1]["home"]        # T4, TBD in the base fixture
        side["lineup_status"] = "partial"
        side["lineup"] = [{"name": f"T4 Hitter{i+1}", "order": i + 1, "bat_side": "R"}
                          for i in range(hitters)]
        return feed

    @staticmethod
    def _platoon(slots=0):
        return {"collected_date": "2026-07-10", "teams": [
            {"abbrev": "T4", "page_updated": "2026-07-10",
             "vs_RHP": [{"player": f"T4 Hitter{i+1}", "slot": i + 1}
                        for i in range(slots)],
             "vs_LHP": [{"player": f"T4 Hitter{i+1}", "slot": i + 1}
                        for i in range(slots)]}]}

    def _t4_hitters(self, pool):
        return sorted(row["Name"] for row in pool["projection_rows"]
                      if row["Team"] == "T4"
                      and "P" not in row["Position"].split("/"))

    def test_posted_starters_outrank_bench_bats_on_a_partial_side(self):
        """Teeth: dropping the seeding puts T4 Hitter6/7/8 out of the pool and
        all four bench bats in it, which is the reproduction this item was filed
        on. The APPG spread is what makes the ranking, not the posting, decide.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pool = lda.build_slate_pool(
                self._salary(tmp), self._partial_feed(hitters=8),
                platoon_json=self._platoon(slots=0))
            names = self._t4_hitters(pool)
            for i in range(8):
                self.assertIn(f"T4 Hitter{i+1}", names,
                              "a POSTED starter is unrosterable")
            # Exactly one slot is left for the fill, and no posted starter is
            # displaced to make room for it.
            self.assertEqual(len(names), 9)
            self.assertEqual([n for n in names if "Bench" in n], ["T4 Bench1"])
            report = pool["pool_report"]
            self.assertEqual(report["teams"]["T4"]["status"],
                             "posted_partial_plus_appg_fallback")
            self.assertEqual(report["teams"]["T4"]["hitters"], 9)
            self.assertFalse([w for w in report["warnings"] if "left out" in w],
                             report["warnings"])

    def test_posted_starters_are_seeded_ahead_of_the_platoon_projection(self):
        """The platoon reference is a prior; a posted slot is not. When both
        name a nine, the posted names take the seats they claim."""
        with tempfile.TemporaryDirectory() as tmp:
            feed = pool_lineups_feed()
            side = feed["games"][1]["home"]
            side["lineup_status"] = "partial"
            # Posted side is the four bench bats; the platoon file projects the
            # nine regulars. Posted wins the four seats it names.
            side["lineup"] = [{"name": f"T4 Bench{i+1}", "order": i + 1,
                               "bat_side": "R"} for i in range(4)]
            pool = lda.build_slate_pool(
                self._salary(tmp, posted_appg=9.0, bench_appg=2.0), feed,
                platoon_json=self._platoon(slots=9))
            names = self._t4_hitters(pool)
            self.assertEqual(len(names), 9)
            for i in range(4):
                self.assertIn(f"T4 Bench{i+1}", names)
            self.assertEqual(pool["pool_report"]["teams"]["T4"]["status"],
                             "posted_partial_plus_platoon")

    def test_an_excluded_tbd_team_leaves_no_rows_in_the_pool(self):
        """R60(b). 'team excluded' has to mean excluded.

        Teeth: before the fix the platoon-seeded rows stayed in the pool while
        the blocker said the team was out, so the report and the pool disagreed
        at the moment the operator reads the blocker to decide.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "salary.csv"
            pool_salary_csv(path)
            pool = lda.build_slate_pool(
                path, pool_lineups_feed(), platoon_json=self._platoon(slots=5),
                tbd_fallback="exclude")
            report = pool["pool_report"]
            self.assertEqual(self._t4_hitters(pool), [])
            self.assertEqual(report["teams"]["T4"]["hitters"], 0)
            self.assertEqual(report["teams"]["T4"]["status"],
                             "excluded_no_order_data")
            hit = [b for b in report["blockers"] if "T4" in b and "excluded" in b]
            self.assertEqual(len(hit), 1, report["blockers"])
            self.assertIn("5 row(s) dropped from the pool", hit[0])

    def test_a_posted_starter_that_does_not_reach_the_pool_is_named(self):
        """The safety net behind the seeding: the failure R60 was filed on was
        silent, so any posted starter still missing is named with his DK ID."""
        with tempfile.TemporaryDirectory() as tmp:
            pool = lda.build_slate_pool(
                self._salary(tmp), self._partial_feed(hitters=8),
                platoon_json=self._platoon(slots=0), tbd_fallback="exclude")
            named = [w for w in pool["pool_report"]["warnings"]
                     if "posted starter(s) left out of the pool" in w]
            self.assertEqual(len(named), 1, pool["pool_report"]["warnings"])
            for i in range(8):
                self.assertIn(f"T4 Hitter{i+1}", named[0])

    def test_a_fully_posted_side_is_not_platoon_dependent(self):
        """The staleness gate follows what the projection SUPPLIED, not what it
        covers. Posted seeds can take all nine seats, and a stale reference that
        supplied nothing must not block the build — the same reasoning CLAUDE.md
        item 2 applies to a fully pasted slate.

        Teeth: deriving platoon_dependent_teams from coverage rather than use
        puts T4 back in the list and the 39-day blocker fires on a side whose
        nine were all posted.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stale = self._platoon(slots=9)
            stale["collected_date"] = "2026-06-01"      # 39 days before the slate
            stale["teams"][0]["page_updated"] = "2026-06-01"
            pool = lda.build_slate_pool(
                self._salary(tmp), self._partial_feed(hitters=9),
                platoon_json=stale, stale_platoon_policy="block")
            report = pool["pool_report"]
            self.assertEqual(report["teams"]["T4"]["status"], "posted_partial")
            self.assertEqual(report["platoon_dependent_teams"], [])
            self.assertFalse([b for b in report["blockers"] if "days old" in b],
                             report["blockers"])
            # The guard on the guard: a side that DOES lean on the projection
            # still blocks on the same reference.
            leaning = lda.build_slate_pool(
                self._salary(tmp), self._partial_feed(hitters=4),
                platoon_json=stale, stale_platoon_policy="block")
            self.assertEqual(
                leaning["pool_report"]["platoon_dependent_teams"], ["T4"])
            self.assertTrue([b for b in leaning["pool_report"]["blockers"]
                             if "39 days old" in b],
                            leaning["pool_report"]["blockers"])

    def test_a_confirmed_side_is_untouched_by_the_seeding(self):
        """Over-reach guard: the confirmed path owns its nine and keeps its F2
        stamp, and nothing about a fully confirmed slate moves."""
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp)
            pool = lda.build_slate_pool(salary, pool_lineups_feed(t4_confirmed=True))
            report = pool["pool_report"]
            for team in ("T1", "T2", "T3", "T4"):
                self.assertEqual(report["teams"][team]["status"], "confirmed")
            stamped = [row for row in pool["projection_rows"]
                       if row["Team"] == "T4" and row.get("Batting_Order")]
            self.assertEqual(len(stamped), 9)
            self.assertFalse([w for w in report["warnings"] if "seeded" in w],
                             report["warnings"])


class IntakeFailOpenTests(unittest.TestCase):
    """R69. Three intake reads that failed OPEN: they degraded to silence
    instead of to a signal, so a disarmed guard and a healthy slate produced
    byte-identical output.

    The shared teeth across all three: each test pairs the failure case with a
    HEALTHY control, because a guard that fires on everything is the same
    defect wearing the other sign.
    """

    HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position",
              "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame",
              "Status", "Starting"]

    def _salary_file(self, tmp, header=None, rows=60, status_of=None,
                     name="salary.csv"):
        path = Path(tmp) / name
        if status_of is None:
            def status_of(i):
                return "IL" if i == 0 else ""
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header or self.HEADER)
            for i in range(rows):
                w.writerow(["OF", f"P{i} ({100 + i})", f"P{i}", str(100 + i),
                            "OF", "4000", "T1@T2 08/13/2026 07:05PM ET", "T1",
                            "7.0", status_of(i), "SP" if i == 1 else ""])
        return path

    # ---- (a) the Status/Starting read ---------------------------------------

    def test_healthy_salary_file_warns_about_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._salary_file(tmp)
            cov = sim.salary_status_coverage(sim.parse_dk_salary_csv(str(path)))
            self.assertEqual(cov["warnings"], [])
            self.assertTrue(cov["status_column_present"])
            self.assertTrue(cov["starting_column_present"])
            self.assertEqual(cov["status_non_blank"], 1)

    def test_renamed_status_column_is_named_as_disarming_the_il_drop(self):
        """The filed scenario: DK renames the column, the schema gate passes it
        because neither column is required, and every player then reads the
        clean tier. Teeth: without the fix the shelved player below survives
        into the pool and NOTHING says so."""
        with tempfile.TemporaryDirectory() as tmp:
            header = list(self.HEADER)
            header[header.index("Status")] = "Injury Status"
            header[header.index("Starting")] = "Starting Pitcher"
            path = self._salary_file(tmp, header=header)
            players = sim.parse_dk_salary_csv(str(path))
            # The disarm itself, unchanged: the shelved player reads clean.
            self.assertEqual(sim.salary_status_tier(players[0].status), "clean")
            cov = sim.salary_status_coverage(players)
            self.assertFalse(cov["status_column_present"])
            self.assertFalse(cov["starting_column_present"])
            self.assertEqual(len(cov["warnings"]), 2)
            self.assertTrue(any("IL drop is disarmed" in w
                                for w in cov["warnings"]), cov["warnings"])
            self.assertTrue(any("opener detection" in w
                                for w in cov["warnings"]), cov["warnings"])
            # The near-miss headers are named, because that is the whole fix
            # on the operator's side.
            self.assertEqual(cov["near_miss_columns"],
                             ["Injury Status", "Starting Pitcher"])

    def test_zero_status_coverage_on_a_slate_sized_file_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._salary_file(tmp, rows=60, status_of=lambda i: "")
            cov = sim.salary_status_coverage(sim.parse_dk_salary_csv(str(path)))
            self.assertTrue(cov["status_column_present"])
            self.assertTrue(any("not one of 60 rows" in w
                                for w in cov["warnings"]), cov["warnings"])

    def test_a_small_pool_with_no_shelved_player_stays_quiet(self):
        """Over-reach guard. A two-game Showdown pool really can carry no
        shelved player, so the zero-coverage signal is floored by row count."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._salary_file(
                tmp, rows=sim.STATUS_COVERAGE_MIN_ROWS - 1,
                status_of=lambda i: "")
            cov = sim.salary_status_coverage(sim.parse_dk_salary_csv(str(path)))
            self.assertEqual(cov["warnings"], [])

    def test_pool_report_carries_the_coverage_block_and_its_warnings(self):
        """The signal has to land where CLAUDE.md says the operator reads before
        approving. ``pool_salary_csv`` carries neither column, which is not a
        contrived fixture: 3 of the 75 real DKSalaries files in data/slates ship
        without both, the most recent dated 2026-08-01."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "salary.csv"
            pool_salary_csv(path)
            report = lda.build_slate_pool(path, pool_lineups_feed())["pool_report"]
            coverage = report["salary_status_coverage"]
            self.assertFalse(coverage["status_column_present"])
            self.assertFalse(coverage["starting_column_present"])
            self.assertEqual(coverage["rows"], 68)
            self.assertTrue(any("IL drop is disarmed" in w
                                for w in report["warnings"]),
                            report["warnings"])
            self.assertTrue(any("opener detection" in w
                                for w in report["warnings"]))

    # ---- (b) the un-ageable platoon reference -------------------------------

    def _unageable_pool(self, tmp, collected, policy, hitters=4):
        ref = PartialSidePoolTests._platoon(slots=9)
        if collected is None:
            ref.pop("collected_date", None)
        else:
            ref["collected_date"] = collected
        return lda.build_slate_pool(
            PartialSidePoolTests._salary(tmp),
            PartialSidePoolTests._partial_feed(hitters=hitters),
            platoon_json=ref, stale_platoon_policy=policy)["pool_report"]

    def test_unknown_platoon_age_blocks_under_the_block_policy(self):
        """Age unknown is not age zero. Teeth: the age came out None, None
        compares against no threshold, and the strictest policy was silent."""
        for collected in ("not-a-date", "", None):
            with self.subTest(collected=collected):
                with tempfile.TemporaryDirectory() as tmp:
                    report = self._unageable_pool(tmp, collected, "block")
                    self.assertIsNone(report["platoon_age_days"])
                    self.assertEqual(report["platoon_dependent_teams"], ["T4"])
                    hit = [b for b in report["blockers"] if "UNKNOWN" in b]
                    self.assertEqual(len(hit), 1, report["blockers"])
                    self.assertIn("no parseable collected_date", hit[0])

    def test_unknown_platoon_age_warns_under_the_warn_policy(self):
        """It reports at the POLICY's severity, which is what build_slate.py and
        late_swap.py pass, so the build still ships."""
        with tempfile.TemporaryDirectory() as tmp:
            report = self._unageable_pool(tmp, "not-a-date", "warn")
            self.assertFalse([b for b in report["blockers"] if "UNKNOWN" in b])
            self.assertEqual(
                len([w for w in report["warnings"] if "UNKNOWN" in w]), 1)

    def test_a_reference_the_build_does_not_lean_on_says_nothing(self):
        """Over-reach guard, and the F17/R60 rule this rides on: the gate follows
        what the projection SUPPLIED. A fully posted side takes all nine seats,
        so an unageable reference supplied nothing and must stay silent."""
        with tempfile.TemporaryDirectory() as tmp:
            report = self._unageable_pool(tmp, "not-a-date", "block", hitters=9)
            self.assertEqual(report["platoon_dependent_teams"], [])
            self.assertFalse([b for b in report["blockers"] if "UNKNOWN" in b],
                             report["blockers"])
            self.assertFalse([w for w in report["warnings"] if "UNKNOWN" in w])

    def test_a_parseable_date_still_takes_the_days_old_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self._unageable_pool(tmp, "2026-06-01", "block")
            self.assertEqual(report["platoon_age_days"], 39)
            self.assertFalse([b for b in report["blockers"] if "UNKNOWN" in b])
            self.assertTrue([b for b in report["blockers"] if "39 days old" in b])


class LateSwapIdentityTests(unittest.TestCase):
    """F16. The only permitted post-delivery path, given the identity and the
    verification the build already had.

    Coverage boundary, stated so it is not mistaken for more than it is: the
    downgrade REFUSAL is not exercised end to end here, because reaching it
    requires a promoted parent run and a completed joint solve. What is covered
    is the scoring the refusal is computed from (``_score_roster`` under two
    shapes, and the unscorable case reading as no-comparison rather than
    no-downgrade). The refusal branch itself is guarded only by review.
    """

    @staticmethod
    def _tool():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_late_swap_tool", Path(__file__).resolve().parents[1] / "tools" / "late_swap.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _slate(self, tmp, contest_names, date="2026-07-10", feed=None):
        """A REPO-shaped temp tree: data/slates/<date>/{DKSalaries,lineups_feed}."""
        repo = Path(tmp)
        slate = repo / "data" / "slates" / date
        slate.mkdir(parents=True)
        pool_salary_csv(slate / "DKSalaries.csv")
        (slate / "lineups_feed.json").write_text(
            json.dumps(feed if feed is not None else pool_lineups_feed()),
            encoding="utf-8")
        parent = repo / "parent.csv"
        with parent.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(HEADER)
            for i, name in enumerate(contest_names, start=1):
                writer.writerow([str(7000 + i), name, str(800 + i), "$1",
                                 *([""] * 10), "", ""])
        return repo, parent

    def _run(self, tool, repo, parent, date="2026-07-10", extra=()):
        import contextlib, io, sys
        argv = ["late_swap.py", "--date", date, "--parent-entries", str(parent), *extra]
        old_repo, old_argv = tool.REPO, sys.argv
        tool.REPO = repo
        sys.argv = argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = tool.main()
        finally:
            tool.REPO, sys.argv = old_repo, old_argv
        return code, out.getvalue(), err.getvalue()

    def test_unresolved_contest_identity_blocks_the_swap(self):
        """A contest the archetypes do not recognise stops the swap.

        Teeth: before the fix the tool never resolved a posture at all, so this
        name silently became large_wta and main() proceeded. Removing the
        resolution block makes this return something other than 3.
        """
        tool = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            repo, parent = self._slate(tmp, ["Some Contest Nobody Named"])
            code, out, err = self._run(tool, repo, parent)
            self.assertEqual(code, 3)
            self.assertIn("POSTURE BLOCKER", err)
            self.assertIn("--postures", err)

    def test_operator_supplied_posture_resolves_and_routes(self):
        tool = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            repo, parent = self._slate(tmp, ["Some Contest Nobody Named"])
            code, out, err = self._run(
                tool, repo, parent, extra=["--postures", "801=cash", "--dry-run"])
            self.assertIn("contest 801 cash -> cash (operator_supplied)", out)
            self.assertNotEqual(code, 3)

    def test_two_contests_resolve_to_two_different_shapes(self):
        """The defect in one line: every entry used to be stamped large_wta.

        Teeth: with contest_shapes not passed through, both entries carry
        'large_wta' and the inequality assertion fails.
        """
        from mlb_engine.pipeline.execution_pipeline import _resolve_contest_postures
        from mlb_engine.swap.late_swap_manager import build_entry_requirements
        tool = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            repo, parent = self._slate(
                tmp, ["MLB $5 Double Up", "MLB Satellite to the Slam"])
            postures = _resolve_contest_postures(
                list(parse_dk_entry_rows(parent)),
                tool._parse_postures("801=cash,802=wta_satellite"), None)
            shapes = {cid: rec["contest_shape"] for cid, rec in postures.items()}
            self.assertEqual(shapes, {"801": "cash", "802": "large_wta"})
            reqs = build_entry_requirements(
                parent, {}, NOW, shapes, missing_status_policy="treat_as_locked")
            got = {r["entry_id"]: r["contest_shape"] for r in reqs}
            self.assertEqual(got, {"7001": "cash", "7002": "large_wta"})
            self.assertNotEqual(got["7001"], got["7002"])
            default = build_entry_requirements(
                parent, {}, NOW, None, missing_status_policy="treat_as_locked")
            self.assertEqual({r["contest_shape"] for r in default}, {"large_wta"})

    def test_candidates_are_scored_and_scored_in_each_contests_own_shape(self):
        """The swap must hand the allocator scored candidates, not bare rosters.

        ``as_candidates()`` with no projections carries roster and objective
        only: floor_sum reads 0.0, so the cash branch cannot tell a high-floor
        lineup from any other. ``last_payload_report`` records both facts, so a
        dry run states them. Teeth: reverting the call to a bare
        ``cache.as_candidates()`` makes projections_supplied False and
        shapes_scored empty, and both assertions fail.
        """
        tool = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            repo, parent = self._slate(
                tmp, ["MLB $5 Double Up", "MLB Satellite to the Slam"])
            code, out, err = self._run(
                tool, repo, parent,
                extra=["--postures", "801=cash,802=wta_satellite",
                       "--budget", "3", "--dry-run"])
            self.assertEqual(code, 0, err)
            payload = json.loads(out[out.index("{"):])
            scoring = payload["candidate_scoring"]
            self.assertTrue(scoring["projections_supplied"])
            self.assertEqual(sorted(scoring["shapes_scored"]), ["cash", "large_wta"])
            self.assertEqual(payload["contest_shapes"],
                             {"801": "cash", "802": "large_wta"})

    def test_feed_for_the_wrong_date_blocks_and_a_stale_feed_warns(self):
        import datetime as dt
        tool = self._tool()
        now = dt.datetime(2026, 7, 10, 22, 0, tzinfo=dt.timezone.utc)
        wrong = {"date": "2026-07-09", "fetched_at": "2026-07-10T21:55:00Z"}
        blockers, warnings = tool._feed_age_report(wrong, "2026-07-10", now)
        self.assertTrue(any("2026-07-09" in b for b in blockers))
        stale = {"date": "2026-07-10", "fetched_at": "2026-07-10T17:00:00Z"}
        blockers, warnings = tool._feed_age_report(stale, "2026-07-10", now)
        self.assertEqual(blockers, [])
        self.assertTrue(any("300 minutes ago" in w for w in warnings), warnings)
        fresh = {"date": "2026-07-10", "fetched_at": "2026-07-10T21:55:00Z"}
        self.assertEqual(tool._feed_age_report(fresh, "2026-07-10", now), ([], []))

    def test_wrong_date_feed_stops_main_before_any_bank_work(self):
        tool = self._tool()
        feed = pool_lineups_feed()
        feed["date"] = "2026-07-09"
        with tempfile.TemporaryDirectory() as tmp:
            repo, parent = self._slate(tmp, ["MLB $5 Double Up"], feed=feed)
            code, out, err = self._run(tool, repo, parent)
            self.assertEqual(code, 3)
            self.assertIn("FEED BLOCKER", err)

    def test_bad_posture_token_is_rejected_eagerly(self):
        tool = self._tool()
        with self.assertRaises(SystemExit):
            tool._parse_postures("801=gpp_but_not_really")
        with self.assertRaises(SystemExit):
            tool._parse_postures("801")
        self.assertEqual(tool._parse_postures(None), {})

    def test_cash_and_wta_shapes_rank_the_same_two_rosters_differently(self):
        """The done-when for F16's scoring half.

        A high-floor roster and a high-ceiling roster are scored under both
        shapes. Cash weights floor, WTA takes pure ceiling, so the ordering
        flips. Teeth: score both under one hardcoded mode (which is what
        as_candidates() with no shapes did) and the two deltas have the same
        sign, failing the flip assertion.
        """
        import pandas as pd
        tool = self._tool()
        rows = []
        for i in range(10):
            floor_heavy = i % 2 == 0
            rows.append({
                "Player_ID": str(90000 + i), "Name": f"P{i}",
                "Position": "P" if i < 2 else "OF", "Team": "T1" if i % 2 else "T2",
                "Salary": 5000, "Base": 10.0,
                "Ceiling": 30.0 if not floor_heavy else 16.0,
                "Floor": 4.0 if not floor_heavy else 13.0,
                "Projected_Ownership_Pct": 12.0, "Batting_Order": (i % 9) + 1,
            })
        frame = pd.DataFrame(rows)
        floor_roster = [r["Player_ID"] for r in rows if r["Floor"] > 10]
        ceiling_roster = [r["Player_ID"] for r in rows if r["Floor"] <= 10]
        cash_delta = (tool._score_roster(frame, floor_roster, "cash")
                      - tool._score_roster(frame, ceiling_roster, "cash"))
        wta_delta = (tool._score_roster(frame, floor_roster, "large_wta")
                     - tool._score_roster(frame, ceiling_roster, "large_wta"))
        self.assertGreater(cash_delta, wta_delta,
                           "cash and WTA ranked the same rosters identically")
        self.assertLess(wta_delta, 0, "WTA must prefer the ceiling roster")

    def test_unscorable_roster_reads_as_no_comparison_not_no_downgrade(self):
        import pandas as pd
        tool = self._tool()
        frame = pd.DataFrame([{"Player_ID": "1", "Ceiling": 10.0, "Floor": 5.0,
                               "Salary": 4000, "Team": "T1", "Position": "OF"}])
        self.assertIsNone(tool._score_roster(frame, ["1", "2"], "large_wta"))
        self.assertIsNone(tool._score_roster(frame, [], "large_wta"))


class LateSwapDeltaAuthorizationTests(unittest.TestCase):
    """F16. An explicitly empty authorized set is not 'anything may change'."""

    def _pair(self, tmp, changed: bool):
        ids = write_salary(Path(tmp) / "salary.csv")
        r1, r2 = legal_rosters(ids)
        source = Path(tmp) / "source.csv"
        candidate = Path(tmp) / "candidate.csv"
        write_entries(source, [r1, r2])
        write_entries(candidate, [r2 if changed else r1, r2])
        return source, candidate

    def test_empty_authorized_set_means_nothing_may_change(self):
        """Teeth: restoring ``if mutable and entry_id not in mutable`` makes the
        empty-set case pass, which is the bug. The None case below is the
        over-blocking guard, and validate_template_preservation has always read
        the empty set this way, so the two now agree."""
        from mlb_engine.swap.late_swap_manager import validate_late_swap_delta
        with tempfile.TemporaryDirectory() as tmp:
            source, candidate = self._pair(tmp, changed=True)
            empty = validate_late_swap_delta(source, candidate, mutable_entry_ids=[])
            self.assertFalse(empty["passed"])
            self.assertTrue(any("without permission" in e for e in empty["errors"]))
            self.assertEqual(empty["authorization"], "0 authorized Entry ID(s)")

            unrestricted = validate_late_swap_delta(source, candidate,
                                                    mutable_entry_ids=None)
            self.assertTrue(unrestricted["passed"])
            self.assertEqual(unrestricted["authorization"], "unrestricted")
            self.assertEqual(unrestricted["changed_entry_ids"], ["5001"])

            authorized = validate_late_swap_delta(source, candidate,
                                                  mutable_entry_ids=["5001"])
            self.assertTrue(authorized["passed"])

    def test_an_unchanged_file_passes_under_every_authorization(self):
        from mlb_engine.swap.late_swap_manager import validate_late_swap_delta
        with tempfile.TemporaryDirectory() as tmp:
            source, candidate = self._pair(tmp, changed=False)
            for mutable in (None, [], ["5001"]):
                self.assertTrue(
                    validate_late_swap_delta(source, candidate,
                                             mutable_entry_ids=mutable)["passed"])


class EnvironmentFactorOwnershipTests(unittest.TestCase):
    """F18. Park was priced twice, doubleheader totals collapsed, delay risk was
    a constant, the most wind-sensitive park never took wind, and the neutral-site
    override file was never loaded.

    Park ownership decided on the record 2026-07-27: F5 owns the ballpark and F1's
    implied total is de-parked before the slate-mean ratio, so the product prices
    the park once. Every gate below was verified by sabotage; where a test passes
    with and without the fix, its own docstring says so.
    """

    @staticmethod
    def _pb():
        from mlb_engine.projections import projection_builder as pb
        return pb

    @staticmethod
    def _module():
        return BuildSlateScriptTests._module()

    # -- park priced once ---------------------------------------------------

    def test_deparking_pulls_the_combined_uplift_back_inside_the_f1_clip(self):
        """The defect in one number. An extreme park's hitters carried the park in
        F1 (through the posted total) and again in F5, so Base x F1 x F5 escaped
        the band F1's own clip defines. On a realistic slate spread the product is
        1.173 before and 1.098 after, against a 1.15 clip ceiling.

        Sabotage check: drop ``park_run_factor_by_game_id`` from the second call
        and the combined product returns to 1.173, failing ``assertLessEqual``.
        """
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 9.5}, "CCC@DDD": {"total": 8.0}}
        teams = {"a": "AAA", "b": "BBB", "c": "CCC", "d": "DDD"}
        parks = {"AAA@BBB": 1.08, "CCC@DDD": 0.94}
        low, high = pb.F1_HITTER_CLIP

        f1_raw, _ = pb.build_f1_factors(odds, teams)
        self.assertGreater(f1_raw["b"] * parks["AAA@BBB"], high)

        f1_deparked, report = pb.build_f1_factors(
            odds, teams, park_run_factor_by_game_id=parks)
        combined = f1_deparked["b"] * parks["AAA@BBB"]
        self.assertLessEqual(combined, high)
        self.assertGreaterEqual(combined, low)
        self.assertLess(f1_deparked["b"], f1_raw["b"])
        self.assertTrue(report["park_adjusted"])
        self.assertEqual(report["f1_ratio_basis"], "deparked_implied_total")

    def test_the_clip_band_is_not_a_bound_on_the_combined_product(self):
        """Stated so it is not rediscovered as a bug. De-parking removes the
        double count; it does not cap Base x F1 x F5. The clip is applied to F1
        alone, so on a slate whose de-parked spread still exceeds the band, F1
        saturates at 1.15 and the product reaches 1.15 x park anyway.

        The backlog's F18 acceptance line ("a Coors fixture's combined uplift
        stays inside the F1 clip band") is therefore true of realistic slates and
        NOT true in general. Capping the product would require F1 to read F5,
        which is the ownership boundary this item exists to draw. If the product
        needs a hard ceiling it belongs at the composition site, as its own
        decision.
        """
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 12.0}, "CCC@DDD": {"total": 6.0}}
        teams = {"a": "AAA", "b": "BBB", "c": "CCC", "d": "DDD"}
        parks = {"AAA@BBB": 1.08, "CCC@DDD": 0.94}
        _, high = pb.F1_HITTER_CLIP
        f1, _ = pb.build_f1_factors(odds, teams, park_run_factor_by_game_id=parks)
        self.assertAlmostEqual(f1["b"], high)
        self.assertGreater(f1["b"] * parks["AAA@BBB"], high)

    def test_two_equal_totals_in_unequal_parks_rank_by_the_deparked_view(self):
        """A 9.0 total in a 1.08 park is a weaker offensive read than the same 9.0
        in a 0.94 park, because the market has already paid for the ballpark. With
        the park factor removed, the pitcher's-park team ranks higher.

        Sabotage check: without the park map both games price identically and
        assertGreater fails.
        """
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 9.0}, "CCC@DDD": {"total": 9.0}}
        teams = {"a": "AAA", "c": "CCC"}
        flat, _ = pb.build_f1_factors(odds, teams)
        self.assertAlmostEqual(flat["a"], flat["c"])
        deparked, _ = pb.build_f1_factors(
            odds, teams, park_run_factor_by_game_id={"AAA@BBB": 1.08, "CCC@DDD": 0.94})
        self.assertGreater(deparked["c"], deparked["a"])

    def test_raw_implied_totals_survive_de_parking_in_the_report(self):
        """The de-park changes F1, not what "implied total" means. The brief and
        the ownership work read ``implied_total_by_team`` as the market's number,
        so it stays raw and the de-parked view gets its own key."""
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 9.0}}
        _, report = pb.build_f1_factors(
            odds, {"a": "AAA", "b": "BBB"},
            park_run_factor_by_game_id={"AAA@BBB": 1.08})
        self.assertAlmostEqual(report["implied_total_by_team"]["AAA"], 4.5)
        self.assertAlmostEqual(report["deparked_implied_total_by_team"]["AAA"], 4.17)
        self.assertAlmostEqual(report["league_mean_implied_total"], 4.5)
        self.assertAlmostEqual(report["f1_ratio_denominator"], 4.167, places=3)

    def test_a_game_with_no_park_factor_is_named_and_kept(self):
        """Missing venue data divides by 1.0 and says which game. Dropping the
        game would be the forbidden pool reduction arriving as a data condition."""
        pb = self._pb()
        odds = {"AAA@BBB": {"total": 9.0}, "CCC@DDD": {"total": 9.0}}
        f1, report = pb.build_f1_factors(
            odds, {"a": "AAA", "c": "CCC"},
            park_run_factor_by_game_id={"AAA@BBB": 1.08})
        self.assertEqual(report["games_without_park_factor"], ["CCC@DDD"])
        self.assertIn("c", f1)

    def test_omitting_the_park_map_says_the_build_is_not_park_adjusted(self):
        """A caller with no venue data still gets an F1, and the report refuses to
        imply an adjustment it did not make."""
        pb = self._pb()
        _, report = pb.build_f1_factors({"AAA@BBB": {"total": 9.0}}, {"a": "AAA"})
        self.assertFalse(report["park_adjusted"])
        self.assertEqual(report["f1_ratio_basis"], "implied_total")
        self.assertIn("NO park adjustment", report["note"])

    # -- doubleheader legs --------------------------------------------------

    @staticmethod
    def _dh_events():
        def event(event_id, commence, total):
            return {"id": event_id, "home_team": "New York Yankees",
                    "away_team": "Boston Red Sox", "commence_time": commence,
                    "bookmakers": [{"key": "dk", "markets": [
                        {"key": "totals", "outcomes": [{"point": total}]}]}]}
        return [event("matinee", "2026-07-27T17:05:00Z", 7.5),
                event("nightcap", "2026-07-27T23:05:00Z", 11.5)]

    def test_odds_resolve_the_doubleheader_leg_the_salary_file_names(self):
        """The lineups feed got leg resolution and the odds packet did not, so a
        matinee draftgroup could be priced off the nightcap's total.

        Sabotage check: restore the ``odds_by_game_id[game_id] = ...`` assignment
        loop and the nightcap's 11.5 wins on input order alone, so the matinee
        assertion below fails.
        """
        from mlb_engine.intake.live_data_adapters import parse_the_odds_api_totals
        events = self._dh_events()
        matinee = {"BOS@NYY": datetime(2026, 7, 27, 17, 5, tzinfo=timezone.utc)}
        night = {"BOS@NYY": datetime(2026, 7, 27, 23, 5, tzinfo=timezone.utc)}
        for source in (events, list(reversed(events))):
            self.assertEqual(
                parse_the_odds_api_totals(source, slate_game_times=matinee)
                ["odds_by_game_id"]["BOS@NYY"]["total"], 7.5)
            self.assertEqual(
                parse_the_odds_api_totals(source, slate_game_times=night)
                ["odds_by_game_id"]["BOS@NYY"]["total"], 11.5)

    def test_the_dropped_odds_leg_is_reported_with_its_own_total(self):
        """Both totals stay visible. A collapsed key that silently discards one is
        how the wrong game gets priced without anything saying so."""
        from mlb_engine.intake.live_data_adapters import parse_the_odds_api_totals
        out = parse_the_odds_api_totals(
            self._dh_events(),
            slate_game_times={"BOS@NYY": datetime(2026, 7, 27, 17, 5, tzinfo=timezone.utc)})
        dropped = out["doubleheader_legs_dropped"]
        self.assertEqual([d["event_id"] for d in dropped], ["nightcap"])
        self.assertEqual(dropped[0]["total"], 11.5)
        self.assertEqual(
            sorted(leg["total"] for leg in out["legs_by_game_id"]["BOS@NYY"]),
            [7.5, 11.5])

    def test_without_salary_times_the_earliest_leg_wins_not_the_last_parsed(self):
        """First-wins is a rule; last-write-wins is an accident of iteration
        order. This is the no-salary-file fallback and it matches what
        ``_select_slate_legs`` already did for the lineups feed."""
        from mlb_engine.intake.live_data_adapters import parse_the_odds_api_totals
        events = self._dh_events()
        for source in (events, list(reversed(events))):
            self.assertEqual(
                parse_the_odds_api_totals(source)["odds_by_game_id"]["BOS@NYY"]["total"],
                7.5)

    def test_one_leg_selector_serves_both_the_feed_and_the_odds(self):
        """Two copies of a leg rule are two answers to one question. The feed
        wrapper and the odds parser must CALL the same function, not merely
        mention it: a first pass at this test matched the string anywhere in the
        source and a genuine duplicated implementation slid past it, because the
        wrapper's docstring still named the shared helper. The check is on the
        parsed call graph for that reason."""
        import ast
        import textwrap
        from mlb_engine.intake import live_data_adapters as lda

        def calls(fn):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            return {node.func.id for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

        self.assertTrue(hasattr(lda, "select_one_leg_per_matchup"))
        self.assertIn("select_one_leg_per_matchup", calls(lda._select_slate_legs))
        self.assertIn("select_one_leg_per_matchup", calls(lda.parse_the_odds_api_totals))

    # -- delay and postponement risk ---------------------------------------

    def test_precip_reader_accepts_the_key_the_bundle_actually_writes(self):
        """``_legacy_risk_from_precip`` read ``precip_probability``. Nothing in the
        repo emits that key; ``fetch_slate_bundle`` writes
        ``precip_probability_pct``, so the reader returned ("", "") on every real
        payload.

        Sabotage check: narrow the key list back to ``precip_probability`` and the
        ``_pct`` assertion below fails.
        """
        from mlb_engine.intake.slate_intake_manager import (
            _legacy_risk_from_precip, risk_from_precip_probability,
        )
        self.assertEqual(_legacy_risk_from_precip({"precip_probability_pct": 70}),
                         ("high", "medium"))
        self.assertEqual(_legacy_risk_from_precip({"precip_probability": 70}),
                         ("high", "medium"))
        self.assertEqual(_legacy_risk_from_precip({}), ("", ""))
        self.assertEqual(risk_from_precip_probability(40), ("medium", "low"))
        self.assertEqual(risk_from_precip_probability(0), ("none", "none"))

    def test_a_rained_out_forecast_reaches_the_pitcher_delay_factor(self):
        """``build_f5_map`` hardcoded delay and postponement to "none", so both
        branches of ``compute_f5_factor`` were unreachable from production.

        Sabotage check: hardcode ``delay_risk="none"`` in ``build_f5_map`` again
        and the pitcher factor returns to 1.0, failing the assertion below.
        """
        mod = self._module()
        pool = {"team_by_player_id": {"1": "SEA"},
                "pitcher_roles": {"9": "declared_probable_sp"},
                "projection_rows": [
                    {"Player_ID": "1", "Team": "SEA", "Game_ID": "SEA@ATH"},
                    {"Player_ID": "9", "Team": "SEA", "Game_ID": "SEA@ATH"}]}
        venues, _ = mod.resolve_slate_venues(pool, "2026-07-27")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle.json"
            bundle.write_text(json.dumps({"weather": {"Sutter Health Park": {
                "hourly_window": [
                    {"wind_speed_mph": 3.0, "wind_direction_deg": 200,
                     "precip_probability_pct": 5},
                    {"wind_speed_mph": 3.0, "wind_direction_deg": 200,
                     "precip_probability_pct": 80}]}}}), encoding="utf-8")
            args = types.SimpleNamespace(bundle=str(bundle))
            f5, report = mod.build_f5_map(pool, args, venues)
        entry = report["f5_by_team"]["SEA"]
        self.assertEqual(entry["delay"]["level"], "high")
        self.assertAlmostEqual(entry["delay"]["pitcher_factor"], 0.85)
        self.assertAlmostEqual(f5["9"], 0.85)
        self.assertEqual(report["delay_risk_by_team"]["SEA"]["postponement_risk"],
                         "medium")
        self.assertAlmostEqual(report["game_exposure_caps"]["SEA"], 0.25)

    def test_delay_risk_reads_the_worst_hour_not_the_middle_one(self):
        """A shower an hour after first pitch shortens the same starter's outing.
        The middle hour, which is what the wind read uses, cannot see it."""
        mod = self._module()
        pool = {"team_by_player_id": {"1": "SEA"}, "pitcher_roles": {},
                "projection_rows": [{"Player_ID": "1", "Team": "SEA",
                                     "Game_ID": "SEA@ATH"}]}
        venues, _ = mod.resolve_slate_venues(pool, "2026-07-27")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle.json"
            bundle.write_text(json.dumps({"weather": {"Sutter Health Park": {
                "hourly_window": [{"precip_probability_pct": 0},
                                  {"precip_probability_pct": 0},
                                  {"precip_probability_pct": 65}]}}}),
                encoding="utf-8")
            _, report = mod.build_f5_map(pool, types.SimpleNamespace(bundle=str(bundle)),
                                         venues)
        self.assertEqual(report["delay_risk_by_team"]["SEA"]["delay_risk"], "high")

    # -- the wind gate ------------------------------------------------------

    def test_a_temporary_roof_takes_wind_like_any_other_open_park(self):
        """The gate tested ``roof_type == "outdoor"`` while the library's own
        ``OUTDOOR_ROOF_TYPES`` also holds "temporary". Sutter Health Park is the
        only temporary roof on the schedule, and it is the most wind-sensitive
        park there is: sensitivity HIGH, threshold 8mph.

        Sabotage check: put the ``== "outdoor"`` gate back and wind_row is None,
        failing every assertion below.
        """
        mod = self._module()
        from mlb_engine.intake.slate_intake_manager import OUTDOOR_ROOF_TYPES
        self.assertIn("temporary", OUTDOOR_ROOF_TYPES)
        pool = {"team_by_player_id": {"1": "ATH"}, "pitcher_roles": {},
                "projection_rows": [{"Player_ID": "1", "Team": "ATH",
                                     "Game_ID": "SEA@ATH"}]}
        venues, _ = mod.resolve_slate_venues(pool, "2026-07-27")
        self.assertEqual(venues["SEA@ATH"]["roof_type"], "temporary")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle.json"
            bundle.write_text(json.dumps({"weather": {"Sutter Health Park": {
                "hourly_window": [{"wind_speed_mph": 15.0,
                                   "wind_direction_deg": 235,
                                   "precip_probability_pct": 0}] * 3}}}),
                encoding="utf-8")
            f5, report = mod.build_f5_map(pool, types.SimpleNamespace(bundle=str(bundle)),
                                          venues)
        wind = report["f5_by_team"]["ATH"]["wind"]
        self.assertIsNotNone(wind)
        self.assertEqual(wind["direction"], "out")
        self.assertNotAlmostEqual(f5["1"], venues["SEA@ATH"]["park_run_factor"])

    # -- neutral-site overrides --------------------------------------------

    def test_a_neutral_site_row_changes_the_venue_on_the_production_path(self):
        """``game_venue_overrides.csv`` had a loader, a resolver and zero callers
        outside its own module, so a Field of Dreams game silently took Target
        Field's park factor, roof and coordinates.

        Sabotage check: stop consulting the overrides in ``resolve_slate_venues``
        and the venue reads "Target Field", failing the first assertion.
        """
        mod = self._module()
        pool = {"team_by_player_id": {"1": "MIN"}, "pitcher_roles": {},
                "projection_rows": [{"Player_ID": "1", "Team": "MIN",
                                     "Game_ID": "PHI@MIN"}]}
        on_date, report = mod.resolve_slate_venues(pool, "2026-08-13")
        self.assertEqual(on_date["PHI@MIN"]["venue"], "Field of Dreams")
        self.assertEqual(on_date["PHI@MIN"]["venue_source"], "game_override")
        off_date, _ = mod.resolve_slate_venues(pool, "2026-08-12")
        self.assertEqual(off_date["PHI@MIN"]["venue"], "Target Field")
        self.assertEqual(off_date["PHI@MIN"]["venue_source"], "home_team_default")
        self.assertEqual([e["game_id"] for e in report["override_manual_required"]],
                         ["PHI@MIN"])

    def test_manual_required_takes_a_neutral_park_factor_not_the_home_park(self):
        """An unapproved special venue is not a licence to reuse the wrong park's
        number. Neutral 1.0, named in the report, is the honest read."""
        mod = self._module()
        pool = {"team_by_player_id": {"1": "MIN"}, "pitcher_roles": {},
                "projection_rows": [{"Player_ID": "1", "Team": "MIN",
                                     "Game_ID": "PHI@MIN"}]}
        venues, _ = mod.resolve_slate_venues(pool, "2026-08-13")
        record = venues["PHI@MIN"]
        self.assertTrue(record["manual_required"])
        self.assertAlmostEqual(record["park_run_factor"], 1.0)
        self.assertEqual(record["park_factor_source"], "override_manual_neutral")
        f5, report = mod.build_f5_map(
            pool, types.SimpleNamespace(bundle=None), venues)
        self.assertAlmostEqual(f5["1"], 1.0)
        self.assertEqual(report["forecast_missing_for_venue"], ["Field of Dreams"])

    def test_f1_and_f5_read_one_venue_resolution(self):
        """Two venue resolutions would be two answers to one question. The park
        factor F1 de-parks with is the same record F5 prices the park from."""
        mod = self._module()
        pool = {"team_by_player_id": {"1": "MIN"}, "pitcher_roles": {},
                "projection_rows": [{"Player_ID": "1", "Team": "MIN",
                                     "Game_ID": "PHI@MIN"}]}
        venues, _ = mod.resolve_slate_venues(pool, "2026-08-12")
        park = venues["PHI@MIN"]["park_run_factor"]
        f5, _ = mod.build_f5_map(pool, types.SimpleNamespace(bundle=None), venues)
        self.assertAlmostEqual(f5["1"], park)
        _, f1_report = mod.build_f1_map(
            pool, {"PHI@MIN": {"total": 9.0}},
            {gid: rec["park_run_factor"] for gid, rec in venues.items()})
        self.assertAlmostEqual(f1_report["park_run_factor_by_team"]["MIN"], park)


class ClaimToolTests(unittest.TestCase):
    """R19: the multi-session claim protocol as one command.

    The contract's primitive is an atomic mkdir; these pin the tool's exit
    codes and bookkeeping around it, against a temp root so no test touches
    the repo's live claims/.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _claim(self, *argv):
        import subprocess
        import sys as _sys
        repo = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [_sys.executable, str(repo / "tools" / "claim.py"),
             "--root", self.root, *argv],
            capture_output=True, text=True, timeout=120)

    def test_take_writes_owner_and_exits_zero(self):
        import json as _json
        proc = self._claim("take", "slate_2026-07-29_1905", "--role", "BUILD",
                           "--scope", "main slate")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        owner = _json.loads(Path(self.root, "claims", "slate_2026-07-29_1905",
                                 "owner.json").read_text(encoding="utf-8"))
        self.assertEqual(owner["role"], "BUILD")
        self.assertIsNone(owner["released_utc"])

    def test_second_take_is_held_exit_2_and_names_the_owner(self):
        self._claim("take", "ledger", "--role", "ARCHIVE", "--date", "2026-07-28")
        proc = self._claim("take", "ledger", "--role", "DEV",
                           "--date", "2026-07-28")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("HELD", proc.stdout)
        self.assertIn("ARCHIVE", proc.stdout)

    def test_release_then_retake_succeeds(self):
        self._claim("take", "engine", "--role", "DEV", "--date", "2026-07-28")
        released = self._claim("release", "engine", "--date", "2026-07-28")
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertTrue(Path(self.root, "claims", "engine_2026-07-28",
                             "RELEASED").exists())
        check = self._claim("check", "engine", "--date", "2026-07-28")
        self.assertEqual(check.returncode, 0)
        self.assertIn("released", check.stdout)
        retake = self._claim("take", "engine", "--role", "DEV",
                             "--date", "2026-07-28")
        self.assertEqual(retake.returncode, 0, retake.stdout)

    def test_sweep_reports_a_stale_held_claim_and_deletes_nothing(self):
        # R110, 2026-08-12: the fixture is backdated in owner.json rather than
        # only in the NAME. `take --date 2020-01-01` writes taken_utc=now, and
        # staleness reads taken_utc first because the name can lie in the
        # direction that costs something: a BUILD session past UTC midnight
        # working the previous ET slate holds a live claim whose name reads
        # yesterday, and sweeping on the name would clear it.
        self._claim("take", "inbox", "--role", "ARCHIVE", "--date", "2020-01-01")
        owner = Path(self.root, "claims", "inbox_2020-01-01", "owner.json")
        payload = json.loads(owner.read_text(encoding="utf-8"))
        payload["taken_utc"] = "2020-01-01T00:00:00Z"
        owner.write_text(json.dumps(payload), encoding="utf-8")
        proc = self._claim("sweep")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("STALE", proc.stdout)
        self.assertIn("inbox_2020-01-01", proc.stdout)
        self.assertTrue(Path(self.root, "claims", "inbox_2020-01-01").exists())

    def test_dirt_blocks_on_foreign_dirt_inside_the_write_set(self):
        proc = self._claim("dirt", "--role", "DEV",
                           "--porcelain", " M tools/preflight_upload.py\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BLOCK", proc.stdout)

    def test_dirt_notes_outside_dirt_and_never_blocks_fragments(self):
        porcelain = ("?? ledger/own_results.json\n"
                     "?? docs/backlog_inbox/2026-07-28_build_note.md\n")
        proc = self._claim("dirt", "--role", "DEV", "--porcelain", porcelain)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("note", proc.stdout)
        self.assertIn("frag", proc.stdout)

    def test_a_beacon_on_a_held_claim_exits_zero_and_says_proceed(self):
        """R24: builds never block builds; the beacon informs, never stops."""
        self._claim("take", "slate_2026-07-29_1905", "--role", "BUILD",
                    "--scope", "first build")
        proc = self._claim("take", "slate_2026-07-29_1905", "--role", "BUILD",
                           "--scope", "second build", "--beacon")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("never block builds", proc.stdout)

    def test_a_held_slate_without_the_beacon_flag_still_reports_held(self):
        """The flag carries the semantics, not the resource name, so mutex
        behavior stays available on any resource."""
        self._claim("take", "slate_2026-07-29_1905", "--role", "BUILD")
        proc = self._claim("take", "slate_2026-07-29_1905", "--role", "BUILD")
        self.assertEqual(proc.returncode, 2)

    def test_docs_instruct_the_tool_not_the_raw_mkdir(self):
        """R19 done-when: SKILL.md and the runbook each instruct one command.

        The raw mkdir procedure stays correct and stays documented in
        CLAUDE.md's contract text; the two operating procedures must name
        the tool, because a protocol that is a procedure gets skipped at
        T-20. This pins the docs to the tool so they cannot drift back.
        """
        repo = Path(__file__).resolve().parents[1]
        skill = (repo / "skills" / "generate-lineups" / "SKILL.md"
                 ).read_text(encoding="utf-8")
        runbook = (repo / "docs" / "cowork_archival_runbook.md"
                   ).read_text(encoding="utf-8")
        for name, text in (("SKILL.md", skill), ("runbook", runbook)):
            self.assertIn("tools/claim.py", text,
                          f"{name} no longer names the claim tool")
            self.assertNotIn("mkdir claims/", text,
                             f"{name} still instructs the raw mkdir")
            self.assertIn("claim.py release", text,
                          f"{name} must instruct release as one command too")


class LateSwapDeliveryNameTests(unittest.TestCase):
    """R21: two late swaps are two files, and the delivered name carries the
    same draftgroup tag the build's mirror uses, so the manifest supersession
    key (contest_type, slate_tag) matches and the swap replaces the parent
    build as "the" delivery for this slate."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        repo = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "late_swap_tool", repo / "tools" / "late_swap.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_name_carries_tag_and_run_suffix(self):
        self.assertEqual(
            self.mod.lateswap_dest_name("2138_3g", "20260728T120000Z_1dbcfc3b"),
            "DKEntries_lateswap_2138_3g_1dbcfc3b.csv")

    def test_fallbacks_when_tag_or_run_id_is_missing(self):
        self.assertEqual(self.mod.lateswap_dest_name("", ""),
                         "DKEntries_lateswap_untagged_norun.csv")

    # R29(3): the first argument is the file's resolved postures, not a flat
    # defaults dict. The flat dict was the bug; see
    # SwapControlsInheritanceTests.
    POSTURES = {"900": {"posture": "large_gpp", "contest_shape": "large_wta",
                        "posture_source": "test"}}

    def test_solver_budget_bounds_the_joint_solve(self):
        """R25: the joint MILP's time limit becomes a first-class flag."""
        controls = self.mod.resolve_swap_controls(self.POSTURES, None, 15)
        self.assertEqual(controls["time_limit"], 15.0)
        self.assertEqual(controls["max_shared_players"], 6)

    def test_an_explicit_controls_override_still_wins(self):
        controls = self.mod.resolve_swap_controls(
            self.POSTURES, {"time_limit": 25}, 15)
        self.assertEqual(controls["time_limit"], 25)


class BankCacheMergeOnSaveTests(unittest.TestCase):
    """R22: the later of two concurrent slices must merge the earlier one's
    work instead of discarding it, and one session's stale-purge must not
    erase another session's live work from the shared file."""

    @staticmethod
    def _roster(tag):
        return [f"{tag}{i}" for i in range(10)]

    def test_two_writers_union_on_disk(self):
        import tempfile
        from mlb_engine.optimize.bank_cache import BankCache
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            a = BankCache(path)
            b = BankCache(path)
            a.add(self._roster("a"), 1.0, job="pa|TA||SIG1")
            a.attempted.add("pa|TA||SIG1")
            b.add(self._roster("b"), 2.0, job="pb|TB||SIG2")
            b.attempted.add("pb|TB||SIG2")
            b.save()
            a.save()  # the last writer used to win; now it merges
            merged = BankCache(path)
            rosters = {tuple(c["roster"]) for c in merged.candidates}
            self.assertIn(tuple(self._roster("a")), rosters)
            self.assertIn(tuple(self._roster("b")), rosters)
            self.assertEqual(merged.attempted, {"pa|TA||SIG1", "pb|TB||SIG2"})

    def test_memory_stays_the_writers_own_view(self):
        import tempfile
        from mlb_engine.optimize.bank_cache import BankCache
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            a = BankCache(path)  # loads before b writes, like a real race
            b = BankCache(path)
            b.add(self._roster("b"), 2.0, job="pb|TB||SIG2")
            b.save()
            a.add(self._roster("a"), 1.0, job="pa|TA||SIG1")
            a.save()
            self.assertEqual(len(a.candidates), 1)  # a serves only its own work
            on_disk = {tuple(c["roster"]) for c in BankCache(path).candidates}
            self.assertEqual(on_disk, {tuple(self._roster("a")),
                                       tuple(self._roster("b"))})

    def test_a_purge_no_longer_erases_the_other_sessions_work_on_disk(self):
        import tempfile
        from mlb_engine.optimize.bank_cache import BankCache
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            seed = BankCache(path)
            seed.add(self._roster("a"), 1.0, job="pa|TA||SIG1")
            seed.attempted.add("pa|TA||SIG1")
            seed.add(self._roster("b"), 2.0, job="pb|TB||SIG2")
            seed.attempted.add("pb|TB||SIG2")
            seed.save()
            purger = BankCache(path)
            purger.drop_stale_jobs("SIG1")  # memory keeps SIG1 only
            self.assertEqual(len(purger.candidates), 1)
            purger.save()
            after = BankCache(path)
            rosters = {tuple(c["roster"]) for c in after.candidates}
            self.assertIn(tuple(self._roster("b")), rosters,
                          "the purge leaked to disk and erased SIG2's work")
            self.assertIn("pb|TB||SIG2", after.attempted)


class BankCacheBucketingTests(unittest.TestCase):
    """R101. A targeted slice must not discard the bank it is extending.

    ``late_swap.py`` calls ``extend_bank`` once for the general bank and then
    once per pinned entry, each with that entry's own ``excludes``. The exclude
    set was folded into ONE conditions signature and ``drop_stale_jobs`` deleted
    every candidate carrying a different one, so each targeted slice wiped the
    previous slices and the general bank with them: measured on
    ``outputs/2026-08-03/_swap1..9.log``, a cache of 1,007 candidates handed the
    joint solve 8.

    The split these tests pin: the PROJECTION half of the signature still
    invalidates destructively, because a changed projection means the stored
    answer is an answer to a different question (the 2026-07-26 incident in
    ``_job_key``'s docstring). The per-request half -- excludes and stack bounds
    -- only NARROWS, so it buckets and never destroys. Safe because per-entry
    legality is enforced downstream in ``_entry_candidate_compatible``: the bank
    is a superset, the allocator is the filter.
    """

    @staticmethod
    def _pinned(frame, team):
        """A locked_slot_assignments dict pinning one hitter slot on `team`."""
        hitters = frame[(frame["Position"] == "C") & (frame["Team"] == team)]
        return {"C": str(hitters.iloc[0]["Player_ID"])}

    @staticmethod
    def _team_ids(frame, team):
        return [str(p) for p in frame[frame["Team"] == team]["Player_ID"]]

    def _swap_shaped_slices(self, tmp):
        """The real call shape: one general slice, then two targeted ones whose
        exclude sets differ, exactly as tools/late_swap.py:613 and :635 run."""
        frame = diverse_projection_frame()
        cache = bank_cache.BankCache(Path(tmp) / "bank.json")
        general = bank_cache.extend_bank(cache, frame, time_budget_s=25,
                                         max_candidates=8)
        pin_a = self._pinned(frame, "T1")
        excl_a = [p for p in self._team_ids(frame, "T3")
                  if p not in set(pin_a.values())]
        targeted_a = bank_cache.extend_bank(
            cache, frame, time_budget_s=25, locked_slot_assignments=pin_a,
            excludes=excl_a)
        pin_b = self._pinned(frame, "T2")
        excl_b = [p for p in self._team_ids(frame, "T4")
                  if p not in set(pin_b.values())]
        targeted_b = bank_cache.extend_bank(
            cache, frame, time_budget_s=25, locked_slot_assignments=pin_b,
            excludes=excl_b)
        return cache, frame, general, targeted_a, targeted_b

    def test_as_candidates_serves_the_general_bank_plus_every_targeted_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, frame, general, a, b = self._swap_shaped_slices(tmp)
            for report, label in ((general, "general"), (a, "targeted a"),
                                  (b, "targeted b")):
                self.assertGreater(report["built_this_slice"], 0,
                                   f"the {label} slice built nothing, so this "
                                   f"test cannot measure what survives it")
            self.assertEqual(a["superseded_jobs_dropped"], 0,
                             "a targeted slice discarded the general bank")
            self.assertEqual(b["superseded_jobs_dropped"], 0,
                             "a targeted slice discarded the previous slices")
            expected = (general["built_this_slice"] + a["built_this_slice"]
                        + b["built_this_slice"])
            served = cache.as_candidates(frame, requested_n=3)
            self.assertEqual(len(served), expected,
                             "the joint solve is handed fewer candidates than "
                             "the slices built")
            self.assertEqual(len(cache), expected)
            self.assertEqual(cache.last_payload_report["candidates"], len(served))

    def test_the_report_counts_the_union_it_will_serve(self):
        """`bank: N candidates` and `candidate scoring: N scored` are the two
        numbers that misled the operator for twenty minutes. They agree now."""
        with tempfile.TemporaryDirectory() as tmp:
            cache, frame, general, a, b = self._swap_shaped_slices(tmp)
            self.assertEqual(b["total_candidates"], len(cache))
            served = cache.as_candidates(frame, requested_n=3)
            self.assertEqual(b["total_candidates"], len(served))
            self.assertEqual(cache.last_payload_report["scored"]
                             + cache.last_payload_report["scoring_failed"],
                             len(served),
                             "every served candidate is either scored or "
                             "counted as a scoring failure")
            self.assertEqual(b["conditions_buckets_live"], 3)
            self.assertEqual(general["projection_digest"], a["projection_digest"])
            self.assertEqual(a["projection_digest"], b["projection_digest"])
            self.assertNotEqual(general["conditions_signature"],
                                a["conditions_signature"])
            self.assertNotEqual(a["conditions_signature"],
                                b["conditions_signature"])

    def test_buckets_do_not_double_count_a_roster(self):
        """Two buckets can legitimately hold the same ten players in the same
        slots; the solve must see one candidate, not two."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache = bank_cache.BankCache(path)
            roster = [str(i) for i in range(10)]
            cache.candidates = [
                {"roster": list(roster), "objective": 1.0, "job": "p|T|" "|SIG1"},
                {"roster": list(roster), "objective": 2.0, "job": "p|T||SIG2"},
            ]
            cache._seen = {tuple(roster)}
            served = cache.as_candidates()
            self.assertEqual(len(served), 1)
            self.assertEqual(cache.last_payload_report["duplicate_rosters_dropped"], 1)
            # And a reload repairs the stored duplicate rather than serving it.
            cache.save()
            self.assertEqual(len(bank_cache.BankCache(path).candidates), 1)

    def test_a_projection_change_still_invalidates_destructively(self):
        """The 2026-07-26 incident: a rebuild after the DK Status filter landed
        certified a pitcher with no role, served from a cache built before the
        filter existed. Bucketing must not resurrect that."""
        with tempfile.TemporaryDirectory() as tmp:
            frame = diverse_projection_frame()
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            first = bank_cache.extend_bank(cache, frame, time_budget_s=25,
                                           max_candidates=6)
            self.assertGreater(len(cache), 0)
            enriched = frame.copy()
            enriched.loc[enriched["Position"] == "P", "Ceiling"] = 44.0
            after = bank_cache.extend_bank(cache, enriched, time_budget_s=25,
                                           max_candidates=6)
            self.assertNotEqual(first["projection_digest"],
                                after["projection_digest"])
            self.assertGreaterEqual(after["superseded_jobs_dropped"], 1,
                                    "an enrichment pass must still purge the "
                                    "candidates built before it")
            for entry in cache.candidates:
                self.assertTrue(
                    str(entry["job"]).endswith(after["conditions_signature"]),
                    "a candidate built under the old projections survived")

    def test_a_narrowed_bucket_cannot_reach_an_entry_it_violates(self):
        """The guard that makes bucketing safe, tested on its own.

        A candidate built under entry A's exclude set is now visible to entry B.
        `_entry_candidate_compatible` is what stops B from being assigned it, so
        the union is a superset of legal candidates and never a wider legal set.
        """
        roster_bad = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "X"]
        roster_good = ["L", "P2", "C1", "B1", "B2", "B3", "B4", "B5", "B6", "B7"]
        team_map = {pid: "CCC" for pid in set(roster_bad + roster_good)}
        team_map.update({"L": "AAA", "X": "AAA"})
        # Entry 1 has locked AAA and may not take a NEW Yankee; entry 2 has not.
        entry_one = {
            "entry_id": "1", "contest_id": "x", "contest_shape": "large_wta",
            "locked_slot_assignments": {"P1": "L"}, "locked_player_ids": ["L"],
            "excluded_new_teams": ["AAA"], "player_team_by_id": team_map,
        }
        entry_two = {
            "entry_id": "2", "contest_id": "x", "contest_shape": "large_wta",
            "player_team_by_id": team_map,
        }
        bank = [candidate("from_other_bucket", roster_bad, 100),
                candidate("legal_here", roster_good, 99)]
        self.assertFalse(_entry_candidate_compatible(bank[0], dict(entry_one)))
        self.assertTrue(_entry_candidate_compatible(bank[1], dict(entry_one)))
        self.assertTrue(_entry_candidate_compatible(bank[0], dict(entry_two)))
        result = select_and_assign_entries(
            bank, [dict(entry_one), dict(entry_two)],
            {"max_shared_players": 10})
        self.assertTrue(result["passed"], result.get("errors"))
        chosen = {row["entry_id"]: row["candidate_id"] for row in result["assignments"]}
        self.assertEqual(chosen["1"], "legal_here",
                         "an entry was assigned a candidate built under another "
                         "entry's excludes that its own excludes forbid")


class MinerPaidPlacesTests(unittest.TestCase):
    """R30(a). Nothing in the archival path could write paid_places.

    No flag, no own_results field, and the only consumer
    (posture_allocator.classify_tier) reads it off a contest dict the archival
    path never populated -- so every archived contest classified UNRESOLVED and a
    rank-1 satellite finish could not be graded as a seat. Ben's entry-history
    export has carried the numbers since 2026-07-29, parked in
    data/reference/dk_contest_paid_places.json because no CLI could read them.
    The item's done-when is both halves: a mined record carries paid_places, and
    posture_allocator stops returning UNRESOLVED.
    """

    @staticmethod
    def _mined(field_size=53, ranks=(1, 7)):
        entries = []
        for i in range(field_size):
            entries.append({"entry_id": str(9000 + i), "rank": i + 1,
                            "points": 100.0 - i, "players_norm": [f"p{i}"]})
        return {"contest_id": "192892126",
                "meta": {"entries_total": field_size, "winning_points": 100.0},
                "entries": entries}, [str(9000 + r - 1) for r in ranks]

    def test_a_mined_record_carries_paid_places_and_its_observed_breadth(self):
        from mlb_engine.field import field_miner as fm
        mined, ids = self._mined()
        summary = fm.summarize_own_entries(mined, ids, entry_fee=0.25, paid_places=1)
        self.assertEqual(summary["paid_places"], 1)
        self.assertEqual(summary["payout_breadth_observed"], round(1 / 53, 4))
        # rank 1 of the two own entries is inside a one-place payout, rank 7 is not
        self.assertEqual(summary["cashed_entries"], 1)

    def test_omitting_it_records_unknown_rather_than_a_guess(self):
        from mlb_engine.field import field_miner as fm
        mined, ids = self._mined()
        summary = fm.summarize_own_entries(mined, ids, entry_fee=0.25)
        self.assertIsNone(summary["paid_places"])
        self.assertIsNone(summary["payout_breadth_observed"])
        self.assertIsNone(summary["cashed_entries"])

    def test_posture_allocator_stops_returning_unresolved(self):
        """The item's done-when, driven end to end rather than asserted about."""
        from mlb_engine.field import field_miner as fm
        from mlb_engine.allocate.posture_allocator import classify_tier
        mined, ids = self._mined()

        before = classify_tier({"field_size": 53})
        self.assertEqual(before["tier"], "UNRESOLVED")

        summary = fm.summarize_own_entries(mined, ids, paid_places=1)
        after = classify_tier({"field_size": summary["field_size"],
                               "paid_places": summary["paid_places"]})
        self.assertNotEqual(after["tier"], "UNRESOLVED")
        # paid_places == 1 is winner-take-all, which is what a one-seat satellite is
        self.assertEqual(after["tier"], "A")
        self.assertIn("winner-take-all", after["reason"])

    def test_a_no_match_record_still_reports_the_paid_line(self):
        # The early return had no paid_places key at all, so a contest whose own
        # ids did not resolve looked like a contest with no paid line.
        from mlb_engine.field import field_miner as fm
        mined, _ids = self._mined()
        summary = fm.summarize_own_entries(mined, ["not-an-entry"], paid_places=3)
        self.assertEqual(summary["matched"], 0)
        self.assertEqual(summary["paid_places"], 3)

    # -- the bulk loader ---------------------------------------------------

    def _table(self, tmp, payload):
        path = Path(tmp) / "paid.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_the_bulk_file_reads_both_shapes(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            wrapped = self._table(tmp, {"_label": "x", "contests": {"1": {"paid_places": 4}}})
            self.assertEqual(fm.paid_places_from_file(wrapped, "1")[0], 4)
            flat = self._table(tmp, {"1": {"paid_places": 5}})
            self.assertEqual(fm.paid_places_from_file(flat, "1")[0], 5)

    def test_every_unreadable_case_says_which_one_it_was(self):
        """A parked file nothing reads is the state this closes, so "the file did
        not carry it" and "the file was never read" have to be distinguishable."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nope.json")
            self.assertEqual(fm.paid_places_from_file(missing, "1")[0], None)
            self.assertIn("does not exist", fm.paid_places_from_file(missing, "1")[1])

            bad = Path(tmp) / "bad.json"; bad.write_text("{not json", encoding="utf-8")
            self.assertIn("unreadable", fm.paid_places_from_file(str(bad), "1")[1])

            table = self._table(tmp, {"contests": {"1": {"paid_places": 4}}})
            self.assertIn("not in", fm.paid_places_from_file(table, "2")[1])
            self.assertIn("no contest id", fm.paid_places_from_file(table, "")[1])

            nofield = self._table(tmp, {"contests": {"1": {"field_size": 10}}})
            self.assertIn("carries no paid_places",
                          fm.paid_places_from_file(nofield, "1")[1])

            junk = self._table(tmp, {"contests": {"1": {"paid_places": "many"}}})
            self.assertIn("non-integer", fm.paid_places_from_file(junk, "1")[1])

    def test_the_parked_export_resolves_a_real_archived_contest(self):
        """The file has existed since 2026-07-29 with 100 contests in it and no
        code path could read it. Pinned against the real file, not a fixture."""
        from mlb_engine.field import field_miner as fm
        parked = REPO / "data" / "reference" / "dk_contest_paid_places.json"
        if not parked.exists():
            self.skipTest("the parked paid-places export is not staged")
        value, note = fm.paid_places_from_file(str(parked), "192784475")
        self.assertEqual(value, 1)
        self.assertIn("dk_contest_paid_places.json", note)


class MinerMoneyHonestyTests(unittest.TestCase):
    """R30(b) and R50: the two ends of the same lie about fees.

    (b) --entry-fee and --winnings are consumed only inside the own-results
    stage, which runs only when own entry ids resolve. On 6 of 10 backfilled
    dates no upload manifest existed, so the mine printed no own-results line,
    exited 0, and left entry_fee null with nothing said. It cost ARCHIVE a full
    pass. (R50) At the other end, a contest mined WITH a fee still emitted "fees
    and winnings not supplied" whenever the net line was absent, recording the
    false half in the permanent archive for 94 contests.
    """

    HEADER = ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup",
              "", "Player", "Roster Position", "%Drafted", "FPTS"]
    CLASSIC = ("P Gerrit Cole P Tarik Skubal C Cal Raleigh 1B Matt Olson "
               "2B Ketel Marte 3B Jose Ramirez SS Bobby Witt Jr. OF Aaron Judge "
               "OF Juan Soto OF Kyle Tucker")

    def _standings_csv(self, tmp):
        path = Path(tmp) / "contest-standings-777777777.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(self.HEADER)
            for i in range(6):
                writer.writerow([str(i + 1), str(9000 + i), f"u{i}", "0",
                                 f"{120 - i}.5", self.CLASSIC, "", "Aaron Judge",
                                 "OF", "41.2%", "18.5"])
        return path

    def _run(self, tmp, *extra):
        # --registry into tmp: R94 made accumulation the default, so a bare mine
        # would otherwise write the real data/reference registry from a test.
        return subprocess.run(
            [sys.executable, "-m", "mlb_engine.field.field_miner",
             "--standings", str(self._standings_csv(tmp)),
             "--contest-id", "777777777",
             "--registry", str(Path(tmp) / "reg.json"), *extra],
            capture_output=True, text=True, cwd=str(REPO))

    def test_a_money_flag_with_no_own_entries_is_an_error_not_a_no_op(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            done = self._run(tmp, "--entry-fee", "0.25")
            self.assertEqual(done.returncode, fm.EXIT_MONEY_WITHOUT_OWN_ENTRIES,
                             done.stdout + done.stderr)
            self.assertIn("--entry-fee", done.stderr)
            self.assertIn("upload_manifest.json", done.stderr,
                          "the error must name the missing manifest")
            self.assertIn("--my-entry-ids", done.stderr,
                          "and the way out of it")

    def test_every_money_flag_is_covered_and_named(self):
        from mlb_engine.field import field_miner as fm
        for flag, value in (("--entry-fee", "0.25"), ("--winnings", "1.00"),
                            ("--paid-places", "1")):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                done = self._run(tmp, flag, value)
                self.assertEqual(done.returncode,
                                 fm.EXIT_MONEY_WITHOUT_OWN_ENTRIES, done.stderr)
                self.assertIn(flag, done.stderr)

    def test_a_mine_with_no_money_flags_still_exits_clean(self):
        # The guard must not fire on the ordinary no-money mine, which is most of
        # them.
        with tempfile.TemporaryDirectory() as tmp:
            done = self._run(tmp)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    # -- R50: the block reports what it actually has ------------------------

    @staticmethod
    def _own(**kw):
        base = {"matched": 2, "field_size": 53, "best_rank": 1,
                "best_finish_percentile": 100.0, "median_finish_percentile": 92.0,
                "best_points": 120.5, "winning_points": 120.5,
                "own_lineups_duplicated_by_field": 0,
                "max_copies_of_an_own_lineup": 1, "entry_fee": None,
                "fees_total": None, "winnings_total": None, "net": None,
                "paid_places": None, "payout_breadth_observed": None,
                "cashed_entries": None}
        base.update(kw)
        return base

    def _block(self, own):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            standings = fm.parse_standings_export(str(self._standings_csv(tmp)))
            mined = fm.mine_contest(standings, None, contest_id="777777777")
        mined["own_results"] = own
        block = fm.emit_ledger_block(mined)
        return block if isinstance(block, str) else "\n".join(block)

    def test_a_supplied_fee_is_never_reported_as_not_supplied(self):
        text = self._block(self._own(entry_fee=0.10, fees_total=0.50))
        self.assertIn("fee $0.10/entry, $0.50 total", text)
        self.assertIn("winnings not captured", text)
        self.assertNotIn("fees and winnings not supplied", text)

    def test_neither_supplied_still_says_so(self):
        text = self._block(self._own())
        self.assertIn("neither fee nor winnings supplied", text)

    def test_both_supplied_reports_the_net_line(self):
        text = self._block(self._own(entry_fee=0.10, fees_total=0.50,
                                     winnings_total=15.0, net=14.5))
        self.assertIn("net $14.50", text)
        self.assertNotIn("not captured", text)

    def test_winnings_without_a_fee_is_its_own_sentence(self):
        text = self._block(self._own(winnings_total=15.0))
        self.assertIn("fee not supplied", text)
        self.assertNotIn("winnings not captured", text)

    def test_the_paid_line_reaches_the_permanent_block(self):
        # R30(a). What makes a rank-1 finish gradeable as a seat belongs in the
        # archived block, not only in JSON.
        text = self._block(self._own(entry_fee=0.25, fees_total=0.50,
                                     paid_places=1, payout_breadth_observed=0.0189,
                                     cashed_entries=1))
        self.assertIn("Paid places 1 of 53", text)
        self.assertIn("observed breadth 0.0189", text)
        self.assertIn("1 own entry inside the paid line", text)


class MinerEdgeIntegrityTests(unittest.TestCase):
    """R74. Three ways the archival tooling failed silently at its edges."""

    def test_a_mine_with_no_contest_identity_is_refused_not_placeholdered(self):
        """R74(a). `.get(key, "unknown")` never defaults when the key EXISTS as
        None, which is what a mine with no winner produces. cid came out None,
        contests_mined accumulated JSON nulls, and a SECOND no-id mine was
        silently skipped as already-mined because None was already in the list."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            registry = str(Path(tmp) / "reg.json")
            mined = {"contest_id": "", "meta": {"winning_entry_id": None},
                     "entries": [], "diagnostics": {}}
            with self.assertRaisesRegex(ValueError, "no contest identity"):
                fm.update_registry(registry, mined)
            self.assertFalse(Path(registry).exists(),
                             "a refused update must not create a registry")

    def test_a_winner_entry_id_still_identifies_a_mine_with_no_contest_id(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            registry = str(Path(tmp) / "reg.json")
            mined = {"contest_id": "", "meta": {"winning_entry_id": "88881111"},
                     "entries": [], "diagnostics": {}}
            reg = fm.update_registry(registry, mined)
            self.assertEqual(reg["contests_mined"], ["88881111"])
            self.assertNotIn(None, reg["contests_mined"])

    def test_two_identityless_mines_cannot_collide_because_neither_is_accepted(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            registry = str(Path(tmp) / "reg.json")
            fm.update_registry(registry, {"contest_id": "111111111", "meta": {},
                                          "entries": [], "diagnostics": {}})
            for _ in range(2):
                with self.assertRaises(ValueError):
                    fm.update_registry(registry, {"contest_id": None, "meta": {},
                                                  "entries": [], "diagnostics": {}})
            reg = json.loads(Path(registry).read_text(encoding="utf-8"))
            self.assertEqual(reg["contests_mined"], ["111111111"])

    # -- R74(b): the inbox contest-ID regex --------------------------------

    def test_the_inbox_id_regex_is_anchored(self):
        """R74(b). Unanchored, the first 9 digits of a longer run (an entry id, a
        timestamp) could yield a real entered contest id and mark it pulled --
        the one direction this tool exists to prevent."""
        sys.path.insert(0, str(REPO / "tools"))
        import awaiting_standings as aw

        self.assertEqual(aw.INBOX_ID_RE.search("contest-standings-192892126").group(1),
                         "192892126")
        # a 10+ digit run is an entry id or a timestamp, not a contest id
        for text in ("1928921260", "01928921261", "20260805123456"):
            with self.subTest(text=text):
                self.assertIsNone(aw.INBOX_ID_RE.search(text),
                                  f"{text} yielded a contest id")
        # embedded in a longer name but still exactly nine digits
        self.assertEqual(aw.INBOX_ID_RE.search("x_192892126_y").group(1), "192892126")

    # -- R74(c): blank reserved rows ---------------------------------------

    def _entries_csv(self, path, rows):
        header = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee",
                  "P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)

    def test_a_blank_reserved_row_does_not_enroll_its_contest(self):
        """R74(c). scan_entered's own docstring says "every Contest ID on a FILLED
        entry row"; it read every row with a Contest ID cell, so the reserved rows
        a DKEntries template carries enrolled never-entered contests."""
        sys.path.insert(0, str(REPO / "tools"))
        import awaiting_standings as aw
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs" / "2026-08-05"
            outputs.mkdir(parents=True)
            self._entries_csv(outputs / "DKEntries.csv", [
                # a real entered row: entry id plus a roster
                ["5157463016", "Entered Contest", "111111111", "$0.25"]
                + [f"P{i}" for i in range(10)],
                # a reserved row: contest columns filled, roster empty
                ["", "Reserved Contest", "222222222", "$0.25"] + [""] * 10,
                # and one DK sometimes writes with an entry id but no roster
                ["5157463017", "Reserved With Id", "333333333", "$0.25"] + [""] * 10,
            ])
            entered, invalid = aw.scan_entered(Path(tmp) / "outputs")
            self.assertIn("111111111", entered)
            self.assertNotIn("222222222", entered)
            self.assertNotIn("222222222", invalid)
            self.assertNotIn("333333333", entered,
                             "an entry id with an empty roster is still reserved")

    def test_an_unrecognized_header_shape_degrades_instead_of_emptying(self):
        # A file with no roster columns falls back to the Entry ID alone rather
        # than rejecting every row, so an unexpected DK template does not silently
        # empty the pull list.
        sys.path.insert(0, str(REPO / "tools"))
        import awaiting_standings as aw
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs" / "2026-08-05"
            outputs.mkdir(parents=True)
            path = outputs / "DKEntries.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee"])
                writer.writerow(["5157463016", "Entered", "111111111", "$0.25"])
                writer.writerow(["", "Reserved", "222222222", "$0.25"])
            entered, _invalid = aw.scan_entered(Path(tmp) / "outputs")
            self.assertIn("111111111", entered)
            self.assertNotIn("222222222", entered)


class MinerOutputPathTests(unittest.TestCase):
    """R93. The `--json` write was the LAST thing main did, so a nonexistent
    archive-date directory failed the mine after its side effects had landed.
    All 30 mines of the 08-05/06 tranche hit this. The defect is the ordering:
    an operation that appends to shared records cannot discover an unusable
    output path at the end."""

    def _standings_csv(self, tmp):
        path = Path(tmp) / "contest-standings-777777777.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(MinerMoneyHonestyTests.HEADER)
            for i in range(6):
                writer.writerow([str(i + 1), str(9000 + i), f"u{i}", "0",
                                 f"{120 - i}.5", MinerMoneyHonestyTests.CLASSIC,
                                 "", "Aaron Judge", "OF", "41.2%", "18.5"])
        return path

    def _run(self, tmp, *extra):
        # --registry into tmp on every invocation: the mine accumulates by
        # default (R94), and a test must never write the real registry.
        return subprocess.run(
            [sys.executable, "-m", "mlb_engine.field.field_miner",
             "--standings", str(self._standings_csv(tmp)),
             "--contest-id", "777777777",
             "--registry", str(Path(tmp) / "reg.json"), *extra],
            capture_output=True, text=True, cwd=str(REPO))

    def test_a_missing_json_parent_directory_is_created(self):
        """The concrete fix: the first mine into a fresh archive date works."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "archive" / "2026-08-05" / "mined_777777777.json"
            self.assertFalse(target.parent.exists())
            done = self._run(tmp, "--json", str(target))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(target.exists(), "the mine's JSON never landed")
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["contest_id"], "777777777")

    def test_an_unusable_json_path_fails_before_any_side_effect(self):
        """The general rule, and the one that actually matters: when the path
        cannot be made usable, NOTHING is written -- no own-results row, no
        ledger fragment, no registry entry -- so a re-run cannot double-append."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            # a FILE where the parent directory would have to be
            blocker = Path(tmp) / "not_a_dir"
            blocker.write_text("", encoding="utf-8")
            registry = Path(tmp) / "reg.json"
            done = self._run(tmp, "--json", str(blocker / "mined.json"))
            self.assertEqual(done.returncode, fm.EXIT_OUTPUT_PATH_UNUSABLE,
                             done.stdout + done.stderr)
            self.assertIn("--json destination unusable", done.stderr)
            self.assertFalse(registry.exists(),
                             "the registry was written before the path check")
            self.assertNotIn("ledger block written", done.stdout)
            self.assertNotIn("own results appended", done.stdout)

    def test_the_exit_code_is_distinct_from_every_structural_code(self):
        # A scheduled task has to tell "I cannot write there" from "this is the
        # wrong salary file" without parsing prose.
        from mlb_engine.field import field_miner as fm
        codes = [fm.EXIT_OK, fm.EXIT_WRONG_SALARY_FILE, fm.EXIT_PARSED_NOTHING,
                 fm.EXIT_MOSTLY_UNPARSED, fm.EXIT_STRUCTURAL_OTHER,
                 fm.EXIT_MONEY_WITHOUT_OWN_ENTRIES, fm.EXIT_OUTPUT_PATH_UNUSABLE]
        self.assertEqual(len(codes), len(set(codes)))

    def test_check_output_path_names_each_refusal(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(fm.check_output_path(str(root / "a" / "b" / "m.json")))
            self.assertTrue((root / "a" / "b").is_dir(), "the parent was not created")
            (root / "plain").write_text("", encoding="utf-8")
            self.assertIn("not a directory",
                          fm.check_output_path(str(root / "plain" / "m.json")))
            self.assertIn("is a directory", fm.check_output_path(str(root / "a")))


class MinerSalaryJoinFloorTests(unittest.TestCase):
    """R49(3). `contest_type_mismatch` caught the Showdown-file-on-a-Classic-
    export case; nothing caught the SAME-TYPE wrong slate. Five 1910_4g contests
    were mined against the 1235_5g Classic file on 2026-08-08, joined 0.0%, and
    archived as coverage "full" at exit 0 with every stack_pattern empty."""

    HEADER = MinerMoneyHonestyTests.HEADER
    CLASSIC = MinerMoneyHonestyTests.CLASSIC
    SALARY_HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position",
                     "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame"]

    def _standings_csv(self, tmp):
        path = Path(tmp) / "contest-standings-777777777.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(self.HEADER)
            for i in range(6):
                writer.writerow([str(i + 1), str(9000 + i), f"u{i}", "0",
                                 f"{120 - i}.5", self.CLASSIC, "", "Aaron Judge",
                                 "OF", "41.2%", "18.5"])
        return path

    def _salary_csv(self, tmp, names, name="DKSalaries.csv"):
        """A Classic salary file naming `names`. A wrong-slate file is simply one
        whose players are not the players the standings drafted."""
        path = Path(tmp) / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(self.SALARY_HEADER)
            for i, (pos, nm, team) in enumerate(names):
                writer.writerow([pos, f"{nm} ({7000 + i})", nm, str(7000 + i),
                                 pos, "5000", "AAA@BBB 07:05PM ET", team, "8.0"])
        return path

    RIGHT_SLATE = [("P", "Gerrit Cole", "NYY"), ("P", "Tarik Skubal", "DET"),
                   ("C", "Cal Raleigh", "SEA"), ("1B", "Matt Olson", "ATL"),
                   ("2B", "Ketel Marte", "ARI"), ("3B", "Jose Ramirez", "CLE"),
                   ("SS", "Bobby Witt Jr.", "KC"), ("OF", "Aaron Judge", "NYY"),
                   ("OF", "Juan Soto", "NYM"), ("OF", "Kyle Tucker", "CHC")]
    WRONG_SLATE = [("P", "Zack Wheeler", "PHI"), ("P", "Logan Webb", "SF"),
                   ("C", "Will Smith", "LAD"), ("1B", "Freddie Freeman", "LAD"),
                   ("2B", "Marcus Semien", "TEX"), ("3B", "Rafael Devers", "BOS"),
                   ("SS", "Corey Seager", "TEX"), ("OF", "Mookie Betts", "LAD"),
                   ("OF", "Ronald Acuna Jr.", "ATL"), ("OF", "Kyle Schwarber", "PHI")]

    def _mine(self, tmp, salary_rows):
        from mlb_engine.field import field_miner as fm
        standings = fm.parse_standings_export(str(self._standings_csv(tmp)))
        smap = fm.load_salary_map(str(self._salary_csv(tmp, salary_rows)))
        return fm.mine_contest(standings, smap, contest_id="777777777")

    def test_the_right_slate_still_mines_clean(self):
        """The floor must not fire on the ordinary full-coverage mine."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            mined = self._mine(tmp, self.RIGHT_SLATE)
            g = mined["diagnostics"]
            self.assertEqual(g["salary_join_rate_pct"], 100.0)
            self.assertFalse(g["salary_join_collapsed"])
            self.assertTrue(g["parse_structural_ok"])
            self.assertEqual(mined["coverage"], "full")
            block = fm.emit_ledger_block(mined)
            text = block if isinstance(block, str) else "\n".join(block)
            self.assertNotIn("**unavailable**", text)

    def test_a_same_type_wrong_slate_file_no_longer_passes_as_full(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            mined = self._mine(tmp, self.WRONG_SLATE)
            g = mined["diagnostics"]
            # the failure this gate exists for: right contest type, 0% join
            self.assertFalse(g["contest_type_mismatch"],
                             "both files are Classic; type mismatch cannot catch this")
            self.assertEqual(g["salary_join_rate_pct"], 0.0)
            self.assertTrue(g["salary_join_collapsed"])
            self.assertFalse(g["parse_structural_ok"],
                             "a 0% join archived as coverage 'full' before R49(3)")
            self.assertEqual(fm.structural_exit_code(g), fm.EXIT_WRONG_SALARY_FILE)
            self.assertIn("WRONG SALARY FILE", g["verification_note"])
            self.assertIn("standings_only", g["verification_note"],
                          "the note must name the honest alternative")

    def test_the_cli_blocks_and_writes_nothing(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "reg.json"
            done = subprocess.run(
                [sys.executable, "-m", "mlb_engine.field.field_miner",
                 "--standings", str(self._standings_csv(tmp)),
                 "--salary", str(self._salary_csv(tmp, self.WRONG_SLATE)),
                 "--contest-id", "777777777", "--emit-ledger",
                 "--registry", str(registry)],
                capture_output=True, text=True, cwd=str(REPO))
            self.assertEqual(done.returncode, fm.EXIT_WRONG_SALARY_FILE,
                             done.stdout + done.stderr)
            self.assertIn("BLOCKED", done.stdout)
            self.assertFalse(registry.exists())
            self.assertNotIn("ledger block written", done.stdout)

    def test_forced_through_the_gate_the_salary_tables_are_suppressed(self):
        """--force records the override rather than blocking, so the ONE thing
        that must not happen is a plausible-looking histogram in the archive."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            mined = self._mine(tmp, self.WRONG_SLATE)
            block = fm.emit_ledger_block(mined)
            text = block if isinstance(block, str) else "\n".join(block)
            self.assertIn("**unavailable**", text)
            self.assertIn("different slate's file", text)
            self.assertNotIn("Salary usage:", text)

    def test_the_floor_sits_well_below_the_auto_selection_threshold(self):
        # The two numbers answer different questions and must not be collapsed:
        # 0.95 selects between candidates, 0.50 asks whether this is the slate.
        from mlb_engine.field import field_miner as fm
        self.assertLess(fm.MIN_SALARY_JOIN_RATE, fm.MIN_AUTO_JOIN_RATE)
        self.assertGreater(fm.MIN_SALARY_JOIN_RATE, 0.0,
                           "a floor of 0 is not a floor")


class MinerRegistryDefaultTests(unittest.TestCase):
    """R94. `main` gated the registry update on `--registry`, while the runbook
    says to omit the flag. A runbook-compliant mine therefore never touched the
    registry and said nothing about it; 31 mines of the 2026-08-08 tranche
    skipped accumulation silently. The runbook's wording is load-bearing (a bare
    relative path forked the registry once), so the CODE moved."""

    def _standings_csv(self, tmp, contest="777777777"):
        path = Path(tmp) / f"contest-standings-{contest}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(MinerMoneyHonestyTests.HEADER)
            for i in range(6):
                writer.writerow([str(i + 1), str(9000 + i), f"u{i}", "0",
                                 f"{120 - i}.5", MinerMoneyHonestyTests.CLASSIC,
                                 "", "Aaron Judge", "OF", "41.2%", "18.5"])
        return path

    def test_the_documented_invocation_advances_the_registry(self):
        """The regression test is the RUNBOOK's command -- no `--registry` -- not
        the flagged one. Running the flagged form is what hid this for the whole
        tranche. In-process with the default path redirected, because the point
        is that the tool resolves the path itself and a test must not write the
        real data/reference registry to prove it."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            redirected = str(Path(tmp) / "field_opponent_registry.json")
            with unittest.mock.patch.object(fm, "default_registry_path",
                                            return_value=redirected):
                code = fm.main(["--standings", str(self._standings_csv(tmp)),
                                "--contest-id", "777777777",
                                "--no-archive-move"])
            self.assertEqual(code, 0)
            self.assertTrue(Path(redirected).exists(),
                            "a bare mine did not accumulate the registry")
            reg = json.loads(Path(redirected).read_text(encoding="utf-8"))
            self.assertEqual(reg["contests_mined"], ["777777777"])
            self.assertIn("u0", reg["users"])

    def test_update_registry_resolves_its_own_default_when_passed_none(self):
        """The internal `registry_path or default_registry_path()` was
        unreachable from main, because the only caller sat behind a truthiness
        check on the same value it would have passed. Pinned behaviourally: a
        source-text assertion here is the R91 failure class, and the first
        version of this test proved it by matching its own explanatory comment."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            redirected = str(Path(tmp) / "reg.json")
            mined = {"contest_id": "555555555", "meta": {}, "entries": [],
                     "diagnostics": {}}
            with unittest.mock.patch.object(fm, "default_registry_path",
                                            return_value=redirected):
                fm.update_registry(None, mined)
            self.assertTrue(Path(redirected).exists(),
                            "passing None must resolve the default, not skip")

    def test_a_mine_with_no_identity_declines_loudly_without_killing_the_mine(self):
        """R74(a) still refuses a null identity. Now that the call is
        unconditional, that refusal must not take the whole mine down with it."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            # header only: no entries, so no winning entry id, and no --contest-id
            path = Path(tmp) / "contest-standings-empty.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerow(MinerMoneyHonestyTests.HEADER)
            done = subprocess.run(
                [sys.executable, "-m", "mlb_engine.field.field_miner",
                 "--standings", str(path),
                 "--registry", str(Path(tmp) / "reg.json")],
                capture_output=True, text=True, cwd=str(REPO))
            self.assertIn("registry NOT updated", done.stdout + done.stderr,
                          "the decline must be named, not swallowed")
            self.assertIn("--contest-id", done.stdout + done.stderr,
                          "and must say how to fix it")
            self.assertFalse((Path(tmp) / "reg.json").exists(),
                             "a null identity must never reach the registry")
            del fm

    def test_the_flag_still_overrides_the_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "elsewhere" / "reg.json"
            registry.parent.mkdir(parents=True)
            done = subprocess.run(
                [sys.executable, "-m", "mlb_engine.field.field_miner",
                 "--standings", str(self._standings_csv(tmp)),
                 "--contest-id", "777777777", "--registry", str(registry)],
                capture_output=True, text=True, cwd=str(REPO))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(registry.exists())
            reg = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(reg["contests_mined"], ["777777777"])

    def test_the_runbook_and_the_code_agree(self):
        """The item's done-when is agreement, so the doc is pinned too."""
        text = (REPO / "docs" / "cowork_archival_runbook.md").read_text(encoding="utf-8")
        self.assertIn("Do not pass `--registry`", text)
        self.assertIn("R94", text,
                      "the runbook must record that the sentence is now true")


class AwaitingStandingsSettlementTests(unittest.TestCase):
    """R95. The scan enrolled a contest the moment its DKEntries file existed, so
    four 2026-08-08 contests hit the pull list at 12:43, before the slate locked.
    Ben clicked all four, DK served zero-byte exports, and those files then read
    as "pulled" by filename -- the R74(b) direction, where a contest wrongly
    marked pulled is a contest nobody goes back for."""

    def _aw(self):
        sys.path.insert(0, str(REPO / "tools"))
        import awaiting_standings as aw
        return aw

    ENTERED = {
        "111111111": {"date": "2026-08-06", "name": "Settled Contest"},
        "222222222": {"date": "2026-08-08", "name": "Tonight's Contest"},
        "333333333": {"date": "2026-08-09", "name": "Tomorrow's Contest"},
    }
    NO_EXC = {"unrecoverable": [], "placeholder": []}

    def test_a_slate_dated_today_is_held_back_not_listed(self):
        aw = self._aw()
        by_date = aw.compute_open(self.ENTERED, set(), self.NO_EXC, "2026-08-08")
        self.assertIn("2026-08-06", by_date)
        self.assertNotIn("2026-08-08", by_date,
                         "today's slate has not settled; DK serves an empty export")
        self.assertNotIn("2026-08-09", by_date)

    def test_the_held_back_contests_are_reported_not_silently_dropped(self):
        aw = self._aw()
        unsettled = aw.compute_unsettled(self.ENTERED, set(), self.NO_EXC, "2026-08-08")
        self.assertEqual(sorted(unsettled), ["2026-08-08", "2026-08-09"])
        self.assertEqual(unsettled["2026-08-08"], [("222222222", "Tonight's Contest")])
        # and the two halves partition the entered set exactly
        opened = aw.compute_open(self.ENTERED, set(), self.NO_EXC, "2026-08-08")
        seen = {cid for rows in list(opened.values()) + list(unsettled.values())
                for cid, _ in rows}
        self.assertEqual(seen, set(self.ENTERED))

    def test_the_boundary_is_inclusive(self):
        # >= not >: a slate dated today is still settling whatever the hour.
        aw = self._aw()
        entered = {"444444444": {"date": "2026-08-08", "name": "Edge"}}
        self.assertEqual(aw.compute_open(entered, set(), self.NO_EXC, "2026-08-09"),
                         {"2026-08-08": [("444444444", "Edge")]})
        self.assertEqual(aw.compute_open(entered, set(), self.NO_EXC, "2026-08-08"), {})

    def test_today_is_an_et_day_not_a_utc_one(self):
        """The container runs UTC, so after 8pm ET the UTC date is already
        tomorrow -- exactly when a night slate is mid-flight. On a UTC clock
        tonight's contests satisfy `slate_date < today` and get listed."""
        aw = self._aw()
        sys.path.insert(0, str(REPO))
        from mlb_engine.repo_env import today_et
        self.assertEqual(aw._today(), today_et(),
                         "_today must delegate to the one ET authority (R65)")
        night = datetime(2026, 8, 9, 1, 30, tzinfo=timezone.utc)  # 21:30 ET on 08-08
        self.assertEqual(today_et(night), "2026-08-08")
        self.assertEqual(night.strftime("%Y-%m-%d"), "2026-08-09",
                         "the UTC clock is a day ahead here; that is the bug")

    # -- R95(b): a zero-byte export is not a pull -----------------------------

    def _inbox(self, tmp, files):
        inbox = Path(tmp) / "standings" / "inbox"
        inbox.mkdir(parents=True)
        for name, body in files:
            (inbox / name).write_text(body, encoding="utf-8")
        return Path(tmp)

    def test_a_zero_byte_inbox_file_counts_as_not_pulled(self):
        aw = self._aw()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._inbox(tmp, [
                ("contest-standings-111111111.csv", "Rank,EntryId\n1,9000\n"),
                ("contest-standings-222222222.csv", ""),  # DK pre-settle export
            ])
            pulled, failed = aw._scan_inbox(data)
            self.assertEqual(pulled, {"111111111"})
            self.assertEqual(failed, {"222222222": "contest-standings-222222222.csv"})
            # and the public helper agrees, so every caller inherits the fix
            self.assertEqual(aw.inbox_ids(data), {"111111111"})

    def test_the_failed_pull_keeps_its_contest_on_the_list(self):
        aw = self._aw()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._inbox(tmp, [("contest-standings-222222222.csv", "")])
            pulled, failed = aw._scan_inbox(data)
            entered = {"222222222": {"date": "2026-08-06", "name": "Empty Pull"}}
            by_date = aw.compute_open(entered, pulled, self.NO_EXC, "2026-08-08")
            self.assertEqual(by_date, {"2026-08-06": [("222222222", "Empty Pull")]},
                             "an empty file must not retire its contest")
            md = aw.render_markdown(by_date, 0, {}, self.NO_EXC, "2026-08-08",
                                    failed_pulls=failed, unsettled={})
            self.assertIn("Failed pulls", md)
            self.assertIn("contest-standings-222222222.csv", md,
                          "the checklist must name the empty file, not just omit it")

    def test_a_real_export_beside_a_stray_empty_one_still_counts(self):
        aw = self._aw()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._inbox(tmp, [
                ("contest-standings-111111111.csv", "Rank\n1\n"),
                ("dupe-contest-standings-111111111.csv", ""),
            ])
            pulled, failed = aw._scan_inbox(data)
            self.assertEqual(pulled, {"111111111"})
            self.assertEqual(failed, {}, "a real export outranks a stray empty file")


class MinerManifestFirstSalaryTests(unittest.TestCase):
    """R49(1)(2). Scoring cannot find the right salary file when a same-family
    SUPERSET exists: a 9-game slate's players all sit inside the 10-game file, so
    both join 100% and the resolver correctly declines rather than guessing. The
    manifest already knows -- each delivery records its run_id, and
    runs/<run_id>/inputs/DKSalaries.csv is by construction what the build used.
    Validated by hand across 31 contests on 2026-08-08."""

    SALARY_HEADER = MinerSalaryJoinFloorTests.SALARY_HEADER
    DRAFTED = MinerSalaryJoinFloorTests.RIGHT_SLATE
    # The superset is one extra GAME on top of the same slate, which is the real
    # shape of the failure: the drafted players are all still present and the two
    # extra teams keep team_coverage above MIN_AUTO_TEAM_COVERAGE (9 drafted of 11
    # priced = 0.82), so the 2026-07-24 team-coverage asymmetry cannot separate
    # them either. That leaves both candidates usable at 100% join with differing
    # content, which is the ambiguity branch, which is the decline that cost 11
    # manual resolutions.
    EXTRA = [("OF", "Julio Rodriguez", "SEA"), ("1B", "Pete Alonso", "NYM"),
             ("2B", "Jose Altuve", "HOU"), ("3B", "Austin Riley", "ATL"),
             ("SS", "Trea Turner", "PHI"), ("C", "Adley Rutschman", "NYY"),
             ("P", "Corbin Burnes", "DET"), ("OF", "Yordan Alvarez", "HOU")]

    def _standings(self, tmp, cid="777777777"):
        from mlb_engine.field import field_miner as fm
        path = Path(tmp) / f"contest-standings-{cid}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(MinerMoneyHonestyTests.HEADER)
            for i in range(6):
                w.writerow([str(i + 1), str(9000 + i), f"u{i}", "0", f"{120 - i}.5",
                            MinerMoneyHonestyTests.CLASSIC, "", "Aaron Judge",
                            "OF", "41.2%", "18.5"])
        return fm.parse_standings_export(str(path))

    def _salary(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(self.SALARY_HEADER)
            for i, (pos, nm, team) in enumerate(rows):
                w.writerow([pos, f"{nm} ({7000 + i})", nm, str(7000 + i), pos,
                            "5000", "AAA@BBB 07:05PM ET", team, "8.0"])
        return path

    def _tree(self, tmp, date="2026-08-06", cid="777777777", run="20260806T1607Z_abc",
              deliveries=None, superseded_run=None):
        """The authoritative file in the run inputs, a SUPERSET staged in-date."""
        root = Path(tmp)
        self._salary(root / "runs" / run / "inputs" / "DKSalaries.csv", self.DRAFTED)
        if superseded_run:
            self._salary(root / "runs" / superseded_run / "inputs" / "DKSalaries.csv",
                         self.DRAFTED)
        self._salary(root / "data" / "slates" / date / "DKSalaries.csv",
                     self.DRAFTED + self.EXTRA)
        if deliveries is None:
            deliveries = [{"run_id": run, "contest_ids": [cid], "status": "upload_ready"}]
        manifest = root / "outputs" / date / "upload_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"deliveries": deliveries}), encoding="utf-8")
        return root

    def test_the_manifest_tier_names_the_run_inputs_for_this_contest(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp)
            got = fm.manifest_salary_candidates(root, "2026-08-06", "777777777")
            self.assertEqual(len(got), 1)
            self.assertIn("20260806T1607Z_abc", got[0])

    def test_a_delivery_for_other_contests_is_not_this_contest_s_file(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, deliveries=[
                {"run_id": "20260806T1607Z_abc", "contest_ids": ["999999999"],
                 "status": "upload_ready"}])
            self.assertEqual(fm.manifest_salary_candidates(root, "2026-08-06", "777777777"), [])

    def test_a_live_delivery_outranks_a_superseded_one(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, superseded_run="20260806T1600Z_old", deliveries=[
                {"run_id": "20260806T1600Z_old", "contest_ids": ["777777777"],
                 "status": "superseded"},
                {"run_id": "20260806T1607Z_abc", "contest_ids": ["777777777"],
                 "status": "upload_ready"}])
            got = fm.manifest_salary_candidates(root, "2026-08-06", "777777777")
            self.assertEqual(len(got), 2, "a superseded run is a fallback, not a drop")
            self.assertIn("20260806T1607Z_abc", got[0],
                          "the surviving delivery is the file that was entered")

    def test_the_manifest_resolves_a_superset_that_pooled_scoring_cannot(self):
        """The load-bearing test. Both files join 100%; pooled they are a
        content-differing tie and the resolver declines, which is the state that
        forced 11 manual resolutions on 2026-08-04."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp)
            st = self._standings(tmp)
            pooled = fm.resolve_salary_file(st, [
                str(root / "runs" / "20260806T1607Z_abc" / "inputs" / "DKSalaries.csv"),
                str(root / "data" / "slates" / "2026-08-06" / "DKSalaries.csv")])
            self.assertIsNone(pooled["path"], "pooled scoring must be shown to fail here")
            self.assertIn("ambiguous", pooled["reason"])

            tiered = fm.resolve_salary_tiered(st, root, slate_date="2026-08-06",
                                              contest_id="777777777")
            self.assertEqual(tiered["tier"], "manifest")
            self.assertIn("20260806T1607Z_abc", tiered["path"])

    def test_in_date_answers_when_there_is_no_manifest(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._salary(root / "data" / "slates" / "2026-08-06" / "DKSalaries.csv",
                         self.DRAFTED)
            st = self._standings(tmp)
            tiered = fm.resolve_salary_tiered(st, root, slate_date="2026-08-06",
                                              contest_id="777777777")
            self.assertEqual(tiered["tier"], "in_date")

    def test_the_wide_scan_is_the_last_resort_and_says_so(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # not in-date, not in a manifest: only reachable by the repo-wide glob
            self._salary(root / "data" / "archive" / "2026-07-01" / "DKSalaries.csv",
                         self.DRAFTED)
            st = self._standings(tmp)
            tiered = fm.resolve_salary_tiered(st, root, slate_date="2026-08-06",
                                              contest_id="777777777")
            self.assertEqual(tiered["tier"], "repo_wide")
            self.assertEqual([a["tier"] for a in tiered["attempts"]],
                             ["manifest", "in_date", "repo_wide"],
                             "the tier order is the contract")

    def test_every_tier_failing_leaves_standings_only_with_all_three_reasons(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp)
            tiered = fm.resolve_salary_tiered(st, Path(tmp), slate_date="2026-08-06",
                                              contest_id="777777777")
            self.assertIsNone(tiered["path"])
            self.assertIsNone(tiered["tier"])
            for tier in ("manifest", "in_date", "repo_wide"):
                self.assertIn(tier, tiered["reason"])

    def test_a_delivered_dkentries_is_never_offered_as_a_salary_source(self):
        """R49(1). The runbook and this block both claimed a retained DKEntries
        upload "embeds the full salary block". True of DK's downloaded template;
        false of the engine's delivered file, which has no Salary column at all."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp)
            mined = fm.mine_contest(st, None, contest_id="777777777")
            block = fm.emit_ledger_block(mined)
            text = block if isinstance(block, str) else "\n".join(block)
            self.assertEqual(mined["coverage"], "standings_only")
            self.assertNotIn("embeds the salary block", text)
            self.assertIn("NOT a salary source", text)
        runbook = (REPO / "docs" / "cowork_archival_runbook.md").read_text(encoding="utf-8")
        self.assertNotIn("it embeds the full salary block", runbook)
        self.assertIn("NOT a salary source", runbook)


class MinerCaptainTests(unittest.TestCase):
    """R39. `players_norm` is sorted and position-blind and was the only thing
    carried forward, so the CPT marker the raw Lineup cell carries was normalized
    away one line after being parsed. Captain choice is the largest Showdown
    construction decision; the 2026-08-08 review had to re-parse 64 archived
    standings CSVs directly to measure it at all."""

    HEADER = MinerMoneyHonestyTests.HEADER
    # CPT is priced and counted differently from UTIL; 1CPT + 5UTIL is complete.
    def _sd(self, cpt, utils):
        return f"CPT {cpt} " + " ".join(f"UTIL {u}" for u in utils)

    UTILS = ["Bo Bichette", "Vladimir Guerrero Jr.", "George Springer",
             "Alejandro Kirk", "Daulton Varsho"]

    def _standings(self, tmp, captains, points=None):
        """One entry per captain, with the same five UTIL bats underneath."""
        from mlb_engine.field import field_miner as fm
        path = Path(tmp) / "contest-standings-888888888.csv"
        rows = []
        for i, cpt in enumerate(captains):
            pts = points[i] if points else 100.0 - i
            rows.append([str(i + 1), str(9000 + i), f"u{i}", "0", f"{pts}",
                         self._sd(cpt, self.UTILS), "", cpt, "CPT", "20.0%", "18.5"])
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(self.HEADER)
            w.writerows(rows)
        return fm.parse_standings_export(str(path))

    def test_the_cpt_marker_survives_the_parse(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp, ["Kevin Gausman", "Bo Bichette"])
            self.assertEqual(st["contest_type"], "showdown")
            self.assertEqual([e["captain_norm"] for e in st["entries"]],
                             ["kevin gausman", "bo bichette"])
            # players_norm is why it was lost: sorted, and position-blind.
            self.assertEqual(st["entries"][0]["players_norm"],
                             tuple(sorted(st["entries"][0]["players_norm"])))

    def test_a_classic_lineup_has_no_captain_and_claims_none(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contest-standings-777777777.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(self.HEADER)
                w.writerow(["1", "9000", "u0", "0", "120.5",
                            MinerMoneyHonestyTests.CLASSIC, "", "Aaron Judge",
                            "OF", "41.2%", "18.5"])
            st = fm.parse_standings_export(str(path))
            self.assertEqual(st["contest_type"], "classic")
            self.assertIsNone(st["entries"][0]["captain_norm"])
            mined = fm.mine_contest(st, None, contest_id="777777777")
            self.assertEqual(mined["construction"]["captain_table"], [],
                             "Classic has no captain slot; the table must be empty")
            self.assertIsNone(mined["construction"]["winner_captain"])

    def test_the_captain_table_is_a_standing_per_contest_measurement(self):
        """The point of the item: what 3.18 derived by re-parsing 64 CSVs is now
        emitted per contest."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp, ["Kevin Gausman"] * 3 + ["Bo Bichette"])
            mined = fm.mine_contest(st, None, contest_id="888888888")
            table = mined["construction"]["captain_table"]
            self.assertEqual([r["player"] for r in table],
                             ["Kevin Gausman", "Bo Bichette"])
            self.assertEqual(table[0]["captain_count"], 3)
            self.assertEqual(table[0]["captain_share_pct"], 75.0)
            self.assertEqual(table[1]["captain_share_pct"], 25.0)
            # captain share and roster share sit on the same row, because the
            # 3.18 comparison is one against the other.
            self.assertIn("pct_drafted", table[0])

    def test_the_winner_s_captain_is_recorded_with_its_ownership(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            # the chalk captain is used 3 times; the WINNER captains the other one
            st = self._standings(tmp, ["Kevin Gausman", "Kevin Gausman",
                                       "Kevin Gausman", "Bo Bichette"],
                                 points=[10.0, 9.0, 8.0, 99.0])
            mined = fm.mine_contest(st, None, contest_id="888888888")
            wc = mined["construction"]["winner_captain"]
            self.assertEqual(wc["player"], "Bo Bichette")
            self.assertEqual(wc["captain_share_pct"], 25.0)
            self.assertFalse(wc["was_top_owned_captain"],
                             "the winner captained the 25% option, not the 75% one")

    def test_the_top_owned_captain_winning_is_recorded_as_such(self):
        # 22 of 85 in the 3.18 sample, so both branches are live.
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp, ["Kevin Gausman", "Kevin Gausman", "Bo Bichette"],
                                 points=[99.0, 9.0, 8.0])
            mined = fm.mine_contest(st, None, contest_id="888888888")
            self.assertTrue(mined["construction"]["winner_captain"]["was_top_owned_captain"])

    def test_captain_norm_reaches_the_archived_entries(self):
        """A re-mine must backfill the archive, so the field has to be in the
        per-entry projection, not only in the aggregate."""
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp, ["Kevin Gausman", "Bo Bichette"])
            mined = fm.mine_contest(st, None, contest_id="888888888")
            self.assertEqual([e["captain_norm"] for e in mined["entries"]],
                             ["kevin gausman", "bo bichette"])

    def test_the_ledger_block_carries_the_captain_lines(self):
        from mlb_engine.field import field_miner as fm
        with tempfile.TemporaryDirectory() as tmp:
            st = self._standings(tmp, ["Kevin Gausman", "Kevin Gausman", "Bo Bichette"],
                                 points=[9.0, 8.0, 99.0])
            mined = fm.mine_contest(st, None, contest_id="888888888")
            block = fm.emit_ledger_block(mined)
            text = block if isinstance(block, str) else "\n".join(block)
            self.assertIn("Captain field share (top)", text)
            self.assertIn("Winning entry captained Bo Bichette", text)
            self.assertIn("top-owned captain: no", text)

    def test_a_lineup_with_no_cpt_slot_yields_none_rather_than_a_guess(self):
        from mlb_engine.field import field_miner as fm
        self.assertIsNone(fm._captain_norm([("UTIL", "Bo Bichette")]))
        self.assertIsNone(fm._captain_norm([]))
        self.assertEqual(fm._captain_norm([("UTIL", "A B"), ("CPT", "Kevin Gausman")]),
                         "kevin gausman")


class FieldMinerArchiveHousekeepingTests(unittest.TestCase):
    """R23: the miner owns the inbox move, and the ledger block becomes a
    consumable fragment instead of stdout to paste twice."""

    def test_moves_only_repo_inbox_files(self):
        import tempfile
        from mlb_engine.field.field_miner import archive_mined_standings
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "data" / "standings" / "inbox"
            inbox.mkdir(parents=True)
            src = inbox / "contest-standings-42.csv"
            src.write_text("x", encoding="utf-8")
            dest = archive_mined_standings(src, "2026-07-01", repo_root=root)
            self.assertEqual(
                Path(dest),
                root / "data" / "archive" / "2026-07-01" / src.name)
            self.assertFalse(src.exists())
            self.assertTrue(Path(dest).exists())

    def test_leaves_files_outside_the_inbox_alone(self):
        import tempfile
        from mlb_engine.field.field_miner import archive_mined_standings
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loose = root / "contest-standings-42.csv"
            loose.write_text("x", encoding="utf-8")
            self.assertIsNone(
                archive_mined_standings(loose, "2026-07-01", repo_root=root))
            self.assertTrue(loose.exists())

    def test_no_slate_date_means_no_move(self):
        import tempfile
        from mlb_engine.field.field_miner import archive_mined_standings
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "data" / "standings" / "inbox"
            inbox.mkdir(parents=True)
            src = inbox / "contest-standings-42.csv"
            src.write_text("x", encoding="utf-8")
            self.assertIsNone(archive_mined_standings(src, "", repo_root=root))
            self.assertTrue(src.exists())

    def test_fragment_is_written_and_named_for_its_contest(self):
        import tempfile
        from mlb_engine.field.field_miner import write_ledger_fragment
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_ledger_fragment("## A-XXX block", "2026-07-01",
                                         "192784", repo_root=root)
            expected = root / "ledger" / "inbox" / "2026-07-01_miner_192784.md"
            self.assertEqual(Path(path), expected)
            self.assertIn("A-XXX", expected.read_text(encoding="utf-8"))


class PromotePointerCasTests(unittest.TestCase):
    """R20(c): last-promoter-wins on runs/latest_valid_run.json becomes one
    winner and one loud refusal that leaves the losing run valid."""

    @staticmethod
    def _certified_run(root):
        from mlb_engine.pipeline.build_state_manager import (
            create_run, update_run_certification)
        run = create_run(root, "initial_build")
        update_run_certification(run["run_dir"], {
            "workflow_valid": True, "selection_certified": True,
            "allocation_certified": True})
        return run

    def test_promotion_refused_when_the_pointer_moved(self):
        import json as _json
        import tempfile
        from mlb_engine.pipeline.build_state_manager import (
            promote_run, read_pointer_sha256)
        with tempfile.TemporaryDirectory() as tmp:
            a = self._certified_run(tmp)
            b = self._certified_run(tmp)
            expected = read_pointer_sha256(tmp)  # None: no pointer yet
            self.assertTrue(promote_run(a["run_dir"])["passed"])
            refused = promote_run(b["run_dir"],
                                  expected_pointer_sha256=expected)
            self.assertFalse(refused["passed"])
            self.assertTrue(refused.get("pointer_conflict"))
            manifest = _json.loads(
                (Path(b["run_dir"]) / "manifest.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(manifest["status"], "building",
                             "a refused promotion must not poison the run")

    def test_promotion_succeeds_when_the_pointer_is_unmoved(self):
        import tempfile
        from mlb_engine.pipeline.build_state_manager import (
            promote_run, read_pointer_sha256)
        with tempfile.TemporaryDirectory() as tmp:
            a = self._certified_run(tmp)
            first = promote_run(a["run_dir"],
                                expected_pointer_sha256=read_pointer_sha256(tmp))
            self.assertTrue(first["passed"], first["errors"])
            b = self._certified_run(tmp)
            second = promote_run(b["run_dir"],
                                 expected_pointer_sha256=read_pointer_sha256(tmp))
            self.assertTrue(second["passed"], second["errors"])

    def test_legacy_promote_stays_unconditional(self):
        import tempfile
        from mlb_engine.pipeline.build_state_manager import promote_run
        with tempfile.TemporaryDirectory() as tmp:
            a = self._certified_run(tmp)
            b = self._certified_run(tmp)
            self.assertTrue(promote_run(a["run_dir"])["passed"])
            self.assertTrue(promote_run(b["run_dir"])["passed"],
                            "the manual-recovery path must keep working")


class DeferredPromotionTests(unittest.TestCase):
    """R29(2): the pointer is a claim about delivery, so it moves at delivery.

    Teeth: a downgrade-refused swap mirrored nothing to outputs/ and still
    promoted runs/latest_valid_run.json to itself. The next swap then failed on
    a parent mismatch that reads like a multi-session collision, and the
    documented way around it was --allow-parent-mismatch on every later call,
    which is exactly the R20(c) protection being switched off because a bug
    taught the operator to distrust it.
    """

    def _gates(self):
        return {
            "salary_gate_passed": True, "entry_grid_gate_passed": True,
            "lineup_gate_passed": True, "pitcher_audit_gate_passed": True,
            "weather_gate_passed": True, "odds_gate_passed": True,
            "projection_schema_gate_passed": True, "optimizer_gate_passed": True,
        }

    def _build(self, root, *, defer):
        salary = root / "salary.csv"
        ids = write_salary(salary)
        entries = root / "DKEntries.csv"
        write_entries(entries)
        r1, r2 = legal_rosters(ids)
        return run_initial_build(
            runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
            projections=projection_frame(ids),
            candidates=[candidate("A", r1, 100), candidate("B", r2, 99, "CCC")],
            entry_requirements=[
                {"entry_id": "5001", "contest_id": "900",
                 "contest_name": "Test WTA", "contest_shape": "large_wta"},
                {"entry_id": "5002", "contest_id": "900",
                 "contest_name": "Test WTA", "contest_shape": "large_wta"},
            ],
            workflow_gates=self._gates(),
            portfolio_controls={"max_player_exposure_pct": 1.0,
                                "max_pitcher_exposure_pct": 1.0,
                                "max_primary_stack_exposure_pct": 1.0,
                                "max_sp_pair_repetition": 2,
                                "max_shared_players": 9},
            defer_promotion=defer,
        )

    def test_a_deferred_run_certifies_without_touching_the_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._build(root, defer=True)
            self.assertTrue(result["passed"], result.get("errors"))
            self.assertTrue(result["workflow_valid"])
            self.assertTrue(Path(result["output_path"]).exists(),
                            "the certified file is still written")
            self.assertTrue(result["promotion_deferred"])
            self.assertFalse(result["promoted"])
            self.assertFalse((root / "runs" / "latest_valid_run.json").exists(),
                             "a run nothing was delivered from must not own the "
                             "pointer")

    def test_completing_the_promotion_moves_the_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._build(root, defer=True)
            done = promote_deferred_run(result)
            self.assertTrue(done["promoted"], done.get("errors"))
            self.assertFalse(done["promotion_deferred"])
            pointer = json.loads(
                (root / "runs" / "latest_valid_run.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["run_id"], result["run_id"])

    def test_the_compare_and_swap_survives_the_deferral(self):
        """R20(c) must not be weakened by the longer window: a session that
        promoted while this one was deciding still wins, loudly."""
        from mlb_engine.pipeline.build_state_manager import (
            create_run, promote_run, update_run_certification)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deferred = self._build(root, defer=True)
            other = create_run(root / "runs", "initial_build")
            update_run_certification(other["run_dir"], {
                "workflow_valid": True, "selection_certified": True,
                "allocation_certified": True})
            self.assertTrue(promote_run(other["run_dir"])["passed"])
            refused = promote_deferred_run(deferred)
            self.assertFalse(refused["promoted"])
            self.assertTrue(refused["pointer_conflict"])
            manifest = json.loads(
                (Path(deferred["run_dir"]) / "manifest.json").read_text(
                    encoding="utf-8"))
            self.assertNotEqual(manifest["status"], "promoted")
            pointer = json.loads(
                (root / "runs" / "latest_valid_run.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["run_id"], other["run_id"],
                             "the refusal must not overwrite the winner")

    def test_the_default_still_promotes_inline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._build(root, defer=False)
            self.assertTrue(result["passed"], result.get("errors"))
            self.assertFalse(result.get("promotion_deferred"))
            self.assertTrue((root / "runs" / "latest_valid_run.json").exists())

    def test_completing_a_run_that_was_never_deferred_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._build(root, defer=False)
            before = (root / "runs" / "latest_valid_run.json").read_text(
                encoding="utf-8")
            promote_deferred_run(result)
            self.assertEqual(
                (root / "runs" / "latest_valid_run.json").read_text(encoding="utf-8"),
                before, "calling this unconditionally must be safe")

    def test_late_swap_defers_and_promotes_only_after_the_mirror(self):
        """The ordering is the fix. A refusal between the two is what used to
        leave the pointer naming an undelivered run.

        R96(2), 2026-08-11: the mirror write is now to the DO_NOT_UPLOAD_ name,
        because a refused promotion left an uploadable unrecorded file here -- one
        of R96's six paths. R29(2)'s invariant is unchanged and is what this still
        pins: SOMETHING is in outputs/ before the pointer moves, so a refusal never
        names a run nothing was mirrored from. Which NAME it wears is R96's business
        and is pinned in test_upload_integrity.R96PerCallerTests.
        """
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertIn("defer_promotion=True", text)
        mirror = text.index("os.replace(tmp, provisional)")
        promote = text.index("promote_deferred_run(result)")
        refusal = text.index("late swap refused: these entries score below")
        self.assertLess(mirror, promote,
                        "promotion must follow the mirror to outputs/")
        self.assertLess(refusal, promote,
                        "promotion must follow the accept-downgrade decision")


class SwapControlsInheritanceTests(unittest.TestCase):
    """R29(3): a swap inherits the caps of the build it refines.

    Teeth: late_swap.py carried one flat dict with max_sp_pair_repetition of 1,
    stricter than every posture in STRATEGY_DEFAULTS (2 or 3). The first swap
    attempt on an already-certified portfolio failed nearly every entry, the
    message was a bare "no compatible candidate", and the session spent twenty
    minutes growing a bank that was never the problem.
    """

    @staticmethod
    def _late_swap():
        import importlib
        import sys as _sys
        tools = str(Path(__file__).resolve().parents[1] / "tools")
        if tools not in _sys.path:
            _sys.path.insert(0, tools)
        return importlib.import_module("late_swap")

    @staticmethod
    def _postures(*postures):
        return {str(900 + i): {"posture": p, "contest_shape": "large_wta",
                               "posture_source": "test"}
                for i, p in enumerate(postures)}

    def test_a_single_posture_yields_exactly_that_postures_controls(self):
        ls = self._late_swap()
        for posture, spec in epi.STRATEGY_DEFAULTS.items():
            if not spec["controls"]:
                continue
            derived = ls.resolve_swap_controls(self._postures(posture), None, None)
            self.assertEqual(derived, dict(spec["controls"]),
                             f"{posture}: the swap must not assert its own caps")

    def test_the_derivation_is_the_builds_own_function(self):
        """Not a parallel implementation: the same call, so they cannot drift."""
        ls = self._late_swap()
        postures = self._postures("large_gpp", "mme", "wta_satellite")
        self.assertEqual(ls.resolve_swap_controls(postures, None, None),
                         epi._merged_controls_for_build(postures, None))

    def test_the_old_flat_cap_of_one_is_gone_for_every_multi_entry_posture(self):
        for posture in ("large_gpp", "mme", "small_gpp", "wta_satellite"):
            derived = self._late_swap().resolve_swap_controls(
                self._postures(posture), None, None)
            self.assertGreaterEqual(
                derived["max_sp_pair_repetition"], 2,
                "1 was tighter than any multi-entry posture the build could use")
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertNotIn('"max_sp_pair_repetition": 1', text)

    def test_single_entry_keeps_a_pair_cap_of_one_and_that_is_correct(self):
        """The counterexample to a careless reading of the fix. single_entry's
        cap of 1 is not the deleted flat default coming back: one entry cannot
        repeat an SP pair, and it is what the build uses for that posture too."""
        derived = self._late_swap().resolve_swap_controls(
            self._postures("single_entry"), None, None)
        self.assertEqual(derived["max_sp_pair_repetition"], 1)
        self.assertEqual(derived,
                         dict(epi.STRATEGY_DEFAULTS["single_entry"]["controls"]))

    def test_a_cash_only_file_enforces_no_cap_and_matches_the_build(self):
        """The other counterexample. cash carries no exposure CAP, so a
        cash-only swap enforces none. That is inheritance working, not a cap
        going missing, and the pre-solve line prints it rather than looking
        blank.

        R37, 2026-08-09: cash is no longer literally empty. It declares
        `primary_stack_min_size` and nothing else, and the reason is the
        floor-merge rule rather than an opinion about cash games -- a floor is
        retired for the whole portfolio the moment one posture goes silent on
        it, so a single cash contest in a mixed file would otherwise switch the
        floor off for every other contest in that file. The assertion that
        matters here never was 'the dict is empty', it is 'cash contributes no
        cap', so that is what it now says."""
        derived = self._late_swap().resolve_swap_controls(
            self._postures("cash"), None, None)
        self.assertEqual(derived, {"primary_stack_min_size": 4})
        self.assertEqual(epi.STRATEGY_DEFAULTS["cash"]["controls"],
                         {"primary_stack_min_size": 4})
        self.assertEqual(
            [k for k in derived if k.startswith("max_")], [],
            "cash must contribute no exposure or repetition cap")
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertIn("none for these postures", text)

    def test_tightest_cap_wins_across_the_contests_present(self):
        ls = self._late_swap()
        derived = ls.resolve_swap_controls(
            self._postures("large_gpp", "mme"), None, None)
        self.assertEqual(derived["max_player_exposure_pct"], 0.35)
        self.assertEqual(derived["max_sp_pair_repetition"], 3)

    def test_an_explicit_override_still_wins(self):
        ls = self._late_swap()
        derived = ls.resolve_swap_controls(
            self._postures("large_gpp"), {"max_sp_pair_repetition": 5}, 12)
        self.assertEqual(derived["max_sp_pair_repetition"], 5)
        self.assertEqual(derived["time_limit"], 12.0)
        explicit = ls.resolve_swap_controls(
            self._postures("large_gpp"), {"time_limit": 3}, 12)
        self.assertEqual(explicit["time_limit"], 3,
                         "an operator who passed JSON meant it (R25)")

    def test_a_cash_only_file_matches_the_build_rather_than_inventing_caps(self):
        ls = self._late_swap()
        self.assertEqual(ls.resolve_swap_controls(self._postures("cash"), None, None),
                         epi._merged_controls_for_build(self._postures("cash"), None))

    def test_the_swap_applies_the_same_feasibility_floors_the_build_applies(self):
        """The half that was missing. run_slate floors the merged caps by
        _slate_feasibility BEFORE the override; a swap that skipped the floors
        re-derived tighter caps than the build shipped on a thin slate, which is
        the same failure this item exists to close, arriving automatically
        instead of through the operator."""
        ls = self._late_swap()
        postures = self._postures("wta_satellite", "large_gpp")
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "salary.csv"
            ids = write_salary(salary)
            projections = projection_frame(ids)
            requirements = [
                {"entry_id": str(5000 + i), "contest_id": str(900 + (i % 2)),
                 "contest_name": "T", "contest_shape": "large_wta"}
                for i in range(18)
            ]
            floors = epi.feasibility_floors_from(epi._slate_feasibility(
                postures, requirements, projections, None))
            expected = epi._merged_controls_for_build(
                postures, None, feasibility_floors=floors)
            derived = ls.resolve_swap_controls(
                postures, None, None,
                requirements=requirements, projections=projections)
        self.assertEqual(derived, expected)
        unfloored = epi._merged_controls_for_build(postures, None)
        self.assertTrue(
            floors, "the fixture must actually trip a floor or this proves nothing")
        self.assertNotEqual(
            derived, unfloored,
            "with floors active the floored result must differ from the raw merge")

    def test_omitting_the_frame_leaves_the_merge_unfloored_rather_than_guessing(self):
        ls = self._late_swap()
        postures = self._postures("large_gpp")
        self.assertEqual(ls.resolve_swap_controls(postures, None, None),
                         epi._merged_controls_for_build(postures, None))


class SwapFailureClassificationTests(unittest.TestCase):
    """R29(3), second half: a control mismatch and a thin bank must never read
    the same. Both messages now classify themselves."""

    @staticmethod
    def _classify(errors, controls=None, bank_report=None):
        return SwapControlsInheritanceTests._late_swap().classify_swap_failure(
            errors, controls or {"max_sp_pair_repetition": 3,
                                 "max_player_exposure_pct": 0.4},
            bank_report=bank_report)

    def test_a_control_violation_names_the_control_and_its_value(self):
        lines = self._classify(["SP pair 43703590/43709134 count 2>1"])
        self.assertIn("binding control: max_sp_pair_repetition=3", lines[0])
        # R61: --controls-override moved OFF the per-error line and into the
        # ordered trailer. On the per-error line it read as the fix for that one
        # violation; in the trailer it arrives after the bank and after the
        # floor-versus-cap split, which is the order that fixes the problem.
        self.assertNotIn("--controls-override", lines[0])
        self.assertIn("--controls-override", " ".join(lines))

    def test_every_control_prefix_is_mapped(self):
        cases = {
            "player 123 count 4>3": "max_player_exposure_pct",
            "pitcher 123 count 4>3": "max_pitcher_exposure_pct",
            "primary stack AAA count 4>3": "max_primary_stack_exposure_pct",
            "SP pair 1/2 count 4>3": "max_sp_pair_repetition",
            # R61: both of these fell through unannotated, and they are the two
            # that most often bind on a swap.
            "entries 900/901 share 6>5": "max_shared_players",
            "game AAA@BBB exposure 7>5": "max_game_exposure_pct_by_game",
        }
        for err, control in cases.items():
            self.assertIn(f"binding control: {control}",
                          self._classify([err])[0], err)

    def test_floors_and_caps_are_not_presented_as_the_same_lever(self):
        """R61, reusing R98(2)'s vocabulary rather than writing a third copy."""
        from mlb_engine.allocate.contest_allocator import (
            STRATEGY_CAP_CONTROLS, STRUCTURAL_FLOOR_CONTROLS,
        )
        self.assertIn("max_shared_players", STRUCTURAL_FLOOR_CONTROLS)
        self.assertIn("max_player_exposure_pct", STRATEGY_CAP_CONTROLS)
        structural = " ".join(self._classify(
            ["entries 900/901 share 6>5"],
            {"max_shared_players": 5}))
        self.assertIn("ARITHMETIC, not strategy", structural)
        self.assertNotIn("A STRATEGY DECISION", structural)
        strategy = " ".join(self._classify(
            ["player 123 count 4>3"], {"max_player_exposure_pct": 0.4}))
        self.assertIn("A STRATEGY DECISION", strategy)
        self.assertIn("not a recommendation", strategy)
        self.assertNotIn("ARITHMETIC, not strategy", strategy)
        both = " ".join(self._classify(
            ["entries 900/901 share 6>5", "player 123 count 4>3"],
            {"max_shared_players": 5, "max_player_exposure_pct": 0.4}))
        self.assertLess(both.index("ARITHMETIC, not strategy"),
                        both.index("A STRATEGY DECISION"))

    def test_a_partial_bank_is_named_before_any_control_change(self):
        partial = {"job_list_exhausted": False, "jobs_attempted": 21,
                   "jobs_total": 1176}
        lines = self._classify(["player 123 count 4>3"], bank_report=partial)
        blob = " ".join(lines)
        self.assertIn("GROW THE BANK FIRST", blob)
        self.assertIn("21 of 1176", blob)
        self.assertLess(blob.index("GROW THE BANK FIRST"),
                        blob.index("A STRATEGY DECISION"))
        # An exhausted bank says nothing about the bank, and a missing report
        # never asserts that the bank was complete.
        for report in ({"job_list_exhausted": True}, None, {}):
            self.assertNotIn("GROW THE BANK FIRST", " ".join(
                self._classify(["player 123 count 4>3"], bank_report=report)))
        # No cap violation, nothing to order: the bank line is not a preamble.
        self.assertNotIn("GROW THE BANK FIRST", " ".join(self._classify(
            ["no compatible candidate for Entry ID 900"], bank_report=partial)))

    def test_the_parents_own_cap_is_checked_before_a_new_value(self):
        blob = " ".join(self._classify(["player 123 count 4>3"]))
        self.assertIn("R29(3)", blob)
        self.assertIn("not a strategy change", blob)

    def test_an_allocator_refusal_is_not_re_steered(self):
        """R61's refusals arrive carrying their own ordered remedies, and this
        function must add nothing to them: a cap-loosening trailer under a
        refusal that just said not to loosen the cap is a contradiction.

        No special case enforces that. It holds because no refusal string starts
        with a prefix in `_CONTROL_BY_ERROR_PREFIX`, so none is annotated and
        none reaches the trailer. That is a property of two vocabularies that
        live in different modules, which is exactly the kind of coupling that
        rots silently, so it is asserted here against the real strings. Adding a
        prefix like "max_player" to the map, or renaming a refusal to lead with
        "player ", turns this red.
        """
        ls = SwapControlsInheritanceTests._late_swap()
        refusals = [
            # contest_allocator._untouchable_cap_conflicts
            "max_player_exposure_pct: player 40003 already appears in 10 of the "
            "8 row(s) this solve cannot change, against a whole-file cap of 9 "
            "at 20 complete rows",
            "max_sp_pair_repetition: SP pair 1/2 already appears in 3 of the 8 "
            "row(s) this solve cannot change, against a cap of 2",
            "This is not a solver infeasibility and not a bank problem. In "
            "order: (1) authorize the rows holding the excess with --entry-ids",
            # the starve refusal
            "Entry ID 1: every compatible candidate is ruled out by the 8 row(s) "
            "this solve cannot change",
            # contest_allocator._infeasibility_remedies (R98(2))
            "FIRST REMEDY, grow the bank: the job list was NOT exhausted",
            "NEXT REMEDY, --controls-override, and the two kinds are not alike:",
        ]
        for refusal in refusals:
            with self.subTest(refusal=refusal[:40]):
                self.assertEqual(
                    [], [c for p, c in ls._CONTROL_BY_ERROR_PREFIX
                         if refusal.startswith(p)],
                    "a refusal that matches a control prefix would be annotated "
                    "and would drag the cap-loosening trailer in behind it")
                lines = self._classify([refusal], {"max_player_exposure_pct": 0.45,
                                                   "max_sp_pair_repetition": 2})
                self.assertEqual(lines, [f"  {refusal}"])
        # And the two error sources cannot arrive together: execute_portfolio
        # returns on a failed allocation before any export gate runs, so a
        # refusal is never mixed with a validator cap violation.
        source = (Path(__file__).resolve().parents[1] / "mlb_engine" / "pipeline"
                  / "execution_pipeline.py").read_text(encoding="utf-8")
        head = source.split("allocation = select_and_assign_entries", 1)[1]
        self.assertLess(head.index('if not allocation.get("passed")'),
                        head.index("validate_dk_entries_file"))

    def test_no_compatible_candidate_says_it_is_not_a_control(self):
        lines = self._classify(["no compatible candidate for Entry ID 5202734526"])
        self.assertIn("not a portfolio control", lines[0])
        self.assertNotIn("binding control", lines[0])
        # R47: the bank was NOT the cause in the one case this was reproduced on
        # (entry 5207638174, both P slots pinned to one game -- the pinned pair is
        # excluded from the job list, so no bank size produces a candidate). The
        # pins are what to read first, so --budget no longer leads.
        self.assertNotIn("--budget", lines[0])
        self.assertIn("locked slots", lines[0])

    def test_the_two_failure_classes_do_not_read_alike(self):
        control = self._classify(["SP pair 1/2 count 2>1"])[0]
        bank = self._classify(["no compatible candidate for Entry ID 900"])[0]
        self.assertNotEqual(control, bank)
        self.assertNotIn("grow the bank", control.lower())

    def test_an_unrecognised_error_is_passed_through_unannotated(self):
        lines = self._classify(["something else entirely"])
        self.assertEqual(lines, ["  something else entirely"])

    def test_the_controls_in_effect_are_printed_before_the_solve(self):
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertIn("portfolio controls (derived from this file's postures", text)
        # The print has to sit BEFORE the solve or it is a post-mortem, not a
        # diagnostic. The source order is the only thing that guarantees it.
        self.assertLess(text.index("portfolio controls (derived"),
                        text.index("result = run_late_swap("))


class SwapInputOverrideTests(unittest.TestCase):
    """R29(4): a swap must not depend on the shared, date-keyed staging path.

    Teeth: on 2026-07-29 a concurrent Showdown build for the same date
    overwrote data/slates/<date>/DKSalaries.csv mid-swap. Every entry then
    failed with "embedded player pool overlaps the salary file at 0.0%", and
    with no flag to point elsewhere the only route around it was swapping staged
    files in and out around each of the ~19 remaining calls.
    """

    def setUp(self):
        self.ls = SwapControlsInheritanceTests._late_swap()

    def test_the_staged_names_are_still_the_defaults(self):
        salary, feed = self.ls.resolve_swap_inputs(None, None, Path("/slates/d"))
        self.assertEqual(salary, Path("/slates/d/DKSalaries.csv"))
        self.assertEqual(feed, Path("/slates/d/lineups_feed.json"))

    def test_an_explicit_salary_wins_and_the_staged_file_is_not_consulted(self):
        salary, feed = self.ls.resolve_swap_inputs(
            "/runs/abc/inputs/DKSalaries.csv", None, Path("/slates/d"))
        self.assertEqual(salary, Path("/runs/abc/inputs/DKSalaries.csv"))
        self.assertEqual(feed, Path("/slates/d/lineups_feed.json"),
                         "the feed default is independent of the salary override")

    def test_both_overrides_are_independent(self):
        salary, feed = self.ls.resolve_swap_inputs(
            "/tagged/DKSalaries_1910_8g.csv", "/fresh/lineups_feed.json",
            Path("/slates/d"))
        self.assertEqual(salary, Path("/tagged/DKSalaries_1910_8g.csv"))
        self.assertEqual(feed, Path("/fresh/lineups_feed.json"))

    def test_the_hardcoded_salary_path_is_gone(self):
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertNotIn('salary = slate / "DKSalaries.csv"', text)
        self.assertIn("resolve_swap_inputs(args.salary, args.lineups, slate)", text)

    def test_the_explicit_path_is_the_one_the_cli_actually_checks(self):
        """Exit 4 names the path it looked for, which is how a test sees which
        path the run resolved without running a swap."""
        import subprocess
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            bogus = Path(tmp) / "tagged" / "DKSalaries_1910_8g.csv"
            result = subprocess.run(
                [__import__("sys").executable, str(repo / "tools" / "late_swap.py"),
                 "--date", "2099-01-02", "--parent-entries", str(Path(tmp) / "p.csv"),
                 "--salary", str(bogus)],
                capture_output=True, text=True, cwd=str(repo))
            self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
            self.assertIn(str(bogus), result.stderr)
            # os.sep-agnostic: the same assertion has to hold on Ben's Windows
            # box, where the staged path prints with backslashes, or it passes
            # vacuously there and the negative half proves nothing.
            normalised = result.stderr.replace("\\", "/")
            self.assertNotIn("data/slates/2099-01-02/DKSalaries.csv", normalised)

    def test_the_shared_staging_path_is_flagged_as_shared(self):
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertIn("SHARED staging path", text)

    def test_no_second_entries_path_was_introduced(self):
        """Deliberate: every entries read already comes from --parent-entries, so
        a second entries path would only let the reserved grid disagree with the
        file being refined, and nothing checks that."""
        text = (Path(__file__).resolve().parents[1] / "tools" / "late_swap.py").read_text(
            encoding="utf-8")
        self.assertNotIn('"--entries-source"', text.replace("# ", ""))
        self.assertIn("No --entries-source", text)


class InputsUnmovedTests(unittest.TestCase):
    """R20(b): a staged source clobbered mid-build (the 2026-07-23 incident)
    blocks promotion by name instead of certifying against a vanished world."""

    @staticmethod
    def _run_with_source(root):
        from mlb_engine.pipeline.build_state_manager import (
            create_run, snapshot_run_inputs, update_run_certification)
        source = Path(root) / "DKSalaries.csv"
        source.write_text("v1", encoding="utf-8")
        run = create_run(Path(root) / "runs", "initial_build")
        snapshot_run_inputs(run["run_dir"], [source])
        update_run_certification(run["run_dir"], {
            "workflow_valid": True, "selection_certified": True,
            "allocation_certified": True})
        return run, source

    def test_a_clobbered_staged_source_blocks_promotion(self):
        import json as _json
        import tempfile
        from mlb_engine.pipeline.build_state_manager import promote_run
        with tempfile.TemporaryDirectory() as tmp:
            run, source = self._run_with_source(tmp)
            source.write_text("v2 clobbered by another session",
                              encoding="utf-8")
            result = promote_run(run["run_dir"])
            self.assertFalse(result["passed"])
            self.assertTrue(any("moved underneath the run" in e
                                for e in result["errors"]), result["errors"])
            manifest = _json.loads(
                (Path(run["run_dir"]) / "manifest.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(manifest["status"], "blocked")

    def test_untouched_sources_promote_clean(self):
        import tempfile
        from mlb_engine.pipeline.build_state_manager import promote_run
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = self._run_with_source(tmp)
            result = promote_run(run["run_dir"])
            self.assertTrue(result["passed"], result["errors"])

    def test_a_vanished_source_blocks_too(self):
        import tempfile
        from mlb_engine.pipeline.build_state_manager import promote_run
        with tempfile.TemporaryDirectory() as tmp:
            run, source = self._run_with_source(tmp)
            source.unlink()
            result = promote_run(run["run_dir"])
            self.assertFalse(result["passed"])
            self.assertTrue(any("vanished underneath the run" in e
                                for e in result["errors"]), result["errors"])


class ParentLineageGuardTests(unittest.TestCase):
    """R20(c), swap half: refining a parent the pointer no longer names is a
    block, not a metadata note."""

    def test_a_mismatch_raises(self):
        from mlb_engine.pipeline.execution_pipeline import _assert_parent_lineage
        with self.assertRaises(ValueError):
            _assert_parent_lineage(
                {"current_matches_parent_export": False}, False)

    def test_a_match_passes_and_the_override_is_explicit(self):
        from mlb_engine.pipeline.execution_pipeline import _assert_parent_lineage
        _assert_parent_lineage({"current_matches_parent_export": True}, False)
        _assert_parent_lineage({"current_matches_parent_export": False}, True)


class SolverIndependentBehaviorTests(unittest.TestCase):
    """R6(a): the five behavior tests from the 07-25 final, plus the loud-scipy
    pin. Every test here runs and means something with scipy absent, because
    each drives a production validation or resolution surface that must hold
    whether or not a solver ever runs. The MILP-side enforcement of the same
    contracts is pinned end-to-end by the two golden replays."""

    # -- 1. blank-row block ---------------------------------------------------
    def test_blank_reserved_row_blocks_and_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            r1, _ = legal_rosters(ids)
            # entry 5001 filled, entry 5002 left blank in the "export"
            write_entries(entries, rosters=[r1, None])
            report = validate_dk_entries_file(
                entries, salary_csv_path=salary, require_all_reserved_filled=True)
            self.assertFalse(report["passed"])
            self.assertEqual(report["blank_entries"], ["5002"])
            self.assertTrue(any("5002" in e for e in report["errors"]),
                            "the blocking error must name the blank entry")
            # certification derivation refuses the same fact downstream
            from mlb_engine.entries.dk_entries_manager import derive_workflow_certification
            cert = derive_workflow_certification(
                pre_export={"passed": True, "selection_certified": True},
                post_export={**{k: True for k in (
                    "template_preservation_passed", "entry_reconciliation_passed",
                    "roster_legality_passed", "portfolio_caps_passed",
                    "locked_immutability_passed", "export_hash_binding_passed")},
                    "entry_reconciliation_passed": False},
                allocation_required=False)
            self.assertFalse(cert["workflow_valid"])
            self.assertIn("entry_reconciliation_passed", cert["failed_post_export_gates"])

    # -- 2. over-cap rejection ------------------------------------------------
    def test_over_cap_portfolio_is_rejected_by_the_post_export_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            r1, r2 = legal_rosters(ids)
            write_entries(entries, rosters=[r1, r2])
            # both rosters carry the same SP pair; cap 1 makes count 2 over-cap
            report = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                portfolio_controls={"max_sp_pair_repetition": 1})
            self.assertFalse(report["portfolio_caps_passed"])
            self.assertTrue(any("SP pair" in e and ">1" in e for e in report["errors"]))
            # and the same file under a permissive cap passes the caps gate
            clean = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                portfolio_controls={"max_sp_pair_repetition": 2})
            self.assertTrue(clean["portfolio_caps_passed"])

    def test_cap_count_arithmetic_is_floor_and_both_copies_agree(self):
        """dk_entries_manager._cap_count promises in its docstring that the
        solved model and the post-export validator can never disagree on a cap
        value. Nothing held the two implementations together until now."""
        from mlb_engine.allocate.contest_allocator import _cap_count as solve_side
        from mlb_engine.entries.dk_entries_manager import _cap_count as export_side
        cases = [(18, 0.5), (14, 0.43), (7, 0.35), (4, 0.4), (10, 0.05),
                 (100, 0.29), (18, 1.0), (1, 0.99), (2, 0.5)]
        for total, pct in cases:
            self.assertEqual(solve_side(total, pct), export_side(total, pct),
                             f"cap arithmetic disagrees at ({total}, {pct})")
        self.assertEqual(export_side(18, 0.5), 9)     # exact
        self.assertEqual(export_side(14, 0.43), 6)    # floor(6.02)
        self.assertEqual(export_side(7, 0.35), 2)     # floor(2.45)
        self.assertEqual(export_side(4, 0.4), 1)      # floor(1.6): thin-slate pinch
        self.assertEqual(export_side(10, 0.05), 1)    # max(1, floor(0.5))
        self.assertEqual(export_side(100, 0.29), 29)  # epsilon rescues 28.999...
        self.assertIsNone(export_side(18, None))      # unset means unset
        self.assertIsNone(export_side(18, 0))         # <=0 means not set

    # -- 3. overlap honored on a produced bank --------------------------------
    def test_overlap_and_du_arithmetic_on_fixture_rosters(self):
        """The pairwise overlap contract, tested on the arithmetic the solver
        constraints and the post-export validator are built from. Also the
        first direct coverage of the DU primitives R15 kept (its correction
        note records they had zero direct references in the suite)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            r1, r2 = legal_rosters(ids)
            write_entries(entries, rosters=[r1, r2])
            # r1 and r2 share exactly the two pitchers
            report = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                portfolio_controls={"max_shared_players": 1})
            self.assertEqual(
                [(v["entry_a"], v["entry_b"], v["shared"]) for v in report["overlap_violations"]],
                [("5001", "5002", 2)])
            ok = validate_dk_entries_file(
                entries, salary_csv_path=salary,
                portfolio_controls={"max_shared_players": 2})
            self.assertEqual(ok["overlap_violations"], [])
            # identical signature across contests is approved reuse, never overlap
            same = root / "DKEntries_same.csv"
            write_entries(same, rosters=[r1, r1], contest_ids=["900", "901"])
            reused = validate_dk_entries_file(
                same, salary_csv_path=salary,
                portfolio_controls={"max_shared_players": 1})
            self.assertEqual(reused["overlap_violations"], [])
        from mlb_engine.optimize.optimizer_v3 import du_distance, validate_du_portfolio
        sig_a = {"sp_pair": "10001/10002", "primary_stack": "AAA",
                 "secondary_stack": "CCC", "game_environment": "AAA@BBB",
                 "chalk_one_off": "none"}
        sig_b = dict(sig_a, primary_stack="CCC", secondary_stack="AAA")
        sig_c = dict(sig_a, sp_pair="10001/10003")
        self.assertEqual(du_distance(sig_a, sig_a), 0)
        self.assertEqual(du_distance(sig_a, sig_b), 2)
        self.assertEqual(du_distance(sig_a, sig_c), 1)
        self.assertEqual(du_distance(sig_a, sig_c, exclude_anchor=True), 0)
        verdict = validate_du_portfolio([sig_a, sig_b, sig_c], "wta", (3, 3))
        self.assertFalse(verdict["pass"])
        pairs = {(v["lineup_i"], v["lineup_j"]) for v in verdict["within_family_violations"]}
        self.assertIn((0, 2), pairs)  # distance 1 < 3, recorded i<j
        self.assertTrue(validate_du_portfolio([sig_a, sig_b], "wta", (2, 2))["pass"])

    # -- 4. posture/shape resolution at the front door ------------------------
    def test_checkpoint_resolves_explicit_postures_shapes_and_floors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary = root / "salary.csv"
            ids = write_salary(salary)
            entries = root / "DKEntries.csv"
            write_entries(entries, contest_ids=["900", "901"])
            frame = projection_frame(ids)
            result = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=frame, approve=False,
                contest_postures={"900": "wta_satellite", "901": "large_gpp"})
            self.assertTrue(result["passed"])
            postures = result["posture_by_contest"]
            self.assertEqual(postures["900"]["posture"], "wta_satellite")
            self.assertEqual(postures["901"]["posture"], "large_gpp")
            shapes = {cid: rec["contest_shape"] for cid, rec in postures.items()}
            self.assertNotEqual(shapes["900"], shapes["901"])
            # the satellite pair cap survives the merge with the gpp posture
            self.assertEqual(result["merged_controls"].get("max_sp_pair_repetition"), 2)
            # auto-floors on this deliberately thin fixture are applied AND said
            floors = result["feasibility"]["controls_feasibility"]["floors_applied"]
            self.assertIn("max_shared_players", floors)
            self.assertEqual(floors["max_shared_players"]["reason"], "feasibility floor")
            self.assertNotIn(
                "runs", {p.name for p in root.iterdir()},
                "approve=False must not create a run directory")

    # -- 5. export geometry ----------------------------------------------------
    def test_export_geometry_is_preserved_and_drift_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = write_salary(root / "salary.csv")
            r1, r2 = legal_rosters(ids)
            template = root / "template.csv"
            write_entries(template, rosters=[r1, r2])
            # identical copy preserves
            copy = root / "copy.csv"
            copy.write_bytes(template.read_bytes())
            self.assertTrue(validate_template_preservation(template, copy)["passed"])
            # a mutated non-roster cell (contest id) is named by row and column
            rows = [line.split(",") for line in template.read_text().splitlines()]
            rows[1][2] = "999"
            tampered = root / "tampered.csv"
            tampered.write_text("\n".join(",".join(r) for r in rows))
            verdict = validate_template_preservation(template, tampered)
            self.assertFalse(verdict["passed"])
            self.assertTrue(any("non-roster cell changed at row 2" in e
                                for e in verdict["errors"]))
            # a completed row's roster may change only with an explicit grant
            rows2 = [line.split(",") for line in template.read_text().splitlines()]
            r1_swapped = list(r1); r1_swapped[-1], r1_swapped[-2] = r1_swapped[-2], r1_swapped[-1]
            rows2[1][4:14] = r1_swapped
            swapped = root / "swapped.csv"
            swapped.write_text("\n".join(",".join(r) for r in rows2))
            self.assertFalse(validate_template_preservation(template, swapped)["passed"])
            self.assertTrue(validate_template_preservation(
                template, swapped, mutable_entry_ids=["5001"])["passed"])

    # -- done-when: blocking scipy is loud, never quiet ------------------------
    def test_missing_scipy_is_loud_not_quiet(self):
        from mlb_engine.optimize import optimizer_v3 as opt_mod
        with unittest.mock.patch.object(opt_mod, "SCIPY_AVAILABLE", False), \
                unittest.mock.patch.object(opt_mod, "SCIPY_IMPORT_ERROR", "simulated absence"):
            avail = opt_mod.runtime_preflight()
            self.assertFalse(avail["scipy_available"])
            self.assertFalse(avail["optimizer_certifiable"])
            with self.assertRaises(RuntimeError) as ctx:
                opt_mod._select_solver_backend("auto")
            self.assertIn("simulated absence", str(ctx.exception))
            # optimizer_provenance_line() reports solve HISTORY, not current
            # availability, so it is deliberately not asserted here: under
            # full-suite ordering earlier solves have already succeeded and
            # the line truthfully says so.


class ChangelogDebtTests(unittest.TestCase):
    """The changelog rule has an enforcing path, so it is a MUST and not a hope.

    CLAUDE.md says a DEV change is not shipped until CHANGELOG.md carries its
    entry. The 07-25 review named documented-but-unenforced as a proven failure
    class in this repo, which is the whole reason this check exists rather than
    a third sentence asking nicely.

    Every test here builds a throwaway git repo. Nothing touches the real one.
    """

    def _audit(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "audit.py"
        spec = importlib.util.spec_from_file_location("audit_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _repo(self, tmp):
        root = Path(tmp)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def git(*args):
            subprocess.run(("git", "-C", str(root)) + args, check=True,
                           capture_output=True, env=env)

        subprocess.run(("git", "init", "-q", str(root)), check=True,
                       capture_output=True)
        (root / "mlb_engine").mkdir()
        (root / "tools").mkdir()
        (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (root / "mlb_engine" / "a.py").write_text("x = 1\n", encoding="utf-8")
        git("add", "CHANGELOG.md", "mlb_engine/a.py")
        git("commit", "-q", "-m", "initial, changelog and code together")
        return root, git

    def test_code_and_changelog_in_one_commit_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self._repo(tmp)
            (root / "mlb_engine" / "a.py").write_text("x = 2\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text("# Changelog\n\n- did a thing\n",
                                               encoding="utf-8")
            git("add", "mlb_engine/a.py", "CHANGELOG.md")
            git("commit", "-q", "-m", "R99: a thing, recorded")
            debt = self._audit().changelog_debt(root)
            self.assertTrue(debt["available"])
            self.assertEqual(debt["unrecorded_commits"], 0)

    def test_engine_commits_without_a_changelog_entry_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self._repo(tmp)
            for n in (2, 3):
                (root / "mlb_engine" / "a.py").write_text(f"x = {n}\n",
                                                          encoding="utf-8")
                git("add", "mlb_engine/a.py")
                git("commit", "-q", "-m", f"R99: unrecorded change {n}")
            debt = self._audit().changelog_debt(root)
            self.assertEqual(debt["unrecorded_commits"], 2)
            self.assertTrue(debt["commits"][0].endswith("unrecorded change 3"),
                            "the newest is named first, so the warning is useful")

    def test_a_root_prose_commit_outside_the_write_set_is_not_debt(self):
        # The rule covers the DEV write set. A root-level prose file outside
        # it owes the changelog nothing and must not nag later sessions.
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self._repo(tmp)
            (root / "NOTES.md").write_text("notes\n", encoding="utf-8")
            git("add", "NOTES.md")
            git("commit", "-q", "-m", "notes: scratch")
            self.assertEqual(self._audit().changelog_debt(root)["unrecorded_commits"], 0)

    def test_docs_skills_and_claudemd_commits_are_debt(self):
        # Ben's 2026-08-01 rule: every change, code or otherwise, carries its
        # changelog entry. CLAUDE.md, docs/, and skills/ are changes too.
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self._repo(tmp)
            (root / "docs").mkdir()
            (root / "skills").mkdir()
            (root / "docs" / "plan.md").write_text("p\n", encoding="utf-8")
            git("add", "docs/plan.md")
            git("commit", "-q", "-m", "R99: docs change, unrecorded")
            (root / "skills" / "s.md").write_text("s\n", encoding="utf-8")
            git("add", "skills/s.md")
            git("commit", "-q", "-m", "R99: skill change, unrecorded")
            (root / "CLAUDE.md").write_text("c\n", encoding="utf-8")
            git("add", "CLAUDE.md")
            git("commit", "-q", "-m", "R99: contract change, unrecorded")
            self.assertEqual(self._audit().changelog_debt(root)["unrecorded_commits"], 3)

    def test_backlog_inbox_fragments_are_exempt(self):
        # Fragments are inputs addressed to an owning role, not shipped
        # changes; the owner's merge commit is the change the log records.
        with tempfile.TemporaryDirectory() as tmp:
            root, git = self._repo(tmp)
            (root / "docs" / "backlog_inbox").mkdir(parents=True)
            (root / "docs" / "backlog_inbox" / "f.md").write_text("f\n",
                                                                  encoding="utf-8")
            git("add", "docs/backlog_inbox/f.md")
            git("commit", "-q", "-m", "fragment: for DEV")
            self.assertEqual(self._audit().changelog_debt(root)["unrecorded_commits"], 0)

    def test_it_degrades_to_silence_without_a_changelog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _git = self._repo(tmp)
            (root / "CHANGELOG.md").unlink()
            debt = self._audit().changelog_debt(root)
            self.assertFalse(debt["available"])
            self.assertEqual(debt["unrecorded_commits"], 0)

    def test_it_degrades_to_silence_outside_a_work_tree(self):
        # An audit that fails on its own bookkeeping is worse than a quiet one.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            debt = self._audit().changelog_debt(root)
            self.assertFalse(debt["available"])

    def test_the_claudemd_rule_cites_its_enforcing_path(self):
        text = (Path(__file__).resolve().parent.parent / "CLAUDE.md").read_text(
            encoding="utf-8")
        self.assertIn("CHANGELOG.md carries its entry", text)
        self.assertIn("changelog_debt", text,
                      "a MUST in CLAUDE.md names the code that enforces it, or "
                      "it is guidance wearing a MUST's clothes")


class EnvLockTests(unittest.TestCase):
    """R7: pinned runtime. The lock is the resolution authority, the probe is
    the one instructed command, and every manifest names the versions it ran
    under. The decision logic is tested pure; nothing here touches pip."""

    def _lock_path(self):
        return Path(__file__).resolve().parent.parent / "requirements.lock"

    def test_lock_pins_engine_deps_with_hashes_and_satisfies_floors(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        try:
            import env_probe
        finally:
            sys.path.pop(0)
        text = self._lock_path().read_text(encoding="utf-8")
        pins = env_probe.parse_lock(text)
        for name in ("numpy", "pandas", "scipy"):
            self.assertIn(name, pins, f"lock must pin {name}")
        # every pinned distribution carries a hash line
        pin_lines = [ln for ln in text.splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
        dists = [ln for ln in pin_lines if "==" in ln]
        hashes = [ln for ln in pin_lines if ln.strip().startswith("--hash=sha256:")]
        self.assertEqual(len(dists), len(hashes),
                         "one sha256 hash per pinned distribution")
        # floors in requirements.txt hold under the pins
        floors = {"numpy": (2, 0), "pandas": (2, 2), "scipy": (1, 13)}
        for name, floor in floors.items():
            got = tuple(int(p) for p in pins[name].split(".")[:2])
            self.assertGreaterEqual(got, floor,
                                    f"{name} pin below requirements.txt floor")

    def test_probe_decision_table(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        try:
            import env_probe
        finally:
            sys.path.pop(0)
        pins = {"numpy": "2.2.6", "pandas": "2.3.3", "scipy": "1.15.3"}
        warm = {"numpy": "2.2.6", "pandas": "2.3.3", "scipy": "1.15.3"}
        v = env_probe.evaluate(warm, pins, milp_ok=True)
        self.assertTrue(v["warm"])
        # missing scipy is cold, not a soft warning
        v = env_probe.evaluate({**warm, "scipy": None}, pins, milp_ok=False)
        self.assertFalse(v["warm"])
        self.assertEqual(v["missing"], ["scipy"])
        # a drifted version is cold even though the import succeeds
        v = env_probe.evaluate({**warm, "numpy": "2.3.0"}, pins, milp_ok=True)
        self.assertFalse(v["warm"])
        self.assertIn("numpy 2.3.0 != 2.2.6", v["mismatched"])
        # scipy importable but milp gone is cold: the solver is the point
        v = env_probe.evaluate(warm, pins, milp_ok=False)
        self.assertFalse(v["warm"])

    def test_manifest_records_environment_and_lock_sha(self):
        import numpy, pandas, scipy  # noqa: E401
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock_src = self._lock_path()
            (root / "requirements.lock").write_text(
                lock_src.read_text(encoding="utf-8"), encoding="utf-8")
            run = create_run(root / "runs", "validate_only")
            env = run["manifest"]["environment"]
            self.assertEqual(env["packages"]["numpy"], numpy.__version__)
            self.assertEqual(env["packages"]["pandas"], pandas.__version__)
            self.assertEqual(env["packages"]["scipy"], scipy.__version__)
            self.assertEqual(env["lock_sha256"], sha256_file(root / "requirements.lock"))
        # without a lock beside runs/, the manifest says so rather than guessing
        with tempfile.TemporaryDirectory() as td:
            run = create_run(Path(td) / "runs", "validate_only")
            self.assertIsNone(run["manifest"]["environment"]["lock_sha256"])

    def test_docs_instruct_the_probe_not_raw_pip(self):
        root = Path(__file__).resolve().parent.parent
        skill = (root / "skills" / "generate-lineups" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("tools/env_probe.py --install", skill)
        self.assertNotIn("pip install -r requirements.txt", skill,
                         "SKILL.md must not instruct the unpinned resolve")
        audit_src = (root / "tools" / "audit.py").read_text(encoding="utf-8")
        self.assertIn("env_probe.py --install", audit_src,
                      "the audit remedy names the probe")


class VendoredPylibsTests(unittest.TestCase):
    """R42(a): env_probe.py and audit.py must use a working `.pylibs` before
    either declares scipy missing or reaches for pip. Filed 2026-08-01,
    re-confirmed live twice more on 2026-08-03 -- one build that most likely
    locked two games unbuilt, one saved only by a 26-minute-to-lock handoff.
    Pure filesystem/sys.path logic throughout; no real scipy or pip touched,
    except the one integration test that checks this repo's own vendored copy
    (skipped if the checkout does not have one)."""

    @staticmethod
    def _env_probe():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        try:
            import env_probe
        finally:
            sys.path.pop(0)
        return env_probe

    @staticmethod
    def _audit():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        try:
            import audit
        finally:
            sys.path.pop(0)
        return audit

    def test_absent_pylibs_is_none(self):
        ep = self._env_probe()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ep.vendored_pylibs(Path(tmp)))

    def test_empty_pylibs_dir_is_none(self):
        # An empty directory is not a vendored install; treat it the same as
        # absent rather than reporting a false warm.
        ep = self._env_probe()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".pylibs").mkdir()
            self.assertIsNone(ep.vendored_pylibs(Path(tmp)))

    def test_populated_pylibs_is_found(self):
        ep = self._env_probe()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pylibs = root / ".pylibs"
            pylibs.mkdir()
            (pylibs / "placeholder").write_text("x", encoding="utf-8")
            self.assertEqual(ep.vendored_pylibs(root), pylibs)

    def test_ensure_on_path_inserts_it_and_makes_it_importable(self):
        ep = self._env_probe()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pylibs = root / ".pylibs"
            pylibs.mkdir()
            (pylibs / "totally_fake_r42_module.py").write_text(
                "MARKER = 'vendored'\n", encoding="utf-8")
            import sys as _sys
            before = list(_sys.path)
            try:
                found = ep.ensure_vendored_on_path(root)
                self.assertEqual(found, pylibs)
                self.assertIn(str(pylibs), _sys.path)
                import totally_fake_r42_module as fake  # noqa: F401
                self.assertEqual(fake.MARKER, "vendored")
            finally:
                _sys.path[:] = before
                _sys.modules.pop("totally_fake_r42_module", None)

    def test_ensure_on_path_is_idempotent(self):
        ep = self._env_probe()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pylibs = root / ".pylibs"
            pylibs.mkdir()
            (pylibs / "placeholder").write_text("x", encoding="utf-8")
            import sys as _sys
            before = list(_sys.path)
            try:
                ep.ensure_vendored_on_path(root)
                ep.ensure_vendored_on_path(root)
                self.assertEqual(
                    _sys.path.count(str(pylibs)), 1,
                    "calling twice must not duplicate the sys.path entry")
            finally:
                _sys.path[:] = before

    def test_check_dependencies_reports_the_real_vendored_path(self):
        # Integration point with audit.py, against this checkout's own real
        # .pylibs -- a fake stand-in cannot exercise the actual scipy import.
        audit = self._audit()
        root = Path(__file__).resolve().parent.parent
        if not (root / ".pylibs" / "scipy").is_dir():
            self.skipTest("no vendored .pylibs/scipy in this checkout")
        deps = audit.check_dependencies(root)
        self.assertEqual(deps["vendored_pylibs"], str(root / ".pylibs"))
        self.assertTrue(deps["passed"],
                        "a populated .pylibs must be enough to pass with "
                        "zero installs")

    def test_run_tests_subprocess_gets_the_vendored_pythonpath(self):
        """sys.path mutations in this process do not cross a subprocess
        boundary, so the test-runner subprocess `--run-tests` spawns needs
        `.pylibs` on its own PYTHONPATH explicitly -- otherwise a warm
        dependency check can be followed by a test run that cannot import
        scipy at all, which is worse than an honest cold report."""
        audit = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_core.py").write_text("", encoding="utf-8")
            fake_deps = {
                "required": [], "missing": [], "scipy_milp_available": True,
                "passed": True, "vendored_pylibs": "/fake/.pylibs",
                "remedy": None,
            }
            fake_result = subprocess.CompletedProcess(
                args=["fake"], returncode=0,
                stdout="Ran 0 tests in 0.0s\n\nOK\n", stderr="")
            with unittest.mock.patch.object(
                    audit, "check_dependencies", return_value=fake_deps), \
                unittest.mock.patch.object(
                    audit.subprocess, "run", return_value=fake_result) as spy:
                audit.run_audit(root, run_tests=True)
            self.assertTrue(spy.called)
            env_used = spy.call_args.kwargs.get("env") or {}
            self.assertIn(
                "/fake/.pylibs", env_used.get("PYTHONPATH", ""),
                "the test subprocess must inherit the vendored path "
                "check_dependencies found, not just this process's sys.path")


class PrimaryStackSizeFloorTests(unittest.TestCase):
    """R34: the primary-stack SIZE control.

    Everything asserted here is engine behaviour. The archive evidence that
    motivated the control is an observed outcome and a deterministic
    descriptive statistic; no test here asserts that a shape wins, because the
    engine cannot know that and neither can the archive.
    """

    @staticmethod
    def _lineup(primary_count, primary="NYY", filler="BOS"):
        rows = []
        pos = ["OF", "1B", "2B", "3B", "SS", "C", "OF", "OF"]
        for i in range(8):
            rows.append({
                "Player": f"h{i}", "Player_ID": str(i + 1),
                "Team": primary if i < primary_count else filler,
                "Position": pos[i],
            })
        rows.append({"Player": "p1", "Player_ID": "9", "Team": "SEA", "Position": "P"})
        rows.append({"Player": "p2", "Player_ID": "10", "Team": "TEX", "Position": "P"})
        return pd.DataFrame(rows)

    def test_size_helper_counts_the_primary_stack(self):
        self.assertEqual(opt.candidate_primary_stack_size(self._lineup(5)), 5)
        self.assertEqual(opt.candidate_primary_stack_size(self._lineup(4)), 4)
        self.assertEqual(opt.candidate_primary_stack(self._lineup(5)), "NYY")

    def test_stackless_lineup_reports_zero_not_none(self):
        # eight different teams: no team reaches PRIMARY_STACK_MIN_HITTERS
        df = pd.DataFrame([
            {"Player": f"h{i}", "Player_ID": str(i + 1), "Team": f"T{i}",
             "Position": ["OF", "1B", "2B", "3B", "SS", "C", "OF", "OF"][i]}
            for i in range(8)
        ] + [
            {"Player": "p1", "Player_ID": "9", "Team": "SEA", "Position": "P"},
            {"Player": "p2", "Player_ID": "10", "Team": "TEX", "Position": "P"},
        ])
        self.assertEqual(opt.candidate_primary_stack(df), "")
        self.assertEqual(opt.candidate_primary_stack_size(df), 0)

    def test_allocator_reads_size_and_defaults_to_zero_on_a_stale_bank(self):
        from mlb_engine.allocate.contest_allocator import _candidate_primary_stack_size as size
        self.assertEqual(size({"primary_stack_size": 5}), 5)
        self.assertEqual(size({"contest_fit": {"primary_stack_size": 4}}), 4)
        # a candidate built before the field existed must NOT count toward a
        # floor it may not meet
        self.assertEqual(size({"primary_stack": "NYY"}), 0)
        self.assertEqual(size({"primary_stack_size": "junk"}), 0)

    def test_floor_selects_the_five_stack_over_the_higher_scoring_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = write_salary(Path(tmp) / "salary.csv")
            r1, r2 = legal_rosters(ids)
            four = candidate("four", r1, 100); four["primary_stack_size"] = 4
            five = candidate("five", r2, 1, "CCC"); five["primary_stack_size"] = 5
            entries = [{"entry_id": "1", "contest_id": "x", "contest_shape": "large_wta"}]
            # off: the objective wins and the 4-stack is taken
            off = select_and_assign_entries([four, five], entries, {"max_shared_players": 9})
            self.assertTrue(off["passed"])
            self.assertEqual(off["assignments"][0]["candidate_id"], "four")
            # on: the floor binds even though the 5-stack scores 99 points worse
            on = select_and_assign_entries(
                [four, five], entries,
                {"max_shared_players": 9, "min_five_stack_share_pct": 1.0},
            )
            self.assertTrue(on["passed"])
            self.assertEqual(on["assignments"][0]["candidate_id"], "five")
            self.assertEqual(on["assignments"][0]["primary_stack_size"], 5)

    def test_floor_names_the_constraint_when_no_candidate_qualifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids = write_salary(Path(tmp) / "salary.csv")
            r1, r2 = legal_rosters(ids)
            a = candidate("a", r1, 100); a["primary_stack_size"] = 4
            b = candidate("b", r2, 99, "CCC"); b["primary_stack_size"] = 4
            res = select_and_assign_entries(
                [a, b],
                [{"entry_id": "1", "contest_id": "x", "contest_shape": "large_wta"}],
                {"max_shared_players": 9, "min_five_stack_share_pct": 1.0},
            )
            self.assertFalse(res["passed"])
            self.assertFalse(res["selection_certified"])
            joined = " ".join(res["errors"])
            self.assertIn("min_five_stack_share_pct", joined)
            self.assertIn("0 such candidates", joined)
            self.assertIn("never trim the pool", joined)

    def test_posture_default_is_off_so_behaviour_is_unchanged(self):
        for posture, spec in epi.STRATEGY_DEFAULTS.items():
            share = spec["controls"].get("min_five_stack_share_pct", 0.0)
            self.assertEqual(
                float(share or 0.0), 0.0,
                f"{posture} ships the five-stack quota on; R34 ships it off",
            )

    def test_floor_merges_to_the_least_demanding_posture(self):
        merged = epi._merged_controls_for_build(
            {"a": {"posture": "wta_satellite"}, "b": {"posture": "large_gpp"}}, None)
        # wta_satellite declares the key at 0.0; large_gpp does not declare it,
        # so the merge takes the least demanding value it saw
        self.assertEqual(merged.get("min_five_stack_share_pct", 0.0), 0.0)
        # a floor present on one posture only still merges down, never up
        with unittest.mock.patch.dict(
            epi.STRATEGY_DEFAULTS["wta_satellite"]["controls"],
            {"min_five_stack_share_pct": 0.6}, clear=False,
        ):
            both = epi._merged_controls_for_build(
                {"a": {"posture": "wta_satellite"}, "b": {"posture": "large_gpp"}}, None)
            self.assertEqual(both.get("min_five_stack_share_pct", 0.0), 0.0)
            alone = epi._merged_controls_for_build({"a": {"posture": "wta_satellite"}}, None)
            self.assertAlmostEqual(alone["min_five_stack_share_pct"], 0.6)

    def test_feasibility_relaxes_the_quota_downward_not_upward(self):
        with unittest.mock.patch.dict(
            epi.STRATEGY_DEFAULTS["wta_satellite"]["controls"],
            {"min_five_stack_share_pct": 0.6}, clear=False,
        ):
            floors = {"min_five_stack_share_pct": 0.2}
            out = epi._merged_controls_for_build(
                {"a": {"posture": "wta_satellite"}}, None, feasibility_floors=floors)
            self.assertAlmostEqual(out["min_five_stack_share_pct"], 0.2,
                                   msg="a thin slate must lower the quota, not raise it")

    def test_feasibility_caps_the_quota_by_stackable_teams_times_exposure(self):
        floors = epi.feasibility_floors_from({
            "available": True, "stackable_team_count": 2,
            "floor_stack_exposure_pct": 0.35,
        })
        # two stackable teams at a 35% team cap cannot put more than 70% of the
        # bank into five-stacks
        self.assertAlmostEqual(floors["min_five_stack_share_pct"], 0.70)
        wide = epi.feasibility_floors_from({
            "available": True, "stackable_team_count": 6,
            "floor_stack_exposure_pct": 0.35,
        })
        self.assertEqual(wide["min_five_stack_share_pct"], 1.0)

    def test_bank_build_keeps_the_old_hardcoded_floor_as_its_default(self):
        sig = inspect.signature(opt.build_diverse_candidate_bank)
        self.assertEqual(sig.parameters["bank_stack_min_size"].default, 4)
        self.assertEqual(sig.parameters["bank_secondary_size"].default, 0)


class RebuildRegistryResolutionTests(unittest.TestCase):
    """R97: the rebuild resolves salary the way the miner does, and --restart
    survives a filesystem that refuses deletion."""

    @staticmethod
    def _tool():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_rebuild_registry_tool",
            Path(__file__).resolve().parents[1] / "tools" / "rebuild_registry.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_rebuild_cannot_reach_the_pooled_resolver(self):
        """One question, one policy. The tool imports the tiered resolver and
        does NOT import the repo-wide pooled one, so it cannot silently drift
        back to scoring 289 candidates against every contest the way it did
        before R97 -- the name is not in its namespace to call."""
        mod = self._tool()
        self.assertTrue(hasattr(mod, "resolve_salary_tiered"))
        self.assertFalse(
            hasattr(mod, "resolve_salary_file"),
            msg="rebuild_registry must not carry the pooled resolver; R49 "
                "replaced it in the miner and R97 replaced it here")
        self.assertFalse(
            hasattr(mod, "default_salary_candidates"),
            msg="the repo-wide candidate list is the pooled policy's input; "
                "the tiered resolver builds its own tiers")

    def test_discard_staged_deletes_when_the_filesystem_allows_it(self):
        mod = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / ".registry.rebuild"
            staged.write_text(json.dumps({"contests_mined": ["1", "2"]}), encoding="utf-8")
            self.assertEqual(mod.discard_staged(staged), "deleted")
            self.assertFalse(staged.exists())

    def test_discard_staged_truncates_when_unlink_is_refused(self):
        """The Cowork device mount raises PermissionError on unlink, so the
        flag whose whole job is to start clean used to crash before mining
        anything. Truncating to {} is equivalent for every reader: nothing
        resumes, and update_registry setdefaults from {} exactly as it does
        from a missing file."""
        mod = self._tool()
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / ".registry.rebuild"
            staged.write_text(json.dumps({"contests_mined": ["1", "2"]}), encoding="utf-8")

            def refuse(self, *a, **k):
                raise PermissionError(1, "Operation not permitted")

            with unittest.mock.patch.object(Path, "unlink", refuse):
                self.assertEqual(mod.discard_staged(staged), "truncated")
            self.assertTrue(staged.exists())
            payload = json.loads(staged.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("contests_mined", []), [],
                             msg="a truncated stage must resume nothing")


class PrimaryStackFloorTests(unittest.TestCase):
    """R37 stage 1: the universal primary-stack SIZE floor.

    Ben's dated decision of 2026-08-09. Three tranches put the `<=3-primary`
    family negative while our own share of it climbed to 26.3%, and the
    2026-08-05 probe priced a floor of 4 at 0.00-0.76% of the unconstrained
    objective. What is pinned here is the MECHANISM, not the numbers: that the
    floor binds, that it relaxes and counts rather than starving an entry, that
    it refuses to guess when the bank cannot be read, and that it is absent
    when nobody asked for it.
    """

    ENTRIES = [
        {"entry_id": "1", "contest_id": "x", "contest_shape": "large_field_gpp"},
        {"entry_id": "2", "contest_id": "x", "contest_shape": "large_field_gpp"},
    ]

    @staticmethod
    def _cand(cid, roster, score, size, primary="AAA"):
        payload = candidate(cid, roster, score, primary)
        if size is not None:
            payload["primary_stack_size"] = size
        return payload

    def _bank(self, sizes, scores=None):
        """One candidate per size, each on a disjoint-enough roster.

        ``scores`` matters more than it looks. Left to descend with the index,
        the solver picks the leading candidates anyway and a floor that is never
        enforced still passes -- the test would be measuring the report instead
        of the constraint. Callers that care put the ineligible candidate on top.
        """
        out = []
        for i, size in enumerate(sizes):
            roster = [f"P{i}a", f"P{i}b"] + [f"H{i}_{j}" for j in range(8)]
            score = (scores or [100 - j for j in range(len(sizes))])[i]
            out.append(self._cand(f"c{i}", roster, score, size))
        return out

    def test_the_floor_excludes_a_smaller_stack_and_counts_what_it_dropped(self):
        """The three-stack is the BEST-scoring candidate here, so an unenforced
        floor selects it and this test fails. That is the point: a floor whose
        removal changes no outcome is a floor that was never binding."""
        bank = self._bank([4, 4, 3], scores=[98, 97, 100])
        unfloored = select_and_assign_entries(bank, self.ENTRIES, {})
        self.assertIn("c2", {a["candidate_id"] for a in unfloored["assignments"]},
                      "fixture is wrong: the three-stack must win without the floor")

        result = select_and_assign_entries(
            bank, self.ENTRIES, {"primary_stack_min_size": 4})
        self.assertTrue(result["passed"], result.get("errors"))
        block = result["primary_stack_floor"]
        self.assertEqual(block["applied"], 4)
        self.assertEqual(block["status"], "applied")
        self.assertEqual(block["relaxations"], 0)
        self.assertEqual(block["candidates_excluded"], 1)
        self.assertEqual(block["size_histogram"], {"3": 1, "4": 2})
        self.assertEqual(block["assigned_below_requested"], 0)
        self.assertNotIn("c2", {a["candidate_id"] for a in result["assignments"]},
                         "the three-stack was still selected, so the floor is inert")

    def test_a_bank_the_floor_cannot_carry_relaxes_and_counts_instead_of_starving(self):
        """The Showdown rule, applied here: relax before you truncate. A floor
        that refuses leaves a blank reserved row, and a blank row blocks
        certification -- which is strictly worse than a counted relaxation."""
        result = select_and_assign_entries(
            self._bank([3, 3, 3]), self.ENTRIES, {"primary_stack_min_size": 4})
        self.assertTrue(result["passed"], result.get("errors"))
        block = result["primary_stack_floor"]
        self.assertEqual(block["requested"], 4)
        self.assertEqual(block["applied"], 3)
        self.assertEqual(block["status"], "applied_relaxed")
        self.assertEqual(block["relaxations"], 1)
        self.assertEqual(block["relaxation_steps"][0]["from"], 4)
        self.assertEqual(block["relaxation_steps"][0]["to"], 3)
        self.assertEqual(block["relaxation_steps"][0]["trigger"],
                         "entry_starved_before_solve")
        self.assertEqual(block["assigned_below_requested"], 2)
        self.assertTrue(
            any("relaxed 1 time" in w for w in result.get("warnings", [])),
            f"a relaxation must be stated, not just counted: {result.get('warnings')}")

    def test_a_bank_that_reports_no_size_at_all_is_unmeasurable_not_empty(self):
        """The failure this repairs. Before R37 `bank_cache.as_candidates`
        emitted the stack TEAM and not the SIZE, so every sliced-path candidate
        read 0 -- the same value a stackless lineup carries. Excluding a whole
        bank on the strength of a field its producer never wrote is the worst
        available reading of that ambiguity."""
        result = select_and_assign_entries(
            self._bank([None, None, None]), self.ENTRIES,
            {"primary_stack_min_size": 4})
        self.assertTrue(result["passed"], result.get("errors"))
        block = result["primary_stack_floor"]
        self.assertEqual(block["status"], "unmeasurable")
        self.assertIsNone(block["applied"])
        self.assertEqual(block["candidates_excluded"], 0)
        self.assertTrue(any("NOT enforced" in w for w in result.get("warnings", [])))

    def test_an_absent_control_leaves_the_result_shape_exactly_as_it_was(self):
        """Absent means absent: no exclusion, and no floor key on the result."""
        result = select_and_assign_entries(self._bank([4, 3]), self.ENTRIES, {})
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertNotIn("primary_stack_floor", result)
        self.assertEqual(
            {a["candidate_id"] for a in result["assignments"]}, {"c0", "c1"},
            "with no floor requested the three-stack stays selectable")

    def test_the_ladder_stops_at_the_bucket_rule_then_switches_off(self):
        from mlb_engine.allocate.contest_allocator import primary_stack_floor_rungs
        self.assertEqual(primary_stack_floor_rungs(4), [4, 3, None])
        self.assertEqual(primary_stack_floor_rungs(5), [5, 4, 3, None])
        # Below the bucket rule the quantity is always 0, so a floor of 2 would
        # exclude every candidate while looking like the loosest rung there is.
        self.assertEqual(primary_stack_floor_rungs(2), [None])

    def test_every_posture_declares_the_floor_so_the_merge_is_unanimous(self):
        for posture, spec in epi.STRATEGY_DEFAULTS.items():
            self.assertEqual(
                spec["controls"].get("primary_stack_min_size"), 4,
                f"{posture} does not declare the floor; one silent posture "
                f"retires it for the whole portfolio")
        merged = epi._merged_controls_for_build(
            {"1": {"posture": "wta_satellite"}, "2": {"posture": "cash"}}, None)
        self.assertEqual(merged["primary_stack_min_size"], 4)
        self.assertIsInstance(merged["primary_stack_min_size"], int)

    def test_one_silent_posture_still_retires_the_floor_for_the_portfolio(self):
        """The R34 floor-merge rule, which R37 inherits rather than restates. A
        portfolio serving a contest that never asked for the floor must not
        carry one; forcing it on is a strategy change made invisibly."""
        silent = dict(epi.STRATEGY_DEFAULTS["cash"])
        silent["controls"] = {}
        with unittest.mock.patch.dict(
                epi.STRATEGY_DEFAULTS, {"cash": silent}, clear=False):
            merged = epi._merged_controls_for_build(
                {"1": {"posture": "wta_satellite"}, "2": {"posture": "cash"}}, None)
        self.assertEqual(merged["primary_stack_min_size"], 0,
                         "a silent posture must retire the floor, not inherit it")

    def test_the_mme_plan_string_no_longer_claims_a_five_three(self):
        """The archive has 5-3 at-share in every slice measured, and the
        mini-MAX slice this posture serves prefers the lone five. The retired
        name stays in the size map because archived records still carry it."""
        self.assertNotEqual(epi.STRATEGY_DEFAULTS["mme"]["stack_plan"],
                            "five_three_with_diversification")
        self.assertEqual(
            epi._STACK_SIZE_BY_PLAN[epi.STRATEGY_DEFAULTS["mme"]["stack_plan"]], 5,
            "the label changed; the size it resolves to must not")
        self.assertEqual(
            epi._STACK_SIZE_BY_PLAN.get("five_three_with_diversification"), 5,
            "a replayed record carrying the old name must still resolve")

    def test_the_bank_cache_payload_carries_the_size_the_lineup_has(self):
        """The plumbing the floor rides on, pinned at its producer. This is the
        test that would have caught the original omission: the team was emitted
        and the count was not, which reads as working."""
        from mlb_engine.optimize.bank_cache import BankCache
        from mlb_engine.allocate.contest_allocator import _candidate_primary_stack_size
        with tempfile.TemporaryDirectory() as tmp:
            ids = write_salary(Path(tmp) / "salary.csv")
            frame = projection_frame(ids)
            roster, _ = legal_rosters(ids)
            cache = BankCache(Path(tmp) / "bank.json")
            self.assertTrue(cache.add(roster, 100.0, job="j0"))
            payload = cache.as_candidates(frame, requested_n=1)[0]
            expected = opt.candidate_primary_stack_size(
                frame.assign(pid=frame["Player_ID"].astype(str))
                     .set_index("pid", drop=False).loc[[str(p) for p in roster]])
            self.assertEqual(payload["primary_stack_size"], expected)
            self.assertEqual(_candidate_primary_stack_size(payload), expected)
            self.assertGreater(expected, 0, "the fixture roster carries a real stack")


class SyncCheckTests(unittest.TestCase):
    """R102. The three-way sync report.

    The rule these pin: this mount reports mtime changes as modifications, so
    every claim of drift must be confirmed against content, and a GitHub head
    that was never actually read must be reported as unread rather than as
    agreement."""

    def test_stat_noise_is_not_reported_as_a_change(self):
        from tools import sync_check
        porcelain = " M tools/audit.py\n M CLAUDE.md\n M tests/test_core.py\n"
        # Only one of the three differs from HEAD by content.
        out = sync_check.classify_dirt(porcelain, "tools/audit.py\n")
        self.assertEqual(out["real_modified"], ["tools/audit.py"])
        self.assertEqual(out["stat_noise"], ["CLAUDE.md", "tests/test_core.py"])

    def test_content_wins_when_porcelain_misses_a_file(self):
        """The regression this pins, found on the mount 2026-08-10. Seconds
        after a write-back the mount served a stale stat, so `git status`
        omitted a CHANGELOG.md that `git diff HEAD` scored at +51 lines.
        Deriving modifications from porcelain made the file vanish from every
        bucket. A sync tool that under-reports drift is worse than none."""
        from tools import sync_check
        out = sync_check.classify_dirt(" M tools/audit.py\n",
                                       "tools/audit.py\nCHANGELOG.md\n")
        self.assertIn("CHANGELOG.md", out["real_modified"])
        self.assertNotIn("CHANGELOG.md", out["stat_noise"])

    def test_untracked_is_separated_from_modified(self):
        from tools import sync_check
        out = sync_check.classify_dirt("?? notes.md\n M tools/audit.py\n",
                                       "tools/audit.py\n")
        self.assertEqual(out["untracked"], ["notes.md"])
        self.assertEqual(out["real_modified"], ["tools/audit.py"])
        self.assertEqual(out["stat_noise"], [])

    def test_a_rename_is_keyed_to_its_destination(self):
        from tools import sync_check
        out = sync_check.classify_dirt('R  old.py -> tools/new.py\n',
                                       "tools/new.py\n")
        self.assertEqual(out["real_modified"], ["tools/new.py"])

    def test_a_placeholder_token_is_not_a_credential(self):
        """The container ships GH_TOKEN and GITHUB_TOKEN set to 14-character
        stubs. Treating one as real produces an auth failure that reads like a
        network outage, which is the wrong thing to go debugging."""
        from tools import sync_check
        name, token = sync_check.find_token({"GH_TOKEN": "x" * 14})
        self.assertIsNone(name)
        self.assertIsNone(token)

    def test_gh_pat_wins_over_the_container_stubs(self):
        from tools import sync_check
        name, token = sync_check.find_token(
            {"GH_TOKEN": "y" * 14, "GH_PAT": "z" * 40})
        self.assertEqual(name, "GH_PAT")
        self.assertEqual(token, "z" * 40)

    def test_unmeasured_github_is_never_called_agreement(self):
        from tools import sync_check
        code, lines = sync_check.verdict({
            "local_head": "a" * 40, "origin_ref": "a" * 40,
            "ever_fetched": False, "token_env_var": None,
            "remote_reachable": False, "remote_head": None,
            "ahead_of_origin_ref": 0, "behind_origin_ref": 0,
            "dirt": {"real_modified": [], "stat_noise": [], "untracked": []},
            "errors": []})
        self.assertEqual(code, 0)
        body = "\n".join(lines)
        self.assertIn("unmeasured", body)
        self.assertIn("never fetched", body)
        self.assertNotIn("disk and GitHub agree", body)

    def test_unpushed_commits_are_drift(self):
        from tools import sync_check
        code, lines = sync_check.verdict({
            "local_head": "b" * 40, "origin_ref": "a" * 40,
            "ever_fetched": False, "token_env_var": None,
            "remote_reachable": False, "remote_head": None,
            "ahead_of_origin_ref": 1, "behind_origin_ref": 0,
            "dirt": {"real_modified": [], "stat_noise": [], "untracked": []},
            "errors": []})
        self.assertEqual(code, 2)
        self.assertIn("push from Windows", "\n".join(lines))

    def test_a_measured_matching_remote_is_agreement(self):
        from tools import sync_check
        code, lines = sync_check.verdict({
            "local_head": "c" * 40, "origin_ref": "c" * 40,
            "ever_fetched": True, "token_env_var": "GH_PAT",
            "remote_reachable": True, "remote_head": "c" * 40,
            "ahead_of_origin_ref": 0, "behind_origin_ref": 0,
            "dirt": {"real_modified": [], "stat_noise": [], "untracked": []},
            "errors": []})
        self.assertEqual(code, 0)
        self.assertIn("disk and GitHub agree", "\n".join(lines))

    def test_stat_noise_alone_does_not_raise_the_exit_code(self):
        from tools import sync_check
        code, lines = sync_check.verdict({
            "local_head": "d" * 40, "origin_ref": "d" * 40,
            "ever_fetched": True, "token_env_var": "GH_PAT",
            "remote_reachable": True, "remote_head": "d" * 40,
            "ahead_of_origin_ref": 0, "behind_origin_ref": 0,
            "dirt": {"real_modified": [], "stat_noise": ["a.py", "b.py"],
                     "untracked": []},
            "errors": []})
        self.assertEqual(code, 0)
        self.assertIn("stat noise", "\n".join(lines))

    def test_uncommitted_content_is_drift(self):
        from tools import sync_check
        code, _ = sync_check.verdict({
            "local_head": "e" * 40, "origin_ref": "e" * 40,
            "ever_fetched": True, "token_env_var": "GH_PAT",
            "remote_reachable": True, "remote_head": "e" * 40,
            "ahead_of_origin_ref": 0, "behind_origin_ref": 0,
            "dirt": {"real_modified": ["mlb_engine/optimize/bank_cache.py"],
                     "stat_noise": [], "untracked": []},
            "errors": []})
        self.assertEqual(code, 2)

    def test_a_ref_resolves_out_of_packed_refs(self):
        """Reading refs off the filesystem avoids a git call, and therefore an
        index.lock this mount cannot unlink. Packed refs must still resolve."""
        from tools import sync_check
        with tempfile.TemporaryDirectory() as tmp:
            git = Path(tmp) / ".git"
            git.mkdir()
            (git / "packed-refs").write_text(
                "# pack-refs with: peeled fully-peeled sorted \n"
                f"{'f' * 40} refs/heads/main\n", encoding="utf-8")
            self.assertEqual(
                sync_check._read_ref(Path(tmp), "refs/heads/main"), "f" * 40)


class ClaimReleaseMarkerTests(unittest.TestCase):
    """R102. A hand-written RELEASED marker does not release a claim.

    CLAUDE.md used to say it did. It cannot: `take` clears the marker with
    unlink, which fails on this mount, so making the marker authoritative
    would report a live claim as free. The tool fails closed and says so."""

    def _claim(self, root, name, released=False, marker=False):
        target = Path(root) / "claims" / name
        target.mkdir(parents=True)
        (target / "owner.json").write_text(json.dumps({
            "role": "DEV", "scope": "",
            "taken_utc": "2026-08-10T01:05:16Z",
            "released_utc": "2026-08-10T02:00:00Z" if released else None,
        }), encoding="utf-8")
        if marker:
            (target / "RELEASED").touch()
        return target

    def test_a_marker_alone_leaves_the_claim_held(self):
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            target = self._claim(tmp, "engine_2026-08-10", marker=True)
            self.assertTrue(claim._is_held(target))
            self.assertTrue(claim._release_incomplete(target))

    def test_a_completed_release_is_not_flagged(self):
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            target = self._claim(tmp, "engine_2026-08-10",
                                 released=True, marker=True)
            self.assertFalse(claim._is_held(target))
            self.assertFalse(claim._release_incomplete(target))

    def test_a_held_claim_without_a_marker_is_not_flagged(self):
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            target = self._claim(tmp, "engine_2026-08-10")
            self.assertTrue(claim._is_held(target))
            self.assertFalse(claim._release_incomplete(target))

    def test_check_names_the_command_that_completes_the_release(self):
        """The failure this closes: a marker-only release left an engine claim
        reading HELD for three hours, and nothing on screen said why."""
        import contextlib
        import io
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            self._claim(tmp, "engine_2026-08-10", marker=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = claim.main(["--root", tmp, "check", "engine",
                                   "--date", "2026-08-10"])
            out = buf.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("HELD", out)
            self.assertIn("release engine_2026-08-10", out)

    def test_take_on_an_incomplete_release_blocks_and_explains(self):
        import contextlib
        import io
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            self._claim(tmp, "engine_2026-08-10", marker=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = claim.main(["--root", tmp, "take", "engine",
                                   "--role", "DEV", "--date", "2026-08-10"])
            out = buf.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("does not release", out)

    def test_release_then_check_is_clean(self):
        import contextlib
        import io
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            self._claim(tmp, "engine_2026-08-10", marker=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(claim.main(
                    ["--root", tmp, "release", "engine",
                     "--date", "2026-08-10"]), 0)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = claim.main(["--root", tmp, "check", "engine",
                                   "--date", "2026-08-10"])
            self.assertEqual(code, 0)
            self.assertIn("free", buf.getvalue())


class ClaimStaleSweepTests(unittest.TestCase):
    """R110(a) plus the sweep that uses it.

    `check` and `sweep` print the DATED directory name and `_incomplete_note`
    interpolates it into the release command they tell the operator to run, but
    `release` re-derived the name and appended today's date again. The printed
    command therefore failed on every claim whose directory is not exactly
    `<resource>`, which is the loop that leaves a session hand-writing a
    RELEASED marker: seven claims sat HELD-with-a-marker on 2026-08-12.
    """

    def _claim(self, root, name, *, role="DEV", taken, marker=False):
        target = Path(root) / "claims" / name
        target.mkdir(parents=True)
        (target / "owner.json").write_text(json.dumps({
            "role": role, "scope": "", "taken_utc": taken,
            "released_utc": None,
        }), encoding="utf-8")
        if marker:
            (target / "RELEASED").touch()
        return target

    def _run(self, argv):
        import contextlib
        import io
        from tools import claim
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = claim.main(argv)
        return code, buf.getvalue()

    def test_the_command_check_prints_actually_releases_the_claim(self):
        """Teeth: with `release` re-deriving the name, this exits 3 with
        'no claim at claims/engine_2026-08-04_full_audit_<today>'. That exact
        failure is R110's reproduction."""
        with tempfile.TemporaryDirectory() as tmp:
            self._claim(tmp, "engine_2026-08-04_full_audit",
                        taken="2026-08-04T18:47:06Z", marker=True)
            code, out = self._run(["--root", tmp, "check"])
            self.assertEqual(code, 0)
            self.assertIn("release engine_2026-08-04_full_audit", out)
            # The name the tool printed, run verbatim.
            code, _ = self._run(["--root", tmp, "release",
                                 "engine_2026-08-04_full_audit"])
            self.assertEqual(code, 0)
            code, out = self._run(["--root", tmp, "sweep"])
            self.assertIn("no stale held claims", out)

    def test_the_bare_resource_name_still_releases(self):
        """The other end of the round trip must keep working: `release engine`
        resolves to today's dated directory when no exact match exists."""
        with tempfile.TemporaryDirectory() as tmp:
            from tools import claim
            self._claim(tmp, f"engine_{claim._today()}",
                        taken="2026-08-12T20:07:03Z")
            code, _ = self._run(["--root", tmp, "release", "engine"])
            self.assertEqual(code, 0)

    def test_take_does_not_mint_a_doubled_name(self):
        """`engine_2026-08-10_2026-08-10` in claims/ is what this produced."""
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = self._run(["--root", tmp, "take", "engine_2026-08-10",
                                 "--role", "DEV"])
            self.assertEqual(code, 0)
            names = {p.name for p in (Path(tmp) / "claims").iterdir()}
            self.assertEqual(names, {"engine_2026-08-10"})

    def test_sweep_release_clears_every_stale_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._claim(tmp, "engine_2026-08-04_full_audit",
                        taken="2026-08-04T18:47:06Z", marker=True)
            self._claim(tmp, "slate_2026-07-30_1910_6g", role="BUILD",
                        taken="2026-07-30T21:24:23Z")
            code, out = self._run(["--root", tmp, "sweep", "--release"])
            self.assertEqual(code, 0)
            self.assertIn("released 2 stale held claim(s)", out)
            _, after = self._run(["--root", tmp, "sweep"])
            self.assertIn("no stale held claims", after)

    def test_sweep_release_never_touches_a_claim_taken_today(self):
        """Staleness is owner.json's `taken_utc`, not the name's date.

        Teeth: reading staleness off the name alone releases this claim while
        the summary line prints that nothing taken today was touched, which is
        a live session's mutex cleared under a false reassurance.
        """
        from tools import claim
        with tempfile.TemporaryDirectory() as tmp:
            # Old-looking NAME, taken now.
            self._claim(tmp, "engine_2026-08-10",
                        taken=f"{claim._today()}T20:08:28Z")
            code, out = self._run(["--root", tmp, "sweep", "--release"])
            self.assertEqual(code, 0)
            self.assertIn("no stale held claims", out)
            code, _ = self._run(["--root", tmp, "check", "engine_2026-08-10"])
            self.assertEqual(code, 2, "a claim taken today must survive a sweep")

    def test_plain_sweep_still_releases_nothing(self):
        """The reporting form is what a session runs at start; it must stay
        read-only, because releasing is Ben's call per the contract."""
        with tempfile.TemporaryDirectory() as tmp:
            self._claim(tmp, "slate_2026-07-30_1910_6g", role="BUILD",
                        taken="2026-07-30T21:24:23Z")
            code, out = self._run(["--root", tmp, "sweep"])
            self.assertEqual(code, 0)
            self.assertIn("nothing is deleted here", out)
            code, _ = self._run(["--root", tmp, "check",
                                 "slate_2026-07-30_1910_6g"])
            self.assertEqual(code, 2)


class AuditSkipHonestyTests(unittest.TestCase):
    """R62(b): the audit must not advise lowering the pin over lost coverage.

    The defect, reconfirmed the day this landed: the R101 dev cycle ran against
    a matched-dependency copy of the tree off this machine, got `Ran 783`
    against a pin of 792, and the audit said "the suite passed, so this is a
    stale pin. Update EXPECTED_TEST_COUNT." The nine missing tests were
    `test_golden_replay` in full. Following that advice writes the golden
    replay out of the gate permanently, and nothing would ever say so.

    Two unittest behaviours make this invisible without per-suite pins, both
    measured on 3.10 while writing this:
      - a class-level `skipUnless` keeps its tests in `Ran` AND adds them to
        `skipped`, so the count holds while coverage drops;
      - a `setUpClass` raising SkipTest removes the whole class from `Ran` and
        adds exactly ONE to `skipped`, so nine lost tests report "skipped=1".
    """

    def _audit(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "audit.py"
        spec = importlib.util.spec_from_file_location("audit_skip_honesty", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_pinned_total_is_the_sum_of_the_per_suite_pins(self):
        audit = self._audit()
        self.assertEqual(audit.EXPECTED_TEST_COUNT,
                         sum(audit.EXPECTED_SUITE_COUNTS.values()))

    def test_every_audited_suite_carries_its_own_pin(self):
        """A suite added to the gate without a pin is a suite whose shortfall
        cannot be attributed, which is the whole defect."""
        audit = self._audit()
        self.assertEqual(sorted(audit.EXPECTED_SUITE_COUNTS),
                         sorted(audit.AUDITED_SUITES))

    def test_footer_parsing_reads_skips_failures_and_errors(self):
        audit = self._audit()
        self.assertEqual(audit.parse_unittest_report("Ran 75 tests in 9.1s\n\nOK"),
                         {"ran": 75, "skipped": 0, "failures": 0, "errors_count": 0})
        self.assertEqual(
            audit.parse_unittest_report("Ran 75 tests in 9.1s\n\nOK (skipped=29)"),
            {"ran": 75, "skipped": 29, "failures": 0, "errors_count": 0})
        self.assertEqual(
            audit.parse_unittest_report(
                "Ran 4 tests\n\nFAILED (failures=1, errors=2, skipped=3)"),
            {"ran": 4, "skipped": 3, "failures": 1, "errors_count": 2})

    def test_a_shortfall_is_never_called_a_stale_pin(self):
        """The R62 case verbatim: golden replay's nine vanish behind a
        setUpClass skip and report `skipped=1`."""
        audit = self._audit()
        verdict = audit.classify_suite(
            "tests.test_golden_replay",
            {"ran": 1, "skipped": 1, "present": True})
        self.assertEqual(verdict["state"], "shortfall")
        self.assertIn("not a stale pin", verdict["advice"])
        self.assertNotIn("update EXPECTED", verdict["advice"].lower(),
                         "the advice must never tell the operator to move the "
                         "pin down to meet lost coverage")
        self.assertIn("LOST COVERAGE", verdict["advice"])
        self.assertIn("do not lower", verdict["advice"])
        self.assertIn("data/archive/2026-06-03", verdict["advice"],
                      "the advice names the precondition, not just a number")

    def test_skips_that_keep_the_count_are_still_reported(self):
        """The paste suite's 29: `Ran 75` matches the pin exactly and 29 of
        those tests asserted nothing. The count proves nothing about coverage
        and the old PASS line never mentioned it.

        R62, 2026-08-10: the paste suite's own precondition is gone -- both
        salary files are vendored and tracked now -- so this keeps the historical
        case as the vehicle for the STATE and moves the names-its-precondition
        assertion to a suite that still has one. Deleting that assertion instead
        would drop the coverage along with the precondition.
        """
        audit = self._audit()
        verdict = audit.classify_suite(
            "tests.test_paste_lineups", {"ran": 75, "skipped": 29, "present": True})
        self.assertEqual(verdict["state"], "skipped_in_place")
        self.assertNotIn("update EXPECTED", verdict["advice"].lower())
        self.assertIn("29 were SKIPPED", verdict["advice"])
        self.assertNotIn("data/slates/2026-07-29", verdict["advice"],
                         "R62 vendored the paste fixtures; the audit must stop "
                         "telling the operator to stage a gitignored slate")
        with_precondition = audit.classify_suite(
            "tests.test_golden_replay", {"ran": 9, "skipped": 9, "present": True})
        self.assertEqual(with_precondition["state"], "skipped_in_place")
        self.assertIn("data/archive/2026-06-03", with_precondition["advice"],
                      "a skipped_in_place suite that HAS a precondition still "
                      "names it, not just the count")

    def test_an_absent_suite_file_is_named_rather_than_silently_dropped(self):
        """The same defect one level up: the audit used to filter AUDITED_SUITES
        by file existence, so a renamed suite ran 0 tests, shrank the total, and
        produced the stale-pin advice with nothing naming the missing file."""
        audit = self._audit()
        verdict = audit.classify_suite(
            "tests.test_golden_replay", {"present": False, "ran": None})
        self.assertEqual(verdict["state"], "absent")
        self.assertIn("not a stale pin", verdict["advice"])
        self.assertNotIn("update EXPECTED", verdict["advice"].lower())
        self.assertIn("not on disk", verdict["advice"])

    def test_a_genuinely_stale_pin_still_says_so(self):
        """The conditional has to stay useful in the one case it is true for,
        or the next session learns to ignore it."""
        audit = self._audit()
        # Derived from the live pin, never a literal: a test that hardcodes the
        # count it is testing goes red every time the pin legitimately moves,
        # which teaches the next session to edit the assertion reflexively.
        pinned = audit.EXPECTED_SUITE_COUNTS["tests.test_core"]
        verdict = audit.classify_suite(
            "tests.test_core", {"ran": pinned + 6, "skipped": 0, "present": True})
        self.assertEqual(verdict["state"], "grew")
        self.assertIn("IS a stale pin", verdict["advice"])
        self.assertIn("EXPECTED_SUITE_COUNTS", verdict["advice"])

    def test_a_clean_suite_says_nothing(self):
        audit = self._audit()
        pinned = audit.EXPECTED_SUITE_COUNTS["tests.test_core"]
        verdict = audit.classify_suite(
            "tests.test_core", {"ran": pinned, "skipped": 0, "present": True})
        self.assertEqual(verdict["state"], "clean")
        self.assertIsNone(verdict["advice"])

    def test_the_clean_pass_line_is_the_one_CLAUDE_md_quotes(self):
        """CLAUDE.md's session-start step quotes this string exactly, so the
        clean line stays byte-identical and everything new prints only when
        there is something to say."""
        audit = self._audit()
        root = Path(__file__).resolve().parent.parent
        modules = audit.engine_module_count(root)
        result = {"passed": True, "warnings": [],
                  "project_version": audit.PROJECT_VERSION,
                  "errors": [],
                  "checks": {"tests": {
                      "runtime_test_count": audit.EXPECTED_TEST_COUNT,
                      "skipped_total": 0,
                      "suite_results": {n: {"suite": n, "state": "clean"}
                                        for n in audit.AUDITED_SUITES}}}}
        line = audit.terse_output(result, root)
        self.assertEqual(
            line,
            f"PASS  {audit.PROJECT_VERSION}  {modules} modules  "
            f"{audit.EXPECTED_TEST_COUNT} tests")
        self.assertIn(line, (root / "CLAUDE.md").read_text(encoding="utf-8"),
                      "CLAUDE.md's session-start line and the audit's clean "
                      "output have drifted apart")

    def test_the_pass_line_shows_skips_and_the_suite_that_is_off_its_pin(self):
        audit = self._audit()
        root = Path(__file__).resolve().parent.parent
        result = {"passed": True, "warnings": [], "errors": [],
                  "project_version": audit.PROJECT_VERSION,
                  "checks": {"tests": {
                      "runtime_test_count": 821, "skipped_total": 1,
                      "suite_results": {
                          "tests.test_core": {"suite": "tests.test_core",
                                              "state": "clean"},
                          "tests.test_golden_replay": {
                              "suite": "tests.test_golden_replay", "ran": 1,
                              "pinned": 9, "skipped": 1, "state": "shortfall"}}}}}
        line = audit.terse_output(result, root)
        self.assertIn("1 skipped", line)
        self.assertIn("test_golden_replay 1/9", line)
        self.assertIn("shortfall", line)


class TestDataDependenciesAreVendoredOrGuardedTests(unittest.TestCase):
    """R62(a): every `REPO / "data" / ...` path in tests/ is vendored or guarded.

    The defect this pins: five classes in test_paste_lineups read salary files
    under the gitignored `data/slates/` with no skip guard, so a tracked-files
    checkout ERRORED on them, and 29 more paste tests skipped behind a guard
    nobody could see. CLAUDE.md's mandated session-start PASS line was
    therefore unsatisfiable anywhere but this machine, and the audit's advice
    for the resulting shortfall was to lower the pin.

    Fixing the five classes once does not hold; the sixth gets written next
    month. This walks the AST instead, so a new unguarded data dependency
    fails here on the commit that adds it, with the file, line, class and the
    constant named. It is also what makes the deferred fixture vendoring safe
    to land later: whichever paths get vendored, the rest stay guarded.

    Vendored means git tracks it (`data/reference/`, `data/archive/2026-06-03/`
    -- the golden replay's inputs are in history and were never the gitignored
    half). Guarded means a `skipUnless`/`skipIf` on the class names the
    constant, or the class raises SkipTest from setUpClass/setUp.
    """

    ROOT_NAMES = {"REPO", "REPO_ROOT", "ROOT"}
    # Used only when git cannot answer. Mirrors .gitignore's policy: per-slate
    # dirs are ignored, reference and archive are tracked.
    TRACKED_PREFIXES = ("data/reference/", "data/archive/")

    @classmethod
    def _segments(cls, node):
        """Flatten `REPO / "a" / "b"` to ('REPO', 'a', 'b'); None if not that."""
        import ast
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return (node.value,)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = cls._segments(node.left)
            right = cls._segments(node.right)
            return None if left is None or right is None else left + right
        return None

    @classmethod
    def _is_data_path(cls, segs):
        return bool(segs) and segs[0] in cls.ROOT_NAMES and \
            len(segs) >= 2 and segs[1] == "data"

    @classmethod
    def _names_in(cls, node):
        import ast
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    @classmethod
    def _guards_on(cls, node):
        """Names cited by skip decorators, plus a flag for a SkipTest raise."""
        import ast
        names = set()
        for deco in getattr(node, "decorator_list", []):
            if isinstance(deco, ast.Call):
                fn = deco.func
                attr = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if attr in ("skipUnless", "skipIf"):
                    names |= cls._names_in(deco)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise) and sub.exc is not None:
                if "SkipTest" in ast.dump(sub.exc):
                    names.add("__SKIPTEST__")
        return names

    def _tracked(self, repo, rel):
        proc = subprocess.run(["git", "-C", str(repo), "ls-files", rel],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return any(rel.startswith(p) or (rel + "/").startswith(p)
                       for p in self.TRACKED_PREFIXES)
        return bool(proc.stdout.strip())

    def test_no_test_reads_gitignored_data_without_a_skip_guard(self):
        import ast
        repo = Path(__file__).resolve().parent.parent
        offenders = []
        inspected = 0

        for path in sorted((repo / "tests").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))

            constants = {}
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                segs = self._segments(node.value)
                if not self._is_data_path(segs):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = "/".join(segs[1:])

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                guards = self._guards_on(node)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        guards |= self._guards_on(item)
                skip_raised = "__SKIPTEST__" in guards

                # constants referenced by name
                cited = {(name, constants[name], node.lineno)
                         for name in self._names_in(node) & set(constants)}
                # paths written inline, attributed to the enclosing class
                for sub in ast.walk(node):
                    if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
                        segs = self._segments(sub)
                        if self._is_data_path(segs):
                            cited.add(("(inline)", "/".join(segs[1:]), sub.lineno))

                for name, rel, lineno in sorted(cited):
                    inspected += 1
                    if name in guards or skip_raised:
                        continue
                    if self._tracked(repo, rel):
                        continue
                    offenders.append(
                        f"{path.name}:{lineno} {node.name} reads {rel} via "
                        f"{name}: not tracked by git and not behind a skip "
                        f"guard, so a tracked-files-only checkout ERRORS here "
                        f"instead of skipping")

        # R51's class: a walk that finds nothing passes for the wrong reason.
        self.assertGreater(
            inspected, 5,
            "the walk found almost no data-path references, so it is passing "
            "vacuously; the detector broke, not the tree")
        self.assertEqual(offenders, [], "\n" + "\n".join(offenders))


from tools import stage_slate as stage_slate_mod


class StageSlateRoleResolutionTests(unittest.TestCase):
    """R70(a): stage_slate kept the LAST schema-passing file per role.

    Against the real ``data/slates/2026-07-30/`` layout that staged the 1-game
    showdown salary+entries pair on a Classic day, silently, end to end. The
    two salary exports here are the tracked frozen fixtures R62 vendored --
    real DK content, one of them literally the 07-30 6-game Classic file -- so
    the ambiguity is reproduced without depending on an untracked slate dir.
    """

    FIXTURES = REPO / "tests" / "fixtures" / "slates"
    ENTRIES_HEADER = "Entry ID,Contest Name,Contest ID,Entry Fee,Contest Entries\n"

    def _dir(self, salary_names, entries_names=("DKEntries.csv",)):
        import shutil
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        src = sorted(self.FIXTURES.glob("DKSalaries_*.csv"))
        self.assertGreaterEqual(
            len(src), 2, "R62 vendored two frozen salary exports; this test needs both")
        for i, name in enumerate(salary_names):
            shutil.copy(src[i % len(src)], d / name)
        for name in entries_names:
            (d / name).write_text(self.ENTRIES_HEADER + ",,,,\n", encoding="utf-8")
        return d

    def test_two_salary_exports_block_and_name_both(self):
        d = self._dir(["DKSalaries.csv", "DKSalaries_1910_6g.csv"])
        with self.assertRaises(stage_slate_mod.AmbiguousSlateInput) as ctx:
            stage_slate_mod._find_salary_and_entries(d)
        exc = ctx.exception
        self.assertEqual(exc.role, "salary")
        self.assertEqual(exc.flag, "--salary-csv")
        self.assertEqual(
            sorted(p.name for p in exc.candidates),
            ["DKSalaries.csv", "DKSalaries_1910_6g.csv"],
            "the block must name every candidate; a count is not actionable")
        self.assertIn("DKSalaries_1910_6g.csv", str(exc))
        self.assertIn("--salary-csv", str(exc))

    def test_the_conventional_name_is_not_quietly_preferred(self):
        # Preferring bare DKSalaries.csv would be the same wrong-draftgroup
        # bug wearing a nicer hat: DK writes that name for whichever slate was
        # clicked last, so it is not evidence about which one is being built.
        d = self._dir(["DKSalaries.csv", "DKSalaries_1910_6g.csv"])
        with self.assertRaises(stage_slate_mod.AmbiguousSlateInput):
            stage_slate_mod._find_salary_and_entries(d)

    def test_two_entries_files_block_on_their_own_flag(self):
        d = self._dir(["DKSalaries.csv"],
                      entries_names=("DKEntries.csv", "DKEntries_1910_6g.csv"))
        with self.assertRaises(stage_slate_mod.AmbiguousSlateInput) as ctx:
            stage_slate_mod._find_salary_and_entries(d)
        self.assertEqual(ctx.exception.role, "entries")
        self.assertEqual(ctx.exception.flag, "--entries-csv")

    def test_the_block_has_a_channel_out_of_it(self):
        # A tool that refuses without offering a way through teaches the
        # operator to write a driver script that bypasses it (R106's lesson).
        # Both overrides deliberately name the file that sorts FIRST. The old
        # code kept the LAST match, so a test that asked for the last one would
        # pass against the bug it exists to catch.
        d = self._dir(["DKSalaries.csv", "DKSalaries_1910_6g.csv"],
                      entries_names=("DKEntries.csv", "DKEntries_1910_6g.csv"))
        salary, entries = stage_slate_mod._find_salary_and_entries(
            d, salary_override="DKSalaries.csv",
            entries_override="DKEntries.csv")
        self.assertEqual(salary.name, "DKSalaries.csv")
        self.assertEqual(entries.name, "DKEntries.csv")

    def test_one_pair_still_resolves_with_no_flags(self):
        d = self._dir(["DKSalaries.csv"])
        salary, entries = stage_slate_mod._find_salary_and_entries(d)
        self.assertEqual(salary.name, "DKSalaries.csv")
        self.assertEqual(entries.name, "DKEntries.csv")

    def test_a_bare_override_resolves_in_the_slate_dir_not_the_cwd(self):
        # The blocker this pins: resolving CWD-first let `--salary-csv
        # DKSalaries.csv` run from the repo root stage the root's own stray
        # DKSalaries.csv against another date's bundle, printing a provenance
        # line identical to a correct in-dir resolution. R70's defect returning
        # through R70's remedy.
        import os
        import shutil
        d = self._dir(["DKSalaries.csv"])
        decoy_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(decoy_dir, ignore_errors=True))
        shutil.copy(sorted(self.FIXTURES.glob("DKSalaries_*.csv"))[0],
                    decoy_dir / "DKSalaries.csv")
        cwd = os.getcwd()
        os.chdir(decoy_dir)
        self.addCleanup(lambda: os.chdir(cwd))
        salary, _entries = stage_slate_mod._find_salary_and_entries(
            d, salary_override="DKSalaries.csv")
        self.assertEqual(
            salary.resolve().parent, d.resolve(),
            "a bare override must resolve inside the slate dir, not the CWD")

    def test_an_out_of_dir_input_cannot_wear_a_bare_filename(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        outside = Path(tempfile.mkdtemp()) / "DKSalaries.csv"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("x", encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(outside.parent, ignore_errors=True))
        self.assertEqual(stage_slate_mod._provenance(outside, d), str(outside))
        inside = d / "DKSalaries.csv"
        inside.write_text("x", encoding="utf-8")
        self.assertEqual(stage_slate_mod._provenance(inside, d), "DKSalaries.csv")

    def test_swapped_role_flags_are_named_rather_than_staged(self):
        d = self._dir(["DKSalaries.csv"])
        with self.assertRaises(ValueError) as ctx:
            stage_slate_mod._find_salary_and_entries(d, salary_override="DKEntries.csv")
        self.assertIn("swapped", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            stage_slate_mod._find_salary_and_entries(
                d, salary_override="DKSalaries.csv", entries_override="DKSalaries.csv")
        self.assertIn("DKEntries", str(ctx.exception))

    def test_naming_both_roles_does_not_scan_the_dir(self):
        # An undecodable CSV elsewhere in the dir must not fail a resolution
        # that did not depend on reading it.
        d = self._dir(["DKSalaries.csv"])
        (d / "junk.csv").write_bytes(b"\xff\xfe\x00rubbish\x00")
        salary, entries = stage_slate_mod._find_salary_and_entries(
            d, salary_override="DKSalaries.csv", entries_override="DKEntries.csv")
        self.assertEqual(salary.name, "DKSalaries.csv")
        self.assertEqual(entries.name, "DKEntries.csv")

    def test_an_undecodable_csv_is_skipped_not_fatal_when_sniffing(self):
        d = self._dir(["DKSalaries.csv"])
        (d / "junk.csv").write_bytes(b"\xff\xfe\x00rubbish\x00")
        salary, entries = stage_slate_mod._find_salary_and_entries(d)
        self.assertEqual(salary.name, "DKSalaries.csv")
        self.assertEqual(entries.name, "DKEntries.csv")

    def test_an_override_naming_a_missing_file_blocks(self):
        # Operator-typed identifier, R69's precedent: one argument fixes it, so
        # it hard-gates instead of degrading to a warning and staging something
        # else.
        d = self._dir(["DKSalaries.csv"])
        with self.assertRaises(FileNotFoundError) as ctx:
            stage_slate_mod._find_salary_and_entries(d, salary_override="DKSalaries_typo.csv")
        self.assertIn("--salary-csv", str(ctx.exception))


class StageSlatePlatoonShapeTests(unittest.TestCase):
    """R70(a), platoon half: the unvalidated fallback took the first remaining
    JSON in the dir, which on the real 07-30 layout is a lineups feed.

    That costs twice. It fills no projected orders, because
    ``build_projected_order`` iterates ``platoon['teams']`` and a feed has
    ``games``; and it suppresses ``DEFAULT_PLATOON_REFERENCE``, which
    ``build_slate_pool`` loads only when ``platoon_json is None``. A bad guess
    is strictly worse than no guess.
    """

    BUNDLE = {"bundle_version": 1, "lineups": {"games": [{"away": {}, "home": {}}]}}
    FEED_SHAPED = {"date": "2026-07-30", "source": "mlb-api",
                   "games": [{"away": {}, "home": {}}]}

    def _dir(self, files):
        import shutil
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        (d / "slate_bundle.json").write_text(json.dumps(self.BUNDLE), encoding="utf-8")
        for name, obj in files.items():
            (d / name).write_text(json.dumps(obj), encoding="utf-8")
        return d

    def test_a_lineups_feed_is_rejected_rather_than_accepted(self):
        d = self._dir({"_home_sides_feed.json": self.FEED_SHAPED})
        bundle, platoon, _declared, notes = stage_slate_mod._find_bundle_and_platoon(d)
        self.assertEqual(bundle.name, "slate_bundle.json")
        self.assertIsNone(
            platoon,
            "a feed with no 'teams' must not be accepted as the platoon file")
        self.assertTrue(notes, "the rejection must reach the operator")
        self.assertIn("_home_sides_feed.json", notes[0])
        self.assertIn("teams", notes[0])

    def test_rejection_leaves_none_so_the_reference_default_still_loads(self):
        # This is the whole point of the fix: None is the exact condition
        # build_slate_pool checks before loading DEFAULT_PLATOON_REFERENCE.
        d = self._dir({"_home_sides_feed.json": self.FEED_SHAPED,
                       "api_feed_v2.json": self.FEED_SHAPED})
        _b, platoon, _d, notes = stage_slate_mod._find_bundle_and_platoon(d)
        self.assertIsNone(platoon)
        self.assertIn("fangraphs_platoon_lineups.json", notes[0],
                      "say which file the fallthrough lands on")

    def test_the_real_platoon_reference_is_accepted(self):
        # Guards the other direction: validation strict enough to reject the
        # curated reference file would be a worse bug than the one being fixed.
        import shutil
        ref = REPO / "data" / "reference" / "fangraphs_platoon_lineups.json"
        d = self._dir({})
        shutil.copy(ref, d / "fangraphs_platoon_lineups.json")
        _b, platoon, _dec, notes = stage_slate_mod._find_bundle_and_platoon(d)
        self.assertIsNotNone(platoon)
        self.assertEqual(platoon.name, "fangraphs_platoon_lineups.json")
        self.assertEqual(notes, [])

    def test_an_empty_teams_list_is_not_platoon_shaped(self):
        self.assertFalse(stage_slate_mod._is_platoon_shaped({"teams": []}))
        self.assertFalse(stage_slate_mod._is_platoon_shaped({"games": []}))
        self.assertFalse(stage_slate_mod._is_platoon_shaped([]))
        self.assertTrue(stage_slate_mod._is_platoon_shaped({"teams": [{"abbrev": "DET"}]}))

    def test_the_no_platoon_note_names_the_reference_the_engine_actually_loads(self):
        # R70 rider. The note used to promise a top-9 AvgPointsPerGame fallback.
        # build_slate_pool loads DEFAULT_PLATOON_REFERENCE whenever
        # platoon_json is None, so APPG is the fallback only when the reference
        # is absent too -- and a TBD team with a real projected order looked
        # identical to one guessed from season averages.
        note = stage_slate_mod.NO_PLATOON_IN_DIR_NOTE
        self.assertIn("fangraphs_platoon_lineups.json", note)
        self.assertNotRegex(
            note, r"will fall back to top-9",
            "the unconditional APPG-fallback claim is the defect")
        from mlb_engine.intake.platoon_order_adapter import DEFAULT_PLATOON_REFERENCE
        self.assertIn(Path(DEFAULT_PLATOON_REFERENCE).name, note,
                      "the note must name the file the engine really loads")

    def test_a_named_platoon_json_without_teams_blocks(self):
        d = self._dir({"my_platoon.json": self.FEED_SHAPED})
        with self.assertRaises(ValueError) as ctx:
            stage_slate_mod._find_bundle_and_platoon(d, platoon_override="my_platoon.json")
        self.assertIn("teams", str(ctx.exception))

    def test_two_sniffed_bundle_candidates_block(self):
        import shutil
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        (d / "api_feed_a.json").write_text(json.dumps(self.BUNDLE), encoding="utf-8")
        (d / "api_feed_b.json").write_text(json.dumps(self.BUNDLE), encoding="utf-8")
        with self.assertRaises(stage_slate_mod.AmbiguousSlateInput) as ctx:
            stage_slate_mod._find_bundle_and_platoon(d)
        self.assertEqual(ctx.exception.flag, "--bundle-json")


class StageSlateClockReadTests(unittest.TestCase):
    """R70(b): ``--checkpoint`` printed
    ``first_lock=None deadline=None minutes_remaining=None`` on every run.

    It read ``first_lock_et`` / ``delivery_deadline_et`` / ``minutes_remaining``;
    ``slate_clock()`` emits ``first_lock_utc`` / ``deadline_utc`` /
    ``minutes_to_deadline``. Three keys, none of them real, on the T-schedule's
    one budgeting instrument.
    """

    def _real_clock(self):
        from mlb_engine.intake.slate_intake_manager import slate_clock
        frozen = sorted((REPO / "tests" / "fixtures" / "slates").glob("DKSalaries_1910_6g_*.csv"))
        self.assertTrue(frozen, "R62's frozen 07-30 6-game export is the clock fixture")
        return slate_clock(str(frozen[0]))

    def test_the_keys_the_old_code_read_do_not_exist(self):
        # The pin that would have caught this at write time, and catches a
        # rename on either side from here on.
        clock = self._real_clock()
        self.assertTrue(clock.get("available"), clock.get("note"))
        for absent in ("first_lock_et", "delivery_deadline_et", "minutes_remaining"):
            self.assertNotIn(absent, clock)
        for present in ("first_lock_utc", "deadline_utc", "minutes_to_deadline",
                        "past_deadline", "buffer_minutes"):
            self.assertIn(present, clock)

    def test_the_line_carries_the_real_first_lock_and_no_none(self):
        line = stage_slate_mod._format_clock(self._real_clock())
        self.assertIn("19:10 ET", line,
                      "the frozen export is the 1910 slate; the clock must say so")
        self.assertNotIn("None", line)
        self.assertIn("minutes_to_deadline=", line)

    def test_an_unavailable_clock_says_so_instead_of_printing_none(self):
        line = stage_slate_mod._format_clock({
            "available": False, "source": "none", "buffer_minutes": 5,
            "note": "no parseable game datetimes; clock unavailable"})
        self.assertIn("unavailable", line)
        self.assertIn("no parseable game datetimes", line)
        self.assertNotIn("None", line)

    def test_past_deadline_reaches_the_line(self):
        clock = dict(self._real_clock())
        clock["past_deadline"] = True
        self.assertIn("PAST DEADLINE", stage_slate_mod._format_clock(clock))
        clock["past_deadline"] = False
        self.assertNotIn("PAST DEADLINE", stage_slate_mod._format_clock(clock))

    def test_an_absent_clock_block_is_distinguishable_from_a_broken_read(self):
        self.assertIn("absent", stage_slate_mod._format_clock({}))

    def test_et_is_correct_in_EST_not_just_in_the_season(self):
        # The July fixture above cannot catch this: UTC-4 is right in EDT and an
        # hour wrong in EST, so a postseason slate was told its first lock was
        # an hour later than it is. R65 built repo_env for exactly this class.
        from mlb_engine.repo_env import now_et
        for iso in ("2026-08-14T23:05:00+00:00", "2026-11-04T00:08:00+00:00"):
            expected = now_et(datetime.fromisoformat(iso)).strftime("%H:%M ET")
            self.assertEqual(stage_slate_mod._et(iso), expected)
        self.assertEqual(stage_slate_mod._et("2026-11-04T00:08:00+00:00"), "19:08 ET")

    def test_stage_slate_no_longer_hardcodes_a_utc_offset(self):
        src = (REPO / "tools" / "stage_slate.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "timedelta(hours=4)", src,
            "ET goes through repo_env; a hardcoded UTC-4 is R65's named bug")

    def test_an_unparseable_timestamp_is_labeled_not_printed_as_none(self):
        # Returning None here reproduced the exact all-Nones symptom R70(b)
        # removed, on an available=True clock.
        line = stage_slate_mod._format_clock({
            "available": True, "first_lock_utc": "2026-07-30 19:10 ET",
            "deadline_utc": "nonsense", "minutes_to_deadline": 12.0,
            "buffer_minutes": 5})
        self.assertNotIn("None", line)
        self.assertIn("unparseable", line)

    def test_the_checkpoint_door_matches_its_sibling_doors_on_the_r27_gate(self):
        # Making the reference actually load must not make this review-only door
        # stricter than the build door it previews. late_swap and build_slate
        # both pass 'warn'.
        import inspect
        sig = inspect.signature(stage_slate_mod.stage_slate)
        self.assertEqual(sig.parameters["stale_platoon_policy"].default, "warn")
        src = inspect.getsource(stage_slate_mod.stage_slate)
        self.assertIn("stale_platoon_policy=stale_platoon_policy", src,
                      "the policy must reach build_slate_pool, not be inherited")


class FalseSignalBatchTests(unittest.TestCase):
    """R99 + R92 + R71(a) + R119 + R113 + R112 + R103, one session.

    Tier 1's false-signal batch: refusals and brief fields honest line-by-line
    that steer wrong. Five real builds since 2026-08-01 burned on this family;
    every fix here is small and they share the reporting surface.
    """

    @staticmethod
    def _module():
        return BuildSlateScriptTests._module()

    # -- R99: the stderr gate and the brief field now read the same clock ---

    def test_salary_cross_check_note_silent_with_no_cross_check(self):
        mod = self._module()
        self.assertIsNone(mod.salary_cross_check_note({"salary_cross_check": None}))
        self.assertIsNone(mod.salary_cross_check_note({}))

    def test_salary_cross_check_note_silent_when_agreeing(self):
        mod = self._module()
        clock = {"salary_cross_check": {"checked": True, "agrees": True,
                                        "feed_first_lock_game_id": "1",
                                        "salary_first_lock_game_id": "1"}}
        self.assertIsNone(mod.salary_cross_check_note(clock))

    def test_salary_cross_check_note_prints_a_real_disagreement(self):
        mod = self._module()
        clock = {"salary_cross_check": {
            "checked": True, "agrees": False,
            "feed_first_lock_game_id": "away@home-2",
            "salary_first_lock_game_id": "away@home-1",
            "salary_first_lock_utc": "2026-08-11T23:10:00+00:00",
            "drift_minutes": 245.0,
        }}
        note = mod.salary_cross_check_note(clock)
        self.assertIsNotNone(note)
        self.assertIn("away@home-2", note)
        self.assertIn("away@home-1", note)
        self.assertIn("245.0", note)

    def test_the_stderr_gate_no_longer_reads_the_never_set_pool_report_key(self):
        # R99's actual bug: pool_report never carries a salary_cross_check key
        # anywhere in this codebase, so the old gate could never fire, on a
        # clean slate or a genuinely disagreeing one. (The narrower "is False:"
        # match, not a bare substring: this docstring's own prose mentions
        # `pool_report.get("salary_cross_check")` narratively, which a plain
        # substring check would flag as if it were still live code.)
        src = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py").read_text(encoding="utf-8")
        self.assertNotIn('if report.get("salary_cross_check") is False:', src)
        self.assertIn("salary_cross_check_note(clock)", src)

    # -- R92: bank_warnings reads keys extend_bank actually returns ----------

    def test_bank_warnings_no_longer_reads_the_two_dead_keys(self):
        src = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py").read_text(encoding="utf-8")
        self.assertNotIn('bank_report.get("jobs_failed")', src)
        self.assertNotIn('bank_report.get("budget_exhausted")', src)
        self.assertIn('bank_report.get("jobs_raised")', src)
        self.assertIn('bank_report.get("jobs_unanswered")', src)

    def test_extend_bank_never_actually_returns_the_dead_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = diverse_projection_frame()
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            report = bank_cache.extend_bank(cache, frame, time_budget_s=10)
            self.assertNotIn("jobs_failed", report)
            self.assertNotIn("budget_exhausted", report)
            self.assertIn("jobs_raised", report)
            self.assertIn("jobs_unanswered", report)
            self.assertIn("raised_by_reason", report)
            self.assertIn("unanswered_by_status", report)

    # -- R71(a): a units slip no longer disables the cap in silence ---------

    def test_cap_count_rejects_a_units_slip_in_both_copies(self):
        from mlb_engine.allocate.contest_allocator import _cap_count as solve_side
        from mlb_engine.entries.dk_entries_manager import _cap_count as export_side
        for total, pct in ((18, 45), (10, 1.5), (4, 100)):
            with self.assertRaises(ValueError):
                solve_side(total, pct)
            with self.assertRaises(ValueError):
                export_side(total, pct)

    def test_cap_count_still_accepts_the_legal_boundary(self):
        from mlb_engine.allocate.contest_allocator import _cap_count as solve_side
        from mlb_engine.entries.dk_entries_manager import _cap_count as export_side
        self.assertEqual(solve_side(18, 1.0), 18)
        self.assertEqual(export_side(18, 1.0), 18)
        self.assertIsNone(solve_side(18, None))
        self.assertIsNone(solve_side(18, 0))

    # -- R119: the value_guard pointer resolves, and the objective block ----

    def test_summarize_enrichment_writes_the_value_guard_key_it_points_at(self):
        mod = self._module()
        raw = {
            "value_guard": {"applied": True, "clipped_count": 2, "percentile": 0.9},
            "warnings": ["value_guard clipped 2 hitter Base value(s); "
                        "see enrichment['value_guard']"],
        }
        out = mod.summarize_enrichment({}, raw, {}, None)
        self.assertEqual(out["value_guard"], raw["value_guard"])
        self.assertIn("see enrichment['value_guard']", " ".join(out["warnings"]))

    def test_objective_differentiation_is_the_signal_applied_corollary(self):
        mod = self._module()
        unenriched = mod.summarize_enrichment({}, {"value_guard": None}, {}, None)
        self.assertFalse(unenriched["signal_applied"])
        self.assertTrue(
            unenriched["objective_differentiation"]["cash_and_gpp_selection_identical"])
        enriched = mod.summarize_enrichment(
            {}, {"value_guard": None}, {"non_neutral_f4": 3, "hitters_scored": 10}, None)
        self.assertTrue(enriched["signal_applied"])
        self.assertFalse(
            enriched["objective_differentiation"]["cash_and_gpp_selection_identical"])
        self.assertIn("floor_basis", enriched["objective_differentiation"])
        self.assertIn("ceiling_basis", enriched["objective_differentiation"])

    # -- R113: cap and lock relaxations are named off their own counters ----

    def test_showdown_relaxation_caution_names_the_right_mechanism(self):
        mod = self._module()
        cap_only = mod.showdown_relaxation_caution(6, 2, 0, [], 4, 0, 0)
        self.assertIn("captain cap relaxed on 2 slot(s)", cap_only)
        self.assertIn("captain_exposure.by_player", cap_only)
        self.assertNotIn("LOCK", cap_only)

        lock_only = mod.showdown_relaxation_caution(
            6, 0, 1, [{"thesis": "pitchers_duel", "requested": "Dustin May",
                       "actual": "Brandon Lockridge"}], 4, 0, 0)
        self.assertIn("captain LOCK relaxed on 1 slot(s)", lock_only)
        self.assertIn("pitchers_duel: Dustin May -> Brandon Lockridge", lock_only)
        self.assertIn("not a cap event", lock_only)
        self.assertNotIn("captain cap relaxed", lock_only)

        neither = mod.showdown_relaxation_caution(6, 0, 0, [], 4, 0, 0)
        self.assertEqual(neither, "")

        everything = mod.showdown_relaxation_caution(
            6, 1, 1, [{"thesis": "t1", "requested": "A", "actual": "B"}], 4, 2, 1)
        self.assertIn("captain cap relaxed on 1", everything)
        self.assertIn("captain LOCK relaxed on 1", everything)
        self.assertIn("overlap bound relaxed on 2", everything)
        self.assertIn("BOTH the overlap", everything)

    # -- R112: a refusal names the bank as the limiter when the slate has ---
    # -- more capacity than the bank sampled ---------------------------------

    @staticmethod
    def _shared_pair_candidates(n, primary="AAA"):
        return [
            candidate(f"c{i}", ["SPA", "SPB"] + [f"{i}-{j}" for j in range(2, 10)],
                      100.0 - i, primary=primary)
            for i in range(n)
        ]

    def test_binding_constraint_names_the_bank_as_limiter(self):
        cands = self._shared_pair_candidates(3)
        result = select_and_assign_entries(
            cands, _entry_reqs(6), {"max_sp_pair_repetition": 1},
            feasibility_inputs={"viable_sp_pairs": 12})
        self.assertFalse(result["passed"])
        line = next(e for e in result["errors"] if "max_sp_pair_repetition" in e)
        self.assertIn("BANK-LIMITED", line)
        self.assertIn("12 viable SP pairs", line)
        self.assertIn("sampled only 1", line)

    def test_binding_constraint_is_silent_when_the_bank_matches_the_slate(self):
        cands = self._shared_pair_candidates(3)
        result = select_and_assign_entries(
            cands, _entry_reqs(6), {"max_sp_pair_repetition": 1},
            feasibility_inputs={"viable_sp_pairs": 1})
        line = next(e for e in result["errors"] if "max_sp_pair_repetition" in e)
        self.assertNotIn("BANK-LIMITED", line)

    def test_binding_constraint_omits_the_clause_with_no_feasibility_inputs(self):
        cands = self._shared_pair_candidates(3)
        result = select_and_assign_entries(
            cands, _entry_reqs(6), {"max_sp_pair_repetition": 1})
        line = next(e for e in result["errors"] if "max_sp_pair_repetition" in e)
        self.assertNotIn("BANK-LIMITED", line)

    def test_the_bank_not_exhausted_flag_rides_every_binding_line(self):
        """R112 rider: two findings in one solve must BOTH carry the flag, not
        just a remedy trailing the whole list that a truncated read would miss."""
        cands = self._shared_pair_candidates(3, primary="AAA")
        result = select_and_assign_entries(
            cands, _entry_reqs(6),
            {"max_sp_pair_repetition": 1, "max_primary_stack_exposure_pct": 0.34},
            bank_report={"job_list_exhausted": False, "jobs_attempted": 10,
                        "jobs_total": 500})
        binding_lines = [e for e in result["errors"] if "proven infeasible:" in e]
        self.assertGreaterEqual(len(binding_lines), 2, result["errors"])
        for line in binding_lines:
            self.assertIn("BANK JOB LIST NOT EXHAUSTED", line)

    def test_feasibility_inputs_threads_from_run_slate_to_the_allocator(self):
        """Plumbing check: run_slate already computes _slate_feasibility; it
        must reach select_and_assign_entries so a real build's refusal can
        carry the BANK-LIMITED clause with the checkpoint's own numbers."""
        pipeline_src = (REPO / "mlb_engine" / "pipeline" / "execution_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("feasibility_inputs=feasibility_inputs", pipeline_src)
        alloc_src = (REPO / "mlb_engine" / "allocate" / "contest_allocator.py").read_text(encoding="utf-8")
        self.assertIn("feasibility_inputs=feasibility_inputs", alloc_src)

    # -- R103: a hard-pinned same-game SP pair is a fact, not a diversity ---
    # -- candidate, so it survives the same-game filter ----------------------

    def test_a_pinned_same_game_pair_is_not_filtered_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = diverse_projection_frame()
            p_t1 = frame[(frame["Position"] == "P") & (frame["Team"] == "T1")].iloc[0]["Player_ID"]
            p_t2 = frame[(frame["Position"] == "P") & (frame["Team"] == "T2")].iloc[0]["Player_ID"]
            pins = {"P1": str(p_t1), "P2": str(p_t2)}
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            report = bank_cache.extend_bank(
                cache, frame, time_budget_s=20, locked_slot_assignments=pins)
            self.assertTrue(report["pinned_pair_same_game_kept"],
                            "the pinned pair's own game must be reported")
            self.assertGreater(report["jobs_total"], 0,
                               "a hard-pinned same-game pair produced +0 jobs, "
                               "reading as a dry pool instead of a fixed fact")
            self.assertGreater(report["built_this_slice"], 0)

    def test_a_cross_game_pin_is_unaffected_and_unflagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = diverse_projection_frame()
            p_t1 = frame[(frame["Position"] == "P") & (frame["Team"] == "T1")].iloc[0]["Player_ID"]
            p_t3 = frame[(frame["Position"] == "P") & (frame["Team"] == "T3")].iloc[0]["Player_ID"]
            pins = {"P1": str(p_t1), "P2": str(p_t3)}
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            report = bank_cache.extend_bank(
                cache, frame, time_budget_s=20, locked_slot_assignments=pins)
            self.assertFalse(report["pinned_pair_same_game_kept"])
            self.assertGreater(report["built_this_slice"], 0)

    def test_a_single_pin_leaves_the_same_game_filter_untouched(self):
        """The one-pin case still needs the filter: the open slot must not be
        allowed to pair the pinned arm with his own opponent."""
        with tempfile.TemporaryDirectory() as tmp:
            frame = diverse_projection_frame()
            p_t1 = frame[(frame["Position"] == "P") & (frame["Team"] == "T1")].iloc[0]["Player_ID"]
            pins = {"P1": str(p_t1)}
            cache = bank_cache.BankCache(Path(tmp) / "bank.json")
            report = bank_cache.extend_bank(
                cache, frame, time_budget_s=20, locked_slot_assignments=pins)
            self.assertFalse(report["pinned_pair_same_game_kept"])
            self.assertGreater(report["built_this_slice"], 0)


class CandidateReuseDefaultTests(unittest.TestCase):
    """R116: the production allocator's candidate-reuse cap now has a default.

    Before this, `select_and_assign_entries` added a reuse row only when an
    operator typed `max_candidate_reuse`, no posture set it, and nothing outside
    tests passed one -- so the MILP legitimately spent a whole file on its best
    few candidates. The first certified 2207_2g build put 4 distinct lineups
    across 11 apex entries.

    What is pinned here is the MECHANISM in both directions: that the default
    de-concentrates, that an operator value still wins verbatim, that cash is
    left alone, and that the default RELAXES rather than costing a delivery --
    while an operator's own cap still refuses, because relaxing that one would
    be the engine quietly overruling a decision.
    """

    # Eleven single-entry contests: the per-contest uniqueness rule cannot force
    # any diversity here, so every distinct lineup delivered is the reuse cap's
    # doing and nothing else's.
    ENTRIES = [{"entry_id": f"e{n}", "contest_id": f"C{n}",
                "contest_shape": "large_field_gpp"} for n in range(11)]

    @staticmethod
    def _bank(n=7):
        return [candidate(f"c{i}", [f"p{i}_{j}" for j in range(10)], 150 - i)
                for i in range(n)]

    def test_the_default_is_the_minimum_cap_arithmetic(self):
        self.assertEqual(default_candidate_reuse_cap(11, 7), 2)
        self.assertEqual(default_candidate_reuse_cap(20, 500), 1)
        self.assertEqual(default_candidate_reuse_cap(1, 500), 1,
                         "one entry must return 1: the single_entry posture is "
                         "untouched by this default")
        self.assertEqual(default_candidate_reuse_cap(0, 3), 1)
        self.assertEqual(default_candidate_reuse_cap(5, 0), 5,
                         "a zero denominator must not divide by zero")

    def test_the_ladder_is_two_rungs_and_drops_a_rung_that_binds_nothing(self):
        self.assertEqual(candidate_reuse_cap_rungs(11, 7), [2, 4])
        self.assertEqual(candidate_reuse_cap_rungs(18, 29), [1, 2],
                         "the archived 06-03 grid's ladder; rung 2 is the one "
                         "that certifies and rung 1 is the one that does not")
        self.assertEqual(candidate_reuse_cap_rungs(2, 1), [],
                         "a cap at or above the entry count binds nothing, so "
                         "solving it would duplicate the no-cap solve")

    def test_without_the_default_the_whole_file_lands_on_one_lineup(self):
        """The defect, reproduced. Cash is the one family that skips the
        default, so it doubles as the pre-R116 control condition."""
        entries = [dict(e, contest_shape="cash") for e in self.ENTRIES]
        result = select_and_assign_entries(self._bank(), entries, {})
        block = result["candidate_reuse"]
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(block["distinct_lineups"], 1)
        self.assertEqual(block["max_signature_repeat"], 11)
        self.assertEqual(block["cap_skipped_reason"], "cash_only_portfolio")
        self.assertIsNone(block["cap_applied"])

    def test_the_default_de_concentrates_an_uncontrolled_gpp_portfolio(self):
        result = select_and_assign_entries(self._bank(), self.ENTRIES, {})
        block = result["candidate_reuse"]
        self.assertTrue(result["passed"], result.get("errors"))
        self.assertEqual(block["cap_source"], "engine_default")
        self.assertEqual(block["cap_applied"], 2)
        self.assertEqual(block["relaxations"], 0)
        self.assertGreaterEqual(block["distinct_lineups"], math.ceil(11 / 2))
        self.assertLessEqual(block["max_signature_repeat"], 2)
        self.assertEqual(result["direct_constraints"]["max_candidate_reuse"], 2,
                         "the resolved cap must reach the constraints block a "
                         "reader consults to ask what bound this solve")

    def test_one_non_cash_entry_makes_the_whole_file_a_gpp_portfolio(self):
        entries = [dict(e, contest_shape="cash") for e in self.ENTRIES]
        entries[3] = dict(entries[3], contest_shape="large_field_gpp")
        block = select_and_assign_entries(self._bank(), entries, {})["candidate_reuse"]
        self.assertEqual(block["cap_source"], "engine_default")
        self.assertIsNone(block["cap_skipped_reason"])

    def test_an_operator_cap_wins_verbatim_including_a_looser_one(self):
        result = select_and_assign_entries(
            self._bank(), self.ENTRIES, {"max_candidate_reuse": 11})
        block = result["candidate_reuse"]
        self.assertEqual(block["cap_source"], "operator")
        self.assertEqual(block["cap_applied"], 11)
        self.assertEqual(block["distinct_lineups"], 1,
                         "an explicit cap must not be tightened by the default")

    def test_the_cap_is_budgeted_per_signature_not_per_candidate_object(self):
        """Two candidate objects on the same ten players are ONE lineup to
        DraftKings and to the field, so they share one reuse budget.

        Budgeting them separately is the failure worth pinning: with six ids on
        three rosters the denominator would read 6, the default would fall to 1,
        and a portfolio of three lineups would be reported as six distinct.
        """
        rosters = [[f"r{i}_{j}" for j in range(10)] for i in range(3)]
        bank = [candidate(f"c{i}{tag}", list(rosters[i]), 100 - i)
                for i in range(3) for tag in ("a", "b")]
        entries = [dict(e) for e in self.ENTRIES[:6]]
        block = select_and_assign_entries(bank, entries, {})["candidate_reuse"]
        self.assertEqual(block["distinct_lineups_available"], 3,
                         "six candidate objects on three rosters are three lineups")
        self.assertEqual(block["cap_applied"], 2, "ceil(6 entries / 3 lineups)")
        self.assertLessEqual(block["max_signature_repeat"], 2)
        self.assertEqual(block["distinct_lineups"], 3)

    # -- the delivery guarantee ------------------------------------------- #

    @staticmethod
    def _overlap_trap():
        """Seven candidates sharing nine of ten players. Any two DISTINCT
        lineups overlap at 9, so `max_shared_players=4` makes every
        diversified portfolio infeasible while one repeated lineup is legal."""
        common = [f"pc{j}" for j in range(9)]
        return [candidate(f"c{i}", common + [f"uniq{i}"], 150 - i) for i in range(7)]

    def test_an_infeasible_default_relaxes_and_delivers_rather_than_refusing(self):
        result = select_and_assign_entries(
            self._overlap_trap(), self.ENTRIES, {"max_shared_players": 4})
        block = result["candidate_reuse"]
        self.assertTrue(result["passed"],
                        f"the engine's own default cost a delivery: {result.get('errors')}")
        self.assertGreaterEqual(block["relaxations"], 1)
        self.assertEqual(block["cap_skipped_reason"], "engine_default_exhausted")
        self.assertEqual(len(block["relaxation_steps"]), len(block["engine_default_rungs"]))
        self.assertTrue(
            any("max_candidate_reuse" in w and "relaxed" in w
                for w in (result.get("warnings") or [])),
            f"a relaxation that is not counted in the warnings is a silent "
            f"strategy change: {result.get('warnings')}")

    def test_an_operator_cap_that_cannot_fit_still_refuses(self):
        """The engine relaxes its own guess and nobody else's. A typed cap that
        the bank cannot satisfy is a fact the operator has to see."""
        result = select_and_assign_entries(
            self._overlap_trap(), self.ENTRIES,
            {"max_shared_players": 4, "max_candidate_reuse": 2})
        self.assertFalse(result["passed"])
        self.assertTrue(any("max_candidate_reuse" in e for e in result["errors"]),
                        result["errors"])

    def test_the_default_never_relaxes_on_a_timeout(self):
        """The rule that a compute limit may not move a strategy control. A
        time-limited solve reports the clock; it does not buy a wider portfolio
        on the way past."""
        result = select_and_assign_entries(
            self._overlap_trap(), self.ENTRIES,
            {"max_shared_players": 4, "time_limit": 1e-9})
        self.assertFalse(result["passed"], "fixture is wrong: the clock must bite here")
        report = result.get("allocation_solver_report") or {}
        self.assertEqual(report.get("status"), "time_limit", result.get("errors"))
        self.assertEqual(result["candidate_reuse"]["relaxations"], 0,
                         "a compute limit walked the engine down its own "
                         "relaxation ladder; the refusal now describes a "
                         "portfolio the clock chose")
        self.assertEqual(result["candidate_reuse"]["cap_applied"], 2,
                         "the refusal must name the cap that was active when "
                         "the clock ran out: rung 0, ceil(11/7)")


class PortfolioConcentrationInTheBriefTests(unittest.TestCase):
    """R116 fix 2: the brief says how concentrated the delivered file is.

    Nothing in the brief said `distinct_lineups`, and preflight's duplicate
    groups line arrives AFTER certification -- so the 2207_2g concentration was
    only findable by re-joining the export by hand. The count here is taken off
    the delivered bytes on the same sorted-roster signature the allocator keys
    its reuse rows with, so the brief carries a check of the cap and not just
    the allocator's word for it.
    """

    @staticmethod
    def _module():
        import importlib.util
        path = (Path(__file__).resolve().parents[1] / "skills" / "generate-lineups"
                / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location("build_slate_r116", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _files(self, tmp, rosters, contest_ids=None):
        """R128: `contest_ids` is one contest per roster, defaulting to a
        single-contest file so every caller predating the split is unchanged."""
        salary = Path(tmp) / "DKSalaries.csv"
        with salary.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Position", "Name + ID", "Name", "ID", "Roster Position",
                        "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame"])
            for pid in sorted({p for r in rosters for p in r}):
                team = "AAA" if pid.startswith("h") else "BBB"
                w.writerow(["OF", f"n{pid} ({pid})", f"n{pid}", pid, "OF",
                            "4000", "AAA@BBB", team, "8.0"])
        ids = list(contest_ids) if contest_ids else ["1"] * len(rosters)
        entries = Path(tmp) / "DKEntries.csv"
        with entries.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee",
                        "P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"])
            for i, (roster, cid) in enumerate(zip(rosters, ids)):
                w.writerow([str(100 + i), "Contest", cid, "$1"] + list(roster))
        return salary, entries

    def test_the_exposure_block_counts_distinct_lineups_off_the_delivered_file(self):
        module = self._module()
        base = [f"h{j}" for j in range(10)]
        other = [f"h{j}" for j in range(9)] + ["h99"]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = self._files(tmp, [base, list(base), other])
            block = module.portfolio_exposure(salary, entries)
        self.assertEqual(block["lineups"], 3)
        self.assertEqual(block["distinct_lineups"], 2)
        self.assertEqual(block["max_lineup_repeat"], 2)

    def test_slot_order_does_not_invent_a_distinct_lineup(self):
        """DK writes a roster in slot order and two entries holding the same ten
        players can differ in that order. Counting the raw row would report the
        duplicate as diversity, which is the reading this item exists to fix."""
        module = self._module()
        base = [f"h{j}" for j in range(10)]
        shuffled = base[2:] + base[:2]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = self._files(tmp, [base, shuffled])
            block = module.portfolio_exposure(salary, entries)
        self.assertEqual(block["distinct_lineups"], 1)
        self.assertEqual(block["max_lineup_repeat"], 2)

    def test_the_brief_splits_duplication_the_way_the_preflight_does(self):
        """R128, brief half. Seven lineups mirrored across two contests, and
        the brief said `max_lineup_repeat: 2` with no way to tell whether that
        repetition was inside a contest or across two of them."""
        module = self._module()
        rosters, ids = [], []
        for j in range(7):
            lineup = [f"h{i}" for i in range(9)] + [f"h{20 + j}"]
            rosters += [lineup, list(lineup)]
            ids += ["193774256", "193774257"]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = self._files(tmp, rosters, ids)
            block = module.portfolio_exposure(salary, entries)
        self.assertEqual(block["lineups"], 14)
        self.assertEqual(block["distinct_lineups"], 7)
        self.assertEqual(block["max_lineup_repeat"], 2)
        self.assertEqual(block["contests_in_file"], 2)
        self.assertEqual(block["duplicates_within_contest"], 0,
                         "each contest holds seven distinct lineups")
        self.assertEqual(block["duplicates_across_contests"], 7)

    def test_the_brief_calls_a_within_contest_duplicate_the_finding(self):
        """Mutation guard: one contest holding a lineup twice is the waste, and
        it must not read the same as the mirrored-satellite case above."""
        module = self._module()
        base = [f"h{j}" for j in range(10)]
        other = [f"h{j}" for j in range(9)] + ["h99"]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = self._files(tmp, [base, list(base), other],
                                          ["1", "1", "2"])
            block = module.portfolio_exposure(salary, entries)
        self.assertEqual(block["duplicates_within_contest"], 1)
        self.assertEqual(block["duplicates_across_contests"], 0)

    def test_the_brief_and_the_preflight_share_one_implementation(self):
        """Two readers of one delivered file that disagree about how much of it
        duplicates is worse than either number alone, so the brief imports the
        preflight's helper instead of restating the partition."""
        source = (Path(__file__).resolve().parents[1] / "skills"
                  / "generate-lineups" / "scripts" / "build_slate.py"
                  ).read_text(encoding="utf-8")
        self.assertIn(
            "from tools.preflight_upload import partition_duplicate_lineups",
            source)
        module = self._module()
        base = [f"h{j}" for j in range(10)]
        other = [f"h{j}" for j in range(9)] + ["h99"]
        rosters = [base, list(base), other, list(other)]
        ids = ["1", "1", "1", "2"]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = self._files(tmp, rosters, ids)
            block = module.portfolio_exposure(salary, entries)
        from tools.preflight_upload import partition_duplicate_lineups
        direct = partition_duplicate_lineups(
            zip(ids, (tuple(sorted(r)) for r in rosters)))
        for key in ("duplicates_within_contest", "duplicates_across_contests",
                    "contests_in_file", "distinct_lineups"):
            self.assertEqual(block.get(key, direct[key]), direct[key],
                             f"brief and helper disagree on {key}")
        self.assertEqual(direct["duplicates_within_contest"], 1)
        self.assertEqual(direct["duplicates_across_contests"], 1)

    def test_the_brief_note_refuses_to_present_the_two_as_a_total(self):
        module = self._module()
        base = [f"h{j}" for j in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = self._files(tmp, [base, list(base)], ["1", "2"])
            block = module.portfolio_exposure(salary, entries)
        self.assertIn("do not sum to a total", block["note"])
        self.assertIn("is the finding", block["note"])
        self.assertIn("is information", block["note"])

    def test_the_pipeline_hands_the_reuse_block_to_whoever_writes_the_brief(self):
        """`candidate_reuse_counts` has been in the allocation result since v1.9
        and no caller could reach it without re-opening the run directory."""
        source = (Path(__file__).resolve().parents[1] / "mlb_engine" / "pipeline"
                  / "execution_pipeline.py").read_text(encoding="utf-8")
        self.assertEqual(
            source.count('"candidate_reuse": allocation.get("candidate_reuse")'), 2,
            "both the deferred and the promoted return paths must carry it, or a "
            "late swap's brief loses the fact the build's brief has")
        brief_source = (Path(__file__).resolve().parents[1] / "skills"
                        / "generate-lineups" / "scripts" / "build_slate.py"
                        ).read_text(encoding="utf-8")
        self.assertIn('exposure["candidate_reuse"] = result.get("candidate_reuse")',
                      brief_source)
        self.assertIn('exposure["candidate_reuse_counts"]', brief_source)


class PortfolioFrontierTests(unittest.TestCase):
    """R126: apex and washout are the stated objective and nothing measured them.

    Ben named the objective on 2026-08-15 -- "dually optimize apex lineups with
    preventing a total washout across the portfolio" -- and `washout` had zero
    matches across the engine, tools and skills while `apex` existed only as a
    posture-tier name. BUILD hand-rolled both in a scratch script to pick among
    five 2138_2g variants, so the numbers that chose a delivery were neither
    reproducible run to run nor comparable across slates.

    The fixture below is that slate's shape in miniature: two games, and two
    portfolios with the SAME apex and the SAME retained percent that differ only
    in whether any entry survives the binding game. That pair is the whole item.
    """

    G1, G2 = "AAA@BBB", "CCC@DDD"
    TEAMS = (("AAA", G1), ("BBB", G1), ("CCC", G2), ("DDD", G2))

    @staticmethod
    def _frontier():
        from mlb_engine.pipeline.execution_pipeline import compute_portfolio_frontier
        return compute_portfolio_frontier

    def _projections(self, **overrides):
        rows = []
        for team, game in self.TEAMS:
            for i in range(9):
                rows.append({"Player_ID": f"{team}h{i}", "Team": team,
                             "Game_ID": game, "Position": "OF",
                             "Ceiling": 10.0 + i})
            rows.append({"Player_ID": f"{team}p", "Team": team, "Game_ID": game,
                         "Position": "P", "Ceiling": 20.0})
        frame = pd.DataFrame(rows)
        drop = overrides.get("drop") or []
        if drop:
            frame = frame.drop(columns=list(drop))
        return frame

    @staticmethod
    def _entry(entry_id, bats, arms=("AAAp", "CCCp")):
        return {"entry_id": str(entry_id), "sp_ids": list(arms),
                "lineup_ids": list(arms) + list(bats)}

    def _concentrated(self, n=6):
        """Every entry draws four bats from each game: the rejected 2138_2g
        shape, where one cold game touches all of them."""
        bats = [f"AAAh{j}" for j in range(4)] + [f"CCCh{j}" for j in range(4)]
        return [self._entry(100 + i, bats) for i in range(n)]

    def _spread(self, n=6):
        """Half the entries take their bats from one game, half from the other:
        the delivered shape, where a cold game leaves entries untouched."""
        out = []
        for i in range(n // 2):
            out.append(self._entry(200 + i, [f"AAAh{j}" for j in range(4)]
                                   + [f"BBBh{j}" for j in range(4)]))
        for i in range(n - n // 2):
            out.append(self._entry(210 + i, [f"CCCh{j}" for j in range(4)]
                                   + [f"DDDh{j}" for j in range(4)]))
        return out

    # ---------------------------------------------------------------- apex

    def test_apex_is_summed_off_the_runs_own_ceiling_column(self):
        block = self._frontier()(self._projections(), self._concentrated(2))
        apex = block["apex"]
        # Four bats at 10+11+12+13 from each game, two arms at 20: 46+46+40.
        self.assertEqual(132.0, apex["ceiling_best"])
        self.assertEqual(264.0, apex["ceiling_total"])
        self.assertEqual(132.0, apex["ceiling_mean"])

    def test_apex_moves_when_a_ceiling_moves(self):
        """Mutation guard. The numbers above are readable enough to hardwire,
        and a hardwired apex is worse than none: it would agree with the fixture
        forever while measuring nothing. Move one Ceiling, the total must move."""
        proj = self._projections()
        proj.loc[proj["Player_ID"] == "AAAh0", "Ceiling"] = 40.0
        block = self._frontier()(proj, self._concentrated(2))
        self.assertEqual(324.0, block["apex"]["ceiling_total"],
                         "+30 on one bat held by both entries is +60 on the total")

    def test_the_best_entry_is_named_and_the_tie_break_is_stable(self):
        """Ceilings come off a uniform multiplier over a small set of base
        values, so exact ties are routine rather than exotic (determinism.py).
        A tie must resolve to the same entry every run."""
        entries = self._concentrated(4)
        first = self._frontier()(self._projections(), entries)["apex"]
        again = self._frontier()(self._projections(), list(reversed(entries)))["apex"]
        self.assertEqual(first["ceiling_best"], again["ceiling_best"])
        self.assertEqual(first["best_entry_id"], again["best_entry_id"],
                         "a reordered assignment list renamed the best entry")

    def test_the_measurement_is_over_entries_not_distinct_lineups(self):
        """Two entries holding one lineup die together, so the washout objective
        binds on the entered set. Counting distinct lineups would report a
        six-entry portfolio built from one lineup as a single exposure."""
        block = self._frontier()(self._projections(), self._concentrated(6))
        self.assertEqual(6, block["entries"])
        self.assertEqual(792.0, block["apex"]["ceiling_total"])
        self.assertEqual(60, block["roster_players"])

    # ------------------------------------------------------------- washout

    def test_zeroing_a_games_hitters_keeps_the_arms(self):
        """The definition Ben's fragment offered, and it is deliberate: an arm in
        a game that goes badly for hitters is the one roster spot that may
        benefit. An implementation that zeroed the arm too would report a lower
        retained percent for a reason the metric does not mean."""
        block = self._frontier()(self._projections(), self._concentrated(1))
        rows = {row["game"]: row for row in block["washout"]["by_game"]}
        # Zero AAA@BBB's bats: 46 of 132 lost. AAAp is in that game and stays.
        self.assertEqual(round(100.0 * 86.0 / 132.0, 1),
                         rows[self.G1]["ceiling_retained_pct"])

    def test_the_histogram_is_one_bucket_per_entry_and_sums_to_the_entries(self):
        block = self._frontier()(self._projections(), self._spread(6))
        for row in block["washout"]["by_game"]:
            self.assertEqual(6, sum(count for _, count in row["bats_histogram"]),
                             f"{row['game']} histogram does not cover every entry")
        rows = {row["game"]: row for row in block["washout"]["by_game"]}
        self.assertEqual([[0, 3], [8, 3]], rows[self.G1]["bats_histogram"])

    def test_the_2138_2g_pair_is_separated_by_intact_entries_not_by_apex(self):
        """The reproduction, and the reason the histogram is not garnish. Both
        portfolios pass the same gates, post the SAME apex and retain the SAME
        percent of portfolio ceiling; the only thing that distinguishes them is
        that one has entries the binding game cannot touch."""
        proj = self._projections()
        conc = self._frontier()(proj, self._concentrated(6))
        spread = self._frontier()(proj, self._spread(6))
        self.assertEqual(conc["apex"]["ceiling_total"],
                         spread["apex"]["ceiling_total"],
                         "fixture is wrong: apex must not separate these two")
        self.assertEqual(conc["washout"]["worst_ceiling_retained_pct"],
                         spread["washout"]["worst_ceiling_retained_pct"],
                         "fixture is wrong: retained percent must not separate them")
        self.assertEqual(0, conc["washout"]["entries_fully_intact_at_binding_game"])
        self.assertEqual(3, spread["washout"]["entries_fully_intact_at_binding_game"])
        self.assertEqual(6, conc["washout"]["by_game"][0]["entries_materially_exposed"])
        self.assertEqual(3, spread["washout"]["by_game"][0]["entries_materially_exposed"])

    def test_a_game_the_portfolio_draws_no_bat_from_is_not_a_row(self):
        """A game nobody is exposed to retains 100% with every entry intact,
        which is arithmetic rather than a finding, and it would push the real
        binding game out of by_game[0]."""
        bats = [f"AAAh{j}" for j in range(8)]
        block = self._frontier()(self._projections(), [self._entry(1, bats)])
        self.assertEqual([self.G1], [row["game"] for row in block["washout"]["by_game"]])
        self.assertEqual(1, block["washout"]["games_measured"])

    def test_by_game_is_ordered_worst_first_and_deterministically(self):
        """The binding game is by_game[0], so the ordering carries the headline.
        The heavier game here is the alphabetically LATER one on purpose: with
        the two aligned, `touched` is already sorted by game id and dropping the
        sort entirely would still name the right game, which is a guard that
        cannot fail."""
        block = self._frontier()(self._projections(),
                                 [self._entry(1, [f"CCCh{j}" for j in range(6)]
                                              + [f"AAAh{j}" for j in range(2)])])
        rows = block["washout"]["by_game"]
        self.assertEqual(self.G2, block["washout"]["binding_game"])
        self.assertEqual([self.G2, self.G1], [row["game"] for row in rows])
        self.assertLessEqual(rows[0]["ceiling_retained_pct"],
                             rows[1]["ceiling_retained_pct"])
        self.assertEqual(6, rows[0]["max_bats_in_one_entry"])
        self.assertEqual(2, rows[1]["max_bats_in_one_entry"])

    def test_material_exposure_counts_the_threshold_entry(self):
        """`entries_materially_exposed` shares qa_portfolio's threshold so the
        two reports describe the same object. Counted at exactly three bats,
        because a `>` slip is invisible on any fixture that only ever draws two
        or four."""
        from mlb_engine.pipeline.execution_pipeline import FRONTIER_MATERIAL_BATS
        self.assertEqual(3, FRONTIER_MATERIAL_BATS)
        entries = [
            self._entry(1, [f"AAAh{j}" for j in range(3)]
                        + [f"CCCh{j}" for j in range(5)]),
            self._entry(2, [f"AAAh{j}" for j in range(2)]
                        + [f"CCCh{j}" for j in range(6)]),
        ]
        rows = {row["game"]: row
                for row in self._frontier()(self._projections(),
                                            entries)["washout"]["by_game"]}
        self.assertEqual([[2, 1], [3, 1]], rows[self.G1]["bats_histogram"])
        self.assertEqual(1, rows[self.G1]["entries_materially_exposed"],
                         "three bats is material; two is not")
        self.assertEqual(2, rows[self.G2]["entries_materially_exposed"])

    def test_the_washout_note_names_the_cross_slate_comparability_limit(self):
        """The metric is bounded below by the arms plus the other games' bats,
        so it falls as the slate shrinks. Comparability across slates is one of
        the two problems this item exists to fix, so the block has to say which
        of its numbers does not have it rather than leave it to be discovered."""
        note = self._frontier()(self._projections(),
                                self._spread(6))["washout"]["note"]
        self.assertIn("NOT comparable across slates", note)
        self.assertIn("entries_fully_intact is comparable", note)

    # ------------------------------------------------------- honest degrade

    def test_no_ceiling_column_reports_one_fact_and_no_list(self):
        """R127's boundary, applied on purpose. A missing input is one fact
        about the build, not one fact per player, and a zero-valued apex block
        would read as a portfolio with no ceiling."""
        block = self._frontier()(self._projections(drop=["Ceiling"]),
                                 self._concentrated(2))
        self.assertFalse(block["available"])
        self.assertIn("no Ceiling column", block["unavailable_reason"])
        self.assertNotIn("apex", block)
        self.assertNotIn("unpriced_roster_players", block)

    def test_no_game_column_keeps_apex_and_names_the_washout_gap(self):
        block = self._frontier()(self._projections(drop=["Game_ID"]),
                                 self._concentrated(2))
        self.assertTrue(block["available"])
        self.assertEqual(264.0, block["apex"]["ceiling_total"])
        self.assertFalse(block["washout"]["available"])
        self.assertIn("no game column", block["washout"]["unavailable_reason"])

    def test_a_rostered_player_with_no_ceiling_is_named_never_zeroed(self):
        """The R127 lesson in the small: a silent zero here reads as a
        low-ceiling portfolio instead of a missing join, and the apex totals of
        two runs would differ for a reason neither states."""
        proj = self._projections()
        proj = proj[proj["Player_ID"] != "AAAh0"]
        block = self._frontier()(proj, self._concentrated(1))
        self.assertEqual(["AAAh0"], block["unpriced_roster_players"])
        self.assertIn("SHORT", block["unpriced_note"])
        self.assertEqual(122.0, block["apex"]["ceiling_total"],
                         "the total is short by exactly the unpriced ceiling")

    def test_nothing_to_measure_says_so_rather_than_reporting_zeroes(self):
        empty = self._frontier()(self._projections(), [])
        self.assertFalse(empty["available"])
        self.assertEqual(0, empty["entries"])
        self.assertIn("no assignments", empty["unavailable_reason"])
        not_a_frame = self._frontier()(None, self._concentrated(1))
        self.assertFalse(not_a_frame["available"])
        self.assertIn("projections DataFrame", not_a_frame["unavailable_reason"])

    def test_the_diagnostic_can_never_kill_a_run(self):
        """`_bank_coverage`'s rule, and the reason this is wrapped: a review
        proxy that raises turns a certified delivery into a crash."""
        from mlb_engine.pipeline import execution_pipeline as ep

        class Hostile:
            columns = ["Player_ID", "Ceiling"]

            def iterrows(self):
                raise RuntimeError("boom")

        block = ep._portfolio_frontier(Hostile(), self._concentrated(1))
        self.assertFalse(block["available"])
        self.assertIn("boom", block["unavailable_reason"])
        self.assertTrue(block["is_review_proxy"])

    def test_the_labels_never_become_a_probability_claim(self):
        """The house rule, checked on the keys and on every string that is NOT a
        note. The exemption is the point rather than a loophole: the notes are
        where the words appear NEGATED ("neither is a probability, a win rate"),
        and a naive substring sweep over the whole block fails on its own
        disclaimer, which is how this guard was wrong on its first cut."""
        block = self._frontier()(self._projections(), self._spread(6))
        banned = ("win rate", "cash rate", "roi", "probability", "chance",
                  "expected value", "profit")
        notes = ("note", "unavailable_reason", "unpriced_note")

        def sweep(value, key=""):
            if isinstance(value, dict):
                for k, v in value.items():
                    for word in banned:
                        self.assertNotIn(word, str(k).lower(),
                                         f"key {k!r} claims {word!r}")
                    sweep(v, str(k))
            elif isinstance(value, list):
                for item in value:
                    sweep(item, key)
            elif isinstance(value, str) and key not in notes:
                for word in banned:
                    self.assertNotIn(word, value.lower(),
                                     f"{key!r} claims {word!r}")

        sweep(block)
        self.assertIn("deterministic review proxies", block["note"])
        self.assertIn("not an observed outcome", block["note"])
        self.assertTrue(block["is_review_proxy"])

    # ------------------------------------------------------------- wiring

    def test_both_pipeline_return_paths_and_the_run_record_carry_the_block(self):
        """R116's lesson repeated: a block on one return path only is a block a
        late swap's brief loses, and the run record is where the question is
        asked weeks later without the projections frame in hand."""
        source = (Path(__file__).resolve().parents[1] / "mlb_engine" / "pipeline"
                  / "execution_pipeline.py").read_text(encoding="utf-8")
        self.assertEqual(
            source.count('"portfolio_frontier": portfolio_frontier'), 3,
            "the deferred return, the promoted return, and diagnostics.json must "
            "each carry it")
        self.assertIn("portfolio_frontier = _portfolio_frontier(projections, assignments)",
                      source)

    def test_the_brief_carries_the_frontier_inside_the_exposure_block(self):
        """Not a new section. The question it answers -- is this portfolio
        concentrated in a way the gates do not catch -- is the one the exposure
        block already half-answered."""
        module = PortfolioConcentrationInTheBriefTests._module()
        source = (Path(__file__).resolve().parents[1] / "skills"
                  / "generate-lineups" / "scripts" / "build_slate.py"
                  ).read_text(encoding="utf-8")
        self.assertIn('exposure["frontier"] = result.get("portfolio_frontier")',
                      source)
        self.assertTrue(hasattr(module, "format_frontier_line"))

    def test_the_review_line_states_both_ends_and_labels_them(self):
        module = PortfolioConcentrationInTheBriefTests._module()
        block = self._frontier()(self._projections(), self._spread(6))
        line = module.format_frontier_line(block)
        self.assertIn("apex total 792.0", line)
        self.assertIn(f"washout binds on {self.G1}", line)
        self.assertIn("3/6 entries untouched", line)
        self.assertIn("review proxies, not probabilities", line)

    def test_the_review_line_says_unavailable_rather_than_printing_zeroes(self):
        module = PortfolioConcentrationInTheBriefTests._module()
        self.assertIn("UNAVAILABLE", module.format_frontier_line(None))
        blank = self._frontier()(self._projections(drop=["Ceiling"]),
                                 self._concentrated(1))
        line = module.format_frontier_line(blank)
        self.assertIn("UNAVAILABLE", line)
        self.assertIn("no Ceiling column", line)

    def test_the_review_line_flags_a_short_total(self):
        """An apex the reader will compare across builds must not silently be
        short by a missing join."""
        module = PortfolioConcentrationInTheBriefTests._module()
        proj = self._projections()
        block = self._frontier()(proj[proj["Player_ID"] != "AAAh0"],
                                 self._concentrated(1))
        self.assertIn("carry no Ceiling", module.format_frontier_line(block))
        self.assertIn("SHORT", module.format_frontier_line(block))

    def test_qa_portfolio_reads_the_runs_frontier_instead_of_shadowing_it(self):
        """R128's lesson on a new surface. qa_portfolio reads a delivered CSV and
        a salary file, neither of which carries a Ceiling, so its own axes cannot
        be the washout number the build used. It now reports the artifact's
        block first and keeps its share counts as a labeled independent check."""
        from tools.qa_portfolio import frontier_from_brief
        block = self._frontier()(self._projections(), self._spread(6))
        lines = frontier_from_brief({"exposure": {"frontier": block}})
        text = "\n".join(lines)
        self.assertIn("APEX (run's own Ceiling column): total 792.0", text)
        self.assertIn(f"WASHOUT binds on {self.G1}", text)
        self.assertIn("3/6 entries untouched", text)
        self.assertIn("bats-per-entry", text)
        self.assertIn("not comparable across slates", text)

    def test_qa_portfolio_says_absent_rather_than_inventing_the_block(self):
        """A build that predates R126, or one that entered somewhere other than
        run_slate, has no frontier in its brief. Saying so is the whole
        requirement: silently falling through to the structural axes is how a
        reader concludes the run measured something it never did."""
        from tools.qa_portfolio import frontier_from_brief
        absent = "\n".join(frontier_from_brief({}))
        self.assertIn("absent from this brief", absent)
        blank = self._frontier()(self._projections(drop=["Ceiling"]),
                                 self._concentrated(1))
        unavailable = "\n".join(
            frontier_from_brief({"exposure": {"frontier": blank}}))
        self.assertIn("unavailable", unavailable)
        self.assertIn("no Ceiling column", unavailable)

    def test_qa_portfolio_labels_its_own_axes_as_the_independent_check(self):
        """The two are different units and must not read as disagreeing: the
        run's is a ceiling counterfactual, these are share-of-portfolio counts."""
        source = (Path(__file__).resolve().parents[1] / "tools"
                  / "qa_portfolio.py").read_text(encoding="utf-8")
        self.assertIn("INDEPENDENT STRUCTURAL CHECK", source)
        self.assertIn("frontier = frontier_from_brief(brief) + section_frontier",
                      source)

    def test_the_two_game_counts_are_reconciled_in_words_not_left_to_be_found(self):
        """Measured on the archived 06-03 grid the same session this landed: the
        run reports 16/18 materially exposed to SD@PHI, qa_portfolio's axis
        reports 18/18, and both are right -- the axis counts every roster spot
        in the game, the run counts bats only because it keeps the arms. Two
        numbers under one word on one screen with nothing explaining the gap is
        how a reader concludes one of them is broken."""
        from tools import qa_portfolio
        lines = qa_portfolio.section_frontier(
            {"9": {"Roster Position": "P", "Name": "Arm", "TeamAbbrev": "AAA",
                   "Game Info": "AAA@BBB 01:00PM ET"},
             **{str(i): {"Roster Position": "OF", "Name": f"n{i}",
                         "TeamAbbrev": "AAA", "Game Info": "AAA@BBB 01:00PM ET"}
                for i in range(9)}},
            ["Entry ID", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"],
            [["1", "9", "0", "1", "2", "3", "4", "5", "6", "7"]])
        text = "\n".join(lines)
        self.assertIn("counts EVERY roster spot in a game, arms included", text)
        self.assertIn("keeps the arms on purpose", text)

    def test_qa_portfolio_flags_a_short_apex_before_it_is_compared(self):
        from tools.qa_portfolio import frontier_from_brief
        proj = self._projections()
        block = self._frontier()(proj[proj["Player_ID"] != "AAAh0"],
                                 self._concentrated(2))
        text = "\n".join(frontier_from_brief({"exposure": {"frontier": block}}))
        self.assertIn("APEX IS SHORT", text)
        self.assertIn("Do not compare this apex to another build's", text)


class GitFreshnessTests(unittest.TestCase):
    """R145: session start reads `git log`, and a stale log looks current.

    Ben, 2026-08-17: "how can we make sure the git log is up-to-date always?"
    It cannot be guaranteed from here. This sandbox has no credential for a
    private repo, `git fetch` dies on "could not read Username", and the
    remote-tracking ref moves only on fetch or push. So the answer is to make
    the uncertainty visible instead of silent, which is what these pin.

    Every test builds a throwaway repo pair. Nothing touches the real one.
    """

    def _audit(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "audit.py"
        spec = importlib.util.spec_from_file_location("audit_freshness", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _pair(self, tmp):
        """A bare 'remote' and a clone tracking it, both with one commit."""
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        remote, work = Path(tmp) / "remote.git", Path(tmp) / "work"

        def git(where, *args):
            subprocess.run(("git", "-C", str(where)) + args, check=True,
                           capture_output=True, env=env)

        subprocess.run(("git", "init", "-q", "--bare", "-b", "main",
                        str(remote)), check=True, capture_output=True)
        subprocess.run(("git", "init", "-q", "-b", "main", str(work)),
                       check=True, capture_output=True)
        (work / "a.txt").write_text("one\n", encoding="utf-8")
        git(work, "add", "a.txt")
        git(work, "commit", "-q", "-m", "one")
        git(work, "remote", "add", "origin", str(remote))
        git(work, "push", "-q", "-u", "origin", "main")
        return work, git

    def _commit(self, git, work, text):
        (work / "a.txt").write_text(text + "\n", encoding="utf-8")
        git(work, "add", "a.txt")
        git(work, "commit", "-q", "-m", text)

    def test_a_clean_clone_reports_zero_both_ways(self):
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, _ = self._pair(tmp)
            out = module.git_freshness(work)
        self.assertTrue(out["available"])
        self.assertEqual((0, 0), (out["ahead"], out["behind"]))

    def test_unpushed_commits_are_named_as_a_push_ben_owes(self):
        """Sessions commit and Ben pushes (docs/cowork_sync_protocol.md). Until
        he does, no other clone can see the work at all -- which is exactly how
        14 commits sat invisible from 2026-08-14 to 08-17."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, git = self._pair(tmp)
            self._commit(git, work, "two")
            self._commit(git, work, "three")
            out = module.git_freshness(work)
        self.assertEqual(2, out["ahead"])
        self.assertEqual(0, out["behind"])

    def test_commits_the_clone_has_not_pulled_are_named(self):
        """This is the one that makes session start's `git log` a lie, so it is
        the one that has to be detectable."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, git = self._pair(tmp)
            other = Path(tmp) / "other"
            subprocess.run(("git", "clone", "-q", str(Path(tmp) / "remote.git"),
                            str(other)), check=True, capture_output=True)
            env = {**os.environ, "GIT_AUTHOR_NAME": "o",
                   "GIT_AUTHOR_EMAIL": "o@o", "GIT_COMMITTER_NAME": "o",
                   "GIT_COMMITTER_EMAIL": "o@o"}
            (other / "a.txt").write_text("from elsewhere\n", encoding="utf-8")
            for args in (("add", "a.txt"), ("commit", "-q", "-m", "elsewhere"),
                         ("push", "-q", "origin", "main")):
                subprocess.run(("git", "-C", str(other)) + args, check=True,
                               capture_output=True, env=env)
            git(work, "fetch", "-q", "origin")
            out = module.git_freshness(work)
        self.assertEqual(1, out["behind"])
        self.assertEqual(0, out["ahead"])

    def test_the_default_branch_trap_is_named(self):
        """A fresh clone lands on origin/HEAD. On the real repo that is still
        `master`, stale since 2026-08-04, while the work is on `main` -- so a
        new clone silently gets a tree weeks old."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, git = self._pair(tmp)
            self.assertIsNone(module.git_freshness(work)["default_branch_mismatch"],
                              "a clone with no origin/HEAD set is not a finding")
            git(work, "symbolic-ref", "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main")
            self.assertIsNone(module.git_freshness(work)["default_branch_mismatch"],
                              "matching default is not a finding")
            git(work, "branch", "-q", "legacy")
            git(work, "push", "-q", "origin", "legacy")
            git(work, "symbolic-ref", "refs/remotes/origin/HEAD",
                "refs/remotes/origin/legacy")
            out = module.git_freshness(work)
        self.assertEqual("origin/legacy", out["default_branch_mismatch"])

    def test_a_branch_with_no_upstream_is_silent_not_clean(self):
        """No upstream means nothing to measure against. Reporting 0/0 there
        would be the false clean this whole check exists to avoid."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, git = self._pair(tmp)
            git(work, "checkout", "-q", "-b", "detached-work")
            out = module.git_freshness(work)
        self.assertFalse(out["available"])
        self.assertEqual(0, out["behind"])

    def test_a_non_numeric_answer_degrades_to_silent(self):
        """Found by VendoredPylibsTests, which patches subprocess.run to fake
        the suite subprocess and so fed this check unittest output. An `int()`
        on whatever came back raised inside run_audit and took the whole audit
        down. Anything that is not a bare count means git was not the one
        answering, and the honest result is `available: False`, not a crash and
        not a clean 0/0."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, _ = self._pair(tmp)
            real = subprocess.run

            def fake(cmd, *a, **kw):
                if isinstance(cmd, (list, tuple)) and "rev-list" in cmd:
                    return types.SimpleNamespace(
                        returncode=0, stdout="Ran 0 tests in 0.0s\n\nOK", stderr="")
                return real(cmd, *a, **kw)

            with unittest.mock.patch.object(module.subprocess, "run", fake):
                out = module.git_freshness(work)
        self.assertFalse(out["available"])
        self.assertEqual((0, 0), (out["ahead"], out["behind"]))

    def test_a_credential_only_in_dotenv_is_found(self):
        """R146. A valid fine-grained PAT sat in REPO/.env under GH_PAT while
        find_token read os.environ alone, so every run reported "no usable
        token" and GitHub's head went unmeasured against a credential that was
        present and working. repo_env already resolves THE_ODDS_API_KEY from
        .env for exactly this reason."""
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "sync_check.py"
        spec = importlib.util.spec_from_file_location("sync_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fake = "x" * (module.MIN_TOKEN_LEN + 40)
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            for name in module.TOKEN_ENV_VARS:
                os.environ.pop(name, None)
            with unittest.mock.patch(
                    "mlb_engine.repo_env.resolve_secret",
                    side_effect=lambda n, *a, **k: fake if n == "GH_PAT" else None):
                name, token = module.find_token()
        self.assertEqual("GH_PAT", name)
        self.assertEqual(fake, token)

    def test_the_dotenv_fallback_works_when_run_as_a_script(self):
        """The first cut imported mlb_engine without putting REPO on sys.path,
        so `python tools/sync_check.py` -- the invocation its own docstring
        documents -- hit ImportError and the fallback silently no-opped. It
        passed when the function was imported from the repo root and failed
        when the script was run. Run the script."""
        root = Path(__file__).resolve().parents[1]
        if not (root / ".env").exists():
            self.skipTest("no .env on this machine")
        done = subprocess.run(
            [sys.executable, str(root / "tools" / "sync_check.py"), "--no-remote"],
            capture_output=True, text=True, cwd="/", timeout=120)
        source = (root / "tools" / "sync_check.py").read_text(encoding="utf-8")
        self.assertIn("sys.path.insert(0, str(REPO))", source,
                      "the repo root must be on sys.path before the import")
        self.assertNotIn("no usable token", done.stdout,
                         "a credential in .env must be found by the script path")

    def test_an_explicit_environ_still_wins_over_dotenv(self):
        """The .env fallback is a fallback. A caller that passes an environ is
        stating what to use, and a test that pins 'no token' must keep meaning
        it even on a machine whose .env has one."""
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "sync_check.py"
        spec = importlib.util.spec_from_file_location("sync_explicit", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual((None, None), module.find_token(environ={}))

    def test_a_fetch_makes_behind_a_measurement_and_drops_the_hedge(self):
        """With no fetch, `behind: 0` can mean "I cannot know", so a stale
        contact is hedged. After a fetch it is a measurement, and hedging it
        would be false caution -- which trains the reader to discount the real
        warnings."""
        module = self._audit()
        source = (Path(__file__).resolve().parents[1] / "tools" / "audit.py"
                  ).read_text(encoding="utf-8")
        self.assertIn('if not fresh["fetched"] and age is not None', source,
                      "the staleness hedge must be conditional on the fetch")
        with tempfile.TemporaryDirectory() as tmp:
            work, _ = self._pair(tmp)
            out = module.git_freshness(work, allow_fetch=False)
        self.assertFalse(out["fetched"])
        self.assertTrue(out["available"], "no fetch still measures the refs")

    def test_the_token_never_reaches_argv_a_url_or_git_config(self):
        """The one rule that cannot be relaxed. The token goes to git through
        GIT_ASKPASS and an env var, so it stays out of `ps`, out of shell
        history, out of .git/config and out of any remote URL."""
        source = (Path(__file__).resolve().parents[1] / "tools" / "audit.py"
                  ).read_text(encoding="utf-8")
        fetch = source.split("def _try_git_fetch", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("GIT_ASKPASS", fetch)
        self.assertIn("GIT_TERMINAL_PROMPT", fetch)
        self.assertIn('["git", "fetch", "--quiet", "origin"]', fetch,
                      "the remote is named, never a URL carrying a credential")
        # Scan the CODE. The docstring says ".git/config" and "remote URL"
        # describing what is avoided, and a scanner that cannot tell prose from
        # an instruction fails on its own documentation.
        body = fetch.split('"""', 2)[-1]
        for leak in ("{token", "token}", "https://", "remote.origin.url",
                     "git\", \"config", "print(", "done.stdout"):
            self.assertNotIn(leak, body, f"possible credential leak: {leak}")
        # R147 TIGHTENS this rather than relaxing it. The body must now READ
        # git's stderr, because a failure has to be classified instead of
        # blamed on the token. It must still never SURFACE it. So the stream
        # gets exactly one appearance, only as the classifier's argument, and
        # the classifier's whole return set is three fixed strings. The
        # behavioural half is
        # test_a_classified_reason_never_carries_the_stream_it_read; a blanket
        # ban would have been the weaker guard, since it says nothing about
        # what the classifier does with what it reads.
        self.assertEqual(1, body.count("done.stderr"),
                         "the stream is read once, for classification, or not "
                         "at all")
        self.assertIn("classify_git_failure(done.stderr)", body,
                      "the only permitted reader is the classifier")

    def test_freshness_is_wired_as_a_warning_and_never_an_error(self):
        """An out-of-date clone is a real problem and still not a reason to
        refuse to build a slate."""
        source = (Path(__file__).resolve().parents[1] / "tools" / "audit.py"
                  ).read_text(encoding="utf-8")
        wiring = source.split("fresh = git_freshness(root", 1)
        self.assertEqual(2, len(wiring), "run_audit must call git_freshness")
        tail = wiring[1].split("drift = skill_cache_drift(root)", 1)[0]
        self.assertIn("warnings.append(", tail)
        self.assertNotIn("errors.append(", tail)
        self.assertIn('checks["git_freshness"] = fresh', tail)

    # -- R147: a failed remote call names what actually stopped it ----------
    # Measured 2026-08-17, thirty minutes after R146 shipped: from a cloud
    # Cowork session's device VM the audit reported "fetch failed: check the
    # token scope or expiry" against a PAT that was present, in scope and
    # working. That VM has no outbound network at all -- its proxy answers
    # CONNECT with 403 for a PUBLIC repo needing no credential -- and both
    # tools hard-coded the credential explanation for every non-zero return.
    # The remedy the message named was regenerating a good token.

    def _sync(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "sync_check.py"
        spec = importlib.util.spec_from_file_location("sync_classify", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_proxy_refusing_connect_is_a_network_failure_not_a_bad_token(self):
        """The exact stderr measured on the device VM."""
        sync = self._sync()
        self.assertEqual(
            sync.GIT_FAIL_NETWORK,
            sync.classify_git_failure(
                "fatal: unable to access 'https://github.com/o/r.git/': "
                "Received HTTP code 403 from proxy after CONNECT"))

    def test_a_credential_403_is_still_a_credential_failure(self):
        """The other half of the pair, sharing its prefix on purpose. Both
        messages open with git's generic "unable to access '<url>':" and both
        carry a 403; only the tail separates them, so any rule keyed on the
        prefix gets one of the two wrong. Mutation-checked: adding "unable to
        access" to the network markers, which is the edit that nearly shipped,
        fails here and nowhere else."""
        sync = self._sync()
        self.assertEqual(
            sync.GIT_FAIL_CREDENTIAL,
            sync.classify_git_failure(
                "fatal: unable to access 'https://github.com/o/r.git/': "
                "The requested URL returned error: 403"))

    def test_an_unreachable_or_unresolvable_host_is_a_network_failure(self):
        sync = self._sync()
        for stream in ("fatal: unable to access 'x': Could not resolve host: "
                       "github.com",
                       "ssh: connect to host github.com port 22: Network is "
                       "unreachable",
                       "fatal: unable to access 'x': Failed to connect to "
                       "github.com port 443: Connection timed out"):
            self.assertEqual(sync.GIT_FAIL_NETWORK,
                             sync.classify_git_failure(stream), stream)

    def test_a_rejected_credential_is_named_as_one(self):
        sync = self._sync()
        for stream in ("fatal: Authentication failed for 'https://github.com/o/r.git/'",
                       "fatal: could not read Username for 'https://github.com': "
                       "terminal prompts disabled",
                       "remote: Repository not found."):
            self.assertEqual(sync.GIT_FAIL_CREDENTIAL,
                             sync.classify_git_failure(stream), stream)

    def test_every_marker_classifies_into_its_own_bucket(self):
        """The two lists have to stay disjoint in what they can match, and two
        sample messages cannot show that. A marker filed in the wrong list, or
        one the other list already covers as a substring, is invisible until
        the day it decides a real failure."""
        sync = self._sync()
        for marker in sync._GIT_NETWORK_MARKERS:
            self.assertEqual(sync.GIT_FAIL_NETWORK,
                             sync.classify_git_failure(f"fatal: {marker}"),
                             f"network marker misfiled: {marker}")
        for marker in sync._GIT_CREDENTIAL_MARKERS:
            self.assertEqual(sync.GIT_FAIL_CREDENTIAL,
                             sync.classify_git_failure(f"fatal: {marker}"),
                             f"credential marker misfiled: {marker}")

    def test_an_unreadable_reason_claims_neither_cause(self):
        """`--quiet` can swallow the stream, and inventing a cause is the whole
        defect. Unknown is an honest third answer, not a fallback to either."""
        sync = self._sync()
        for stream in ("", None, "fatal: something new in git 3.0"):
            self.assertEqual(sync.GIT_FAIL_UNKNOWN,
                             sync.classify_git_failure(stream), repr(stream))

    def test_a_classified_reason_never_carries_the_stream_it_read(self):
        """git's stderr can echo the remote URL, and a token-in-URL remote
        would put the credential in it. The classifier reads the stream; the
        three strings it can return are the only things that leave."""
        sync = self._sync()
        poisoned = ("fatal: unable to access 'https://x-access-token:"
                    "github_pat_LEAKED@github.com/bleeski/mlb-dfs.git/': "
                    "Received HTTP code 403 from proxy after CONNECT")
        reason = sync.classify_git_failure(poisoned)
        self.assertEqual(sync.GIT_FAIL_NETWORK, reason)
        for fragment in ("github_pat_LEAKED", "x-access-token", "https://",
                         "bleeski", "github.com"):
            self.assertNotIn(fragment, reason)

    def test_both_tools_classify_through_the_one_function(self):
        """Two readers of the same failure that disagree about its cause would
        be worse than either alone (the R128 rule). audit imports it from
        sync_check the same way it already imports find_token."""
        root = Path(__file__).resolve().parents[1] / "tools"
        audit_src = (root / "audit.py").read_text(encoding="utf-8")
        sync_src = (root / "sync_check.py").read_text(encoding="utf-8")
        self.assertIn("from sync_check import classify_git_failure", audit_src)
        self.assertIn("classify_git_failure(proc.stderr)", sync_src)
        self.assertNotIn('"fetch failed: check the token scope', audit_src)
        self.assertNotIn('"ls-remote failed: check the token scope"', sync_src)
        self.assertEqual(1, sync_src.count("def classify_git_failure"))

    def test_a_failed_fetch_does_not_reset_the_contact_age(self):
        """R146's fetch falsified R145's freshness number. A fetch that dies
        still touches .git/FETCH_HEAD and truncates it to zero bytes, so every
        failure reported fetch_age_hours 0.0 -- fresh contact that never
        happened -- and the stale-contact warning, gated on age > 24, could
        never fire on the one clone that cannot reach the remote at all."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            work, _ = self._pair(tmp)
            ref = work / ".git" / "refs" / "remotes" / "origin" / "main"
            self.assertTrue(ref.exists(), "the clone tracks a loose remote ref")
            old = datetime.now(timezone.utc).timestamp() - 48 * 3600
            os.utime(ref, (old, old))
            fetch_head = work / ".git" / "FETCH_HEAD"

            fetch_head.write_text("", encoding="utf-8")
            failed = module.git_freshness(work, allow_fetch=False)
            self.assertIsNotNone(failed["fetch_age_hours"])
            self.assertGreater(
                failed["fetch_age_hours"], 24,
                "a zero-byte FETCH_HEAD is a dead fetch, not contact")

            # And the zero-byte rule has to MEAN something: a fetch that
            # reached the remote writes a line per ref even when everything is
            # already up to date, and that one still counts as contact. Without
            # this half, ignoring FETCH_HEAD outright would pass the assertion
            # above while discarding the only signal a push does not give.
            fetch_head.write_text(
                "0000000000000000000000000000000000000000\t\tbranch 'main'\n",
                encoding="utf-8")
            reached = module.git_freshness(work, allow_fetch=False)
            self.assertLess(reached["fetch_age_hours"], 1.0)

    def test_the_classified_reason_reaches_the_session_start_line(self):
        """The reason is worth nothing in JSON nobody opens. --terse is the
        command CLAUDE.md pins, and a stale contact this run could not refresh
        rides out on it, naming the cause."""
        module = self._audit()
        result = {
            "passed": True, "project_version": "vTEST", "errors": [],
            "warnings": ["last contact with the remote was 48.0h ago and this "
                         "run could not fetch (fetch failed: no network "
                         "reachable from this environment), so 'behind: 0' is "
                         "only as current as that"],
            "checks": {"tests": {}},
        }
        line = module.terse_output(result, Path(__file__).resolve().parents[1])
        self.assertIn("no network reachable from this environment", line)
        self.assertNotIn("token", line)


class DkBattingOrderPrecedenceTests(unittest.TestCase):
    """R143, Ben 2026-08-17: DKSalaries first, a paste second, an API third.

    DK publishes the batting order in the `Starting` column, 1-9 beside the
    Player_ID the build already treats as authoritative. Classic read that
    column only as a crosswalk CHECK and sourced hitters from the feed, so on
    2026-08-16 fifteen of sixteen posted sides carried a complete order in the
    authoritative file while the build fetched the same fact over the network.

    The ranking is PER SIDE. A slate where DK posted five sides and a paste
    covers eight must take DK for those five and the paste for the other three.
    """

    def _adapters(self):
        from mlb_engine.intake import live_data_adapters as lda
        return lda

    def _players(self, orders, probables=None):
        """orders: {team: [name, ...] in slot order}. Returns {pid: obj}."""
        from mlb_engine.intake.slate_intake_manager import SalaryPlayer
        out, pid = {}, 1000
        for team, names in orders.items():
            for slot, name in enumerate(names, start=1):
                out[str(pid)] = SalaryPlayer(
                    player_id=str(pid), name=name, team=team, positions=("OF",),
                    salary=3000.0, game_info=f"{team}@OPP 08/16/2026 07:05PM ET",
                    game_id=f"{team}@OPP", starting=str(slot))
                pid += 1
        for team, name in (probables or {}).items():
            out[str(pid)] = SalaryPlayer(
                player_id=str(pid), name=name, team=team, positions=("SP",),
                salary=9000.0, game_info=f"{team}@OPP 08/16/2026 07:05PM ET",
                game_id=f"{team}@OPP", starting="SP")
            pid += 1
        return out

    NINE = [f"H{i}" for i in range(1, 10)]

    def test_a_complete_dk_nine_is_a_confirmed_side_sourced_from_the_csv(self):
        lda = self._adapters()
        players = self._players({"NYY": self.NINE})
        feed, report = lda.merge_dk_starting_into_feed({}, players)
        self.assertEqual(["NYY"], report["dk_sides"])
        side = feed["games"][0]["away"]
        self.assertEqual("confirmed", side["lineup_status"])
        self.assertEqual("dk_salary_starting", side["lineup_source"])
        self.assertEqual(list(range(1, 10)), [h["order"] for h in side["lineup"]])
        self.assertTrue(all(h["dk_id"] for h in side["lineup"]),
                        "every DK-sourced hitter carries its DK Player_ID, "
                        "which is what removes the name crosswalk")

    def test_a_partial_dk_side_is_not_confirmed_and_falls_through(self):
        """Eight posted slots is a projection. Calling it confirmed would be
        the labels rule broken at the front door, same as R60's partial side."""
        lda = self._adapters()
        players = self._players({"NYY": self.NINE[:8]})
        _, report = lda.merge_dk_starting_into_feed({}, players)
        self.assertEqual([], report["dk_sides"])
        self.assertIn("NYY", report["sides_left_to_feed"])

    def test_precedence_is_per_side_not_per_slate(self):
        """DK covers one side, the feed covers the other. Both are used."""
        lda = self._adapters()
        players = self._players({"NYY": self.NINE, "BOS": self.NINE[:3]})
        feed_in = {"games": [{
            "game_date_utc": "2026-08-16T23:05:00+00:00",
            "away": {"team_abbrev": "BOS", "lineup_status": "confirmed",
                     "lineup": [{"order": 1, "name": "B1", "bat_side": "L"}]},
            "home": {"team_abbrev": "OPP", "lineup_status": "unknown",
                     "lineup": []}}]}
        feed, report = lda.merge_dk_starting_into_feed(feed_in, players)
        self.assertEqual(["NYY"], report["dk_sides"])
        bos = next(g["away"] for g in feed["games"]
                   if g["away"].get("team_abbrev") == "BOS")
        self.assertEqual("confirmed", bos["lineup_status"])
        self.assertEqual([{"order": 1, "name": "B1", "bat_side": "L"}],
                         bos["lineup"], "the feed's side is untouched")

    def test_dk_wins_a_same_side_disagreement_and_it_is_named(self):
        """Neither source can be proven fresher: the CSV is a point-in-time
        download and a paste carries no timestamp. DK wins per Ben's order and
        the difference is reported rather than silently resolved."""
        lda = self._adapters()
        players = self._players({"NYY": self.NINE})
        stale = [{"order": i, "name": n, "bat_side": "R"} for i, n in
                 enumerate(["ZZ_Scratched"] + self.NINE[1:], start=1)]
        feed_in = {"games": [{
            "game_date_utc": "2026-08-16T23:05:00+00:00",
            "away": {"team_abbrev": "NYY", "lineup_status": "confirmed",
                     "lineup": stale},
            "home": {"team_abbrev": "OPP", "lineup": []}}]}
        feed, report = lda.merge_dk_starting_into_feed(feed_in, players)
        self.assertEqual(["NYY"], report["upgraded"])
        self.assertEqual(1, len(report["disagreements"]))
        d = report["disagreements"][0]
        self.assertEqual("dk_salary_starting", d["resolved_to"])
        self.assertEqual(["zz_scratched"], d["in_feed_not_dk"])
        self.assertEqual(["h1"], d["in_dk_not_feed"])
        names = [h["name"] for h in feed["games"][0]["away"]["lineup"]]
        self.assertEqual(self.NINE, names, "DK's order is what survives")

    def test_the_merge_keeps_handedness_the_feed_had(self):
        """DK ships no bat_side and F4 platoon needs it. Where a feed covers
        the same side, its handedness rides along rather than being discarded."""
        lda = self._adapters()
        players = self._players({"NYY": self.NINE})
        feed_in = {"games": [{
            "game_date_utc": "2026-08-16T23:05:00+00:00",
            "away": {"team_abbrev": "NYY", "lineup_status": "confirmed",
                     "lineup": [{"order": i, "name": n, "bat_side": "L"}
                                for i, n in enumerate(self.NINE, start=1)]},
            "home": {"team_abbrev": "OPP", "lineup": []}}]}
        feed, report = lda.merge_dk_starting_into_feed(feed_in, players)
        self.assertTrue(all(h["bat_side"] == "L"
                            for h in feed["games"][0]["away"]["lineup"]))
        self.assertEqual([], report["f4_handedness_unavailable"])

    def test_a_dk_only_side_names_its_missing_handedness(self):
        """The cost of skipping the fetch is stated, never silent. A zeroed F4
        that nobody was told about is the failure this repo has already paid
        for once."""
        lda = self._adapters()
        _, report = lda.merge_dk_starting_into_feed(
            {}, self._players({"NYY": self.NINE}))
        self.assertEqual(["NYY"], report["f4_handedness_unavailable"])

    def test_dk_probables_are_sp_only_never_the_opener_or_the_long_reliever(self):
        """R104 settled that a PO opener is not a declared starter, and
        CLAUDE.md makes rostering a PLR an explicit call. Neither may be
        promoted to a probable by a merge acting on the team's behalf."""
        from mlb_engine.intake.slate_intake_manager import SalaryPlayer
        lda = self._adapters()
        players = {
            "1": SalaryPlayer(player_id="1", name="Opener", team="NYY",
                              positions=("RP",), salary=5000.0, starting="PO"),
            "2": SalaryPlayer(player_id="2", name="Bulk", team="BOS",
                              positions=("RP",), salary=5000.0, starting="PLR"),
            "3": SalaryPlayer(player_id="3", name="Ace", team="TOR",
                              positions=("SP",), salary=9000.0, starting="SP"),
        }
        self.assertEqual({"TOR": "3"}, lda.dk_declared_probables(players))

    def test_coverage_is_one_definition_shared_by_pool_and_caller(self):
        """build_slate.py skips the fetch on this answer and the pool sources
        hitters on the same one. Two rules here means a build that skipped a
        fetch it needed."""
        lda = self._adapters()
        salary = (Path(__file__).resolve().parents[1] / "data" / "slates"
                  / "2026-08-16" / "DKSalaries.csv")
        if not salary.exists():
            self.skipTest("2026-08-16 salary file not staged")
        covered, uncovered = lda.dk_order_coverage(salary)
        self.assertEqual(15, len(covered))
        self.assertEqual(["DET"], uncovered)
        self.assertFalse(bool(covered) and not uncovered,
                         "one uncovered side means the fetch still happens")

    def test_a_fully_posted_slate_builds_a_pool_with_no_feed_at_all(self):
        """The whole point of Ben's ask: no paste, no API call. Against the
        real 2026-08-16 file with an empty feed."""
        from mlb_engine.intake.live_data_adapters import build_slate_pool
        salary = (Path(__file__).resolve().parents[1] / "data" / "slates"
                  / "2026-08-16" / "DKSalaries.csv")
        if not salary.exists():
            self.skipTest("2026-08-16 salary file not staged")
        out = build_slate_pool(str(salary), {}, stale_platoon_policy="warn",
                               now=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
        report = out["pool_report"]["dk_batting_order"]
        self.assertEqual(15, len(report["dk_sides"]))
        self.assertEqual(8, len(report["games_synthesized"]),
                         "games absent from an empty feed come off Game Info")
        confirmed = [t for t, v in out["pool_report"]["teams"].items()
                     if str(v.get("status")) == "confirmed"]
        self.assertEqual(15, len(confirmed))
        self.assertGreaterEqual(out["pool_report"]["hitters_kept"], 135)


class SkillCacheDriftTests(unittest.TestCase):
    """R142: an installed skill snapshot that no longer matches the repo.

    Cowork installs a skill by COPYING its SKILL.md; the copy never re-reads
    the repo and nothing warns when they diverge. Measured 2026-08-16: the
    installed `generate-lineups` was 85 commits and 351 lines behind, missing
    the autobuild path, the paste intake and the preflight exit codes, and its
    trigger still described Showdown as certified.

    Two things this must get right or it is worse than nothing. It must stay
    quiet where the cache is unreachable (Ben's own PowerShell), because a
    check that cannot see the thing must not report it clean. And it must not
    warn forever on a difference that is by design, because a gate that is
    always yellow is a gate nobody reads.

    Nothing here touches the real cache or the real repo.
    """

    def _audit(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "tools" / "audit.py"
        spec = importlib.util.spec_from_file_location("audit_skillcache", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    BODY = "# Do the thing\n\nStep one.\nStep two.\n"

    def _tree(self, tmp, *, cache_desc, repo_desc, cache_body=None,
              repo_body=None, install=True):
        """A throwaway repo plus a throwaway skill cache beside it."""
        root = Path(tmp) / "repo"
        cache = Path(tmp) / "cache"
        (root / "skills" / "demo").mkdir(parents=True)
        (root / "skills" / "demo" / "SKILL.md").write_text(
            f"---\nname: demo\ndescription: {repo_desc}\n---\n\n"
            + (repo_body if repo_body is not None else self.BODY),
            encoding="utf-8")
        if install:
            (cache / "demo").mkdir(parents=True)
            (cache / "demo" / "SKILL.md").write_text(
                f"---\nname: \"demo\"\ndescription: {json.dumps(cache_desc)}\n---\n\n"
                + (cache_body if cache_body is not None else self.BODY),
                encoding="utf-8")
        else:
            cache.mkdir(parents=True)
        return root, cache

    def _drift(self, module, root, cache):
        with unittest.mock.patch.dict(
                os.environ, {module.SKILL_CACHE_ENV: str(cache)}):
            return module.skill_cache_drift(root)

    def test_an_in_sync_copy_reports_no_drift(self):
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, cache = self._tree(tmp, cache_desc="use me", repo_desc="use me")
            out = self._drift(module, root, cache)
        self.assertTrue(out["available"])
        self.assertEqual(1, out["checked"])
        self.assertEqual([], out["drifted"])

    def test_coworks_json_quoting_alone_is_not_drift(self):
        """The repo writes `description: text`; Cowork rewrites it
        `description: "text"` with JSON escaping. Comparing raw lines would
        report every installed skill as drifted forever, on the first run."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, cache = self._tree(
                tmp,
                cache_desc='say "go" now, then stop',
                repo_desc='say "go" now, then stop')
            raw = (cache / "demo" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn('\\"go\\"', raw, "fixture must exercise the escaping")
            out = self._drift(module, root, cache)
        self.assertEqual([], out["drifted"])

    def test_a_stale_body_is_named(self):
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, cache = self._tree(tmp, cache_desc="d", repo_desc="d",
                                     cache_body="# Old\n\nStep one.\n")
            out = self._drift(module, root, cache)
        self.assertEqual([{"skill": "demo", "reasons": ["body"]}], out["drifted"])

    def test_a_stale_trigger_description_is_named(self):
        """The description is what routes a prompt to the skill at all. A
        session that reads only the repo cannot see that it is wrong."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, cache = self._tree(tmp, cache_desc="old trigger",
                                     repo_desc="new trigger")
            out = self._drift(module, root, cache)
        self.assertEqual([{"skill": "demo", "reasons": ["trigger description"]}],
                         out["drifted"])

    def test_a_pointer_body_is_not_drift_but_its_description_still_is(self):
        """Once the installed body is a pointer at the repo file, the bodies
        differ permanently and on purpose. The description is the one thing a
        pointer cannot keep in sync, so it must still be compared."""
        module = self._audit()
        pointer = f"# Demo\n\n<!-- {module.POINTER_SENTINEL} -->\nRead the repo copy.\n"
        with tempfile.TemporaryDirectory() as tmp:
            root, cache = self._tree(tmp, cache_desc="same", repo_desc="same",
                                     cache_body=pointer)
            self.assertEqual([], self._drift(module, root, cache)["drifted"])
            root2, cache2 = self._tree(Path(tmp) / "b", cache_desc="stale",
                                       repo_desc="fresh", cache_body=pointer)
            out = self._drift(module, root2, cache2)
        self.assertEqual([{"skill": "demo", "reasons": ["trigger description"]}],
                         out["drifted"])

    def test_a_repo_skill_that_is_not_installed_is_skipped(self):
        """Not every skill in the repo is installed, and one that is not is
        not this check's business."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, cache = self._tree(tmp, cache_desc="x", repo_desc="y",
                                     install=False)
            out = self._drift(module, root, cache)
        self.assertTrue(out["available"])
        self.assertEqual(0, out["checked"])
        self.assertEqual([], out["drifted"])

    def test_an_unreachable_cache_is_silent_not_clean(self):
        """From Ben's PowerShell the cache sits under an AppData path keyed by
        session GUIDs and is not derivable from the repo. Guessing a path or
        printing a clean line would both be lies; `available: False` is the
        honest answer and produces no warning."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._tree(tmp, cache_desc="a", repo_desc="b")
            out = self._drift(module, root, Path(tmp) / "no-such-cache")
        self.assertFalse(out["available"])
        self.assertEqual([], out["drifted"])
        self.assertEqual(0, out["checked"])

    def test_a_description_too_long_to_install_is_named_even_with_no_cache(self):
        """Cowork refuses a description past 1024 characters, so one written
        longer than that cannot be installed as written; somebody shortens it
        by hand and the copy is drifted the moment it exists. Found on
        mlb-standings-pull-checklist at 1073. This reads only the repo, so it
        must report from Ben's PowerShell too, where the cache is invisible."""
        module = self._audit()
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._tree(tmp, cache_desc="x",
                                 repo_desc="y" * (module.SKILL_DESCRIPTION_LIMIT + 1))
            out = self._drift(module, root, Path(tmp) / "no-such-cache")
        self.assertFalse(out["available"], "cache is unreachable in this case")
        self.assertEqual([{"skill": "demo",
                           "chars": module.SKILL_DESCRIPTION_LIMIT + 1,
                           "limit": module.SKILL_DESCRIPTION_LIMIT}],
                         out["oversized"])

    def test_every_repo_skill_description_fits_the_install_limit(self):
        """The live repo, not a fixture. A skill that cannot be installed as
        written is a defect whether or not anyone has tried lately."""
        module = self._audit()
        root = Path(__file__).resolve().parents[1]
        over = [(p.parent.name, len(module._skill_frontmatter(
                    p.read_text(encoding="utf-8")).get("description", "")))
                for p in sorted((root / "skills").glob("*/SKILL.md"))]
        self.assertTrue(over, "no skills found; the glob is wrong")
        self.assertEqual(
            [], [o for o in over if o[1] > module.SKILL_DESCRIPTION_LIMIT],
            f"over the {module.SKILL_DESCRIPTION_LIMIT}-char install limit")

    def test_drift_is_wired_as_a_warning_and_never_an_error(self):
        """`errors` fails the audit and blocks a session. A stale snapshot is
        real but it is not a reason to refuse to build a slate."""
        source = (Path(__file__).resolve().parents[1] / "tools" / "audit.py"
                  ).read_text(encoding="utf-8")
        wiring = source.split("drift = skill_cache_drift(root)", 1)
        self.assertEqual(2, len(wiring), "run_audit must call skill_cache_drift")
        tail = wiring[1].split("return {", 1)[0]
        self.assertIn("warnings.append(", tail)
        self.assertNotIn("errors.append(", tail)
        self.assertIn('checks["skill_cache"] = drift', tail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
