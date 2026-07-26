"""Solver-independent behaviour tests for the Stage 1 upload-integrity gates.

Every test here builds its CSVs by hand and asserts a behaviour, not a parse.
That is the point: ~26 of 189 tests invoked an engine entry point, so blocking
scipy left the suite green while no lineup could be built. None of these import
scipy, and all of them fail if the corresponding gate is removed.

Covered: DK Status filtering (F1), entries-file geometry detection and the
embedded-pool cross-check (F2), contest-archetype resolution and the unresolved
blocker (F3a), the preflight tool's hard checks (G1), and the upload manifest
(F7).
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from mlb_engine.entries.dk_entries_manager import (  # noqa: E402
    assert_contest_geometry, detect_entries_geometry, detect_salary_contract,
    infer_contest_archetype, load_archetypes, parse_dk_entry_rows,
)
from mlb_engine.intake.slate_intake_manager import (  # noqa: E402
    parse_dk_salary_csv, salary_status_tier,
)
from mlb_engine.pipeline.execution_pipeline import (  # noqa: E402
    _resolve_contest_postures, normalize_posture, unresolved_contest_blockers,
)

SALARY_HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary",
                 "Game Info", "TeamAbbrev", "AvgPointsPerGame", "Status", "Starting"]
GAME_A = "AAA@BBB 07/25/2026 07:05PM ET"
GAME_B = "CCC@DDD 07/25/2026 07:10PM ET"
CLASSIC_HEADER = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee",
                  "P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF",
                  "", "Instructions"]
SHOWDOWN_HEADER = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee",
                   "CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL", "", "Instructions"]


def _salary_row(pid, name, team, game, pos, roster_pos, salary, status="", starting=""):
    return [pos, f"{name} ({pid})", name, str(pid), roster_pos, str(salary),
            game, team, "10.0", status, starting]


SLOT_SPEC = [("SP", "P"), ("C", "C"), ("1B", "1B"), ("2B", "2B"), ("3B", "3B"),
             ("SS", "SS"), ("OF", "OF"), ("OF", "OF"), ("OF", "OF"), ("OF", "OF")]
# Distinct alphabetic surnames. _norm_name strips digits, so Player1 and Player2
# normalise to the same person and every fixture lineup would read as a duplicate.
SURNAMES = ["Aster", "Boone", "Crane", "Dunne", "Ellis", "Frost", "Gable",
            "Hollis", "Ives", "Jarrow"]


def write_classic_salary(path: Path, il_ids=(), dtd_ids=()) -> list[str]:
    """Two full teams per game, two games. Returns the ten IDs of a legal lineup.

    The lineup stacks each rostered SP with his own team's hitters. With only two
    games and both SPs rostered, every team is either an SP's team or an SP's
    opponent, so this is the only shape that satisfies the no-hitter-versus-
    rostered-SP rule while still representing two games.
    """
    rows = [SALARY_HEADER]
    pid = 1000
    for game, teams in ((GAME_A, ("AAA", "BBB")), (GAME_B, ("CCC", "DDD"))):
        for team in teams:
            for i, (pos, roster) in enumerate(SLOT_SPEC):
                pid += 1
                status = ("IL" if str(pid) in il_ids
                          else "DTD" if str(pid) in dtd_ids else "")
                rows.append(_salary_row(
                    pid, f"{team} {SURNAMES[i]}", team, game, pos, roster, 4000,
                    status, "SP" if roster == "P" else str(i)))
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)

    players = {p.player_id: p for p in parse_dk_salary_csv(str(path))}

    def pick(team, slot, taken):
        return next(p.player_id for p in players.values()
                    if p.team == team and slot in p.positions
                    and p.player_id not in taken)

    lineup: list[str] = [pick("AAA", "P", set()), pick("CCC", "P", set())]
    # Five hitters from AAA is the cap; the remaining three come from CCC.
    for slot in ("C", "1B", "2B", "3B", "SS"):
        lineup.append(pick("AAA", slot, set(lineup)))
    for _ in range(3):
        lineup.append(pick("CCC", "OF", set(lineup)))
    return lineup


def write_entries(path: Path, header, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def classic_entry(entry_id, contest_id, lineup, name="MLB Test Contest"):
    return [entry_id, name, contest_id, "$1"] + list(lineup) + ["", "1. instructions"]


def blank_classic_entry(entry_id, contest_id, name="MLB Test Contest"):
    return [entry_id, name, contest_id, "$1"] + [""] * 10 + ["", "1. instructions"]


def run_preflight(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "preflight_upload.py"), *args],
        capture_output=True, text=True)


class StatusTierTests(unittest.TestCase):
    def test_out_statuses_are_out_and_dtd_is_a_watch(self):
        for value in ("IL", "O", "OUT", "NA", "il", " IL60 "):
            self.assertEqual(salary_status_tier(value), "out", value)
        for value in ("DTD", "GTD", "Q"):
            self.assertEqual(salary_status_tier(value), "watch", value)
        for value in ("", None, "SP", "3"):
            self.assertEqual(salary_status_tier(value), "clean", repr(value))

    def test_salary_parser_promotes_status_and_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            write_classic_salary(salary, il_ids=("1002",))
            players = {p.player_id: p for p in parse_dk_salary_csv(str(salary))}
            self.assertEqual(players["1002"].status, "IL")
            self.assertTrue(any(p.starting == "SP" for p in players.values()))


class PoolStatusFilterTests(unittest.TestCase):
    """F1: an IL bat is a dead roster slot; the pool must not carry one."""

    def _pool(self, salary: Path, feed: dict):
        from mlb_engine.intake.live_data_adapters import build_slate_pool
        return build_slate_pool(str(salary), feed)

    def _tbd_feed(self):
        return {"date": "2026-07-25", "games": [
            {"game_pk": 1, "game_date_utc": "2026-07-25T23:05:00Z", "status": "Scheduled",
             "away": {"team_abbrev": t1, "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": f"{t1} Player0", "id": "1", "hand": "R"}},
             "home": {"team_abbrev": t2, "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": f"{t2} Player0", "id": "2", "hand": "R"}}}
            for t1, t2 in (("AAA", "BBB"),)] + [
            {"game_pk": 2, "game_date_utc": "2026-07-25T23:10:00Z", "status": "Scheduled",
             "away": {"team_abbrev": "CCC", "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": "CCC Player0", "id": "3", "hand": "R"}},
             "home": {"team_abbrev": "DDD", "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": "DDD Player0", "id": "4", "hand": "R"}}}]}

    def test_il_player_is_excluded_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            write_classic_salary(salary, il_ids=("1003",))
            pool = self._pool(salary, self._tbd_feed())
            ids = {r["Player_ID"] for r in pool["projection_rows"]}
            self.assertNotIn("1003", ids)
            report = pool["pool_report"]
            self.assertTrue(any(r["player_id"] == "1003"
                                for r in report["status_dropped"]))
            self.assertTrue(any("1003" in w and "IL" in w for w in report["warnings"]),
                            report["warnings"])

    def test_dtd_player_stays_eligible_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            write_classic_salary(salary, dtd_ids=("1003",))
            pool = self._pool(salary, self._tbd_feed())
            self.assertIn("1003", {r["Player_ID"] for r in pool["projection_rows"]})
            self.assertTrue(any("DTD" in w for w in pool["pool_report"]["warnings"]))

    def test_projection_rows_carry_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            write_classic_salary(salary)
            pool = self._pool(salary, self._tbd_feed())
            self.assertTrue(all("DK_Status" in r for r in pool["projection_rows"]))


class EntriesGeometryTests(unittest.TestCase):
    """F2: columns 0-3 are identical in both contracts, so read the slot labels."""

    def test_detects_both_contracts(self):
        self.assertEqual(detect_entries_geometry(CLASSIC_HEADER)[0], "CLASSIC")
        self.assertEqual(detect_entries_geometry(SHOWDOWN_HEADER)[0], "SHOWDOWN")

    def test_unknown_geometry_raises_naming_expected_and_found(self):
        bad = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", "QB", "RB"]
        with self.assertRaises(ValueError) as ctx:
            detect_entries_geometry(bad)
        self.assertIn("QB", str(ctx.exception))
        self.assertIn("CPT", str(ctx.exception))

    def test_showdown_blank_rows_read_blank_at_the_right_width(self):
        """The defect: 17 of 18 blank Showdown rows read as filled at Classic width."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e.csv"
            rows = [["900", "MLB SD", "5", "$1", "", "", "", "", "", "",
                     "", "1. Column A lists all of your contest entries"]
                    for _ in range(3)]
            write_entries(path, SHOWDOWN_HEADER, rows)
            parsed = parse_dk_entry_rows(path)
            self.assertEqual(len(parsed), 3)
            for row in parsed:
                self.assertEqual(row.roster_cells, ("",) * 6)

    def test_contest_geometry_mismatch_between_the_two_files_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary, entries = Path(tmp) / "s.csv", Path(tmp) / "e.csv"
            lineup = write_classic_salary(salary)
            self.assertEqual(detect_salary_contract(salary), "CLASSIC")
            write_entries(entries, SHOWDOWN_HEADER,
                          [["900", "MLB SD", "5", "$1"] + [""] * 6 + ["", "x"]])
            with self.assertRaises(ValueError) as ctx:
                assert_contest_geometry(salary, entries)
            self.assertIn("mismatch", str(ctx.exception))
            write_entries(entries, CLASSIC_HEADER,
                          [classic_entry("900", "5", lineup)])
            self.assertEqual(assert_contest_geometry(salary, entries), "CLASSIC")
            with self.assertRaises(ValueError):
                assert_contest_geometry(salary, entries, declared="SHOWDOWN")


