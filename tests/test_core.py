from __future__ import annotations

import csv
import inspect
import json
import tempfile
import types
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from mlb_engine.optimize import optimizer_v3 as opt

from mlb_engine.pipeline import execution_pipeline as epi

from mlb_engine.pipeline.build_state_manager import (
    create_run, promote_run, register_artifact, sha256_file,
    slate_context_refresh_plan, update_run_certification,
)
from mlb_engine.allocate.contest_allocator import (
    ContestCard, contest_cards_from_reserved_grid, resolve_candidate_bank_plan,
    resolve_phase0_mode, select_and_assign_entries, select_and_assign_portfolio,
)
from mlb_engine.entries.dk_entries_manager import (
    ROSTER_SLOTS, parse_dk_entry_rows, reconcile_entries_against_assignments,
    validate_dk_entries_file, validate_template_preservation,
    validate_upload_ready_gates,
)
from mlb_engine.pipeline.execution_pipeline import run_initial_build, run_late_swap, run_slate, normalize_posture
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


def pool_salary_csv(path: Path, game_dt_et: str = "07/10/2026 07:05PM ET") -> None:
    """Four-team salary file for pool-contract tests: per team, 9 lineup-caliber
    hitters, 4 bench bats, 1 probable SP, and 3 relievers (68 rows total)."""
    header = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary",
              "Game Info", "AvgPointsPerGame", "TeamAbbrev"]
    games = {"T1": "T1@T2", "T2": "T1@T2", "T3": "T3@T4", "T4": "T3@T4"}
    hit_pos = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "1B"]
    rows = []
    pid = 30000
    for team in ("T1", "T2", "T3", "T4"):
        gi = f"{games[team]} {game_dt_et}"
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

    # The six gates this fixture cannot evidence: it supplies no odds map, no
    # weather map, and no pitcher_roles. Before F4 they defaulted to True and the
    # certification read clean; now they are absent, and absent blocks.
    UNEVIDENCED = ["odds_gate_passed", "weather_gate_passed", "pitcher_audit_gate_passed"]

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
    def _pool(self, tmp: str, feed=None, platoon="default", **kwargs):
        salary = Path(tmp) / "salary.csv"
        pool_salary_csv(salary)
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


class BuildSlateScriptTests(unittest.TestCase):
    """Covers the two pure helpers in the generate-lineups build script.

    The script is the production front door but had no test harness; its
    top-level imports are stdlib only, so it loads without the engine.
    """

    @staticmethod
    def _module():
        import importlib.util
        path = (Path(__file__).resolve().parents[1] / "skills" / "generate-lineups"
                / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location("build_slate_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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
            self.assertTrue(any("does not recognize" in b
                                for b in plan["exclusions"]["blockers"]))


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
            self.assertEqual(report["teams"]["T4"]["status"], "platoon")
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

    def test_dk_probable_opener_does_not_enter_as_a_plain_probable(self):
        """DK's Starting=PO is a probable opener, not a starter.

        Teeth: without the token branch every arm resolves to
        declared_probable_sp and both the role assertion and the warning
        assertion fail. Verified against a real file: SD's Randy Vasquez carries
        Starting=PO in data/slates/2026-07-25/DKSalaries.csv and entered that
        build as a declared starter.
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary = self._salary(tmp, starting={"T4 Ace": "PO", "T1 Ace": "SP"})
            pool = lda.build_slate_pool(salary, pool_lineups_feed(),
                                        platoon_json=self._platoon())
            roles = pool["pitcher_roles"]
            by_name = {r["Player_ID"]: r["Name"] for r in pool["projection_rows"]}
            opener = [pid for pid, role in roles.items() if by_name[pid] == "T4 Ace"]
            self.assertEqual(len(opener), 1)
            self.assertEqual(roles[opener[0]], "viable_bulk_or_alt_sp")
            self.assertEqual(roles[[p for p in roles if by_name[p] == "T1 Ace"][0]],
                             "declared_probable_sp")
            self.assertTrue(any("Starting=PO" in w and "T4 Ace" in w
                                for w in pool["pool_report"]["warnings"]))
            # An opener is still rosterable: the gate's allowed-role set and the
            # export validator both accept viable_bulk_or_alt_sp. What changes is
            # that it is outside REQUIRED_SP_AUDIT_STATUSES.
            from mlb_engine.entries.dk_entries_manager import ALLOWED_PITCHER_ROLES
            from mlb_engine.optimize.optimizer_v3 import REQUIRED_SP_AUDIT_STATUSES
            self.assertIn("viable_bulk_or_alt_sp", ALLOWED_PITCHER_ROLES)
            self.assertNotIn("viable_bulk_or_alt_sp", REQUIRED_SP_AUDIT_STATUSES)

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
        self._claim("take", "inbox", "--role", "ARCHIVE", "--date", "2020-01-01")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
