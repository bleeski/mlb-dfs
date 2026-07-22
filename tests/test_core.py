from __future__ import annotations

import csv
import json
import tempfile
import unittest
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

    def test_approved_promotes_with_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            salary, entries, cands, proj = self._inputs(root)
            built = run_slate(
                runs_root=root / "runs", salary_csv=salary, entries_csv=entries,
                projections_override=proj, candidates_override=cands,
                portfolio_controls_override=self.LOOSE, approve=True,
            )
            self.assertTrue(built["passed"], built.get("errors"))
            self.assertTrue(built["approved"])
            self.assertTrue(built["selection_certified"])
            self.assertTrue(built["allocation_certified"])
            self.assertTrue(Path(built["output_path"]).exists())
            self.assertEqual(built["candidate_bank"]["source"], "candidates_override")

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
        self.assertEqual(feas["viable_sp_pairs"], 6)
        self.assertEqual(feas["floor_sp_pair_repetition"], 3)  # ceil(16 / 6)
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
            self.assertAlmostEqual(controls["max_primary_stack_exposure_pct"], 0.6)  # ceil(6/2)=3 <= cap
            applied = plan["checkpoint_plan"]["feasibility"]["controls_feasibility"]["floors_applied"]
            self.assertIn("max_pitcher_exposure_pct", applied)
            self.assertIn("max_player_exposure_pct", applied)
            self.assertNotIn("max_primary_stack_exposure_pct", applied)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