class ContestIdentityTests(unittest.TestCase):
    """F3a: the curated archetypes file was dead and length ties misrouted names."""

    def setUp(self):
        self.archetypes = load_archetypes()

    def _posture(self, name):
        meta = infer_contest_archetype(name, None, self.archetypes)
        return normalize_posture(meta["inferred_type"],
                                 meta["payout_shape_default"],
                                 meta["inferred_max_entries"])

    def test_curated_file_resolves_by_default(self):
        self.assertGreater(len(self.archetypes), 6)

    def test_named_misroutings_now_resolve_correctly(self):
        self.assertEqual(self._posture("MLB $5 Double Up"), "cash")
        self.assertEqual(
            self._posture("MLB Showdown Satellite to $2 MLB Pocket Cup MEGA "
                          "Qualifier (LAD @ NYM)"), "wta_satellite")
        self.assertEqual(
            self._posture("MLB Single Entry Satellite to $15 Relay Throw"),
            "wta_satellite")
        self.assertEqual(self._posture("MLB $0.25 Knuckleball [150-Max]"), "mme")

    def test_unresolved_contest_blocks_and_operator_override_clears_it(self):
        class Row:
            def __init__(self, cid, name):
                self.contest_id, self.contest_name, self.entry_fee = cid, name, 1.0

        rows = [Row("1", "MLB $5 Double Up"), Row("2", "MLB $3 Wednesday Special")]
        resolved = _resolve_contest_postures(rows, None, None)
        self.assertEqual(resolved["1"]["posture_source"], "name_inference")
        self.assertEqual(resolved["2"]["posture_source"], "unresolved")
        blockers = unresolved_contest_blockers(resolved)
        self.assertEqual(len(blockers), 1)
        self.assertIn("Wednesday Special", blockers[0])
        overridden = _resolve_contest_postures(rows, {"2": "large_gpp"}, None)
        self.assertEqual(overridden["2"]["posture_source"], "operator_supplied")
        self.assertEqual(unresolved_contest_blockers(overridden), [])


class PreflightToolTests(unittest.TestCase):
    """G1: the net. Every check is a fact about the file, decidable from disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.lineup = write_classic_salary(self.salary)
        self.entries = self.dir / "DKEntries.csv"
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup),
                       classic_entry("901", "5", self.lineup[:9] + [self.lineup[9]])])

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        return run_preflight("--entries", str(self.entries),
                             "--salary", str(self.salary), *extra)

    def test_clean_file_passes(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_blank_reserved_row_fails(self):
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup),
                       blank_classic_entry("901", "5")])
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("blank reserved row", result.stdout)

    def test_partially_filled_row_fails(self):
        partial = list(self.lineup)
        partial[4] = ""
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", partial)])
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("partially filled", result.stdout)

    def test_duplicate_entry_id_fails(self):
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup),
                       classic_entry("900", "5", self.lineup)])
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate Entry ID", result.stdout)

    def test_shelved_player_fails(self):
        write_classic_salary(self.salary, il_ids=(self.lineup[5],))
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("shelved player", result.stdout)

    def test_over_cap_fails(self):
        with self.salary.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        for row in rows[1:]:
            row[5] = "9000"
        with self.salary.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        result = self._run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("over the 50000 cap", result.stdout)

    def test_declared_contest_type_mismatch_fails(self):
        result = self._run("--expect-contest-type", "showdown")
        self.assertEqual(result.returncode, 2)
        self.assertIn("header geometry is classic", result.stdout)

    def test_truncation_is_caught_against_an_expected_count(self):
        self.assertEqual(self._run("--expect-entries", "2").returncode, 0)
        result = self._run("--expect-entries", "5")
        self.assertEqual(result.returncode, 2)
        self.assertIn("truncated write", result.stdout)

    def test_force_never_blocks_shipping(self):
        write_entries(self.entries, CLASSIC_HEADER,
                      [blank_classic_entry("900", "5")])
        self.assertEqual(self._run().returncode, 2)
        forced = self._run("--force")
        self.assertEqual(forced.returncode, 0)
        self.assertIn("FORCED", forced.stdout)

    def test_json_output_is_parseable(self):
        payload = json.loads(self._run("--json").stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["info"]["contest_type"], "classic")


class UploadManifestTests(unittest.TestCase):
    """F7: one file that answers 'which file do I upload'."""

    def test_supersession_is_keyed_on_contest_type_and_slate_tag(self):
        from mlb_engine.entries import upload_manifest as um

        with tempfile.TemporaryDirectory() as tmp:
            original_root = um.REPO_ROOT
            um.REPO_ROOT = Path(tmp)
            try:
                out = Path(tmp) / "outputs" / "2026-07-25"
                out.mkdir(parents=True)
                first, second, other = (out / "a.csv", out / "b.csv", out / "c.csv")
                first.write_text("one", encoding="utf-8")
                second.write_text("two", encoding="utf-8")
                other.write_text("three", encoding="utf-8")

                um.record_delivery(date="2026-07-25", delivered_file=first,
                                   contest_type="classic", slate_tag="1605_4g",
                                   entries=16)
                um.record_delivery(date="2026-07-25", delivered_file=other,
                                   contest_type="showdown", slate_tag="1610_1g",
                                   entries=6)
                self.assertEqual(len(um.current_deliveries("2026-07-25")), 2)

                um.record_delivery(date="2026-07-25", delivered_file=second,
                                   contest_type="classic", slate_tag="1605_4g",
                                   entries=16)
                current = um.current_deliveries("2026-07-25")
                self.assertEqual(len(current), 2)
                names = sorted(Path(r["delivered_file"]).name for r in current)
                self.assertEqual(names, ["b.csv", "c.csv"])

                superseded = [r for r in um.read_manifest("2026-07-25")["deliveries"]
                              if r["status"] == "superseded"]
                self.assertEqual(len(superseded), 1)
                self.assertTrue(superseded[0]["superseded_by"].endswith("b.csv"))

                # paths are repo-relative, so a new session mount still resolves
                for record in um.read_manifest("2026-07-25")["deliveries"]:
                    self.assertFalse(Path(record["delivered_file"]).is_absolute())
                self.assertTrue(um.verify_manifest("2026-07-25")["passed"])

                second.write_text("tampered", encoding="utf-8")
                check = um.verify_manifest("2026-07-25")
                self.assertFalse(check["passed"])
                self.assertIn("changed after it was delivered", check["problems"][0])
            finally:
                um.REPO_ROOT = original_root


if __name__ == "__main__":
    unittest.main(verbosity=2)
