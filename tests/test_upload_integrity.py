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
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
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


class PreflightContestIdentityTests(unittest.TestCase):
    """R85: DK's contest NAME and DK's roster contract must agree.

    The gap this closes: a Showdown-geometry file whose entries belong to
    Classic contests passed every hard check, because nothing read the Contest
    Name column. Geometry came off the header, legality off the roster, and
    the manifest cross-check only fires when a manifest resolves -- which is
    exactly the case R96 records as able to go missing.

    Preflight-native by contract: no network, no engine import. The tests below
    that compare against the engine's resolver import it themselves; the tool
    does not.
    """

    def setUp(self):
        import preflight_upload
        self.pf = preflight_upload
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.lineup = write_classic_salary(self.salary)
        self.entries = self.dir / "DKEntries.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        return run_preflight("--entries", str(self.entries),
                             "--salary", str(self.salary), *extra)

    def _row(self, name, entry_id="900", contest_id="5"):
        return self.pf.EntryRow(
            1, [entry_id, name, contest_id, "$1"] + [""] * 10, 10)

    def test_classic_geometry_carrying_showdown_contest_names_fails(self):
        write_entries(self.entries, CLASSIC_HEADER, [
            classic_entry("900", "5", self.lineup,
                          name="MLB Showdown $250 Solo Shot (STL @ TOR)"),
            classic_entry("901", "5", self.lineup,
                          name="MLB Showdown $2K Solo Shot (KC @ DET)")])
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("contest identity", result.stdout)
        self.assertIn("header geometry is classic", result.stdout)
        self.assertIn("name showdown contests", result.stdout)
        self.assertIn("Solo Shot", result.stdout)

    def test_showdown_geometry_carrying_classic_contest_names_fails(self):
        """R85's filed case, in the direction that costs money: the file is
        shaped for one contest family and the entries belong to the other."""
        rows = [["900", "MLB $30 Quarter Jukebox [Just $0.25!] (Turbo)", "5",
                 "$1"] + [""] * 6 + ["", "1. instructions"]]
        write_entries(self.entries, SHOWDOWN_HEADER, rows)
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("header geometry is showdown", result.stdout)
        self.assertIn("name classic contests", result.stdout)

    def test_two_contest_families_in_one_file_fails_as_mixed_draftgroups(self):
        write_entries(self.entries, CLASSIC_HEADER, [
            classic_entry("900", "5", self.lineup, name="MLB $1K Daily Dollar"),
            classic_entry("901", "6", self.lineup,
                          name="MLB Showdown $100 Solo Shot (SD @ ARI)")])
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BOTH contest families in one file", result.stdout)

    def test_agreeing_names_and_geometry_pass(self):
        write_entries(self.entries, CLASSIC_HEADER, [
            classic_entry("900", "5", self.lineup,
                          name="MLB $30 Quarter Jukebox [Just $0.25!] (Turbo)")])
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_real_showdown_fixture_is_not_flagged(self):
        """The archived MIN@CHC pair: showdown header, showdown names, clean."""
        rep = self.pf.Report()
        fixture = REPO / "tests" / "fixtures" / "showdown" / "DKEntries_showdown_MIN_CHC.csv"
        contest, _, entries, _, _ = self.pf.load_entries(fixture)
        self.assertEqual(contest, "showdown")
        self.pf.check_contest_identity(contest, entries, rep)
        self.assertEqual(rep.failures, [])
        self.assertEqual(rep.info["contest_identity"]["implied_by_name"],
                         ["showdown"])

    def test_an_unrecognized_contest_name_warns_and_never_fails(self):
        """DK names change faster than the pinned table. An archetype we cannot
        resolve is missing evidence, not a wrong file, and blocking on it would
        stop a legal upload at T-5."""
        rep = self.pf.Report()
        entries = [self._row("MLB $3 Wednesday Special")]
        self.pf.check_contest_identity("classic", entries, rep)
        self.assertEqual(rep.failures, [])
        self.assertTrue(any("match no row" in w for w in rep.warnings))
        self.assertEqual(rep.info["contest_identity"]["unmatched_contest_names"],
                         ["MLB $3 Wednesday Special"])

    def test_empty_entries_do_not_pass_this_check_vacuously(self):
        """R51's class. Row accounting owns the empty-file failure; this check
        must simply not manufacture a verdict from nothing."""
        rep = self.pf.Report()
        self.pf.check_contest_identity("classic", [], rep)
        self.assertEqual(rep.failures, [])
        self.assertNotIn("contest_identity", rep.info)

    def test_preflight_and_the_engine_resolve_archetypes_identically(self):
        """R79(d)'s duplication class, guarded instead of hoped for.

        preflight cannot import the engine, so the precedence table is a second
        copy. Two implementations of one rule is this project's named no-op
        failure, so the copies are pinned equal here and cross-checked on real
        archived contest names.
        """
        from mlb_engine.entries import dk_entries_manager as dem
        self.assertEqual(self.pf.ARCHETYPE_TYPE_PRECEDENCE,
                         dem.ARCHETYPE_TYPE_PRECEDENCE,
                         "the copied precedence table has drifted from the engine's")
        rows = self.pf.load_archetypes()
        engine_rows = dem.load_archetypes(str(self.pf.ARCHETYPES_CSV))
        self.assertGreater(len(rows), 6)
        for name in ("MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (MIN @ CHC)",
                     "MLB Single Entry Satellite to $15 Relay Throw",
                     "MLB $0.25 Knuckleball [150-Max]",
                     "MLB $5 Double Up",
                     "MLB $30 Quarter Jukebox [Just $0.25!] (Turbo)",
                     "MLB $3 Wednesday Special"):
            mine = self.pf.match_archetype(name, rows)
            theirs = dem.infer_contest_archetype(name, None, engine_rows)
            self.assertEqual(
                (mine or {}).get("pattern"), theirs["matched_pattern"],
                f"preflight and the engine disagree about {name!r}")

    def test_longest_pattern_alone_would_misroute_a_satellite(self):
        """The mutation that motivates the precedence table: without it,
        'Satellite to $2 MLB Pocket Cup MEGA Qualifier' resolves on 'Pocket
        Cup' and a ticket_line contest reads as a generic GPP."""
        rows = self.pf.load_archetypes()
        name = "MLB Satellite to $2 MLB Pocket Cup MEGA Qualifier"
        by_length = max(
            [r for r in rows if str(r["pattern"]).casefold() in name.casefold()],
            key=lambda r: len(r["pattern"]))
        self.assertEqual(by_length["pattern"], "Pocket Cup")
        self.assertEqual(self.pf.match_archetype(name, rows)["pattern"],
                         "Satellite")

    def test_a_missing_archetypes_file_degrades_to_the_geometry_check(self):
        """The archetype join is evidence; the geometry contradiction is the
        gate. Losing the CSV must not lose the gate."""
        rep = self.pf.Report()
        self.assertEqual(self.pf.load_archetypes(self.dir / "nope.csv"), [])
        entries = [self._row("MLB Showdown $100 Solo Shot (SD @ ARI)")]
        self.pf.check_contest_identity("classic", entries, rep, archetypes=[])
        self.assertTrue(any("contest identity" in f for f in rep.failures))


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

    def test_float_formatted_entry_ids_fail_instead_of_passing_as_zero_entries(self):
        """R51: an Excel or pandas round-trip reformats the Entry ID column to
        '4.71059E+09'. Every ID then failed .isdigit(), the file parsed to zero
        entries, all four other hard checks iterated an empty list, and the tool
        printed 'PASS 0 classic entries, all hard checks clean' with verdict
        upload_ready. That is the false-PASS class at the money boundary."""
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("4.71059E+09", "5", self.lineup),
                       classic_entry("4710591235.0", "5", self.lineup)])
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("no parseable entries", result.stdout)
        # Root cause: the two row-accounting counters were incremented in the
        # same branch, so hard check 5 was unreachable. They must disagree here.
        self.assertIn("2 Entry ID rows on disk, 0 parsed", result.stdout)
        payload = json.loads(self._run("--json").stdout)
        self.assertEqual(payload["verdict"], "blocked")
        self.assertFalse(payload["passed"])

    def test_a_header_only_file_fails(self):
        """R51: 'nothing to upload' is not 'nothing wrong'. This passed too."""
        write_entries(self.entries, CLASSIC_HEADER, [])
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("no parseable entries", result.stdout)
        self.assertIn("header and no entry rows", result.stdout)

    def test_the_embedded_player_pool_never_counts_as_entry_rows(self):
        """The regression risk in R51's counter. DK writes a full player pool to
        the RIGHT of the roster window in the same file -- 195 rows against 14
        entries in this fixture. A counter that read those rows would fail row
        accounting on every real export, so the fix counts only the Entry ID cell
        and the roster window."""
        import preflight_upload
        fixture = REPO / "tests" / "fixtures" / "showdown" / "DKEntries_showdown_MIN_CHC.csv"
        _, _, entries, raw_rows, entry_id_rows = preflight_upload.load_entries(fixture)
        self.assertGreater(len(raw_rows), len(entries) * 5)
        self.assertTrue(preflight_upload.parse_embedded_pool(raw_rows))
        self.assertEqual(entry_id_rows, len(entries))

    def test_force_never_blocks_shipping_but_never_reports_clean(self):
        """R2: --force used to exit 0, which is the one signal automation
        trusts. A wrapper could not tell "upload-ready" from "the clock beat the
        fix." It exits 4 now: the operator is still unblocked, the caller is
        told the truth, and the overridden failures are still printed."""
        write_entries(self.entries, CLASSIC_HEADER,
                      [blank_classic_entry("900", "5")])
        self.assertEqual(self._run().returncode, 2)
        forced = self._run("--force")
        self.assertEqual(forced.returncode, 4)
        self.assertIn("ACKNOWLEDGED", forced.stdout)
        self.assertIn("blank reserved row", forced.stdout)
        payload = json.loads(self._run("--force", "--json").stdout)
        self.assertEqual(payload["verdict"], "acknowledged")
        self.assertTrue(payload["failures"])

    def test_a_clean_run_never_returns_a_nonzero_code_and_zero_means_clean(self):
        """The other half of R2's done-when: no code path with a non-empty
        failure list returns 0."""
        clean = self._run("--json")
        self.assertEqual(clean.returncode, 0)
        self.assertEqual(json.loads(clean.stdout)["failures"], [])
        self.assertEqual(json.loads(clean.stdout)["verdict"], "upload_ready")

    def test_json_output_is_parseable(self):
        payload = json.loads(self._run("--json").stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["info"]["contest_type"], "classic")


class PreflightManifestBindingTests(unittest.TestCase):
    """R3: the manifest binding stops failing open at the check.

    Teeth: mirror_to_outputs and _record_upload_manifest swallow every exception
    by design, so a certified file could land in outputs/ with no manifest row
    and nothing said so. Preflight only cross-checked a manifest when one
    happened to be there.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.lineup = write_classic_salary(self.salary)
        # A DELIVERED file lives under the repo's outputs/, and is_delivered_file
        # resolves against REPO/outputs specifically, so the fixture cannot move
        # to a tmpdir without testing a different code path than production.
        #
        # The directory name is unique per test rather than a fixed "_test_r3".
        # Isolation used to rest on tearDown deleting the directory, and a mount
        # without the delete grant (the Cowork sandbox is one) refuses the
        # unlink: the leftover upload_manifest.json then satisfied the very
        # check test_a_delivered_file_with_no_manifest_is_a_hard_failure exists
        # to prove fails, so the suite went green-then-red across runs for an
        # environment reason with no engine cause. A unique name makes each test
        # hermetic whether or not the delete lands.
        self.outputs = REPO / "outputs" / f"_test_r3_{uuid.uuid4().hex[:12]}"
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.entries = self.outputs / "DKEntries.csv"
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup)])

    def tearDown(self):
        # Fail open on a refused delete, the same call R23's archive move makes:
        # housekeeping that cannot run is not a test result. outputs/ is
        # gitignored, so an undeletable leftover is litter, never tracked state.
        for path in sorted(self.outputs.glob("*")):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            self.outputs.rmdir()
        except OSError:
            pass
        self.tmp.cleanup()

    def _run(self, *extra):
        return run_preflight("--entries", str(self.entries),
                             "--salary", str(self.salary), *extra)

    def _write_manifest(self, **overrides):
        import hashlib
        digest = hashlib.sha256(self.entries.read_bytes()).hexdigest()
        record = {"delivered_file": f"outputs/_test_r3/{self.entries.name}",
                  "sha256": digest, "contest_type": "classic", "slate_tag": "t",
                  "contest_ids": ["5"], "entries": 1, "status": "candidate",
                  "certification": "certified", "projection_tier": "proxy",
                  "strategy_state": {"state": "clean", "counts": {}}}
        record.update(overrides)
        (self.outputs / "upload_manifest.json").write_text(
            json.dumps({"version": "1.1", "date": "2026-06-03",
                        "deliveries": [record]}), encoding="utf-8")
        return record

    def test_a_delivered_file_with_no_manifest_is_a_hard_failure(self):
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no upload manifest for this delivered file", result.stdout)

    def test_the_waiver_is_explicit_and_says_so(self):
        result = self._run("--no-manifest")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("waived by --no-manifest", result.stdout)

    def test_a_manifest_whose_sha_does_not_match_is_a_hard_failure(self):
        self._write_manifest(sha256="0" * 64)
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("changed after it was recorded", result.stdout)

    def test_an_ad_hoc_file_outside_outputs_still_only_warns(self):
        """The tool covers hand-built exports on purpose; those have no record
        to be missing. Only a file in the delivery location is held to one."""
        loose = self.dir / "DKEntries.csv"
        write_entries(loose, CLASSIC_HEADER, [classic_entry("900", "5", self.lineup)])
        result = run_preflight("--entries", str(loose), "--salary", str(self.salary))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_preflight_stamps_its_verdict_onto_the_matching_record(self):
        self._write_manifest()
        self.assertEqual(self._run().returncode, 0)
        after = json.loads((self.outputs / "upload_manifest.json").read_text())
        record = after["deliveries"][0]
        self.assertEqual(record["status"], "upload_ready")
        self.assertEqual(record["preflight"]["verdict"], "upload_ready")
        self.assertEqual(record["preflight"]["failures"], [])

    def test_a_forced_run_records_acknowledged_with_the_failures(self):
        write_entries(self.entries, CLASSIC_HEADER, [blank_classic_entry("900", "5")])
        self._write_manifest()
        self.assertEqual(self._run("--force").returncode, 4)
        record = json.loads(
            (self.outputs / "upload_manifest.json").read_text())["deliveries"][0]
        self.assertEqual(record["status"], "acknowledged")
        self.assertTrue(record["preflight"]["failures"])

    def test_the_record_carries_projection_tier_and_strategy_state(self):
        from mlb_engine.entries import upload_manifest as um
        with tempfile.TemporaryDirectory() as tmp:
            original = um.REPO_ROOT
            um.REPO_ROOT = Path(tmp)
            try:
                delivered = Path(tmp) / "DKEntries.csv"
                delivered.write_text("x", encoding="utf-8")
                record = um.record_delivery(
                    date="2026-06-03", delivered_file=delivered,
                    contest_type="classic", slate_tag="1605_4g",
                    projection_tier="enriched",
                    strategy_state={"state": "relaxed", "counts": {"overlap": 2}})
                self.assertEqual(record["status"], "candidate")
                self.assertEqual(record["projection_tier"], "enriched")
                self.assertEqual(record["strategy_state"]["state"], "relaxed")
                self.assertIn("candidate", um.STATUS_VALUES)
                self.assertIn("acknowledged", um.STATUS_VALUES)
            finally:
                um.REPO_ROOT = original

    def test_the_tiers_are_derived_from_evidence_not_asserted(self):
        from mlb_engine.pipeline import execution_pipeline as epi
        proxy = {"projection_enrichment": {"f1": {"requested": 0, "applied_count": 0}}}
        enriched = {"projection_enrichment": {"f1": {"requested": 9, "applied_count": 9}}}
        self.assertEqual(epi.manifest_projection_tier(proxy), "proxy")
        self.assertEqual(epi.manifest_projection_tier(enriched), "enriched")
        self.assertEqual(epi.manifest_projection_tier({}), "proxy")
        clean = epi.manifest_strategy_state({"bank_diagnostics": {"relaxations": {}}})
        relaxed = epi.manifest_strategy_state(
            {"bank_diagnostics": {"relaxations": {"overlap_steps": 2, "note": "x"}}})
        self.assertEqual(clean["state"], "clean")
        self.assertEqual(relaxed["state"], "relaxed")
        self.assertEqual(relaxed["counts"], {"overlap_steps": 2})

    def test_a_record_with_no_relaxation_evidence_is_unknown_not_clean(self):
        """R64(a): the sliced path is the PRODUCTION path and it records no
        `relaxations` key at all -- run_slate strips bank_diag to candidate_count
        under candidates_override, and build_slate's own bank_diagnostics never
        carried one. So the delivery record read "clean" structurally, whatever
        happened upstream, and CLAUDE.md's "clean when the relaxation counts are
        zero" is read at T-5 off exactly this field."""
        from mlb_engine.pipeline import execution_pipeline as epi

        sliced = epi.manifest_strategy_state(
            {"bank_diagnostics": {"candidate_count": 1007}})
        self.assertEqual(sliced["state"], "unknown")
        self.assertEqual(sliced["evidence"], "absent")
        self.assertEqual(epi.manifest_strategy_state({})["state"], "unknown")
        # An empty relaxations block IS evidence: it says nothing was relaxed.
        self.assertEqual(
            epi.manifest_strategy_state(
                {"bank_diagnostics": {"relaxations": {}}})["evidence"], "recorded")

    def test_strategy_state_reads_every_place_relaxations_are_recorded(self):
        """R64(a): one key was read; three hold the evidence. `candidate_bank`
        keeps the unstripped diagnostics, Showdown counts its two relaxations at
        the top level rather than under `relaxations` (R54), and bank_warnings is
        where the sliced path's failed cache jobs land."""
        from mlb_engine.pipeline import execution_pipeline as epi

        via_candidate_bank = epi.manifest_strategy_state(
            {"bank_diagnostics": {"candidate_count": 12},
             "candidate_bank": {"relaxations": {"overlap_steps": 3}}})
        self.assertEqual(via_candidate_bank["state"], "relaxed")
        self.assertEqual(via_candidate_bank["counts"], {"overlap_steps": 3})

        showdown = epi.manifest_strategy_state(
            {"bank_diagnostics": {"relaxed_slots": 2, "overlap_relaxed_slots": 1}})
        self.assertEqual(showdown["state"], "relaxed")
        self.assertEqual(showdown["counts"],
                         {"relaxed_slots": 2, "overlap_relaxed_slots": 1})

        # A relaxation WARNING with no counts is still a relaxed portfolio.
        warned = epi.manifest_strategy_state(
            {"bank_diagnostics": {"relaxations": {"warnings": ["overlap relaxed"]}}})
        self.assertEqual(warned["state"], "relaxed")

        # bank_warnings travels as evidence but does not drive the verdict:
        # reduced search effort is not a relaxed control, and conflating them
        # would trade one false label for another.
        sliced = epi.manifest_strategy_state(
            {"bank_diagnostics": {"relaxations": {}},
             "bank_warnings": ["slice was not a full search"]})
        self.assertEqual(sliced["state"], "clean")
        self.assertEqual(sliced["bank_warnings"], ["slice was not a full search"])

    def test_savant_enriched_blocks_read_as_enriched(self):
        """R64(b): `_applied` required a `requested` key that only f1/f4/f5 carry.
        The Savant-fed blocks report considered/matched or an `applied` flag, so
        every one of them returned None and a fully enriched build recorded
        projection_tier='proxy'. Reproduced in the audit."""
        from mlb_engine.pipeline import execution_pipeline as epi

        xwoba = {"projection_enrichment": {"xwoba": {
            "applied": True, "considered": 180, "matched": 151, "match_rate": 0.84}}}
        self.assertEqual(epi.manifest_projection_tier(xwoba), "enriched")
        ceiling = {"projection_enrichment": {"ceiling": {
            "matched": 120, "unmatched": 60, "match_rate": 0.67}}}
        self.assertEqual(epi.manifest_projection_tier(ceiling), "enriched")
        guard = {"projection_enrichment": {"value_guard": {
            "applied": True, "clipped_count": 3}}}
        self.assertEqual(epi.manifest_projection_tier(guard), "enriched")
        # A block that ran and reached nothing is not enrichment, and an
        # opted-out guard is not a failure either -- both stay proxy.
        self.assertEqual(epi.manifest_projection_tier(
            {"projection_enrichment": {"ceiling": {"matched": 0, "unmatched": 180}}}),
            "proxy")
        self.assertEqual(epi.manifest_projection_tier(
            {"projection_enrichment": {"value_guard": {"applied": False}}}), "proxy")
        self.assertIsNone(epi._applied({"matched": 0, "unmatched": 0}))


class LineupGateEvidenceTests(unittest.TestCase):
    """R53: the workflow lineup gate passed vacuously with fabricated evidence.

    `_derive_workflow_gates`' pool-report-absent branch read `elif
    projected_order:` -- and `projected_order` is the four-key SUMMARY dict
    run_slate always builds, truthy even at `requested: 0, applied_count: 0`. So
    every call without a pool_report certified lineup_gate_passed=True and wrote
    "4 players carry a batting order" -- the len of a dict's KEYS -- into the
    immutable diagnostics, while the designed None-blocks branch was unreachable.

    This is the F4 class reopened: on 2026-07-22 a 23-team build with 0/9 lineups
    posted read certified. build_slate.py supplies a pool_report so the primary
    path was covered, which is exactly why the fabricated-evidence leg would have
    stayed invisible until someone built through the API.
    """

    def _gates(self, projections=None, pool_report=None, order_by_team=None):
        from mlb_engine.pipeline import execution_pipeline as epi
        summary = {"requested": 0, "applied_count": 0, "applied_player_ids": [],
                   "note": "no projected order supplied"}
        if order_by_team is None:
            order_by_team = epi.batting_orders_by_team(projections)
        return epi._derive_workflow_gates(
            schema={"passed": True, "summary": "ok"},
            entry_requirements=[{"entry_id": "1", "contest_id": "5"}],
            posture_by_contest={"5": {"posture": "large_gpp"}},
            projected_order=summary,
            pitcher_roles=None,
            projection_enrichment={},
            pool_report=pool_report,
            order_by_team=order_by_team,
        )

    def test_an_empty_order_build_blocks_instead_of_certifying(self):
        import pandas as pd

        frame = pd.DataFrame([
            {"Player_ID": "1", "Team": "AAA", "Batting_Order": None},
            {"Player_ID": "2", "Team": "BBB", "Batting_Order": ""},
        ])
        gates, why = self._gates(projections=frame)
        self.assertIsNone(gates["lineup_gate_passed"],
                          "no orders and no pool report must block, not pass")
        self.assertIn("nothing states that the lineups", why["lineup_gate_passed"])
        # The old fabrication must not reappear in any form.
        self.assertNotIn("4 players carry a batting order", why["lineup_gate_passed"])

    def test_a_frame_with_no_batting_order_column_at_all_blocks(self):
        import pandas as pd

        gates, _ = self._gates(projections=pd.DataFrame(
            [{"Player_ID": "1", "Team": "AAA"}]))
        self.assertIsNone(gates["lineup_gate_passed"])
        self.assertIsNone(self._gates(projections=None)[0]["lineup_gate_passed"])

    def test_the_evidence_states_real_per_team_counts(self):
        import pandas as pd

        rows = ([{"Player_ID": f"a{i}", "Team": "AAA", "Batting_Order": i + 1}
                 for i in range(9)]
                + [{"Player_ID": f"b{i}", "Team": "BBB", "Batting_Order": i + 1}
                   for i in range(9)]
                + [{"Player_ID": "p1", "Team": "AAA", "Batting_Order": None}])
        gates, why = self._gates(projections=pd.DataFrame(rows))
        self.assertTrue(gates["lineup_gate_passed"])
        self.assertIn("AAA 9", why["lineup_gate_passed"])
        self.assertIn("BBB 9", why["lineup_gate_passed"])

    def test_a_team_under_nine_orders_fails_the_gate(self):
        import pandas as pd

        rows = ([{"Player_ID": f"a{i}", "Team": "AAA", "Batting_Order": i + 1}
                 for i in range(9)]
                + [{"Player_ID": f"b{i}", "Team": "BBB", "Batting_Order": i + 1}
                   for i in range(4)])
        gates, why = self._gates(projections=pd.DataFrame(rows))
        self.assertFalse(gates["lineup_gate_passed"])
        self.assertIn("Under nine: BBB", why["lineup_gate_passed"])

    def test_a_supplied_pool_report_still_wins(self):
        gates, why = self._gates(
            pool_report={"blockers": [], "teams": {"AAA": {"hitters": 9}}},
            order_by_team={"AAA": 3})
        self.assertTrue(gates["lineup_gate_passed"])
        self.assertIn("pool report", why["lineup_gate_passed"])

    def test_the_counter_ignores_pitchers_and_non_numeric_cells(self):
        import pandas as pd
        from mlb_engine.pipeline import execution_pipeline as epi

        frame = pd.DataFrame([
            {"Player_ID": "1", "Team": "aaa", "Batting_Order": 1},
            {"Player_ID": "2", "Team": "AAA", "Batting_Order": "2"},
            {"Player_ID": "3", "Team": "AAA", "Batting_Order": 0},
            {"Player_ID": "4", "Team": "AAA", "Batting_Order": "TBD"},
            {"Player_ID": "5", "Team": "AAA", "Batting_Order": float("nan")},
        ])
        self.assertEqual(epi.batting_orders_by_team(frame), {"AAA": 2})


class PreflightFeedDefaultTests(unittest.TestCase):
    """R4: the strongest check stops being opt-in twice.

    Teeth: the posted-lineup cross-check ran only with --feed, and an absence
    was a warning unless --feed-strict was ALSO passed. A 3:55pm bench with a
    blank salary-file Status walked through the default check.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.lineup = write_classic_salary(self.salary)
        self.entries = self.dir / "DKEntries.csv"
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup)])
        self.names = {p.player_id: p.name
                      for p in parse_dk_salary_csv(str(self.salary))}

    def tearDown(self):
        self.tmp.cleanup()

    def _feed(self, benched=(), status="confirmed", fetched_at=None):
        from datetime import datetime, timezone
        by_team = {}
        for pid, name in self.names.items():
            team = next(p.team for p in parse_dk_salary_csv(str(self.salary))
                        if p.player_id == pid)
            if pid in benched:
                continue
            by_team.setdefault(team, []).append({"name": name})
        stamp = fetched_at or datetime.now(timezone.utc).isoformat()
        games = [{"game_pk": 1, "status": "Scheduled",
                  "away": {"team_abbrev": "AAA", "lineup_status": status,
                           "lineup": by_team.get("AAA", []), "probable_pitcher": {}},
                  "home": {"team_abbrev": "CCC", "lineup_status": status,
                           "lineup": by_team.get("CCC", []), "probable_pitcher": {}}}]
        path = self.dir / "lineups_feed.json"
        path.write_text(json.dumps({"date": "2026-06-03", "fetched_at": stamp,
                                    "games": games}), encoding="utf-8")
        return path

    def _run(self, *extra):
        return run_preflight("--entries", str(self.entries),
                             "--salary", str(self.salary), *extra)

    def test_a_confirmed_team_bench_is_a_hard_failure_by_default(self):
        feed = self._feed(benched=(self.lineup[3],))
        result = self._run("--feed", str(feed))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_the_lenient_flag_restores_the_old_warning(self):
        feed = self._feed(benched=(self.lineup[3],))
        result = self._run("--feed", str(feed), "--feed-lenient")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("WARN", result.stdout)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_a_team_that_has_not_posted_stays_soft(self):
        feed = self._feed(benched=(self.lineup[3],), status="unconfirmed")
        result = self._run("--feed", str(feed))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_feed_age_is_printed_so_a_stale_all_clear_is_visibly_stale(self):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        feed = self._feed(fetched_at=old)
        result = self._run("--feed", str(feed))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("feed: lineups_feed.json (5.0h old)", result.stdout)
        self.assertIn("old (fetched", result.stdout)

    def _salary_on_date(self, date_mmddyyyy: str) -> Path:
        """Same fixture, re-dated, so a slate with no feed on disk is reachable."""
        path = self.dir / f"DKSalaries_{date_mmddyyyy.replace('/', '')}.csv"
        with self.salary.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        for row in rows[1:]:
            row[6] = row[6].replace("07/25/2026", date_mmddyyyy)
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        return path

    def test_a_missing_feed_degrades_to_one_warning_and_never_blocks(self):
        salary = self._salary_on_date("01/02/2099")
        result = run_preflight("--entries", str(self.entries), "--salary", str(salary))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("no lineups feed resolved", result.stdout)

    def _repo_skeleton_with_feed(self, slate_date: str = "2026-07-25") -> Path:
        """A throwaway repo root holding only what the resolver reads.

        `resolve_feed_for_slate` globs `REPO_ROOT/data/slates/<date>/` and
        REPO_ROOT is derived from the TOOL's own `__file__`, so the only way to
        exercise the CLI auto-resolve against a feed we control is to run a COPY
        of the tool from a root we built. The tool imports no engine and no
        third-party module, so a copy runs standalone.

        This replaced reading the real `data/slates/2026-07-25/lineups_feed.json`
        off Ben's disk. `data/slates/*/` is gitignored runtime data, so that file
        is in no checkout: the test passed on the machine that built the slate
        and FAILED RED in every fresh clone, where the session-start gate then
        printed `test suite FAILED in tests.test_upload_integrity` and told the
        session not to build. Measured 2026-08-19 on a clone from GitHub -- it
        was the ONLY hard failure in the 1217. The nearby guard
        (`test_core.TestDataDependenciesAreVendoredOrGuardedTests`) could not
        see it because the untracked path is named in the tool, not in the test.
        """
        root = self.dir / "repo"
        (root / "tools").mkdir(parents=True, exist_ok=True)
        (root / "data" / "reference").mkdir(parents=True, exist_ok=True)
        slates = root / "data" / "slates" / slate_date
        slates.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "tools" / "preflight_upload.py", root / "tools")
        shutil.copy2(REPO / "data" / "reference" / "dk_contest_archetypes.csv",
                     root / "data" / "reference")
        shutil.copy2(self._feed(), slates / "lineups_feed.json")
        return root

    def test_the_feed_is_auto_resolved_from_the_slate_date(self):
        """No --feed passed. The fixture's Game Info dates the slate 2026-07-25,
        and a feed sits under data/slates/2026-07-25/ of the root the tool runs
        from, so the resolver finds it unprompted and says which file it used."""
        root = self._repo_skeleton_with_feed()
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "preflight_upload.py"),
             "--entries", str(self.entries), "--salary", str(self.salary),
             "--json"], capture_output=True, text=True)
        payload = json.loads(proc.stdout)
        self.assertIn("resolved", payload["info"]["feed_autoresolve"])
        self.assertIn("2026-07-25", payload["info"]["feed_autoresolve"])
        self.assertTrue(payload["info"]["feed_file"].endswith(".json"))
        self.assertIn("feed_age_minutes", payload["info"])

    def test_a_file_spanning_two_slate_dates_resolves_no_feed_rather_than_a_wrong_one(self):
        from tools.preflight_upload import (
            Report, load_entries, load_salary, resolve_feed_for_slate,
        )
        mixed = self._salary_on_date("01/02/2099")
        with mixed.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        rows[1][6] = rows[1][6].replace("01/02/2099", "07/25/2026")
        with mixed.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        _, _, entries, _, _ = load_entries(self.entries)
        rep = Report()
        self.assertIsNone(resolve_feed_for_slate(entries, load_salary(mixed), rep))
        self.assertIn("spans 2 slate dates", rep.info["feed_autoresolve"])


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


class FieldMinerGateTests(unittest.TestCase):
    """F9: the structural gate computed, then archived anyway."""

    def _mined(self, structural_ok, **flags):
        return {
            "contest_id": "C1", "slate_date": "2026-07-25", "coverage": "full",
            "entries": [], "meta": {"winning_entry_id": "E1"},
            "diagnostics": {"parse_structural_ok": structural_ok,
                            "verification_note": "PARSE FAILURE: test fixture",
                            **flags},
        }

    def test_exit_codes_are_pinned_per_failure_mode(self):
        from mlb_engine.field import field_miner as fm

        self.assertEqual(fm.structural_exit_code({"contest_type_mismatch": True}),
                         fm.EXIT_WRONG_SALARY_FILE)
        self.assertEqual(fm.structural_exit_code({"parsed_nothing": True}),
                         fm.EXIT_PARSED_NOTHING)
        self.assertEqual(fm.structural_exit_code({"mostly_unparsed": True}),
                         fm.EXIT_MOSTLY_UNPARSED)
        self.assertEqual(fm.structural_exit_code({}), fm.EXIT_STRUCTURAL_OTHER)
        # the four codes are distinct, or a caller cannot tell them apart
        codes = {fm.EXIT_WRONG_SALARY_FILE, fm.EXIT_PARSED_NOTHING,
                 fm.EXIT_MOSTLY_UNPARSED, fm.EXIT_STRUCTURAL_OTHER}
        self.assertEqual(len(codes), 4)
        self.assertNotIn(fm.EXIT_OK, codes)

    def test_verification_note_is_line_one_of_every_block(self):
        from mlb_engine.field.field_miner import emit_ledger_block

        mined = self._mined(True)
        mined["diagnostics"]["verification_note"] = "parse structurally sound"
        mined.update({
            "duplication": {"distinct_lineups": 1, "share_duplicated_pct": 0.0,
                            "max_copies": 1, "winner_copies": 1, "copies_histogram": {}},
            "construction": {"at_cap_share_pct": None, "salary_left_histogram": {},
                             "max_stack_histogram": {}, "sp_pair_top": [], "top_owned": []},
            "meta": {"entries_total": 1, "entries_complete_lineups": 1,
                     "winning_points": 1.0, "multi_entry_flag": False},
        })
        mined["diagnostics"].update({
            "salary_join_rate_pct": None, "ownership_recompute_ok": True,
            "ownership_recompute_max_diff_pts": 0.0, "recomputed_total_pct": 100.0,
            "dk_table_total_pct": 100.0, "dk_table_deficit_pts": 0.0,
            "roster_slots_observed": 10, "roster_slots_expected": 10,
            "intra_entry_duplicate_entry_ids": [], "entries_unparsed": 0,
            "ownership_recompute_denominator": "all_entries"})
        body = emit_ledger_block(mined)
        first_bullet = next(l for l in body.splitlines() if l.startswith("- "))
        self.assertIn("Verification:", first_bullet)

    def test_forced_override_is_visible_in_the_block(self):
        from mlb_engine.field.field_miner import emit_ledger_block

        mined = self._mined(False, contest_type_mismatch=True)
        mined.update({
            "duplication": {"distinct_lineups": 1, "share_duplicated_pct": 0.0,
                            "max_copies": 1, "winner_copies": 1, "copies_histogram": {}},
            "construction": {"at_cap_share_pct": 50.0, "salary_left_histogram": {"a": 1},
                             "max_stack_histogram": {"4": 1},
                             "sp_pair_top": [{"pair": ("a", "b"), "field_share_pct": 10}],
                             "top_owned": []},
            "meta": {"entries_total": 1, "entries_complete_lineups": 1,
                     "winning_points": 1.0, "multi_entry_flag": False},
            "forced_override": {"warning": "archived under override",
                                "exit_code_suppressed": 4,
                                "verification_note": "WRONG SALARY FILE"},
        })
        mined["diagnostics"].update({
            "salary_join_rate_pct": 0.0, "ownership_recompute_ok": False,
            "ownership_recompute_max_diff_pts": 99.0, "recomputed_total_pct": 100.0,
            "dk_table_total_pct": 1.0, "dk_table_deficit_pts": 99.0,
            "roster_slots_observed": 10, "roster_slots_expected": 10,
            "intra_entry_duplicate_entry_ids": [], "entries_unparsed": 0,
            "ownership_recompute_denominator": "all_entries"})
        body = emit_ledger_block(mined)
        self.assertIn("ARCHIVED UNDER OVERRIDE", body)
        # and the salary-derived tables are withheld rather than printed wrong
        self.assertIn("unavailable", body)
        self.assertNotIn("Max-stack histogram", body)
        self.assertNotIn("SP-pair field share", body)


class RegistryAccumulationTests(unittest.TestCase):
    """F10: re-mining used to inflate every aggregate silently."""

    def _mined(self, contest_id, usernames):
        return {
            "contest_id": contest_id, "slate_date": "2026-07-25",
            "meta": {"winning_entry_id": "E1"},
            "entries": [
                {"entry_id": f"E{i}", "username": name, "salary_used": 49000,
                 "max_stack": 4, "chalk_score": 1.0, "players_norm": [f"p{i}"]}
                for i, name in enumerate(usernames)
            ],
        }

    def test_remining_a_contest_is_a_no_op(self):
        from mlb_engine.field.field_miner import update_registry

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "reg.json")
            first = update_registry(path, self._mined("C1", ["alice", "bob"]))
            self.assertEqual(first["users"]["alice"]["entries"], 1)
            before = Path(path).read_text(encoding="utf-8")

            update_registry(path, self._mined("C1", ["alice", "bob"]))
            update_registry(path, self._mined("C1", ["alice", "bob"]))
            self.assertEqual(Path(path).read_text(encoding="utf-8"), before)

            # a genuinely new contest still accumulates
            after = update_registry(path, self._mined("C2", ["alice"]))
            self.assertEqual(after["users"]["alice"]["entries"], 2)
            self.assertEqual(after["users"]["bob"]["entries"], 1)
            self.assertEqual(after["contests_mined"], ["C1", "C2"])

    def test_default_path_is_module_relative_and_single(self):
        from mlb_engine.field.field_miner import default_registry_path

        resolved = Path(default_registry_path())
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved.parent.name, "reference")
        self.assertEqual(resolved.name, "field_opponent_registry.json")


class PromotedPointerPortabilityTests(unittest.TestCase):
    """F12: the pointer raised across sessions and late swap died at entry."""

    def _fake_run(self, runs_root: Path, run_id: str) -> Path:
        from mlb_engine.pipeline.build_state_manager import (
            MANIFEST_NAME, sha256_file,
        )
        run_dir = runs_root / run_id
        (run_dir / "final").mkdir(parents=True)
        (run_dir / MANIFEST_NAME).write_text(
            json.dumps({"run_id": run_id, "status": "promoted"}), encoding="utf-8")
        (runs_root / "latest_valid_run.json").write_text(json.dumps({
            "run_id": run_id,
            "run_dir_rel": run_id,
            # An absolute path under a mount that does not exist in this process,
            # which is the shape every pointer written in a prior Cowork session
            # has.
            "run_dir": f"/sessions/dead-session-mount/mnt/mlb-dfs/runs/{run_id}",
            "manifest_sha256": sha256_file(run_dir / MANIFEST_NAME),
            "promoted_utc": "2026-07-25T21:24:40+00:00",
        }), encoding="utf-8")
        return run_dir

    def test_pointer_written_under_one_mount_resolves_under_another(self):
        from mlb_engine.pipeline.build_state_manager import get_latest_promoted_run

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            run_dir = self._fake_run(runs, "20260725T212439Z_c2111186")
            resolved = get_latest_promoted_run(runs)
            self.assertIsNotNone(resolved)
            self.assertEqual(Path(resolved["run_dir"]).resolve(), run_dir.resolve())

    def test_old_shape_pointer_without_run_dir_rel_still_resolves(self):
        """The pointers already on disk predate run_dir_rel; run_id must carry them."""
        from mlb_engine.pipeline.build_state_manager import get_latest_promoted_run

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            run_dir = self._fake_run(runs, "20260725T212439Z_c2111186")
            pointer = runs / "latest_valid_run.json"
            data = json.loads(pointer.read_text(encoding="utf-8"))
            del data["run_dir_rel"]
            pointer.write_text(json.dumps(data), encoding="utf-8")
            resolved = get_latest_promoted_run(runs)
            self.assertIsNotNone(resolved)
            self.assertEqual(Path(resolved["run_dir"]).resolve(), run_dir.resolve())

    def test_a_genuinely_missing_run_returns_none_rather_than_raising(self):
        from mlb_engine.pipeline.build_state_manager import get_latest_promoted_run

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            (runs / "latest_valid_run.json").write_text(json.dumps({
                "run_id": "nope", "run_dir": "/sessions/dead/mnt/runs/nope",
                "manifest_sha256": "x", "promoted_utc": "2026-07-25T00:00:00+00:00",
            }), encoding="utf-8")
            self.assertIsNone(get_latest_promoted_run(runs))
            # and a corrupt pointer is None, not a traceback
            (runs / "latest_valid_run.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(get_latest_promoted_run(runs))


class DiagnosticsHonestyTests(unittest.TestCase):
    """F11: the run record is the project's memory of what was shipped and why."""

    def test_coverage_target_does_not_shrink_to_the_lineups_built(self):
        from mlb_engine.optimize.optimizer_v3 import validate_sp_pair_coverage

        plan = {"policy": "weighted_soft", "target_unique_pairs": 8,
                "required_pairs": [], "coverage_preference": "spread"}
        # Three lineups against an eight-pair target. soft_pass used to be
        # len(observed) >= min(target, len(lineups)), so a truncated portfolio
        # always met its own target while the summary printed the unshrunk one.
        records = [
            {"lineup": None, "sp_ids": [f"p{i}", f"q{i}"]} for i in range(3)
        ]
        result = validate_sp_pair_coverage(records, plan)
        self.assertEqual(result["target_unique_pairs"], 8)
        self.assertTrue(result["truncated_portfolio"])
        self.assertFalse(result["soft_target_met"])
        self.assertFalse(result["pass"])
        self.assertIn("unreachable by construction", result["summary"])

    def test_augmentation_note_reports_a_no_op_as_a_no_op(self):
        """The note asserted forced coverage even when nothing was appended."""
        import re as _re

        from mlb_engine.optimize import optimizer_v3

        source = Path(optimizer_v3.__file__).read_text(encoding="utf-8")
        # The unconditional claim is gone, and the no-op branch says so plainly.
        self.assertNotIn(
            'f"forced coverage across {n_pairs} viable SP pairs and "', source)
        self.assertIn("coverage augmentation appended nothing", source)
        self.assertIn("was NOT forced", source)
        self.assertTrue(_re.search(r"if augmentation\['appended'\] <= 0", source))

    def test_blocked_run_verifies_instead_of_reading_as_tampered(self):
        from mlb_engine.pipeline.build_state_manager import (
            create_run, register_artifact, update_run_certification,
            verify_run_bundle,
        )

        with tempfile.TemporaryDirectory() as tmp:
            run = create_run(Path(tmp) / "runs", "initial_build")
            run_dir = Path(run["run_dir"])
            diagnostics = run_dir / "final" / "diagnostics.json"
            diagnostics.parent.mkdir(parents=True, exist_ok=True)
            diagnostics.write_text(json.dumps({
                "run_id": run["run_id"],
                "status": "blocked",
                "errors": ["pool blocker: ATL matched 0/9"],
                "blockers": ["pool blocker: ATL matched 0/9"],
                "export_declared": False,
                "hash_binding_applicable": False,
            }), encoding="utf-8")
            register_artifact(run_dir, diagnostics, "diagnostics")
            update_run_certification(
                run_dir,
                {"workflow_valid": False, "selection_certified": False,
                 "allocation_certified": False},
                errors=["pool blocker: ATL matched 0/9"], warnings=[],
                status="blocked")
            result = verify_run_bundle(run_dir)
            self.assertTrue(result["passed"], result["errors"])
            self.assertNotIn("diagnostics missing export hash binding",
                             " ".join(result["errors"]))

    def test_a_real_export_still_requires_its_hash_binding(self):
        """The exemption must not become a way to skip the check that matters."""
        from mlb_engine.pipeline.build_state_manager import (
            create_run, register_artifact, verify_run_bundle,
        )

        with tempfile.TemporaryDirectory() as tmp:
            run = create_run(Path(tmp) / "runs", "initial_build")
            run_dir = Path(run["run_dir"])
            diagnostics = run_dir / "final" / "diagnostics.json"
            diagnostics.parent.mkdir(parents=True, exist_ok=True)
            diagnostics.write_text(json.dumps({
                "run_id": run["run_id"], "status": "certified",
                "export_declared": True, "hash_binding_applicable": True,
            }), encoding="utf-8")
            register_artifact(run_dir, diagnostics, "diagnostics")
            result = verify_run_bundle(run_dir)
            self.assertFalse(result["passed"])
            self.assertIn("missing export hash binding", " ".join(result["errors"]))


class BankCacheCorrectnessTests(unittest.TestCase):
    """F14: the cache served answers to questions nobody asked."""

    def _frame(self):
        import pandas as pd
        return pd.DataFrame({
            "Player_ID": ["1", "2", "3"],
            "Ceiling": [10.0, 20.0, 30.0],
            "Salary": [4000, 5000, 6000],
            "Excluded": [False, False, False],
        })

    def test_conditions_signature_moves_with_every_input_that_moves_a_solve(self):
        from mlb_engine.optimize.bank_cache import conditions_signature

        frame = self._frame()
        base = conditions_signature(frame, [], 4, 5)
        self.assertEqual(base, conditions_signature(frame, [], 4, 5))
        self.assertNotEqual(base, conditions_signature(frame, ["2"], 4, 5),
                            "an exclude must change the signature")
        self.assertNotEqual(base, conditions_signature(frame, [], 3, 5),
                            "a stack bound must change the signature")
        enriched = frame.copy()
        enriched.loc[0, "Ceiling"] = 11.5
        self.assertNotEqual(base, conditions_signature(enriched, [], 4, 5),
                            "an enrichment pass must change the signature")

    def test_stale_jobs_are_dropped_when_conditions_change(self):
        from mlb_engine.optimize.bank_cache import BankCache

        with tempfile.TemporaryDirectory() as tmp:
            cache = BankCache(Path(tmp) / "bank.json")
            cache.attempted = {"a+b|TEAM||OLDSIG", "c+d|TEAM||NEWSIG"}
            cache.candidates = [
                {"roster": [str(i) for i in range(10)], "objective": 1.0,
                 "job": "a+b|TEAM||OLDSIG"},
                {"roster": [str(i) for i in range(10, 20)], "objective": 2.0,
                 "job": "c+d|TEAM||NEWSIG"},
            ]
            cache._seen = {tuple(c["roster"]) for c in cache.candidates}
            dropped = cache.drop_stale_jobs("NEWSIG")
            self.assertEqual(dropped, 2)
            self.assertEqual(cache.attempted, {"c+d|TEAM||NEWSIG"})
            self.assertEqual(len(cache.candidates), 1)
            self.assertEqual(cache.candidates[0]["job"], "c+d|TEAM||NEWSIG")
            # idempotent: running it again changes nothing
            self.assertEqual(cache.drop_stale_jobs("NEWSIG"), 0)

    def test_projection_digest_is_the_invalidating_half_only(self):
        """R101. The conditions signature mixed two kinds of fact. The
        projection half is TRUTH -- a change means the stored answer answers a
        different question -- and the excludes/stack-bounds half only NARROWS.
        Splitting them is what lets one bucket while the other still purges."""
        from mlb_engine.optimize.bank_cache import (
            conditions_signature, projection_digest)

        frame = self._frame()
        base = projection_digest(frame)
        self.assertEqual(base, projection_digest(frame))
        # Narrowing does not move the pool digest ...
        self.assertEqual(base, projection_digest(frame),
                         "the pool digest must not read excludes")
        self.assertNotEqual(conditions_signature(frame, ["2"], 4, 5),
                            conditions_signature(frame, [], 4, 5))
        self.assertNotEqual(conditions_signature(frame, [], 3, 5),
                            conditions_signature(frame, [], 4, 5))
        # ... but an enrichment pass moves both.
        enriched = frame.copy()
        enriched.loc[0, "Ceiling"] = 11.5
        self.assertNotEqual(base, projection_digest(enriched))
        self.assertNotEqual(conditions_signature(frame, [], 4, 5),
                            conditions_signature(enriched, [], 4, 5))

    def test_drop_stale_jobs_keeps_sibling_buckets_under_one_pool_digest(self):
        """The R101 fix at the storage contract. Two conditions signatures
        registered under the same projection digest are two live buckets; a
        third registered under a different one is stale and still purged."""
        from mlb_engine.optimize.bank_cache import BankCache

        with tempfile.TemporaryDirectory() as tmp:
            cache = BankCache(Path(tmp) / "bank.json")
            cache.register_conditions("GENERAL", "POOL_A")
            cache.register_conditions("ENTRY_A", "POOL_A")
            cache.register_conditions("OLD_POOL", "POOL_B")
            cache.attempted = {"p|T||GENERAL", "p|T||ENTRY_A", "p|T||OLD_POOL"}
            cache.candidates = [
                {"roster": [str(i) for i in range(10)], "objective": 1.0,
                 "job": "p|T||GENERAL"},
                {"roster": [str(i) for i in range(10, 20)], "objective": 2.0,
                 "job": "p|T||ENTRY_A"},
                {"roster": [str(i) for i in range(20, 30)], "objective": 3.0,
                 "job": "p|T||OLD_POOL"},
            ]
            cache._seen = {tuple(c["roster"]) for c in cache.candidates}
            dropped = cache.drop_stale_jobs("ENTRY_B", projection_digest="POOL_A")
            self.assertEqual(dropped, 2, "only the other pool's job should go")
            self.assertEqual(cache.attempted, {"p|T||GENERAL", "p|T||ENTRY_A"})
            self.assertEqual([c["job"] for c in cache.candidates],
                             ["p|T||GENERAL", "p|T||ENTRY_A"])
            self.assertEqual(cache.live_buckets(), ["ENTRY_A", "GENERAL"])
            # An unindexed signature is not provably under this pool's truth, so
            # it fails closed. That is what keeps a legacy cache file from
            # resurrecting the 2026-07-26 candidates.
            cache.candidates.append(
                {"roster": [str(i) for i in range(30, 40)], "objective": 4.0,
                 "job": "p|T||UNKNOWN"})
            cache._seen.add(tuple(str(i) for i in range(30, 40)))
            self.assertEqual(
                cache.drop_stale_jobs("ENTRY_B", projection_digest="POOL_A"), 1)
            self.assertEqual([c["job"] for c in cache.candidates],
                             ["p|T||GENERAL", "p|T||ENTRY_A"])

    def test_the_conditions_index_survives_a_save_and_unions_writers(self):
        from mlb_engine.optimize.bank_cache import BankCache

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            a = BankCache(path)
            b = BankCache(path)
            a.register_conditions("SIG_A", "POOL")
            b.register_conditions("SIG_B", "POOL")
            b.save()
            a.save()  # the later writer merges rather than overwriting
            merged = BankCache(path)
            self.assertEqual(merged.conditions_index,
                             {"SIG_A": "POOL", "SIG_B": "POOL"})

    def test_corrupt_cache_rebuilds_instead_of_blocking_the_build(self):
        from mlb_engine.optimize.bank_cache import BankCache

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            path.write_text('{"candidates": [{"roster": ["a"', encoding="utf-8")
            cache = BankCache(path)
            self.assertTrue(cache.corrupt_on_load)
            self.assertEqual(cache.candidates, [])
            self.assertEqual(cache.attempted, set())

    def test_save_is_atomic(self):
        from mlb_engine.optimize.bank_cache import BankCache

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.json"
            cache = BankCache(path)
            cache.add([str(i) for i in range(10)], 1.0, job="j")
            cache.save()
            self.assertTrue(path.exists())
            # no tmp files left behind
            self.assertEqual(
                [p.name for p in Path(tmp).iterdir() if p.name != "bank.json"], [])
            self.assertEqual(len(BankCache(path).candidates), 1)


class OwnResultsTests(unittest.TestCase):
    """G4: the rank column was parsed and discarded, so 'are we winning' was unanswerable."""

    def _mined(self):
        return {
            "contest_id": "C1", "slate_date": "2026-07-24",
            "meta": {"entries_total": 100, "winning_points": 150.0},
            "entries": [
                {"rank": "1", "entry_id": "E1", "points": 150.0,
                 "players_norm": ("a", "b")},
                {"rank": "4", "entry_id": "E2", "points": 140.0,
                 "players_norm": ("c", "d")},
                {"rank": "51", "entry_id": "E3", "points": 100.0,
                 "players_norm": ("c", "d")},
                {"rank": "90", "entry_id": "E9", "points": 50.0,
                 "players_norm": ("e", "f")},
            ],
        }

    def test_finish_percentiles_and_duplication_against_the_field(self):
        from mlb_engine.field.field_miner import summarize_own_entries

        summary = summarize_own_entries(self._mined(), ["E2", "E3"],
                                        entry_fee=0.25, winnings=1.50)
        self.assertEqual(summary["matched"], 2)
        self.assertEqual(summary["best_rank"], 4)
        self.assertEqual(summary["worst_rank"], 51)
        self.assertEqual(summary["field_size"], 100)
        self.assertAlmostEqual(summary["best_finish_percentile"], 97.0, places=1)
        self.assertEqual(summary["best_points"], 140.0)
        self.assertEqual(summary["winning_points"], 150.0)
        # E2 and E3 are the same lineup, so both are duplicated by the field
        self.assertEqual(summary["own_lineups_duplicated_by_field"], 2)
        self.assertEqual(summary["max_copies_of_an_own_lineup"], 2)
        self.assertAlmostEqual(summary["fees_total"], 0.50)
        self.assertAlmostEqual(summary["net"], 1.00)
        self.assertIn("never a graded prediction", summary["labels"])

    def test_no_money_supplied_means_no_net_rather_than_a_guess(self):
        from mlb_engine.field.field_miner import summarize_own_entries

        summary = summarize_own_entries(self._mined(), ["E2"])
        self.assertIsNone(summary["net"])
        self.assertIsNone(summary["fees_total"])
        self.assertEqual(summary["matched"], 1)

    def test_unmatched_entry_ids_say_so_instead_of_reporting_zero(self):
        from mlb_engine.field.field_miner import summarize_own_entries

        summary = summarize_own_entries(self._mined(), ["NOPE"])
        self.assertEqual(summary["matched"], 0)
        self.assertIn("check the contest id", summary["note"])

    def test_rank_survives_the_entries_projection(self):
        """It was parsed off the standings and then dropped at the projection."""
        from mlb_engine.field.field_miner import mine_contest, parse_standings_export

        archived = sorted((REPO / "data" / "archive").rglob("contest-standings-*.csv"))
        if not archived:
            self.skipTest("no archived standings on disk")
        standings = parse_standings_export(str(archived[0]))
        # standings_only tier: no salary map needed, so this stays fast.
        mined = mine_contest(standings, None, contest_id="T1")
        entries = mined["entries"]
        self.assertTrue(entries, "fixture standings produced no complete entries")
        self.assertIn("rank", entries[0])
        self.assertTrue(any(str(e["rank"]).strip().isdigit() for e in entries))

    def test_net_to_date_is_keyed_on_contest_id(self):
        sys.path.insert(0, str(REPO / "tools"))
        from net_to_date import append_record, load_records

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "own.json"
            append_record({"contest_id": "C1", "slate_date": "2026-07-24",
                           "net": 0.75, "fees_total": 0.75, "winnings_total": 1.5,
                           "matched": 3}, path)
            append_record({"contest_id": "C2", "slate_date": "2026-07-25",
                           "net": -0.25, "fees_total": 0.25, "winnings_total": 0.0,
                           "matched": 1}, path)
            append_record({"contest_id": "C1", "slate_date": "2026-07-24",
                           "net": 1.10, "fees_total": 0.75, "winnings_total": 1.85,
                           "matched": 3}, path)
            records = load_records(path)
            self.assertEqual(len(records), 2)
            self.assertEqual({r["contest_id"]: r["net"] for r in records},
                             {"C1": 1.10, "C2": -0.25})


class PreflightContractDocumentationTests(unittest.TestCase):
    """R2, skill half: the documented contract has to match the exit codes.

    Teeth: the tool started exiting 4 on --force, hard-failing a manifest-less
    delivered file and a player absent from a confirmed lineup, but --help and
    SKILL.md both still promised the old three-code contract. The caller reads
    those, not the source, so a false doc is a false contract.
    """

    SKILL = REPO / "skills" / "generate-lineups" / "SKILL.md"

    def _preflight_section(self) -> str:
        text = self.SKILL.read_text(encoding="utf-8")
        start = text.index("## Always run the preflight")
        return text[start:text.index("\n## ", start + 1)]

    def test_help_does_not_promise_exit_zero_on_force(self):
        out = subprocess.run(
            [sys.executable, str(REPO / "tools" / "preflight_upload.py"), "--help"],
            capture_output=True, text=True, check=True).stdout
        force = [ln for ln in out.splitlines() if "--force" in ln or "clock beats" in ln]
        self.assertTrue(force, out)
        blob = " ".join(force)
        self.assertNotIn("exit 0", blob.lower())
        self.assertIn("exit 4", blob.lower())

    def test_the_docstring_exit_table_carries_all_four_codes(self):
        import preflight_upload

        doc = preflight_upload.__doc__ or ""
        table = doc[doc.index("Exit codes:"):]
        for code in ("0", "2", "3", "4"):
            self.assertRegex(table, rf"(?m)^\s+{code}\s+\w")
        self.assertIn("acknowledged", table.lower())

    def test_the_skill_states_the_four_codes_and_never_says_force_exits_zero(self):
        section = self._preflight_section()
        for token in ("| 0 |", "| 2 |", "| 3 |", "| 4 |"):
            self.assertIn(token, section)
        lowered = section.lower()
        self.assertNotIn("exits 0", lowered)
        # The old text read "Exit 0 clean, 2 hard failure, 3 IO error" on one
        # wrapped line. Match the phrase, not the wrap, or the assertion can
        # never fire once the section is reflowed.
        self.assertNotIn("exit 0 clean", " ".join(lowered.split()))
        # The one thing an agent must do differently on 4: say what was overridden.
        self.assertIn("overridden", lowered)
        for waiver in ("--no-manifest", "--feed-lenient"):
            self.assertIn(waiver, section)


class ExpectSha256Tests(unittest.TestCase):
    """R20a: --expect-sha256 ties the file Ben selects at upload to the one
    the brief reported. The brief already records delivered_sha256; this is
    the check that makes the pairing enforceable at T-5 instead of a thing
    to eyeball."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.lineup = write_classic_salary(self.salary)
        self.entries = self.dir / "DKEntries.csv"
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup)])
        import hashlib
        self.digest = hashlib.sha256(self.entries.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        return run_preflight("--entries", str(self.entries),
                             "--salary", str(self.salary), *extra)

    def test_matching_full_sha_passes(self):
        result = self._run("--expect-sha256", self.digest)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_matching_prefix_of_twelve_passes(self):
        result = self._run("--expect-sha256", self.digest[:12])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_mismatch_is_a_hard_failure(self):
        result = self._run("--expect-sha256", "0" * 64)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("is not the one the brief reported",
                      result.stdout + result.stderr)

    def test_a_short_prefix_is_a_usage_error_not_a_pass(self):
        result = self._run("--expect-sha256", "abc")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)


class FixedTmpNameRegressionTests(unittest.TestCase):
    """R21: a fixed tmp name means two concurrent writers interleave into one
    tmp file and either can rename partial bytes over the real target. Pin
    both known sites to unique names so the defect cannot quietly return."""

    def test_no_fixed_tmp_names_remain(self):
        preflight = (REPO / "tools" / "preflight_upload.py").read_text(
            encoding="utf-8")
        self.assertNotIn('.preflight.tmp"', preflight)
        self.assertIn("uuid.uuid4().hex", preflight)
        net = (REPO / "tools" / "net_to_date.py").read_text(encoding="utf-8")
        self.assertNotIn('f".{path.name}.tmp"', net)
        self.assertIn("uuid.uuid4().hex", net)


# --------------------------------------------------------------------------
# R29: verify_export's lock derivation cannot go stale mid-use
# --------------------------------------------------------------------------

THREE_GAMES = (
    ("AAA@BBB 07/25/2026 07:05PM ET", ("AAA", "BBB"), "2026-07-25T23:05:00Z"),
    ("CCC@DDD 07/25/2026 07:10PM ET", ("CCC", "DDD"), "2026-07-25T23:10:00Z"),
    ("EEE@FFF 07/25/2026 07:40PM ET", ("EEE", "FFF"), "2026-07-25T23:40:00Z"),
)


def write_three_game_salary(path: Path) -> dict:
    """Three games, two full teams each. Returns {f"{team} {surname}": pid}.

    Two games is not enough to test a swap that introduces a player: with both
    P slots filled and only two games, every unrostered team is an opposing
    team to a rostered SP, so any newly introduced hitter breaks the
    hitter-versus-rostered-SP rule and the lock failure cannot be isolated from
    a legality failure.
    """
    rows = [SALARY_HEADER]
    ids: dict = {}
    pid = 2000
    for game, teams, _utc in THREE_GAMES:
        for team in teams:
            for i, (pos, roster) in enumerate(SLOT_SPEC):
                pid += 1
                name = f"{team} {SURNAMES[i]}"
                ids[name] = str(pid)
                rows.append(_salary_row(pid, name, team, game, pos, roster, 4000,
                                        "", "SP" if roster == "P" else str(i)))
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return ids


def write_three_game_feed(path: Path, postponed=(), confirmed=None,
                          partial=None, probables=None) -> Path:
    """A lineups feed for the same three games, start times matching the salary.

    ``confirmed`` is {team: [player names]}; those sides read ``confirmed`` with
    that posted lineup and every other side stays ``tbd``. R46's check only fires
    against a CONFIRMED side, so a feed of all-tbd sides exercises nothing.

    ``partial`` is the same shape and produces R46-round-2's third case: posted
    hitters under ``lineup_status: partial``, which is what an mlb.com paste
    yields when a posted starter has no DK salary row. ``probables`` is
    {team: name} and attaches a declared probable pitcher to any side.
    """
    posted = {k.upper(): list(v) for k, v in (confirmed or {}).items()}
    part = {k.upper(): list(v) for k, v in (partial or {}).items()}
    arms = {k.upper(): v for k, v in (probables or {}).items()}

    def side(team):
        key = team.upper()
        pp = {"name": arms[key]} if key in arms else None
        names, status = posted.get(key), "confirmed"
        if names is None:
            names, status = part.get(key), "partial"
        if names is None:
            return {"team_abbrev": team, "lineup_status": "tbd",
                    "lineup": [], "probable_pitcher": pp}
        return {"team_abbrev": team, "lineup_status": status,
                "lineup": [{"name": n, "batting_order": i + 1}
                           for i, n in enumerate(names)],
                "probable_pitcher": pp}

    games = []
    for pk, (_game, (away, home), utc) in enumerate(THREE_GAMES, start=1):
        game_id = f"{away}@{home}"
        games.append({
            "game_pk": pk, "game_date_utc": utc, "venue": "Test Park",
            "status": "Postponed" if game_id in postponed else "Pre-Game",
            "away": side(away),
            "home": side(home),
        })
    path.write_text(json.dumps({
        "date": "2026-07-25", "fetched_at": "2026-07-25T22:00:00Z", "games": games,
    }), encoding="utf-8")
    return path


def run_verify(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_export.py"), *args],
        capture_output=True, text=True)


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VerifyExportLockDerivationTests(unittest.TestCase):
    """R29: --locked-teams was the only source of truth and it went stale.

    Teeth: on 2026-07-29 a swap chain ran 7:23-8:02 PM ET against a
    --locked-teams list passed once at 7:23. Two more games locked underneath
    it, this tool printed PASS, and DraftKings rejected 7 of 16 entries. Every
    test here fails if the derivation stops running, or if a supplied list is
    allowed to shrink the derived set again.
    """

    EARLY = "2026-07-25T23:07:00+00:00"   # AAA@BBB started, the other two have not
    LATE = "2026-07-25T23:45:00+00:00"    # all three started
    PREGAME = "2026-07-25T23:20:00+00:00"  # EEE@FFF still open

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.ids = write_three_game_salary(self.salary)
        self.feed = write_three_game_feed(self.dir / "lineups_feed.json")
        # AAA SP + CCC SP + five AAA hitters + three EEE outfielders. The
        # rostered SPs' opponents are BBB and DDD, and EEE faces FFF's
        # unrostered SP, so this is legal on every Classic rule.
        self.parent_lineup = [
            self.ids["AAA Aster"], self.ids["CCC Aster"],
            self.ids["AAA Boone"], self.ids["AAA Crane"], self.ids["AAA Dunne"],
            self.ids["AAA Ellis"], self.ids["AAA Frost"],
            self.ids["EEE Gable"], self.ids["EEE Hollis"], self.ids["EEE Ives"],
        ]
        self.parent = self.dir / "parent.csv"
        write_entries(self.parent, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.parent_lineup)])

    def tearDown(self):
        self.tmp.cleanup()

    def _child_swapping_in_fff(self) -> Path:
        """Replace one EEE outfielder with an FFF outfielder: still legal, and
        the introduced player's game is the one that locks last."""
        lineup = list(self.parent_lineup)
        lineup[9] = self.ids["FFF Ives"]
        child = self.dir / "child.csv"
        write_entries(child, CLASSIC_HEADER, [classic_entry("900", "5", lineup)])
        return child

    def _resolve(self, supplied=None, as_of=None, feed=True):
        sys.path.insert(0, str(REPO / "tools"))
        from datetime import datetime
        import verify_export as ve
        from tools.preflight_upload import Report, load_entries, load_salary
        rep = Report()
        _, _, entries, _, _ = load_entries(self.parent)
        locked, note, source = ve.resolve_locked_teams(
            supplied, load_salary(self.salary), self.salary,
            self.feed if feed else None,
            datetime.fromisoformat(as_of or self.EARLY), rep)
        return locked, note, source, rep, entries

    # -- the derivation itself ------------------------------------------------

    def test_locked_teams_come_from_the_feed_clock_with_no_flag_passed(self):
        locked, _note, source, rep, _ = self._resolve()
        self.assertEqual(locked, {"AAA", "BBB"})
        self.assertIn("lineups feed", source)
        self.assertEqual(rep.warnings, [])

    def test_the_derivation_moves_with_the_clock(self):
        self.assertEqual(self._resolve(as_of=self.LATE)[0],
                         {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF"})
        self.assertEqual(self._resolve(as_of="2026-07-25T22:00:00+00:00")[0], set())

    def test_a_postponed_game_is_not_locked_even_after_its_scheduled_start(self):
        write_three_game_feed(self.feed, postponed=("AAA@BBB",))
        locked, note, _source, _rep, _ = self._resolve(as_of=self.LATE)
        self.assertEqual(locked, {"CCC", "DDD", "EEE", "FFF"})
        self.assertIn("postponed", note)

    def test_no_feed_falls_back_to_game_info_and_says_so(self):
        locked, _note, source, _rep, _ = self._resolve(feed=False)
        self.assertEqual(locked, {"AAA", "BBB"})
        self.assertEqual(source, "salary Game Info")

    # -- the feed cannot shrink the set either --------------------------------

    def test_a_feed_covering_fewer_games_than_the_salary_file_cannot_unlock_them(self):
        """The review caught this: the feed is the preferred source, so a feed
        that covers one game would have reported an EMPTY locked set at a clock
        where two games had started. That is the 07-29 false PASS reachable
        through the fix for it. A shared date-keyed name is exactly where a
        single-game Showdown feed lands."""
        write_three_game_feed(self.feed)
        payload = json.loads(self.feed.read_text(encoding="utf-8"))
        payload["games"] = [payload["games"][2]]  # EEE@FFF only
        self.feed.write_text(json.dumps(payload), encoding="utf-8")
        locked, _note, source, rep, _ = self._resolve(as_of=self.LATE)
        self.assertEqual(locked, {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF"})
        self.assertIn("salary Game Info", source)
        self.assertTrue(any("does not cover" in w for w in rep.warnings))

    def test_a_feed_for_the_wrong_date_cannot_unlock_this_slate(self):
        payload = json.loads(self.feed.read_text(encoding="utf-8"))
        for game in payload["games"]:
            game["game_date_utc"] = "2026-08-02T23:05:00Z"
        self.feed.write_text(json.dumps(payload), encoding="utf-8")
        locked, _note, _source, rep, _ = self._resolve(as_of=self.EARLY)
        self.assertIn("AAA", locked)
        self.assertIn("BBB", locked)
        self.assertTrue(any("does not cover" in w for w in rep.warnings))

    def test_only_an_affirmative_postponement_may_remove_a_team(self):
        """The one subtraction the feed is allowed, and the reason the union is
        safe: a postponed game's scheduled start has passed but nothing in it is
        frozen, so calling it locked would block a legal swap."""
        write_three_game_feed(self.feed, postponed=("AAA@BBB",))
        locked, note, _source, _rep, _ = self._resolve(as_of=self.LATE)
        self.assertNotIn("AAA", locked)
        self.assertNotIn("BBB", locked)
        self.assertEqual(locked, {"CCC", "DDD", "EEE", "FFF"})
        self.assertIn("postponed", note)

    def test_an_underivable_clock_warns_instead_of_printing_a_contradiction(self):
        """It used to report 'every game on this slate has started' alongside an
        empty locked set, and the guard meant to catch that was unreachable."""
        import csv as _csv
        with self.salary.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(_csv.reader(handle))
        for row in rows[1:]:
            row[6] = "Postponed"
        with self.salary.open("w", newline="", encoding="utf-8") as handle:
            _csv.writer(handle).writerows(rows)
        locked, note, source, rep, _ = self._resolve(feed=False)
        self.assertEqual(locked, set())
        self.assertEqual(source, "none")
        self.assertNotIn("has started", str(note))
        self.assertTrue(any("underivable" in w for w in rep.warnings))

    def test_an_unreadable_feed_warns_rather_than_silently_using_game_info(self):
        self.feed.write_text("{not json", encoding="utf-8")
        _locked, _note, source, rep, _ = self._resolve()
        self.assertEqual(source, "salary Game Info")
        self.assertTrue(any("cannot see a postponement" in w for w in rep.warnings))

    # -- a supplied list adds, never shrinks ---------------------------------

    def test_a_stale_supplied_list_cannot_shrink_the_derived_set(self):
        locked, _note, _source, rep, _ = self._resolve(supplied="CCC")
        self.assertEqual(locked, {"AAA", "BBB", "CCC"})
        self.assertTrue(any("STALE --locked-teams" in w for w in rep.warnings))
        self.assertTrue(any("'AAA'" in w and "'BBB'" in w for w in rep.warnings))

    def test_a_supplied_list_may_still_add_a_team_the_clock_calls_open(self):
        locked, _note, _source, rep, _ = self._resolve(supplied="AAA,BBB,EEE")
        self.assertEqual(locked, {"AAA", "BBB", "EEE"})
        self.assertEqual(rep.warnings, [])

    def test_a_complete_supplied_list_is_not_reported_stale(self):
        _locked, _note, _source, rep, _ = self._resolve(supplied="AAA,BBB")
        self.assertEqual(rep.warnings, [])

    # -- end to end: tonight's rejection, reproduced -------------------------

    def test_a_player_introduced_from_a_since_locked_game_fails(self):
        """The 2026-07-29 rejection. The operator's list was passed while only
        the early games had started and never re-derived; by the time this file
        was written, EEE@FFF had locked too."""
        child = self._child_swapping_in_fff()
        result = run_verify("--entries", str(child), "--salary", str(self.salary),
                            "--parent", str(self.parent), "--lineups", str(self.feed),
                            "--locked-teams", "AAA,BBB,CCC,DDD", "--as-of", self.LATE)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("already-started game", result.stdout)
        self.assertIn("STALE --locked-teams", result.stdout)

    def test_the_same_file_passes_while_that_game_is_still_open(self):
        """The clock, not a blanket refusal, is what decides. Same file, same
        stale list, an hour earlier: the swap is legal and this must pass."""
        child = self._child_swapping_in_fff()
        result = run_verify("--entries", str(child), "--salary", str(self.salary),
                            "--parent", str(self.parent), "--lineups", str(self.feed),
                            "--locked-teams", "AAA,BBB,CCC,DDD", "--as-of", self.PREGAME)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("already-started game", result.stdout)

    def test_the_report_names_the_clock_and_the_source_it_read(self):
        result = run_verify("--entries", str(self.parent), "--salary", str(self.salary),
                            "--parent", str(self.parent), "--lineups", str(self.feed),
                            "--as-of", self.EARLY, "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        info = json.loads(result.stdout)["info"]
        self.assertEqual(info["locked_teams"], ["AAA", "BBB"])
        self.assertEqual(info["lock_as_of"], self.EARLY)
        self.assertIn("lineups feed", info["lock_source"])
        self.assertTrue(str(info["lineups_feed"]).endswith("lineups_feed.json"))

    def test_the_feed_is_auto_resolved_from_beside_the_salary_file(self):
        result = run_verify("--entries", str(self.parent), "--salary", str(self.salary),
                            "--as-of", self.EARLY, "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        info = json.loads(result.stdout)["info"]
        self.assertIn("lineups feed", info["lock_source"])
        self.assertIn("staged beside the salary file", info["feed_autoresolve"])

    def test_locked_teams_no_longer_documented_as_an_override_of_the_derivation(self):
        """The docstring is the contract an operator reads under deadline."""
        text = (REPO / "tools" / "verify_export.py").read_text(encoding="utf-8")
        self.assertIn("ADDS to the derived set, never shrinks it", text)
        self.assertNotIn("overrides the Game Info derivation", text)


class VerifyExportSlateTruthTests(unittest.TestCase):
    """R46 + R72(ii): the swap verifier re-derives slate truth from its inputs.

    R46's teeth are a live incident. On the 2026-08-03 1905_7g slate ARI had not
    posted at build time, so the pool filled from a 35-day-stale platoon
    projection (warn-and-ship per R27, which is not in question) and seated Tyler
    Locklear -- a bench player -- in two delivered entries. Real lineups posted
    before lock with Tim Tawa at 1B. workflow_valid, selection_certified,
    allocation_certified and preflight all passed, because preflight's
    confirmed-lineup check existed but its feed still said ARI was tbd, and
    verify_export had no such check at all. Ben caught it by eye.

    Two distinct fixes are pinned here: the check now exists in verify_export
    (imported from preflight, not reimplemented), and a team with no confirmed
    lineup is reported by name instead of being skipped in silence.

    R72(ii): the locked-game membership check lived inside check_parent_slots,
    which ran only when --parent was passed. The parent now resolves from the
    manifest's supersession chain, because this tool's own header says a check
    that runs only when the operator remembers a flag is a check that does not run.
    """

    AS_OF = "2026-07-25T22:30:00+00:00"     # before every game in the fixture

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.ids = write_three_game_salary(self.salary)
        self.lineup = [
            self.ids["AAA Aster"], self.ids["CCC Aster"],
            self.ids["AAA Boone"], self.ids["AAA Crane"], self.ids["AAA Dunne"],
            self.ids["AAA Ellis"], self.ids["AAA Frost"],
            self.ids["EEE Gable"], self.ids["EEE Hollis"], self.ids["EEE Ives"],
        ]
        self.entries = self.dir / "DKEntries.csv"
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup)])
        # AAA's posted nine holds every rostered AAA name EXCEPT Frost, who is
        # this fixture's Locklear: seated off a projection, benched in reality.
        self.aaa_posted = ["AAA Aster", "AAA Boone", "AAA Crane", "AAA Dunne",
                           "AAA Ellis", "AAA Gable", "AAA Hollis", "AAA Ives",
                           "AAA Jarrow"]

    def tearDown(self):
        self.tmp.cleanup()

    def _feed(self, confirmed, **kw) -> Path:
        return write_three_game_feed(self.dir / "lineups_feed.json",
                                     confirmed=confirmed, **kw)

    def _verify(self, *extra, feed: Path):
        return run_verify("--entries", str(self.entries), "--salary", str(self.salary),
                          "--lineups", str(feed), "--as-of", self.AS_OF, *extra)

    def test_a_seated_player_contradicting_a_confirmed_lineup_fails(self):
        result = self._verify(feed=self._feed({"AAA": self.aaa_posted}))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)
        self.assertIn("AAA Frost", result.stdout)

    def test_the_same_file_passes_once_the_posted_lineup_holds_him(self):
        posted = ["AAA Frost"] + self.aaa_posted[:8]
        result = self._verify(feed=self._feed({"AAA": posted}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_feed_lenient_downgrades_the_contradiction_to_a_warning(self):
        result = self._verify("--feed-lenient", feed=self._feed({"AAA": self.aaa_posted}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN", result.stdout)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_an_unconfirmed_team_is_named_rather_than_skipped_in_silence(self):
        """The 2026-08-03 blind spot itself. No team posted, so the check cleared
        nothing -- and said nothing. It stays SOFT: an unposted team pre-lock is
        normal and R27 ships on warn, so this reports rather than blocks."""
        result = self._verify(feed=self._feed({}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no confirmed lineup in this feed", result.stdout)
        for team, slots in (("AAA", 6), ("CCC", 1), ("EEE", 3)):
            self.assertIn(f"{team} ({slots} slot", result.stdout)
        payload = json.loads(self._verify("--json", feed=self._feed({})).stdout)
        self.assertEqual(payload["info"]["feed_unconfirmed_teams"],
                         {"AAA": 6, "CCC": 1, "EEE": 3})

    def test_a_confirmed_team_no_longer_appears_as_uncovered(self):
        payload = json.loads(self._verify(
            "--json", feed=self._feed({"AAA": ["AAA Frost"] + self.aaa_posted[:8]})
        ).stdout)
        self.assertNotIn("AAA", payload["info"]["feed_unconfirmed_teams"])
        self.assertEqual(payload["info"]["feed_absent"], [])

    # -- R46 round 2: the partial side, and naming the player ------------------
    #
    # 2026-08-12, slate 1840_3g. The operator paste held all nine DET slots but
    # the ninth had no DK salary row, so lineups_from_paste wrote
    # lineup_status 'partial'. Every DET slot then skipped this check, a bench
    # catcher (Eduardo Valencia, higher APPG and $1,100 cheaper than the posted
    # catcher) won six of eighteen entries on value, and all three gates plus
    # this preflight passed. The warning that covered him read "DET (32 slots)".
    # R46 had already made the blind spot loud; what it did not do was assemble
    # the finding, and a slot count is a pointer to an analysis nobody runs at
    # T-40. These pin the third case and the naming.

    def _partial_feed(self, names, **kw):
        return self._feed(None, partial={"AAA": list(names)}, **kw)

    def test_a_partial_side_is_cross_checked_instead_of_skipped(self):
        # AAA posted eight, none of them Frost. Frost is legal (one slot is still
        # unknown) but he is NAMED, with his exposure and the posted count.
        result = self._verify(feed=self._partial_feed(self.aaa_posted[:8]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("absent from a posted lineup", result.stdout)
        self.assertIn("AAA Frost (AAA) in 1 of 1", result.stdout)
        self.assertIn("AAA posted 8 of 9", result.stdout)

    def test_a_partial_side_is_no_longer_reported_as_never_cross_checked(self):
        payload = json.loads(self._verify(
            "--json", feed=self._partial_feed(self.aaa_posted[:8])).stdout)
        self.assertNotIn("AAA", payload["info"]["feed_unconfirmed_teams"])
        self.assertEqual(payload["info"]["feed_partial_teams"], {"AAA": 8})
        aaa = {k: v for k, v in payload["info"]["feed_projected_players"].items()
               if k.endswith("(AAA)")}
        self.assertEqual(aaa, {"AAA Frost (AAA)": 1})   # Aster is posted here

    def test_a_posted_name_on_a_partial_side_raises_nothing(self):
        # Every rostered AAA name is among the posted eight, so nothing is named
        # for AAA's hitters at all.
        posted = ["AAA Boone", "AAA Crane", "AAA Dunne", "AAA Ellis", "AAA Frost",
                  "AAA Gable", "AAA Hollis", "AAA Ives"]
        payload = json.loads(self._verify(
            "--json", feed=self._partial_feed(posted)).stdout)
        self.assertEqual(
            [k for k in payload["info"]["feed_projected_players"] if "AAA" in k],
            ["AAA Aster (AAA)"])          # the arm only, no declared probable

    def test_more_absent_hitters_than_unknown_slots_is_a_hard_fail(self):
        # AAA posted eight of nine, so exactly one slot is unknown; this entry
        # seats two AAA hitters who are not in it. Arithmetic, not judgment.
        posted = ["AAA Boone", "AAA Crane", "AAA Dunne", "AAA Jarrow",
                  "AAA Kemp", "AAA Lowry", "AAA Mabry", "AAA Nunn"]
        result = self._verify(feed=self._partial_feed(posted))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("more absent players than the posted lineup leaves unknown",
                      result.stdout)
        self.assertIn("2 AAA hitter(s)", result.stdout)
        self.assertIn("posted 8 of 9", result.stdout)

    def test_feed_lenient_downgrades_the_overdraw_to_a_warning(self):
        posted = ["AAA Boone", "AAA Crane", "AAA Dunne", "AAA Jarrow",
                  "AAA Kemp", "AAA Lowry", "AAA Mabry", "AAA Nunn"]
        result = self._verify("--feed-lenient", feed=self._partial_feed(posted))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN", result.stdout)
        self.assertIn("more absent players than the posted lineup leaves unknown",
                      result.stdout)

    def test_a_declared_probable_is_a_stated_fact_on_a_partial_side(self):
        # The side is partial, so its hitters are priors, but the arm it named is
        # not. A different arm contradicts the feed and fails.
        # aaa_posted[0] is the arm this fixture seats, so post the eight AFTER
        # him: the side names a different probable and Aster contradicts it.
        result = self._verify(feed=self._partial_feed(
            self.aaa_posted[1:9], probables={"AAA": "AAA Quill"}))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("is not AAA's declared probable pitcher", result.stdout)
        self.assertIn("AAA Aster", result.stdout)

    # -- R114 + R67: the two ways a legal ARM read as a contradiction ---------
    #
    # Both live, both the same mistake -- reading a posted BATTING lineup as
    # evidence about pitching.
    #
    # R114, 2026-08-12, slate 2210_2g, run 20260813T005233Z_1b5d3a4a. KC's nine
    # were confirmed and Daniel Lynch IV was the named probable; the build also
    # rostered Mason Black on an explicit declaration (viable_bulk_or_alt_sp,
    # the R104 vocabulary). All three certification gates passed and preflight
    # exited 2 twelve times on "Mason Black (KC) is not in KC's confirmed
    # lineup or probables", because declared_pitchers reached the optimizer and
    # the brief and stopped there. The only way through was --force, i.e. exit
    # 4 on a failure the operator knew was spurious.
    #
    # (The fragment that filed R114 described KC as running a bullpen game.
    # The feed on disk says otherwise -- lineup_status confirmed, probable
    # Daniel Lynch IV -- so the live case is the DECLARED case, not the
    # null-probable one. R67 is the null-probable case and it is separately
    # pinned below; the mechanism and the failure text R114 reported were
    # exactly right.)

    def _brief(self, declared, sha=None, name="build_brief.json") -> Path:
        path = self.dir / name
        path.write_text(json.dumps({
            "delivered_path": str(self.entries),
            "delivered_sha256": sha or _sha256(self.entries),
            "declared_pitchers": declared,
        }), encoding="utf-8")
        return path

    def _preflight(self, *extra):
        return run_preflight("--entries", str(self.entries),
                             "--salary", str(self.salary), *extra)

    # The two feeds below are a minimal pair: the same confirmed nine hitters,
    # differing only in whether the side named a probable. Every rostered AAA
    # HITTER is in that nine, so the only AAA name left to argue about is the
    # arm -- which is the whole subject here.
    AAA_NINE = [f"AAA {s}" for s in SURNAMES[1:]]

    def _confirmed_with_arm(self):
        """AAA confirmed, naming an arm that is NOT the one this fixture seats."""
        return self._feed({"AAA": self.AAA_NINE}, probables={"AAA": "AAA Quill"})

    def test_an_undeclared_arm_absent_from_a_confirmed_lineup_still_fails(self):
        """The control for everything below. Nothing here weakens R4."""
        result = self._preflight("--feed", str(self._confirmed_with_arm()))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)
        self.assertIn("AAA Aster", result.stdout)

    def test_a_declared_arm_is_acknowledged_rather_than_failed(self):
        self._brief({self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"})
        result = self._preflight("--feed", str(self._confirmed_with_arm()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FAIL", result.stdout)

    def test_the_acknowledgement_names_the_role_and_its_evidence_class(self):
        """Pinned by VALUE, not by key presence (R91). The whole point of the
        warning is the sentence the operator reads at T-5: which player, how
        many entries, under what declaration, on whose word."""
        self._brief({self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"})
        result = self._preflight("--feed", str(self._confirmed_with_arm()))
        self.assertIn(
            "1 rostered pitcher(s) absent from the posted lineup but DECLARED "
            "by the build, acknowledged rather than failed: AAA Aster (AAA) in "
            "1 of 1, declared viable_bulk_or_alt_sp. Evidence: "
            "operator_declared. A declaration is the build's own statement of "
            "the role, not confirmation from the feed", result.stdout)

    def test_the_declaration_is_read_from_the_sibling_brief_by_sha256(self):
        self._brief({self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"})
        payload = json.loads(self._preflight(
            "--feed", str(self._confirmed_with_arm()), "--json").stdout)
        self.assertEqual(payload["info"]["feed_declared_pitchers"],
                         {self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"})
        self.assertIn("build_brief.json",
                      payload["info"]["declared_pitchers_source"])
        self.assertEqual(payload["info"]["feed_acknowledged_pitchers"],
                         {"AAA Aster (AAA)": {"role": "viable_bulk_or_alt_sp",
                                              "entries": 1,
                                              "evidence": "operator_declared"}})

    def test_a_brief_describing_other_bytes_is_not_read(self):
        """outputs/2026-08-12/ held eight briefs for four deliveries, and the
        newest and the alphabetically first both belonged to a different slate
        with no declarations. Any resolution weaker than the hash reads the
        wrong slate's facts and this check goes quiet again."""
        self._brief({self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"},
                    sha="0" * 64)
        result = self._preflight("--feed", str(self._confirmed_with_arm()))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_briefs_that_disagree_fall_back_to_what_they_all_carry(self):
        """Every id dropped restores a hard failure and every id kept removes
        one, so a contradictory record resolves toward the closed gate."""
        self._brief({self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"})
        self._brief({}, name="build_brief_second.json")
        result = self._preflight("--feed", str(self._confirmed_with_arm()))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("2 briefs record these bytes and they disagree on "
                      "declared_pitchers", result.stdout)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_declare_pitcher_states_the_same_fact_with_no_run_to_read(self):
        result = self._preflight(
            "--feed", str(self._confirmed_with_arm()),
            "--declare-pitcher", f"{self.ids['AAA Aster']}=declared_probable_sp")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("declared declared_probable_sp", result.stdout)

    def test_a_declaration_cannot_clear_a_benched_hitter(self):
        """--declare-pitcher must not become an off switch for R4. A
        declaration is a statement about an arm; pointed at a hitter it is
        reported and NOT applied."""
        result = self._preflight(
            "--feed", str(self._feed({"AAA": self.aaa_posted})),
            "--declare-pitcher", f"{self.ids['AAA Frost']}=viable_bulk_or_alt_sp")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("1 declared id(s) are not pitcher-position rows, so the "
                      "declaration was NOT applied and the posted-lineup check "
                      "ran normally: AAA Frost (AAA) in 1 of 1, declared "
                      "viable_bulk_or_alt_sp. A declaration names an arm; it "
                      "cannot clear a hitter", result.stdout)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_a_malformed_declaration_is_a_usage_error_not_a_crash(self):
        for bad in ("=viable_bulk_or_alt_sp", "notanid", ""):
            with self.subTest(bad=bad):
                result = self._preflight("--declare-pitcher", bad)
                self.assertEqual(result.returncode, 3,
                                 result.stdout + result.stderr)
                self.assertIn("--declare-pitcher wants a DK player ID",
                              result.stderr)

    def test_a_bare_id_means_what_it_means_to_build_slate(self):
        """Same flag name, same grammar, same default. The operator who
        declared the arm to the build types the same thing here."""
        result = self._preflight("--feed", str(self._confirmed_with_arm()),
                                 "--declare-pitcher", self.ids["AAA Aster"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("declared declared_probable_sp", result.stdout)

    def test_verify_export_reads_the_declaration_too(self):
        """R52's failure class: two checkers, one file, different answers. The
        swap verifier inherits the build's declared arms or it contradicts
        preflight on the delivery preflight just cleared."""
        self._brief({self.ids["AAA Aster"]: "viable_bulk_or_alt_sp"})
        feed = self._confirmed_with_arm()
        self.assertEqual(self._preflight("--feed", str(feed)).returncode, 0)
        result = self._verify(feed=feed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("declared viable_bulk_or_alt_sp", result.stdout)

    # -- R67: a bullpen game posts nine bats and no starter -------------------

    def _bats_only_feed(self):
        """AAA confirmed with all nine HITTERS and no probable: the arm this
        fixture seats is absent from a posting that never claimed to name one."""
        return self._feed({"AAA": self.AAA_NINE})

    def test_a_confirmed_lineup_naming_no_arm_cannot_contradict_one(self):
        result = self._preflight("--feed", str(self._bats_only_feed()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "1 rostered pitcher(s) on a team whose lineup is confirmed but "
            "names no probable, so the posting evidences bats only: AAA Aster "
            "(AAA) in 1 of 1. Evidence: posted_lineup, hitters only. A bullpen "
            "game posts nine bats and no starter, and this check cannot "
            "contradict an arm it has no fact about", result.stdout)

    def test_a_bats_only_team_still_binds_every_one_of_its_hitters(self):
        """R67 must not become a second way to skip R4. AAA posts nine with no
        probable; Frost is not among them and he is a hitter, so he fails
        exactly as he did before."""
        result = self._preflight("--feed", str(self._feed({"AAA": self.aaa_posted})))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("AAA Frost", result.stdout)
        self.assertIn("absent from a confirmed posted lineup", result.stdout)

    def test_a_team_that_did_name_an_arm_still_fails_a_different_one(self):
        """The bats-only path keys off the missing probable, not off the
        position, so a confirmed side WITH an arm is untouched by R67."""
        result = self._preflight("--feed", str(self._confirmed_with_arm()))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("AAA Aster", result.stdout)
        payload = json.loads(self._preflight(
            "--feed", str(self._confirmed_with_arm()), "--json").stdout)
        self.assertEqual(payload["info"]["feed_bats_only_arms"], {})

    # -- R72(ii): the parent stops being opt-in -------------------------------

    def _manifest_chain(self, parent_path: Path, child_path: Path) -> Path:
        """A two-record manifest where the parent names the child as successor,
        exactly as upload_manifest writes it on a late swap."""
        manifest = self.dir / "upload_manifest.json"
        manifest.write_text(json.dumps({"version": "1.1", "date": "2026-07-25",
            "deliveries": [
                {"delivered_file": str(parent_path), "sha256": _sha256(parent_path),
                 "contest_type": "classic", "entries": 1, "status": "superseded",
                 "certification": "certified",
                 "superseded_by": str(child_path)},
                {"delivered_file": str(child_path), "sha256": _sha256(child_path),
                 "contest_type": "classic", "entries": 1, "status": "upload_ready",
                 "certification": "certified"},
            ]}), encoding="utf-8")
        return manifest

    def test_the_parent_resolves_from_the_manifest_supersession_chain(self):
        parent = self.dir / "parent.csv"
        write_entries(parent, CLASSIC_HEADER, [classic_entry("900", "5", self.lineup)])
        manifest = self._manifest_chain(parent, self.entries)
        payload = json.loads(run_verify(
            "--entries", str(self.entries), "--salary", str(self.salary),
            "--manifest", str(manifest), "--as-of", self.AS_OF, "--json").stdout)
        self.assertEqual(payload["info"]["parent_file"], str(parent))
        self.assertIn("supersession chain", payload["info"]["parent_source"])

    def test_a_player_from_a_locked_game_is_caught_with_no_parent_flag(self):
        """The R72(ii) gap: this file introduces FFF Ives after FFF@EEE locked.
        With the parent reachable only via --parent, nothing checked it."""
        parent = self.dir / "parent.csv"
        write_entries(parent, CLASSIC_HEADER, [classic_entry("900", "5", self.lineup)])
        swapped = list(self.lineup)
        swapped[9] = self.ids["FFF Ives"]
        write_entries(self.entries, CLASSIC_HEADER, [classic_entry("900", "5", swapped)])
        manifest = self._manifest_chain(parent, self.entries)
        result = run_verify("--entries", str(self.entries), "--salary", str(self.salary),
                            "--manifest", str(manifest),
                            "--as-of", "2026-07-25T23:45:00+00:00", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertTrue(any("already-started game" in f for f in payload["failures"]),
                        payload["failures"])

    def test_the_manifest_is_found_next_to_the_entries_file(self):
        parent = self.dir / "parent.csv"
        write_entries(parent, CLASSIC_HEADER, [classic_entry("900", "5", self.lineup)])
        self._manifest_chain(parent, self.entries)
        payload = json.loads(run_verify(
            "--entries", str(self.entries), "--salary", str(self.salary),
            "--as-of", self.AS_OF, "--json").stdout)
        self.assertIn("next to the entries file", payload["info"]["manifest_source"])
        self.assertEqual(payload["info"]["parent_file"], str(parent))


class BothFileCheckersShareOneExitContractTests(unittest.TestCase):
    """R52: the two upload gates disagreed on the only contract a caller sees.

    verify_export returned 2 only ``if rep.failures and not args.force``, then
    fell through to ``return 0`` -- so a forced run with hard failures present
    reported clean, against its own module header and against R2's whole
    rationale on preflight. The late-swap verification path reads that code.
    This pins the two tools EQUAL rather than pinning verify_export to 4 on its
    own, because the defect was a divergence: pin the pair and neither tool can
    drift without the other.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        lineup = write_classic_salary(self.salary)
        self.clean = self.dir / "clean.csv"
        write_entries(self.clean, CLASSIC_HEADER, [classic_entry("900", "5", lineup)])
        # One hard failure both tools implement identically: the same person in
        # two slots. It comes from check_legality, which verify_export imports.
        broken = list(lineup)
        broken[1] = broken[0]
        self.broken = self.dir / "broken.csv"
        write_entries(self.broken, CLASSIC_HEADER, [classic_entry("900", "5", broken)])

    def tearDown(self):
        self.tmp.cleanup()

    NEEDLE = "the same person occupies two slots"

    def _both(self, entries: Path, *extra) -> tuple[int, int]:
        """Run both tools on one file. Asserts each tool reached the SAME hard
        failure, so an equal pair of exit codes cannot come from two tools
        failing (or passing) for unrelated reasons."""
        common = ("--entries", str(entries), "--salary", str(self.salary))
        pre = run_preflight(*common, "--no-manifest", *extra)
        ver = run_verify(*common, *extra)
        for tool, result in (("preflight", pre), ("verify_export", ver)):
            if entries == self.broken:
                self.assertIn(self.NEEDLE, result.stdout, f"{tool}: {result.stdout}")
            else:
                self.assertNotIn(self.NEEDLE, result.stdout, f"{tool}: {result.stdout}")
        return pre.returncode, ver.returncode

    def test_forced_failures_exit_4_in_both_tools(self):
        pre, ver = self._both(self.broken, "--force")
        self.assertEqual((pre, ver), (4, 4),
                         f"preflight={pre} verify_export={ver}; --force must never "
                         f"return 0, the one signal automation trusts")

    def test_unforced_failures_exit_2_in_both_tools(self):
        pre, ver = self._both(self.broken)
        self.assertEqual((pre, ver), (2, 2))

    def test_a_clean_file_exits_0_in_both_tools_forced_or_not(self):
        """--force must not invent a failure either: 0 still means clean."""
        self.assertEqual(self._both(self.clean), (0, 0))
        self.assertEqual(self._both(self.clean, "--force"), (0, 0))

    def test_one_shared_implementation_of_the_exit_contract(self):
        """The fix is a shared function, not a copied branch. Two copies of one
        rule is this project's named no-op class: they diverge and the weaker one
        reports success, which is exactly how R52 happened."""
        import preflight_upload
        import verify_export

        self.assertIs(verify_export.verdict_exit_code,
                      preflight_upload.verdict_exit_code)
        for failures, force, expected in (([], False, 0), ([], True, 0),
                                          (["x"], False, 2), (["x"], True, 4)):
            self.assertEqual(
                preflight_upload.verdict_exit_code(failures, force), expected)
        text = (REPO / "tools" / "verify_export.py").read_text(encoding="utf-8")
        self.assertNotIn("if rep.failures and not args.force", text)
        self.assertNotIn("exit 0\"", text)


class UploadReadyIsReservedTests(unittest.TestCase):
    """R34/R35: the promotion label and the provenance gate, both of which lied.

    Teeth, and this one already happened: two Showdown records in
    outputs/2026-07-29/upload_manifest.json read `status: upload_ready` beside
    `certification: review_grade`, which is the exact label CLAUDE.md reserves
    for a run where all three certification gates passed. A third read
    `status: delivered`, which is not in the closed status set at all and so read
    as CURRENT everywhere that only filters out 'superseded'.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.salary = self.dir / "DKSalaries.csv"
        self.lineup = write_classic_salary(self.salary)
        self.entries = self.dir / "DKEntries.csv"
        write_entries(self.entries, CLASSIC_HEADER,
                      [classic_entry("900", "5", self.lineup)])
        self.manifest = self.dir / "upload_manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_manifest(self, status="candidate", certification="certified"):
        import hashlib
        digest = hashlib.sha256(self.entries.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps({
            "version": "1", "date": "2026-07-25", "deliveries": [{
                "delivered_file": str(self.entries), "sha256": digest,
                "contest_type": "classic", "contest_ids": ["5"], "entries": 1,
                "status": status, "certification": certification,
            }]}), encoding="utf-8")

    def _run(self, *extra):
        return run_preflight("--entries", str(self.entries), "--salary",
                             str(self.salary), "--manifest", str(self.manifest),
                             *extra)

    def test_a_certified_record_still_reaches_upload_ready(self):
        self._write_manifest(certification="certified")
        payload = json.loads(self._run("--json").stdout)
        self.assertEqual(payload["verdict"], "upload_ready")

    def test_a_review_grade_record_cannot_reach_upload_ready(self):
        self._write_manifest(certification="review_grade")
        result = self._run("--json")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0,
                         "a clean review-grade file is still a usable artifact")
        self.assertEqual(payload["verdict"], "review_ready")
        self.assertNotEqual(payload["verdict"], "upload_ready")
        self.assertIn("reserved", payload["verdict_note"])

    def test_an_unknown_status_in_the_record_is_a_hard_failure(self):
        self._write_manifest(status="delivered")
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("not one of", result.stdout)

    def test_record_delivery_refuses_a_status_outside_the_closed_set(self):
        from mlb_engine.entries.upload_manifest import record_delivery
        with self.assertRaises(ValueError) as caught:
            record_delivery(date="2026-07-25", delivered_file=self.entries,
                            contest_type="showdown", slate_tag="t",
                            status="delivered", certification="review_grade")
        self.assertIn("delivered", str(caught.exception))

    def test_the_two_status_vocabularies_are_pinned_in_sync(self):
        """preflight imports nothing from the engine by contract, so the set is
        mirrored. A silently diverged copy is worse than an import."""
        from mlb_engine.entries.upload_manifest import STATUS_VALUES as engine_set
        from tools.preflight_upload import STATUS_VALUES as tool_set
        self.assertEqual(tuple(engine_set), tuple(tool_set))

    # ---- R105 ---------------------------------------------------------- #
    def test_a_review_grade_delivery_records_candidate_not_the_verdict(self):
        """R105. The verdict and the manifest status are separate facts.

        R34 grew the VERDICT vocabulary a fifth value, `review_ready`, and
        `stamp_manifest_status` wrote the verdict straight into `status` -- so
        every clean Showdown delivery stamped a status outside the closed set and
        the next read of that record hard-failed. Reproduced on both fragments'
        builds (2026-08-05 STL@NYY, 2026-08-06 SD@ARI); every per-entry check
        passed on both files.

        Teeth: restoring `target["status"] = status` fails the status assertion
        AND the round-trip test below, which is the one that matters, because the
        first read after the stamp is what the operator actually does at T-5.
        """
        self._write_manifest(certification="review_grade")
        payload = json.loads(self._run("--json").stdout)
        record = json.loads(self.manifest.read_text())["deliveries"][0]
        self.assertEqual(payload["verdict"], "review_ready")
        self.assertEqual(record["status"], "candidate")
        # The verdict is not lost. It is recorded where a verdict belongs.
        self.assertEqual(record["preflight"]["verdict"], "review_ready")

    def test_a_stamped_review_grade_record_reads_clean_on_the_next_pass(self):
        """R105's actual consequence: supersession blindness, and a red FAIL on
        every clean Showdown export that trains the operator to ignore FAILs."""
        self._write_manifest(certification="review_grade")
        self.assertEqual(self._run().returncode, 0)
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertNotIn("not one of", second.stdout)

    def test_every_verdict_maps_into_the_closed_status_set(self):
        """The pin that stops the two writers drifting again. Any verdict this
        tool can emit must map to a status the manifest accepts, and the map's
        unknown-verdict fallback must be inside the set too."""
        from tools.preflight_upload import STATUS_VALUES, status_for_verdict
        for verdict in ("upload_ready", "review_ready", "blocked",
                        "acknowledged", "a_verdict_nobody_has_written_yet"):
            self.assertIn(status_for_verdict(verdict), STATUS_VALUES, verdict)
        # A review-grade file is a CANDIDATE. Preflight checks bytes, not
        # certification, and must not promote it past that.
        self.assertEqual(status_for_verdict("review_ready"), "candidate")
        self.assertEqual(status_for_verdict("upload_ready"), "upload_ready")

    def test_an_out_of_vocabulary_status_exits_2_on_both_checkers(self):
        """R105. The two BUILD fragments disagreed on the exit code (08-05 said
        2, 08-06 said 3). Measured 2026-08-10: it is 2 on both tools. Exit 3 in
        verify_export is the setup path -- an unreadable file or no resolvable
        salary -- which is a different failure reached before any check runs."""
        for tool in ("preflight_upload.py", "verify_export.py"):
            # Rewritten per tool: preflight STAMPS the record, so a single write
            # would leave the second tool reading a status the first repaired.
            self._write_manifest(status="review_ready",
                                 certification="review_grade")
            result = subprocess.run(
                [sys.executable, str(REPO / "tools" / tool),
                 "--entries", str(self.entries), "--salary", str(self.salary),
                 "--manifest", str(self.manifest)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, f"{tool}: {result.stdout}")
            self.assertIn("not one of", result.stdout, tool)

    def test_a_corrupt_manifest_blocks_a_delivered_file(self):
        """R35: an ABSENT manifest already hard-failed a delivered file, so
        warning on a CORRUPT one had the provenance gate backwards -- the weaker
        evidence state passed."""
        from tools.preflight_upload import Report, check_manifest, load_entries
        self.manifest.write_text("{not json", encoding="utf-8")
        _, _, entries, _, _ = load_entries(self.entries)
        rep = Report()
        check_manifest(self.entries, entries, self.manifest, rep, delivered=True)
        self.assertTrue(any("unreadable" in f for f in rep.failures))
        self.assertEqual(rep.warnings, [])

    def test_a_corrupt_manifest_only_warns_for_a_file_outside_outputs(self):
        """A scratch file being checked ad hoc is not a provenance claim."""
        from tools.preflight_upload import Report, check_manifest, load_entries
        self.manifest.write_text("{not json", encoding="utf-8")
        _, _, entries, _, _ = load_entries(self.entries)
        rep = Report()
        check_manifest(self.entries, entries, self.manifest, rep, delivered=False)
        self.assertEqual(rep.failures, [])
        self.assertTrue(any("unreadable" in w for w in rep.warnings))


class ArchetypeRowsResolveEndToEndTests(unittest.TestCase):
    """R29(6): every LIVE archetype row must resolve to a real shape and profile.

    Teeth: R1(a) fixed _posture_to_shape("mme") returning the payout token
    mme_top_heavy instead of the contest shape mme_gpp. The two vocabularies look
    alike and sit in adjacent columns, so the confusion is one careless row away
    from returning. Rows are curated by hand, mid-slate, against a DK lobby, and
    the failure would be a contest routed on a shape that is not in the closed
    set. This walks the file on disk, so a row added after this test was written
    is covered by it.
    """

    def setUp(self):
        from mlb_engine.contest_shapes import (
            CONTEST_SHAPE_SET, OBJECTIVE_CLASS_BY_SHAPE,
            objective_class_for_payout_token,
        )
        from mlb_engine.pipeline.execution_pipeline import (
            STRATEGY_DEFAULTS, normalize_posture, resolve_contest_shape,
        )
        self.shapes = CONTEST_SHAPE_SET
        self.objective_by_shape = OBJECTIVE_CLASS_BY_SHAPE
        self.objective_for_token = objective_class_for_payout_token
        self.strategy = STRATEGY_DEFAULTS
        self.normalize = normalize_posture
        self.resolve = resolve_contest_shape
        path = REPO / "data" / "reference" / "dk_contest_archetypes.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            self.rows = list(csv.DictReader(handle))

    def _int(self, value):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def test_the_file_is_readable_and_not_empty(self):
        self.assertGreater(len(self.rows), 6)
        self.assertIn("payout_shape_default", self.rows[0])

    def test_the_token_shape_name_collision_is_exactly_the_one_known_case(self):
        """The R1(a) confusion is possible because the two vocabularies overlap:
        'portfolio_gpp' is both a payout token and a contest shape. That one
        overlap is longstanding and is not a defect on its own. It is pinned so a
        NEW collision has to be looked at rather than inherited, because a token
        that reads like a shape is what let a shape resolver return a token."""
        collisions = {str(r["payout_shape_default"]).strip() for r in self.rows
                      if str(r["payout_shape_default"]).strip() in self.shapes}
        self.assertEqual(
            collisions, {"portfolio_gpp", "single_entry_gpp"},
            "a payout token that is also a contest-shape name is the ambiguity "
            "R1(a) came out of; if this set grew, decide deliberately rather "
            "than widening the pin")

    def test_every_payout_token_is_one_the_engine_recognises(self):
        for row in self.rows:
            token = str(row["payout_shape_default"]).strip()
            with self.subTest(pattern=row["pattern"], token=token):
                self.assertIsNotNone(
                    self.objective_for_token(token),
                    f"{token!r} implies no objective, so a curated "
                    f"objective_class cannot be cross-checked against it")

    def test_every_row_resolves_to_a_posture_a_profile_and_a_real_shape(self):
        from mlb_engine.optimize.optimizer_v3 import resolve_contest_shape_profile
        for row in self.rows:
            inferred = {
                "inferred_type": row["inferred_type"],
                "payout_shape_default": row["payout_shape_default"],
                "inferred_max_entries": self._int(row["inferred_max_entries"]),
                "ticket_count": self._int(row.get("ticket_count")),
            }
            posture = self.normalize(inferred["inferred_type"],
                                     inferred["payout_shape_default"],
                                     inferred["inferred_max_entries"])
            shape = self.resolve(posture, inferred)
            with self.subTest(pattern=row["pattern"]):
                self.assertIn(posture, self.strategy)
                self.assertIn(shape, self.shapes)
                profile = resolve_contest_shape_profile(
                    mode="gpp", requested_n=20, contest_shape=shape)
                self.assertEqual(profile["contest_shape"], shape)
                self.assertEqual(profile["mode_family"],
                                 self.objective_by_shape[shape])

    def test_a_curated_objective_class_agrees_with_its_payout_token(self):
        for row in self.rows:
            curated = str(row.get("objective_class") or "").strip()
            if not curated:
                continue
            implied = self.objective_for_token(row["payout_shape_default"])
            with self.subTest(pattern=row["pattern"]):
                self.assertEqual(curated, implied)

    def test_payout_breadth_is_a_fraction_when_present(self):
        for row in self.rows:
            raw = str(row.get("payout_breadth") or "").strip()
            if not raw:
                continue
            with self.subTest(pattern=row["pattern"]):
                breadth = float(raw)
                self.assertGreater(breadth, 0.0)
                self.assertLessEqual(breadth, 1.0)

    def _require_mini_max(self):
        """Skip when the mini-MAX row is not in the CSV.

        The row was added by an ARCHIVE session whose commit died mid-write, so
        it is live on disk and absent from HEAD. CLAUDE.md makes a failing suite
        a live-slate block, and a committed test that fails on a clean checkout
        would turn another session's unfinished write into a build stoppage. The
        assertions below are worth having the moment the row lands, so they skip
        rather than being deleted or being pinned to a file this commit does not
        own. The generic rows-resolve tests above cover the row whenever present.
        """
        if not any(str(r["pattern"]).strip() == "mini-MAX" for r in self.rows):
            self.skipTest("mini-MAX row not present in dk_contest_archetypes.csv "
                          "(ARCHIVE's uncommitted write); the generic row tests "
                          "still cover every row that IS present")

    def test_the_mini_max_row_routes_a_real_dk_contest_name(self):
        """Ben entered these on 2026-07-29, so the live name is the test case."""
        self._require_mini_max()
        from mlb_engine.entries.dk_entries_manager import (
            infer_contest_archetype, load_archetypes,
        )
        archetypes = load_archetypes(None)
        inferred = infer_contest_archetype(
            "MLB $15K mini-MAX [150 Entry Max]", 15.0, archetypes)
        self.assertEqual(inferred["matched_pattern"], "mini-MAX")
        self.assertEqual(inferred["payout_shape_default"], "mme_top_heavy")
        posture = self.normalize(inferred["inferred_type"],
                                 inferred["payout_shape_default"],
                                 inferred["inferred_max_entries"])
        self.assertEqual(posture, "mme")
        self.assertEqual(self.resolve(posture, inferred), "mme_gpp")

    def test_mini_max_does_not_shadow_the_150_max_family(self):
        """Two patterns, disjoint names, and the same destination either way, so
        neither row can silently take the other's contests."""
        self._require_mini_max()
        from mlb_engine.entries.dk_entries_manager import (
            infer_contest_archetype, load_archetypes,
        )
        archetypes = load_archetypes(None)
        hyphenated = infer_contest_archetype(
            "MLB $0.25 Slugger [150-Max]", 0.25, archetypes)
        self.assertEqual(hyphenated["matched_pattern"], "150-Max")
        self.assertNotIn("mini-MAX", hyphenated["competing_patterns"])
        for name, fee in (("MLB $15K mini-MAX [150 Entry Max]", 15.0),
                          ("MLB $0.25 Slugger [150-Max]", 0.25)):
            inferred = infer_contest_archetype(name, fee, archetypes)
            posture = self.normalize(inferred["inferred_type"],
                                     inferred["payout_shape_default"],
                                     inferred["inferred_max_entries"])
            self.assertEqual(self.resolve(posture, inferred), "mme_gpp", name)


class R96UnrecordedDeliveryTests(unittest.TestCase):
    """R96: a delivery file has a manifest row or it has a self-labelling name.

    One test per path found in step 1's enumeration, not one for the class. The
    six paths differ in HOW they reach the state -- a swallowed record exception,
    an early return between the write and the record, no record call at all, a
    rename that orphans a row -- and a single test over the shared helper would
    pass while any individual caller still wrote its file under an uploadable name.
    That is exactly the "makes the remaining path look closed" failure the entry
    warned about, so the callers are pinned one at a time.

    P1 mirror_to_outputs, P2 late_swap refused promotion, P3 late_swap record
    raises, P4 Showdown record raises, P5 build_showdown_theses (deleted), P6
    preserve_prior_slate rename.
    """

    def setUp(self):
        from mlb_engine.entries import upload_manifest as um
        self.um = um
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._original_root = um.REPO_ROOT
        um.REPO_ROOT = self.root
        self.date = "2026-06-03"
        self.outputs = self.root / "outputs" / self.date
        self.outputs.mkdir(parents=True)
        self.addCleanup(self._restore)

    def _restore(self):
        self.um.REPO_ROOT = self._original_root
        self.tmp.cleanup()

    def _rows(self):
        return self.um.read_manifest(self.date).get("deliveries", [])

    # ---- the shared front door -------------------------------------------

    def test_deliver_promotes_the_name_only_after_the_row_exists(self):
        dest = self.outputs / "DKEntries_1605_4g.csv"
        seen = {}

        def write(provisional):
            seen["path"] = provisional
            # The bytes exist under the provisional name and the row does not
            # exist yet. This is the window every one of the six paths died in.
            self.assertTrue(provisional.name.startswith("DO_NOT_UPLOAD_"))
            self.assertEqual(self._rows(), [])
            provisional.write_text("payload", encoding="utf-8")

        out = self.um.deliver(date=self.date, dest=dest, write=write,
                              contest_type="classic", slate_tag="1605_4g")
        self.assertTrue(out["recorded"], out["error"])
        self.assertEqual(out["path"], str(dest))
        self.assertTrue(dest.is_file())
        self.assertFalse(seen["path"].exists(), "the provisional name is consumed")
        self.assertEqual([r["delivered_file"] for r in self._rows()],
                         [self.um.repo_relative(dest)])

    def test_a_raising_recorder_leaves_the_file_self_labelled(self):
        dest = self.outputs / "DKEntries_1605_4g.csv"
        out = self.um.deliver(
            date=self.date, dest=dest,
            write=lambda p: p.write_text("payload", encoding="utf-8"),
            contest_type="classic", slate_tag="1605_4g",
            status="not-a-real-status")  # _valid_status raises on this
        self.assertFalse(out["recorded"])
        self.assertIn("MANIFEST NOT RECORDED", out["error"])
        self.assertFalse(dest.exists(),
                         "an unrecorded delivery must never wear the upload name")
        self.assertTrue(self.um.unrecorded_name(dest).is_file())
        self.assertEqual(self._rows(), [])

    def test_the_row_names_the_upload_path_and_hashes_the_provisional_bytes(self):
        dest = self.outputs / "DKEntries_1605_4g.csv"
        out = self.um.deliver(
            date=self.date, dest=dest,
            write=lambda p: p.write_text("payload", encoding="utf-8"),
            contest_type="classic", slate_tag="1605_4g")
        self.assertEqual(out["record"]["delivered_file"],
                         self.um.repo_relative(dest))
        self.assertEqual(out["record"]["sha256"], self.um.sha256_file(dest))
        self.assertTrue(self.um.verify_manifest(self.date)["passed"],
                        "the row must not name a file that does not exist")

    def test_a_writer_that_produces_nothing_is_reported_not_recorded(self):
        dest = self.outputs / "DKEntries_1605_4g.csv"
        out = self.um.deliver(date=self.date, dest=dest, write=lambda p: None,
                              contest_type="classic", slate_tag="1605_4g")
        self.assertFalse(out["recorded"])
        self.assertIn("nothing was delivered", out["error"])
        self.assertEqual(self._rows(), [])

    # ---- step 4: the salary file --------------------------------------------

    def test_a_recorded_delivery_stages_the_salary_file(self):
        salary = self.root / "elsewhere" / "DKSalaries.csv"
        salary.parent.mkdir(parents=True)
        salary.write_text("Name,Salary\nA,5000\n", encoding="utf-8")
        dest = self.outputs / "DKEntries_1605_4g.csv"
        out = self.um.deliver(
            date=self.date, dest=dest,
            write=lambda p: p.write_text("payload", encoding="utf-8"),
            salary_csv=salary, contest_type="classic", slate_tag="1605_4g")
        staged = self.root / "data" / "slates" / self.date / "DKSalaries_1605_4g.csv"
        self.assertEqual(out["staged_salary"], str(staged))
        self.assertEqual(staged.read_bytes(), salary.read_bytes())
        # field_miner globs data/slates/<date>/DKSalaries*.csv; the tag is what
        # keeps one draftgroup from answering for another on the same date.
        self.assertTrue(list(staged.parent.glob("DKSalaries*.csv")))

    def test_staging_is_tagged_so_two_draftgroups_do_not_collide(self):
        for tag, body in (("1605_4g", "early"), ("1910_6g", "late")):
            salary = self.root / f"s_{tag}.csv"
            salary.write_text(body, encoding="utf-8")
            self.um.stage_salary_for_delivery(self.date, salary, tag)
        staged = sorted(p.name for p in
                        (self.root / "data" / "slates" / self.date).glob("DKSalaries*.csv"))
        self.assertEqual(staged, ["DKSalaries_1605_4g.csv", "DKSalaries_1910_6g.csv"])

    def test_staging_never_raises_on_a_missing_salary_file(self):
        self.assertIsNone(
            self.um.stage_salary_for_delivery(self.date, self.root / "nope.csv", "t"))

    # ---- step 3: the reverse check ------------------------------------------

    def test_the_reverse_check_names_a_file_with_no_row(self):
        (self.outputs / "upload_manifest.json").write_text(
            json.dumps({"version": "1.1", "date": self.date, "deliveries": []}),
            encoding="utf-8")
        orphan = self.outputs / "DKEntries_1910_4g.csv"
        orphan.write_text("payload", encoding="utf-8")
        self.assertEqual(self.um.unrecorded_deliveries(self.date),
                         [self.um.repo_relative(orphan)])

    def test_the_reverse_check_ignores_a_self_labelled_file(self):
        (self.outputs / "upload_manifest.json").write_text(
            json.dumps({"version": "1.1", "date": self.date, "deliveries": []}),
            encoding="utf-8")
        (self.outputs / "DO_NOT_UPLOAD_DKEntries_1910_4g.csv").write_text(
            "payload", encoding="utf-8")
        self.assertEqual(self.um.unrecorded_deliveries(self.date), [],
                         "a file that says what it is needs no second report")

    def test_the_reverse_check_is_silent_on_a_date_with_no_manifest(self):
        (self.outputs / "DKEntries_1910_4g.csv").write_text("payload", encoding="utf-8")
        self.assertEqual(self.um.unrecorded_deliveries(self.date), [],
                         "the manifest did not exist before 2026-07-25; eleven such "
                         "dates on disk would make this report permanently noisy")

    def test_a_recorded_delivery_is_not_reported(self):
        dest = self.outputs / "DKEntries_1605_4g.csv"
        self.um.deliver(date=self.date, dest=dest,
                        write=lambda p: p.write_text("payload", encoding="utf-8"),
                        contest_type="classic", slate_tag="1605_4g")
        self.assertEqual(self.um.unrecorded_deliveries(self.date), [])

    # ---- P6: the rename follows the row -------------------------------------

    def test_p6_a_rename_carries_the_manifest_row_with_it(self):
        dest = self.outputs / "DKEntries.csv"
        self.um.deliver(date=self.date, dest=dest,
                        write=lambda p: p.write_text("payload", encoding="utf-8"),
                        contest_type="classic", slate_tag="1605_4g")
        before = self._rows()[0]["sha256"]
        moved = self.outputs / "DKEntries_1605_4g.csv"
        dest.rename(moved)
        self.assertTrue(self.um.rename_recorded_delivery(self.date, dest, moved))
        row = self._rows()[0]
        self.assertEqual(row["delivered_file"], self.um.repo_relative(moved))
        self.assertEqual(row["renamed_from"], self.um.repo_relative(dest))
        self.assertEqual(row["sha256"], before,
                         "a rename does not change bytes; rehashing here would "
                         "mask a file that changed underneath")
        self.assertEqual(self.um.unrecorded_deliveries(self.date), [],
                         "the renamed file must not read as orphaned")

    def test_p6_a_rename_of_an_unrecorded_file_moves_nothing(self):
        self.assertFalse(self.um.rename_recorded_delivery(
            self.date, self.outputs / "a.csv", self.outputs / "b.csv"))


class R96PerCallerTests(unittest.TestCase):
    """The per-path half: each production caller, pinned at its own call site.

    These read source rather than executing a build, deliberately and with the
    limitation stated: R79(b) already records that a source-text pin un-pins
    itself under a helper-extraction refactor. The behavioural half lives in
    R96UnrecordedDeliveryTests above, which exercises the shared door these
    callers route through; what these add is that each caller actually routes
    through it, which is the part the shared tests cannot see.
    """

    def _text(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    def test_p1_the_engine_mirror_delivers_through_the_recorded_door(self):
        text = self._text("mlb_engine/pipeline/execution_pipeline.py")
        self.assertIn("_deliver_mirror(", text)
        self.assertIn("from mlb_engine.entries.upload_manifest import deliver", text)
        self.assertNotIn("dest.write_bytes(source.read_bytes())", text,
                         "the mirror must not write the upload name directly")

    def test_p2_late_swap_writes_provisionally_before_it_promotes(self):
        text = self._text("tools/late_swap.py")
        provisional = text.index("os.replace(tmp, provisional)")
        promote = text.index("promote_deferred_run(result)")
        record = text.index("record = record_delivery(")
        rename = text.index("os.replace(provisional, dest)")
        # R29(2)'s invariant survives: something is in outputs/ before promotion.
        self.assertLess(provisional, promote,
                        "the file must exist before the pointer moves, or a "
                        "refusal leaves a run nothing was mirrored from")
        # R96's addition: the uploadable NAME appears only after the row.
        self.assertLess(record, rename,
                        "the name is promoted only once a row names it")
        self.assertLess(promote, record)

    def test_p3_late_swap_leaves_the_provisional_name_when_recording_fails(self):
        text = self._text("tools/late_swap.py")
        self.assertTrue("MANIFEST NOT RECORDED for" in text,
                        "the raising-recorder branch must still say so out loud")
        # The promotion sits INSIDE the try, so a raising recorder skips it.
        head = text[text.index("record = record_delivery("):]
        body = head[:head.index("except Exception as exc:")]
        self.assertIn("os.replace(provisional, dest)", body,
                      "promotion inside the try is what makes a raising "
                      "recorder leave the DO_NOT_UPLOAD_ name")

    def test_p4_showdown_records_before_it_promotes(self):
        text = self._text("skills/generate-lineups/scripts/build_slate.py")
        self.assertIn("promote=False", text)
        record = text.index("record_delivery(")
        rename = text.index("os.replace(provisional, dest)")
        self.assertLess(record, rename)
        self.assertIn("stage_salary_for_delivery(", text)

    def test_p4_the_showdown_writer_can_withhold_the_promotion(self):
        from mlb_engine.optimize import showdown as sd
        import inspect
        self.assertIn("promote", inspect.signature(sd.write_showdown_entries).parameters)

    def test_p5_the_unrecorded_thesis_writer_is_gone(self):
        script = REPO / "skills" / "generate-lineups" / "scripts" / "build_showdown_theses.py"
        self.assertFalse(
            script.exists(),
            "P5 wrote a filled DKEntries to an operator-chosen --out with no "
            "record_delivery anywhere in the file, so it was unrecorded by "
            "construction. Ben's call 2026-08-11: deleted in favour of "
            "run_showdown rather than gated, per R31(e)'s own remedy.")

    def test_p6_preserve_prior_slate_is_told_the_date(self):
        text = self._text("skills/generate-lineups/scripts/build_slate.py")
        self.assertIn("rename_recorded_delivery", text)
        self.assertIn("date=args.date,", text,
                      "without the date preserve_prior_slate cannot find the row "
                      "its rename would orphan")

    def test_the_archival_scanner_carries_the_reverse_check(self):
        text = self._text("tools/awaiting_standings.py")
        self.assertIn("scan_unrecorded_deliveries", text)
        self.assertIn("UNRECORDED DELIVERIES", text)


class CorruptManifestIsItsOwnStateTests(unittest.TestCase):
    """R36 F6m(1). CORRUPT and ABSENT were the same answer, and the write erased.

    ``read_manifest`` answered both states with an empty manifest, so the next
    ``record_delivery`` os.replaced the unreadable original away and every prior
    record's supersession history went with it. Reproduced before the fix on a
    two-row manifest holding one superseded record: one row survived, the history
    did not.
    """

    def setUp(self):
        from mlb_engine.entries import upload_manifest as um
        self.um = um
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._original_root = um.REPO_ROOT
        um.REPO_ROOT = self.root
        self.date = "2026-08-15"
        self.outputs = self.root / "outputs" / self.date
        self.outputs.mkdir(parents=True)
        self.addCleanup(self._restore)

    def _restore(self):
        self.um.REPO_ROOT = self._original_root
        self.tmp.cleanup()

    def _payload(self):
        return json.dumps({"version": "1.1", "date": self.date, "deliveries": [
            {"delivered_file": f"outputs/{self.date}/DKEntries_a.csv",
             "sha256": "aa" * 32, "contest_type": "classic", "slate_tag": "t",
             "status": "superseded",
             "superseded_by": f"outputs/{self.date}/DKEntries_b.csv"},
            {"delivered_file": f"outputs/{self.date}/DKEntries_b.csv",
             "sha256": "bb" * 32, "contest_type": "classic", "slate_tag": "t",
             "status": "upload_ready"}]})

    def _corrupt(self):
        text = self._payload()[:120]
        (self.outputs / self.um.MANIFEST_NAME).write_text(text, encoding="utf-8")
        return text

    def _new_delivery(self, name="DKEntries_c.csv"):
        path = self.outputs / name
        path.write_text("bytes\n", encoding="utf-8")
        return path

    def test_an_absent_manifest_is_not_reported_as_corrupt(self):
        read = self.um.read_manifest(self.date)
        self.assertEqual(read["deliveries"], [])
        self.assertNotIn("corrupt", read,
                         "never-existed is a different fact from unreadable, and "
                         "collapsing them is the whole defect")

    def test_a_corrupt_manifest_reports_the_error_and_the_byte_count(self):
        text = self._corrupt()
        read = self.um.read_manifest(self.date)
        self.assertEqual(read["deliveries"], [])
        self.assertIn("corrupt", read)
        self.assertEqual(read["corrupt"]["bytes"], len(text))
        self.assertIn("JSONDecodeError", read["corrupt"]["error"])

    def test_valid_json_of_the_wrong_shape_is_corrupt_not_empty(self):
        (self.outputs / self.um.MANIFEST_NAME).write_text('"a string"', encoding="utf-8")
        read = self.um.read_manifest(self.date)
        self.assertIn("corrupt", read)
        self.assertIn("not an object", read["corrupt"]["error"])

    def test_recording_over_a_corrupt_manifest_quarantines_the_exact_bytes(self):
        text = self._corrupt()
        self.um.record_delivery(date=self.date, delivered_file=self._new_delivery(),
                                contest_type="classic", slate_tag="t")
        quarantined = sorted(self.outputs.glob("upload_manifest.corrupt.*.json"))
        self.assertEqual(len(quarantined), 1, "the unreadable bytes must survive")
        self.assertEqual(quarantined[0].read_text(encoding="utf-8"), text)
        fresh = json.loads((self.outputs / self.um.MANIFEST_NAME).read_text())
        self.assertEqual(fresh["recovered_from_corrupt"]["quarantined_to"],
                         self.um.repo_relative(quarantined[0]))
        self.assertIn("NO prior delivery record survives",
                      fresh["recovered_from_corrupt"]["note"])
        self.assertEqual(len(fresh["deliveries"]), 1)

    def test_a_clean_manifest_carries_no_recovery_block(self):
        (self.outputs / self.um.MANIFEST_NAME).write_text(self._payload(), encoding="utf-8")
        self.um.record_delivery(date=self.date, delivered_file=self._new_delivery(),
                                contest_type="showdown", slate_tag="sd")
        fresh = json.loads((self.outputs / self.um.MANIFEST_NAME).read_text())
        self.assertNotIn("recovered_from_corrupt", fresh)
        self.assertEqual(len(fresh["deliveries"]), 3, "the prior rows survive")

    def test_an_unquarantinable_manifest_refuses_rather_than_overwrites(self):
        text = self._corrupt()
        original = self.um.quarantine_corrupt_manifest

        def refuse(date):
            raise self.um.CorruptManifestError("quarantine device full")

        self.um.quarantine_corrupt_manifest = refuse
        self.addCleanup(setattr, self.um, "quarantine_corrupt_manifest", original)
        with self.assertRaises(self.um.CorruptManifestError):
            self.um.record_delivery(date=self.date,
                                    delivered_file=self._new_delivery(),
                                    contest_type="classic", slate_tag="t")
        self.assertEqual((self.outputs / self.um.MANIFEST_NAME).read_text(encoding="utf-8"),
                         text, "the corrupt original is left exactly as it was")

    def test_deliver_leaves_the_self_labelling_name_when_the_manifest_cannot_be_saved(self):
        self._corrupt()
        original = self.um.quarantine_corrupt_manifest
        self.um.quarantine_corrupt_manifest = lambda date: (_ for _ in ()).throw(
            self.um.CorruptManifestError("quarantine device full"))
        self.addCleanup(setattr, self.um, "quarantine_corrupt_manifest", original)
        dest = self.outputs / "DKEntries_1905_7g.csv"
        out = self.um.deliver(date=self.date, dest=dest,
                              write=lambda p: p.write_text("payload", encoding="utf-8"),
                              contest_type="classic", slate_tag="1905_7g")
        self.assertFalse(out["recorded"])
        self.assertIn("MANIFEST NOT RECORDED", out["error"])
        self.assertFalse(dest.exists(), "an unrecorded file never wears the upload name")
        self.assertTrue(self.um.unrecorded_name(dest).is_file())

    def test_verify_manifest_fails_on_a_corrupt_manifest(self):
        self._corrupt()
        check = self.um.verify_manifest(self.date)
        self.assertFalse(check["passed"],
                         "passed=True with checked=0 reads as 'nothing recorded, "
                         "nothing wrong' on the file preflight cross-checks against")
        self.assertIn("unreadable", check["problems"][0])


class RePromoteRunTests(unittest.TestCase):
    """R129. Supersession was a one-way door; ``tools/promote_run.py`` is the way back.

    Two independent filings, opposite directions: a better variant that could not
    be delivered because a later build in the same session superseded it
    (2026-08-15 2138_2g), and an earlier certified run that could not be restored
    (2026-08-14). One missing operation, exercised here end to end against a run
    tree built by hand.
    """

    def setUp(self):
        from mlb_engine.entries import upload_manifest as um
        self.um = um
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._original_root = um.REPO_ROOT
        um.REPO_ROOT = self.root
        self.date = "2026-08-15"
        self.outputs = self.root / "outputs" / self.date
        self.outputs.mkdir(parents=True)
        self.addCleanup(self._restore)

    def _restore(self):
        self.um.REPO_ROOT = self._original_root
        self.tmp.cleanup()

    def _entries_csv(self, entry_ids):
        header = (["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]
                  + ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"])
        rows = [header]
        for i, eid in enumerate(entry_ids):
            rows.append([eid, "MLB $2.5K Solo Shot (Night)", "193774256", "$5"]
                        + [str(1000 + i * 10 + s) for s in range(10)])
        return "\n".join(",".join(c for c in row) for row in rows) + "\n"

    def _make_run(self, run_id, entry_ids=("111", "222"), workflow_valid=True,
                  tamper=False):
        run_dir = self.root / "runs" / run_id
        (run_dir / "final").mkdir(parents=True)
        (run_dir / "inputs").mkdir(parents=True)
        (run_dir / "inputs" / "DKSalaries.csv").write_text("Position,Name\n", encoding="utf-8")
        export = run_dir / "final" / "DKEntries.csv"
        export.write_text(self._entries_csv(entry_ids), encoding="utf-8")
        digest = self.um.sha256_file(export)
        if tamper:
            export.write_text(self._entries_csv(tuple(entry_ids) + ("333",)),
                              encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": run_id, "status": "promoted",
            "certification": {"workflow_valid": workflow_valid,
                              "selection_certified": workflow_valid,
                              "allocation_certified": workflow_valid},
            "artifacts": {"final/DKEntries.csv": {"sha256": digest,
                                                 "role": "dk_export"}},
        }), encoding="utf-8")
        return run_dir

    def _promote(self, *argv):
        import promote_run
        return promote_run.main(["--repo-root", str(self.root), *argv])

    def _rows(self):
        return self.um.read_manifest(self.date).get("deliveries", [])

    def _seed_row(self, run_id, name, status="upload_ready", sha=None):
        path = self.outputs / name
        if not path.exists():
            path.write_text("seeded\n", encoding="utf-8")
        rows = self._rows()
        rows.append({"delivered_file": self.um.repo_relative(path),
                     "sha256": sha or self.um.sha256_file(path),
                     "contest_type": "classic", "slate_tag": "2138_2g",
                     "contest_ids": ["193774256"], "entries": 2,
                     "run_id": run_id, "status": status,
                     "certification": "certified"})
        self.um._write(self.um.manifest_path(self.date),
                       {"version": "1.1", "date": self.date, "deliveries": rows})

    # ---- the operation itself --------------------------------------------

    def test_a_superseded_run_can_be_delivered_again_with_a_truthful_row(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        run_dir = self._make_run(run_id)
        self._seed_row(run_id, "DKEntries_2138_2g.csv", status="superseded",
                       sha=self.um.sha256_file(run_dir / "final" / "DKEntries.csv"))
        self._seed_row("20260815T214500Z_bbbbbbbb", "DKEntries_2138_2g_later.csv")
        self.assertEqual(self._promote("--run-id", run_id), 0)
        rows = self._rows()
        new = rows[-1]
        self.assertEqual(new["re_promoted_from"], run_id)
        self.assertEqual(new["status"], "candidate",
                         "'current' is not in the closed status set; a row nothing "
                         "has checked yet is exactly what 'candidate' means")
        self.assertEqual(new["entries"], 2, "counted off the delivered bytes")
        # The row that WAS current is superseded by this one, and the run's own
        # earlier row keeps its history rather than being edited.
        beaten = [r for r in rows if r["run_id"] == "20260815T214500Z_bbbbbbbb"][0]
        self.assertEqual(beaten["status"], "superseded")
        self.assertEqual(beaten["superseded_by"], new["delivered_file"])
        self.assertEqual(rows[0]["status"], "superseded")

    def test_the_run_final_export_is_the_source_and_is_left_untouched(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        run_dir = self._make_run(run_id)
        self._seed_row(run_id, "DKEntries_2138_2g.csv", status="superseded")
        before = (run_dir / "final" / "DKEntries.csv").read_bytes()
        self.assertEqual(self._promote("--run-id", run_id), 0)
        self.assertEqual((run_dir / "final" / "DKEntries.csv").read_bytes(), before,
                         "immutability of runs/<id>/final/ is the contract this "
                         "whole operation rests on")
        delivered = self.root / self._rows()[-1]["delivered_file"]
        self.assertEqual(delivered.read_bytes(), before)

    def test_the_default_destination_is_run_scoped_and_canonical_is_opt_in(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        self._make_run(run_id)
        self._seed_row(run_id, "DKEntries_2138_2g.csv", status="superseded")
        self.assertEqual(self._promote("--run-id", run_id), 0)
        self.assertTrue(self._rows()[-1]["delivered_file"].endswith(
            "DKEntries_2138_2g_aaaaaaaa.csv"),
            "the canonical path must not be the only place a certified file lives")
        self.assertEqual(self._promote("--run-id", run_id, "--canonical"), 0)
        self.assertTrue(self._rows()[-1]["delivered_file"].endswith(
            "DKEntries_2138_2g.csv"))

    def test_a_dry_run_writes_nothing(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        self._make_run(run_id)
        self._seed_row(run_id, "DKEntries_2138_2g.csv", status="superseded")
        before = len(self._rows())
        self.assertEqual(self._promote("--run-id", run_id, "--dry-run"), 0)
        self.assertEqual(len(self._rows()), before)

    # ---- the refusals ----------------------------------------------------

    def test_a_run_with_no_final_export_is_refused(self):
        self.assertEqual(self._promote("--run-id", "20260815T000000Z_nosuchrun"), 2)

    def test_a_final_export_that_no_longer_matches_its_run_record_is_refused(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        self._make_run(run_id, tamper=True)
        self._seed_row(run_id, "DKEntries_2138_2g.csv", status="superseded")
        self.assertEqual(self._promote("--run-id", run_id), 2,
                         "promoting bytes that drifted from the run record would "
                         "launder a mutated 'immutable' artifact")

    def test_a_run_no_manifest_row_names_needs_the_slate_said_out_loud(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        self._make_run(run_id)
        self.assertEqual(self._promote("--run-id", run_id), 2)
        self.assertEqual(self._promote("--run-id", run_id, "--date", self.date,
                                       "--tag", "2138_2g"), 0)

    def test_an_uncertified_run_promotes_as_not_certified_rather_than_being_refused(self):
        run_id = "20260815T213800Z_aaaaaaaa"
        self._make_run(run_id, workflow_valid=False)
        self._seed_row(run_id, "DKEntries_2138_2g.csv", status="superseded")
        self.assertEqual(self._promote("--run-id", run_id), 0,
                         "refusing here would put this tool back in the business "
                         "of process preventing a lineup")
        self.assertEqual(self._rows()[-1]["certification"], "not_certified")


class ManifestRecordMatchingTests(unittest.TestCase):
    """R129. One sha256 with more than one row is ordinary once re-promotion exists.

    Both readers in ``preflight_upload.py`` took the FIRST row matching the
    sha256. That was adequate while bytes and rows were one-to-one; a re-promoted
    run has two rows for one digest, and first-wins then read the OLD superseded
    one. Two live defects on a copy of the real 2026-08-15 manifest: a current
    file reported as superseded, and ``stamp_manifest_status`` writing
    ``upload_ready`` onto a SUPERSEDED row, which is the lost-supersession failure
    R36 F6m names arriving through a different door.
    """

    def setUp(self):
        import preflight_upload
        self.pf = preflight_upload
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _rows(self):
        return [
            {"delivered_file": "outputs/2026-08-15/DKEntries_2138_2g.csv",
             "sha256": "cc" * 32, "status": "superseded", "run_id": "old_run"},
            {"delivered_file": "outputs/2026-08-15/DKEntries_2138_2g.csv",
             "sha256": "dd" * 32, "status": "superseded", "run_id": "beaten_run"},
            {"delivered_file": "outputs/2026-08-15/DKEntries_2138_2g_cc.csv",
             "sha256": "cc" * 32, "status": "candidate", "run_id": "old_run"},
        ]

    def _re_promoted_rows(self):
        """Run 'old_run' delivered to the canonical path, beaten, then re-promoted
        to a run-scoped path. Both rows carry the SAME bytes and one is live."""
        return [
            {"delivered_file": "outputs/2026-08-15/DKEntries_2138_2g.csv",
             "sha256": "cc" * 32, "status": "superseded", "run_id": "old_run",
             "superseded_by": "outputs/2026-08-15/DKEntries_2138_2g_cc.csv"},
            {"delivered_file": "outputs/2026-08-15/DKEntries_2138_2g_cc.csv",
             "sha256": "cc" * 32, "status": "upload_ready", "run_id": "old_run"},
        ]

    def test_the_live_row_for_this_path_wins_over_an_older_superseded_one(self):
        match = self.pf.match_manifest_record(
            self._rows(), "cc" * 32, "DKEntries_2138_2g_cc.csv")
        self.assertEqual(match["status"], "candidate")
        self.assertEqual(match["delivered_file"],
                         "outputs/2026-08-15/DKEntries_2138_2g_cc.csv")

    def test_a_live_row_elsewhere_does_not_absolve_the_path_that_lost(self):
        """The mutation that found this: dropping the same-path preference reddened
        nothing, so it was written down as a fix that could not fail.

        These bytes exist at two paths. The run-scoped copy is current; the
        canonical copy is superseded and still sitting on disk holding the same
        bytes. Matching on bytes alone hands the canonical file the LIVE row and
        preflight passes an obsolete file at T-5, which is the exact state the
        manifest exists to make impossible. The question is about a path, so the
        match has to be about a path.
        """
        rows = self._re_promoted_rows()
        canonical = self.pf.match_manifest_record(
            rows, "cc" * 32, "DKEntries_2138_2g.csv")
        self.assertEqual(canonical["status"], "superseded")
        self.assertEqual(canonical["delivered_file"],
                         "outputs/2026-08-15/DKEntries_2138_2g.csv")
        promoted = self.pf.match_manifest_record(
            rows, "cc" * 32, "DKEntries_2138_2g_cc.csv")
        self.assertEqual(promoted["status"], "upload_ready")

    def test_two_rows_for_one_path_and_one_sha_resolve_to_the_live_one(self):
        """Re-promoting onto --canonical is how a path ends up with a superseded
        row and a live row for identical bytes; first-wins reads the dead one."""
        rows = self._re_promoted_rows()
        rows[1] = dict(rows[1],
                       delivered_file="outputs/2026-08-15/DKEntries_2138_2g.csv")
        match = self.pf.match_manifest_record(rows, "cc" * 32, "DKEntries_2138_2g.csv")
        self.assertEqual(match["status"], "upload_ready")

    def test_a_path_with_only_a_superseded_row_still_matches_it(self):
        match = self.pf.match_manifest_record(
            self._rows(), "dd" * 32, "DKEntries_2138_2g.csv")
        self.assertEqual(match["status"], "superseded",
                         "the block has to keep firing for the file that lost")

    def test_an_unknown_filename_falls_back_to_the_bytes_and_prefers_live(self):
        match = self.pf.match_manifest_record(self._rows(), "cc" * 32, "")
        self.assertEqual(match["status"], "candidate")

    def test_bytes_no_row_carries_return_nothing(self):
        self.assertIsNone(self.pf.match_manifest_record(self._rows(), "ee" * 32, "x.csv"))

    def test_stamping_never_overwrites_a_superseded_status(self):
        path = self.root / "upload_manifest.json"
        path.write_text(json.dumps({"deliveries": self._rows()}), encoding="utf-8")
        rep = self.pf.Report()
        self.pf.stamp_manifest_status(path, "dd" * 32, "upload_ready", [], rep,
                                      entries_name="DKEntries_2138_2g.csv")
        row = json.loads(path.read_text())["deliveries"][1]
        self.assertEqual(row["status"], "superseded",
                         "a supersession is a fact about a LATER delivery; a "
                         "verdict is a fact about bytes, and the second must not "
                         "erase the first")
        self.assertEqual(row["preflight"]["verdict"], "upload_ready",
                         "the verdict is recorded beside the status, not lost")
        self.assertTrue(any("superseded" in w for w in rep.warnings))

    def test_stamping_a_live_row_still_writes_the_status(self):
        path = self.root / "upload_manifest.json"
        path.write_text(json.dumps({"deliveries": self._rows()}), encoding="utf-8")
        rep = self.pf.Report()
        self.pf.stamp_manifest_status(path, "cc" * 32, "upload_ready", [], rep,
                                      entries_name="DKEntries_2138_2g_cc.csv")
        rows = json.loads(path.read_text())["deliveries"]
        self.assertEqual(rows[2]["status"], "upload_ready")
        self.assertEqual(rows[0]["status"], "superseded",
                         "the old row for the same bytes is not touched")

    def test_the_superseded_refusal_names_the_run_to_re_promote(self):
        text = (REPO / "tools" / "preflight_upload.py").read_text(encoding="utf-8")
        self.assertIn("tools/promote_run.py --run-id", text,
                      "the message named only the path that beat this file, which "
                      "is not a next move; the run id is")
        self.assertIn("no run_id, so there is no run to re-promote", text,
                      "a row with no run id has no re-promote path and must say so "
                      "rather than print a command that cannot work")


OF_DEPTH_SURNAMES = ["Kerr", "Lomax", "Mundy", "Nash", "Oakes", "Pike"]


def write_deep_of_salary(path: Path) -> list[str]:
    """`write_classic_salary` plus six extra OF per team. Returns a legal lineup.

    The stock fixture gives each team one C/1B/2B/3B/SS and four OF, which
    leaves exactly THREE distinct legal lineups. R128's shape needs ten, and a
    fixture that cannot build ten distinct lineups cannot express the bug: the
    partition would be tested against a file with almost nothing to partition.
    """
    rows = [SALARY_HEADER]
    pid = 1000
    for game, teams in ((GAME_A, ("AAA", "BBB")), (GAME_B, ("CCC", "DDD"))):
        for team in teams:
            for i, (pos, roster) in enumerate(SLOT_SPEC):
                pid += 1
                rows.append(_salary_row(pid, f"{team} {SURNAMES[i]}", team, game,
                                        pos, roster, 4000, "",
                                        "SP" if roster == "P" else str(i)))
            for j, sur in enumerate(OF_DEPTH_SURNAMES):
                pid += 1
                rows.append(_salary_row(pid, f"{team} {sur}", team, game, "OF",
                                        "OF", 3000, "", str(10 + j)))
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    players = {p.player_id: p for p in parse_dk_salary_csv(str(path))}

    def pick(team, slot, taken):
        return next(p.player_id for p in players.values()
                    if p.team == team and slot in p.positions
                    and p.player_id not in taken)

    lineup = [pick("AAA", "P", set()), pick("CCC", "P", set())]
    for slot in ("C", "1B", "2B", "3B", "SS"):
        lineup.append(pick("AAA", slot, set(lineup)))
    for _ in range(3):
        lineup.append(pick("CCC", "OF", set(lineup)))
    return lineup


def distinct_lineups(salary_path: Path, base: list[str], k: int) -> list[list[str]]:
    """k distinct legal lineups, varying only the three CCC outfielders."""
    import itertools
    players = {p.player_id: p for p in parse_dk_salary_csv(str(salary_path))}
    ofs = sorted(pid for pid, p in players.items()
                 if p.team == "CCC" and "OF" in p.positions)
    out = [base[:7] + list(combo)
           for combo in itertools.islice(itertools.combinations(ofs, 3), k)]
    assert len(out) == k and len({frozenset(v) for v in out}) == k
    return out


class DuplicateLineupContextTests(unittest.TestCase):
    """R128. Duplication inside a contest and duplication across contests are
    two facts, and the preflight reported their union under one name that reads
    as a finding.

    Every fixture here is built so that the old flat count and the new split
    DISAGREE. That is the whole discipline: a fixture where each contest holds
    one entry, or where the two numbers happen to coincide, passes under both
    implementations, and a guard that cannot fail is not a guard (R65).
    """

    @staticmethod
    def _pf():
        import importlib
        return importlib.import_module("preflight_upload")

    def _advisory(self, tmp, plan, salary=None):
        """plan is [(contest_id, contest_name, lineup)]; returns the advisory."""
        pf = self._pf()
        salary_path = Path(tmp) / "DKSalaries.csv"
        if salary is None:
            salary = write_deep_of_salary(salary_path)
        entries_path = Path(tmp) / "DKEntries.csv"
        rows, eid = [], 4700000000
        for contest_id, name, lineup in plan:
            eid += 1
            rows.append([str(eid), name, contest_id, "$1"] + list(lineup)
                        + ["", "1. instructions"])
        write_entries(entries_path, CLASSIC_HEADER, rows)
        contest, _slots, entries, _raw, _n = pf.load_entries(entries_path)
        return pf.advisory(contest, entries, pf.load_salary(salary_path))

    def _2138_2g_plan(self, lineups):
        """The delivered 2026-08-15 shape: seven lineups mirrored across two
        identical Pocket Cup satellites, plus five single-entry contests whose
        five lineups form two duplicate pairs and a singleton.

        Both satellites carry the SAME contest NAME and different contest IDs,
        because that is what identical satellites actually look like on DK. A
        partition keyed on the name collapses them into one bucket and reports
        seven within-contest duplicates that do not exist.
        """
        seven, x, y, z = lineups[:7], lineups[7], lineups[8], lineups[9]
        plan = [(cid, "MLB $5 Pocket Cup", lu)
                for cid in ("193774256", "193774257") for lu in seven]
        plan += [(f"1937750{i}", f"MLB Solo Shot {i}", lu)
                 for i, lu in enumerate([x, x, y, y, z])]
        return plan

    def test_the_2138_2g_shape_reads_zero_within_and_nine_across(self):
        """The delivered file from 2026-08-15, and the one extra entry that
        proves the zero was computed.

        The shape's honest answer for `within` is 0, so this test on its own
        cannot tell a working partition from one that returns 0 unconditionally
        -- checked by hand, and a mutation hardwiring `within = 0` passed the
        first cut of this test. The second half moves the number on the same
        fixture, which is the assertion that makes the first half mean
        something (R65).
        """
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            lineups = distinct_lineups(salary_path, base, 10)
            plan = self._2138_2g_plan(lineups)
            adv = self._advisory(tmp, plan, salary=base)
            # One more entry in the first satellite, duplicating a lineup that
            # satellite already holds. Nothing else about the file changes.
            worse = self._advisory(tmp, plan + [("193774256", "MLB $5 Pocket Cup",
                                                 lineups[0])], salary=base)
        self.assertEqual(adv["entries"], 19)
        self.assertEqual(adv["contests_in_file"], 7)
        self.assertEqual(adv["distinct_lineups"], 10)
        self.assertEqual(adv["duplicates_within_contest"], 0,
                         "no contest holds the same lineup twice; this portfolio "
                         "wastes nothing and must not read as if it does")
        self.assertEqual(adv["duplicates_across_contests"], 9)
        self.assertEqual(adv["duplicate_lineup_groups"], 9,
                         "the flat count is unchanged; the split is what is new")
        self.assertEqual(worse["duplicates_within_contest"], 1,
                         "one duplicated entry inside one satellite must move "
                         "this number, or the zero above is hardwired")
        self.assertEqual(worse["duplicates_across_contests"], 9,
                         "within-contest waste does not change what crosses a "
                         "contest boundary")
        self.assertEqual(worse["duplicate_lineup_groups"], 9,
                         "the flat count cannot see the difference at all, which "
                         "is the defect in one line")

    def test_identical_satellites_sharing_a_name_are_still_two_contests(self):
        """Mutation guard: key the partition on contest NAME and this fixture
        reports seven within-contest duplicates instead of zero."""
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            lineups = distinct_lineups(salary_path, base, 10)
            plan = self._2138_2g_plan(lineups)
            adv = self._advisory(tmp, plan, salary=base)
        names = {name for _cid, name, _lu in plan}
        self.assertLess(len(names), 7, "fixture must reuse a contest name or it "
                                       "cannot catch a name-keyed partition")
        self.assertEqual(adv["duplicates_within_contest"], 0)

    def test_duplication_inside_one_contest_is_the_finding(self):
        """Mutation guard: make `across` mirror the flat count and this fails.
        One contest holds a lineup twice, so it is in the flat count, but it
        spans no contest boundary and across must stay 0."""
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            a, b = distinct_lineups(salary_path, base, 2)
            adv = self._advisory(tmp, [("111", "Cup", a), ("111", "Cup", a),
                                       ("222", "Shot", b)], salary=base)
        self.assertEqual(adv["duplicates_within_contest"], 1)
        self.assertEqual(adv["duplicates_across_contests"], 0)
        self.assertEqual(adv["duplicate_lineup_groups"], 1)

    def test_three_copies_in_one_contest_is_one_group_not_two(self):
        """Mutation guard: count copies (or c-1) instead of groups and this
        reads 3 (or 2). The unit is the group, matching the flat count it
        replaces, so the two numbers stay comparable."""
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            a, = distinct_lineups(salary_path, base, 1)
            adv = self._advisory(tmp, [("111", "Cup", a)] * 3, salary=base)
        self.assertEqual(adv["duplicates_within_contest"], 1)
        self.assertEqual(adv["distinct_lineups"], 1)

    def test_the_two_numbers_do_not_sum_to_the_flat_count(self):
        """The trap for whoever simplifies this into a partition. One signature
        held twice by each of two contests is: two within-contest groups, one
        signature crossing a boundary, and one flat group. 2 + 1 != 1, and all
        three readings are correct about different questions."""
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            a, = distinct_lineups(salary_path, base, 1)
            adv = self._advisory(tmp, [("111", "Cup", a), ("111", "Cup", a),
                                       ("222", "Cup B", a), ("222", "Cup B", a)],
                                 salary=base)
        self.assertEqual(adv["duplicates_within_contest"], 2)
        self.assertEqual(adv["duplicates_across_contests"], 1)
        self.assertEqual(adv["duplicate_lineup_groups"], 1)
        self.assertNotEqual(
            adv["duplicates_within_contest"] + adv["duplicates_across_contests"],
            adv["duplicate_lineup_groups"],
            "nothing may present these as summing to the flat count")

    def test_a_single_contest_file_can_never_report_across_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            a, b = distinct_lineups(salary_path, base, 2)
            adv = self._advisory(tmp, [("111", "Cup", a), ("111", "Cup", a),
                                       ("111", "Cup", b)], salary=base)
        self.assertEqual(adv["contests_in_file"], 1)
        self.assertEqual(adv["duplicates_across_contests"], 0)
        self.assertEqual(adv["duplicates_within_contest"], 1)

    def test_blank_contest_columns_degrade_to_the_old_flat_reading(self):
        """A hand-assembled file can leave both columns empty. Everything lands
        in one bucket, which is the OLD reading, not a wrong new one."""
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            a, b = distinct_lineups(salary_path, base, 2)
            adv = self._advisory(tmp, [("", "", a), ("", "", a), ("", "", b)],
                                 salary=base)
        self.assertEqual(adv["contests_in_file"], 1)
        self.assertEqual(adv["duplicates_within_contest"],
                         adv["duplicate_lineup_groups"])

    def test_the_printed_block_says_which_duplication_it_found(self):
        """The T-5 surface. `duplicate lineup groups: 9` unqualified is what
        nearly cost a good portfolio, so the bare phrasing must be gone."""
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            lineups = distinct_lineups(salary_path, base, 10)
            entries_path = Path(tmp) / "DKEntries.csv"
            rows, eid = [], 4700000000
            for contest_id, name, lineup in self._2138_2g_plan(lineups):
                eid += 1
                rows.append([str(eid), name, contest_id, "$1"] + list(lineup)
                            + ["", "1. instructions"])
            write_entries(entries_path, CLASSIC_HEADER, rows)
            out = run_preflight("--entries", str(entries_path),
                                "--salary", str(salary_path)).stdout
        self.assertIn("duplicate lineups WITHIN a contest: 0", out)
        self.assertIn("same lineup in MORE THAN ONE contest: 9 of 10", out)
        self.assertIn("across 7 contests", out)
        self.assertIn("information, not a finding", out)
        self.assertNotIn("duplicate lineup groups:", out,
                         "the unqualified line is the defect, not a fallback")

    def test_verify_export_reports_the_same_split_from_the_same_helper(self):
        """Both tools call one `advisory()`. Forking a second implementation
        into verify_export is the outcome this repo does not want, so the shared
        call is pinned rather than assumed."""
        source = (REPO / "tools" / "verify_export.py").read_text(encoding="utf-8")
        self.assertIn("advisory(contest, entries, salary)", source)
        self.assertNotIn("duplicates_within_contest", source,
                         "verify_export must inherit the split, never restate it")
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            lineups = distinct_lineups(salary_path, base, 10)
            entries_path = Path(tmp) / "DKEntries.csv"
            rows, eid = [], 4700000000
            for contest_id, name, lineup in self._2138_2g_plan(lineups):
                eid += 1
                rows.append([str(eid), name, contest_id, "$1"] + list(lineup)
                            + ["", "1. instructions"])
            write_entries(entries_path, CLASSIC_HEADER, rows)
            proc = run_verify("--entries", str(entries_path),
                              "--salary", str(salary_path), "--json")
        adv = json.loads(proc.stdout)["advisory"]
        self.assertEqual(adv["duplicates_within_contest"], 0)
        self.assertEqual(adv["duplicates_across_contests"], 9)
        self.assertEqual(adv["contests_in_file"], 7)

    def test_the_brief_and_the_preflight_agree_on_one_delivered_file(self):
        """Cross-tool, on DK-shaped bytes. The brief reads the delivered file
        directly and the preflight reads it through `advisory`; two readers of
        one file that disagree about how much of it duplicates is worse than
        either number alone."""
        import importlib.util
        path = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location("build_slate_r128", path)
        build_slate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_slate)
        with tempfile.TemporaryDirectory() as tmp:
            salary_path = Path(tmp) / "DKSalaries.csv"
            base = write_deep_of_salary(salary_path)
            lineups = distinct_lineups(salary_path, base, 10)
            entries_path = Path(tmp) / "DKEntries.csv"
            rows, eid = [], 4700000000
            for contest_id, name, lineup in self._2138_2g_plan(lineups):
                eid += 1
                rows.append([str(eid), name, contest_id, "$1"] + list(lineup)
                            + ["", "1. instructions"])
            write_entries(entries_path, CLASSIC_HEADER, rows)
            block = build_slate.portfolio_exposure(salary_path, entries_path)
            pf = self._pf()
            contest, _slots, parsed, _raw, _n = pf.load_entries(entries_path)
            adv = pf.advisory(contest, parsed, pf.load_salary(salary_path))
        for key in ("duplicates_within_contest", "duplicates_across_contests",
                    "contests_in_file", "distinct_lineups"):
            self.assertEqual(block[key], adv[key],
                             f"brief and preflight disagree on {key}")
        self.assertEqual(block["duplicates_within_contest"], 0)
        self.assertEqual(block["duplicates_across_contests"], 9)

    def test_the_helper_carries_the_reason_the_split_is_not_a_filter(self):
        """The across number is what says whether a satellite bank is being
        reused deliberately. A later reader who thinks it is noise has the
        rationale in front of them."""
        source = (REPO / "tools" / "preflight_upload.py").read_text(encoding="utf-8")
        self.assertIn("SPLIT, not a filter", source)
        self.assertIn("no_duplicates_within_contest", source,
                      "the brief half rides the allocator's own vocabulary")
        self.assertIn("allow_cross_contest_reuse", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ThinTeamBarTests(unittest.TestCase):
    """R133(3). One bar, read in one place, keyed to the solver constant.

    Before this, three readers answered "how short is too short" and two of them
    disagreed. ``build_slate_pool``'s confirmed path calls 5 through 8 a warning
    and under 5 a crosswalk blocker; a later loop in the same function blocked
    at anything under NINE with the sentence "the team cannot fill a stack";
    ``_derive_workflow_gates`` recomputed the nine-bar a third time and its
    verdict is the one that decided certification.

    ``MAX_HITTERS_PER_TEAM`` is 5, so a team with five CAN fill a maximum DK
    stack and the sentence was false everywhere from 5 to 8. On 2026-08-12 DET
    read "8/9 hitters after dropping [15 IL arms/bats]; the team cannot fill a
    stack" -- eight hitters, a false claim, and a dropped list naming PITCHERS
    that had nothing to do with the shortfall.
    """

    def _pool(self, il_ids=()):
        from mlb_engine.intake.live_data_adapters import build_slate_pool
        feed = {"date": "2026-07-25", "games": [
            {"game_pk": 1, "game_date_utc": "2026-07-25T23:05:00Z",
             "status": "Scheduled",
             "away": {"team_abbrev": "AAA", "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": "AAA Aster", "id": "1",
                                           "hand": "R"}},
             "home": {"team_abbrev": "BBB", "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": "BBB Aster", "id": "2",
                                           "hand": "R"}}},
            {"game_pk": 2, "game_date_utc": "2026-07-25T23:10:00Z",
             "status": "Scheduled",
             "away": {"team_abbrev": "CCC", "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": "CCC Aster", "id": "3",
                                           "hand": "R"}},
             "home": {"team_abbrev": "DDD", "lineup_status": "tbd", "lineup": [],
                      "probable_pitcher": {"name": "DDD Aster", "id": "4",
                                           "hand": "R"}}}]}
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            write_classic_salary(salary, il_ids=il_ids)
            return build_slate_pool(str(salary), feed)["pool_report"]

    # AAA's ten rows are 1001 (SP) then 1002..1010 (nine hitters).
    AAA_SP = "1001"
    AAA_HITTERS = tuple(str(1002 + i) for i in range(9))

    @staticmethod
    def _shortfall(report, team="AAA"):
        """Blockers about the HITTER count, which is what this bar decides. A
        side with no rosterable arm is a different fact with its own blocker,
        and the SP-on-IL fixture below legitimately produces one."""
        return [b for b in report["blockers"]
                if b.startswith(f"{team}:")
                and ("hitters" in b or "crosswalk" in b)]

    def test_eight_hitters_is_not_a_blocker(self):
        report = self._pool(il_ids=(self.AAA_HITTERS[0],))
        self.assertEqual(report["teams"]["AAA"]["hitters"], 8)
        self.assertEqual(self._shortfall(report), [])
        self.assertEqual(report["thin_teams"]["short_of_nine"], ["AAA"])
        self.assertEqual(report["thin_teams"]["cannot_fill_a_stack"], [])

    def test_four_hitters_blocks_and_names_the_stack_bar(self):
        report = self._pool(il_ids=self.AAA_HITTERS[:5])
        self.assertEqual(report["teams"]["AAA"]["hitters"], 4)
        hits = self._shortfall(report)
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("cannot fill a stack of any legal size", hits[0])
        self.assertIn("under 5", hits[0])
        self.assertEqual(report["thin_teams"]["cannot_fill_a_stack"], ["AAA"])

    def test_five_hitters_fills_a_maximum_stack_and_does_not_block(self):
        """The bar itself. Five is what MAX_HITTERS_PER_TEAM admits, so five is
        exactly where "cannot fill a stack" stops being true."""
        report = self._pool(il_ids=self.AAA_HITTERS[:4])
        self.assertEqual(report["teams"]["AAA"]["hitters"], 5)
        self.assertEqual(self._shortfall(report), [])
        self.assertEqual(report["thin_teams"]["short_of_nine"], ["AAA"])

    def test_the_bar_is_the_solver_constant_not_a_literal(self):
        from mlb_engine.optimize.optimizer_v3 import MAX_HITTERS_PER_TEAM
        self.assertEqual(self._pool()["thin_teams"]["stack_bar"],
                         MAX_HITTERS_PER_TEAM)

    def test_an_il_pitcher_is_not_named_as_a_reason_a_team_lacks_hitters(self):
        """The 2026-08-12 message's worst line. The dropped list came off every
        salary row, so five IL ARMS were offered as the reason DET was short of
        HITTERS -- and the actual ninth was a starter with no salary row, who
        appears in no dropped list at all."""
        report = self._pool(il_ids=(self.AAA_SP,) + self.AAA_HITTERS[:5])
        self.assertEqual(report["teams"]["AAA"]["hitters"], 4)
        hits = self._shortfall(report)
        self.assertEqual(len(hits), 1, hits)
        self.assertNotIn("Aster", hits[0])   # the SP fixture surname
        self.assertIn("Boone", hits[0])      # the first IL hitter
        dropped = {r["name"]: r["is_pitcher"] for r in report["status_dropped"]}
        self.assertTrue(dropped["AAA Aster"])
        self.assertFalse(dropped["AAA Boone"])

    def test_a_confirmed_team_is_not_double_decided(self):
        """The confirmed path owns this call and says it better (it names the
        crosswalk). Two blockers from one fact is what the old loop did."""
        from mlb_engine.intake.live_data_adapters import build_slate_pool
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "s.csv"
            # Six AAA hitters shelved, so DK's own Starting 1-9 is INCOMPLETE
            # for AAA and R143 does not source the side from the salary file --
            # the feed's three-name confirmed lineup is what reaches the pool.
            write_classic_salary(salary, il_ids=self.AAA_HITTERS[3:])
            lineup = [{"order": i + 1, "id": str(9000 + i),
                       "name": f"AAA {SURNAMES[i + 1]}", "position": "OF"}
                      for i in range(3)]
            feed = {"date": "2026-07-25", "games": [
                {"game_pk": 1, "game_date_utc": "2026-07-25T23:05:00Z",
                 "status": "Scheduled",
                 "away": {"team_abbrev": "AAA", "lineup_status": "confirmed",
                          "lineup": lineup, "probable_pitcher": None},
                 "home": {"team_abbrev": "BBB", "lineup_status": "tbd",
                          "lineup": [], "probable_pitcher": None}}]}
            report = build_slate_pool(str(salary), feed)["pool_report"]
        self.assertEqual(report["teams"]["AAA"]["status"], "confirmed")
        self.assertEqual(report["teams"]["AAA"]["hitters"], 3)
        hits = self._shortfall(report)
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("crosswalk failure", hits[0])
        self.assertEqual(report["thin_teams"]["cannot_fill_a_stack"], ["AAA"])


class LineupGateBarAgreesWithThePoolTests(unittest.TestCase):
    """R133(3), the third reader. The gate recomputed the nine-bar itself, so a
    team the pool report called a WARNING failed certification anyway, and no
    override could reach it because the gate's `thin` half never consulted the
    blockers list."""

    def _gate(self, pool_report):
        from mlb_engine.pipeline import execution_pipeline as epi
        return epi._derive_workflow_gates(
            schema={"passed": True, "summary": "ok"},
            entry_requirements=[{"entry_id": "1", "contest_id": "5"}],
            posture_by_contest={"5": {"posture": "large_gpp"}},
            projected_order={"requested": 0}, pitcher_roles=None,
            projection_enrichment={}, pool_report=pool_report, order_by_team=None)

    def test_a_stackable_team_short_of_nine_no_longer_fails_the_gate(self):
        gates, why = self._gate({
            "blockers": [], "teams": {"AAA": {"status": "confirmed", "hitters": 8}},
            "thin_teams": {"cannot_fill_a_stack": [], "short_of_nine": ["AAA"],
                           "stack_bar": 5}})
        self.assertTrue(gates["lineup_gate_passed"])
        self.assertIn("short of nine but stackable (AAA)", why["lineup_gate_passed"])

    def test_an_unstackable_team_still_fails_the_gate(self):
        gates, why = self._gate({
            "blockers": [], "teams": {"AAA": {"status": "confirmed", "hitters": 4}},
            "thin_teams": {"cannot_fill_a_stack": ["AAA"], "short_of_nine": [],
                           "stack_bar": 5}})
        self.assertFalse(gates["lineup_gate_passed"])
        self.assertIn("under 5 hitters", why["lineup_gate_passed"])

    def test_the_fallback_bar_equals_the_pool_reports_bar(self):
        """A hand-assembled report carries no `thin_teams`. The fallback must
        classify identically or there are two definitions again -- which is the
        defect this closed, reintroduced as a compatibility branch."""
        for hitters in range(0, 10):
            teams = {"AAA": {"status": "confirmed", "hitters": hitters}}
            split = {"cannot_fill_a_stack": ["AAA"] if hitters < 5 else [],
                     "short_of_nine": ["AAA"] if 5 <= hitters < 9 else [],
                     "stack_bar": 5}
            with_key = self._gate({"blockers": [], "teams": teams,
                                   "thin_teams": split})
            without = self._gate({"blockers": [], "teams": teams})
            self.assertEqual(with_key[0]["lineup_gate_passed"],
                             without[0]["lineup_gate_passed"], hitters)
            self.assertEqual(with_key[1]["lineup_gate_passed"],
                             without[1]["lineup_gate_passed"], hitters)

    def test_an_excluded_team_at_zero_is_not_thin(self):
        gates, _ = self._gate({
            "blockers": [],
            "teams": {"AAA": {"status": "excluded_postponed", "hitters": 0},
                      "BBB": {"status": "confirmed", "hitters": 9}}})
        self.assertTrue(gates["lineup_gate_passed"])


class GateAssumptionVersusOverrideTests(unittest.TestCase):
    """R133(4). Two documented escape hatches, neither of which worked.

    Measured on 2026-08-12 and reproduced here: ``--ignore-pool-blockers`` let
    the build run and the pre-export gate re-read the same pool report and
    failed; ``--assume-gates lineup_gate_passed`` did not suppress it either.
    The mechanism was one line -- ``run_slate`` promoted a gate only where the
    derived value was ``None``, so an assumption against a derived ``False`` was
    dropped WHILE STILL being written into ``assumed_gates``: a recorded
    assumption that changed nothing.

    An operator following CLAUDE.md's own autonomy section ("override a pool
    blocker whose shape you have classified benign, and assert
    ``lineup_gate_passed`` on that same evidence. Both together or neither") got
    a blocked build for doing exactly what the contract says.
    """

    BLOCKED_POOL = {
        "blockers": ["AAA: 4/9 hitters in the pool; under 5, so the team cannot "
                     "fill a stack of any legal size"],
        "teams": {"AAA": {"status": "platoon", "hitters": 4}},
        "thin_teams": {"cannot_fill_a_stack": ["AAA"], "short_of_nine": [],
                       "stack_bar": 5},
    }

    def _merge(self, assume, pool_report=None):
        """run_slate's own gate merge, called rather than reimplemented.

        The first cut of this helper copied the fifteen lines out of run_slate,
        and it passed against two mutations of the lines it named -- promoting
        None only, and recording an override as an assumption. A test over a copy
        of the logic pins the copy. `resolve_gate_assertions` was extracted for
        exactly this reason (R133(4)).
        """
        from mlb_engine.pipeline import execution_pipeline as epi
        derived, evidence = epi._derive_workflow_gates(
            schema={"passed": True, "summary": "ok"},
            entry_requirements=[{"entry_id": "1", "contest_id": "5"}],
            posture_by_contest={"5": {"posture": "large_gpp"}},
            projected_order={"requested": 0}, pitcher_roles=None,
            projection_enrichment={},
            pool_report=self.BLOCKED_POOL if pool_report is None else pool_report,
            order_by_team=None)
        defaults = {**derived, "projection_schema_gate_passed": True,
                    "optimizer_gate_passed": True}
        gates, assumed, over, refused = epi.resolve_gate_assertions(
            defaults, {}, assume, derived, evidence)
        return (gates, assumed, [r["gate"] for r in over],
                [r["gate"] for r in refused], evidence)

    def test_without_the_flag_the_gate_still_fails(self):
        gates, assumed, over, refused, _ = self._merge([])
        self.assertFalse(gates["lineup_gate_passed"])
        self.assertEqual((assumed, over, refused), ([], [], []))

    def test_asserting_the_lineup_gate_now_reaches_the_pre_export_gate(self):
        gates, assumed, over, refused, evidence = self._merge(
            ["lineup_gate_passed"])
        self.assertTrue(gates["lineup_gate_passed"])
        self.assertEqual(over, ["lineup_gate_passed"])
        # And it is an OVERRIDE, not an assumption. The distinction is the whole
        # point: one says nothing checked, the other says the check said no.
        self.assertEqual(assumed, [])
        self.assertEqual(refused, [])
        from mlb_engine.entries.dk_entries_manager import (
            validate_upload_ready_gates)
        pre = validate_upload_ready_gates(gates, allocation_required=False)
        self.assertNotIn("lineup_gate_passed", pre["failed_gates"])
        self.assertIn("under 5 hitters", evidence["lineup_gate_passed"])

    def test_a_gate_that_was_never_checked_is_an_assumption_not_an_override(self):
        """The pre-R133 semantics, still intact for the T-5 fast path. A pool
        report absent and no batting orders leaves the gate None."""
        gates, assumed, over, refused, _ = self._merge(
            ["lineup_gate_passed"], pool_report={})
        self.assertTrue(gates["lineup_gate_passed"])
        self.assertEqual(assumed, ["lineup_gate_passed"])
        self.assertEqual(over, [])

    def test_another_gate_against_a_false_derivation_is_refused_not_silent(self):
        """The silent discard is what cost the 2026-08-12 build. Widening the
        override to every gate would let an operator certify a broken salary CSV,
        so the other five are refused BY NAME instead."""
        from mlb_engine.pipeline import execution_pipeline as epi
        self.assertEqual(epi.OVERRIDABLE_GATES, ("lineup_gate_passed",))
        gates, assumed, over, refused, _ = self._merge(["salary_gate_passed"])
        self.assertEqual(refused, ["salary_gate_passed"])
        self.assertEqual((assumed, over), ([], []))
        self.assertTrue(gates["salary_gate_passed"])  # derived True on its own

    def test_the_override_record_carries_the_evidence_it_contradicts(self):
        """A gate name alone would not tell a later reader WHAT was overruled.
        The whole reason this is not `assumed_gates` is that it has a because."""
        from mlb_engine.pipeline import execution_pipeline as epi
        derived, evidence = epi._derive_workflow_gates(
            schema={"passed": True, "summary": "ok"},
            entry_requirements=[{"entry_id": "1", "contest_id": "5"}],
            posture_by_contest={"5": {"posture": "large_gpp"}},
            projected_order={"requested": 0}, pitcher_roles=None,
            projection_enrichment={}, pool_report=self.BLOCKED_POOL,
            order_by_team=None)
        _, _, over, _ = epi.resolve_gate_assertions(
            derived, {}, ["lineup_gate_passed"], derived, evidence)
        self.assertEqual(len(over), 1)
        self.assertEqual(over[0]["gate"], "lineup_gate_passed")
        self.assertFalse(over[0]["derived"])
        self.assertEqual(over[0]["evidence_contradicted"],
                         evidence["lineup_gate_passed"])
        self.assertIn("under 5 hitters", over[0]["evidence_contradicted"])

    def test_a_refused_request_says_which_of_the_two_reasons_it_was(self):
        from mlb_engine.pipeline import execution_pipeline as epi
        defaults = {"lineup_gate_passed": False, "salary_gate_passed": True,
                    "odds_gate_passed": False}
        _, _, _, refused = epi.resolve_gate_assertions(
            defaults, {}, ["salary_gate_passed", "odds_gate_passed"], defaults,
            {"odds_gate_passed": "no odds matched"})
        by_gate = {r["gate"]: r for r in refused}
        self.assertIn("nothing to assume", by_gate["salary_gate_passed"]["reason"])
        self.assertIn("not in OVERRIDABLE_GATES",
                      by_gate["odds_gate_passed"]["reason"])
        self.assertEqual(by_gate["odds_gate_passed"]["evidence"],
                         "no odds matched")

    def test_the_run_slate_payload_keeps_the_two_records_apart(self):
        """The keys where a caller actually reads them."""
        import inspect
        from mlb_engine.pipeline import execution_pipeline as epi
        src = inspect.getsource(epi.run_slate)
        self.assertIn('"overridden_gates": overridden_gates', src)
        self.assertIn('"gates_assumption_refused": gates_assumption_refused', src)
        self.assertIn("resolve_gate_assertions(", src)


class IgnorePoolBlockersIsHonestTests(unittest.TestCase):
    """R133(4), the other half. The flag is documented as "build anyway and have
    the override recorded", and alone it never certified. It now says so at the
    moment it is used, and it refuses outright the one blocker CLAUDE.md's hard
    list calls stop-and-ask above all others."""

    def _build_slate(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_bs_r133",
            str(REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_crosswalk_failure_is_not_overridable(self):
        bs = self._build_slate()
        for blocker in (
            "AAA: confirmed lineup matched 3/9 salary hitters; crosswalk "
            "failure, real lineup went unused",
            "AAA: DK marks 9 confirmed batting slots in the salary file but the "
            "pool holds 2; crosswalk failure, the authoritative order went unused",
        ):
            self.assertTrue(bs.UNOVERRIDABLE_POOL_BLOCKER_RE.search(blocker),
                            blocker)

    def test_an_ordinary_thin_team_blocker_stays_overridable(self):
        """The fixture that stops the regex from being "refuse everything". A
        blocker that matched every string would make the flag useless and the
        test above would still pass."""
        bs = self._build_slate()
        for blocker in (
            "AAA: 4/9 hitters in the pool; under 5, so the team cannot fill a "
            "stack of any legal size",
            "AAA: TBD lineup and platoon data filled only 3/9; team excluded",
            "feed does not match this draftgroup",
        ):
            self.assertFalse(bs.UNOVERRIDABLE_POOL_BLOCKER_RE.search(blocker),
                             blocker)

    def test_the_flag_help_and_the_override_note_name_the_second_move(self):
        import inspect
        bs = self._build_slate()
        src = inspect.getsource(bs)
        self.assertIn("POOL BLOCKER NOT OVERRIDABLE", src)
        self.assertIn("--assume-gates lineup_gate_passed to", src)
        self.assertIn("both together or neither", src.replace(
            '"\n                  "', ""))


# ---------------------------------------------------------------------------
# R234 / R191 / R192. The two things that stand between a build and the money
# boundary read the wrong file and count the wrong noun.
# ---------------------------------------------------------------------------

SD_GAME = "AAA@BBB 07/25/2026 07:05PM ET"
SD_CONTEST = "MLB Showdown Captain Mode $5 (AAA @ BBB)"


def write_showdown_salary(path: Path, first_pid: int = 2000) -> dict:
    """Six players a side, each priced twice: a CPT row and a UTIL row.

    Returns {person label: {"CPT": id, "UTIL": id}} so a test can put the same
    human in either role and see whether the tool notices it is one person.
    """
    rows = [SALARY_HEADER]
    people: dict = {}
    pid = first_pid
    for team in ("AAA", "BBB"):
        for i in range(6):
            name = f"{team} {SURNAMES[i]}"
            util_id, cpt_id = pid, pid + 500
            pid += 1
            pos = "P" if i == 0 else "OF"
            rows.append(_salary_row(util_id, name, team, SD_GAME, pos, "UTIL", 4000))
            rows.append(_salary_row(cpt_id, name, team, SD_GAME, pos, "CPT", 6000))
            people[name] = {"UTIL": str(util_id), "CPT": str(cpt_id)}
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return people


def showdown_entry(entry_id, contest_id, lineup, name=SD_CONTEST):
    return [entry_id, name, contest_id, "$1"] + list(lineup) + ["", "1. instructions"]


class R234SalaryAutoResolveIsScopedTests(unittest.TestCase):
    """The resolver reads a last-writer-wins pointer and never saw the file.

    Three field hits on clean delivered files (2026-08-20 x2, 2026-08-24), each
    a hard FAIL at the last check before the money boundary because the pointer
    named somebody else's build. A Showdown preflight is the guaranteed case:
    build_slate.py promotes no run, so there is never one of its own to find.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        (self.runs / "20260823T200036Z_0fe4a983" / "inputs").mkdir(parents=True)
        self.snapshot = (self.runs / "20260823T200036Z_0fe4a983"
                         / "inputs" / "DKSalaries.csv")
        (self.runs / "latest_valid_run.json").write_text(json.dumps({
            "run_id": "20260823T200036Z_0fe4a983",
            "run_dir": str(self.runs / "20260823T200036Z_0fe4a983"),
            "promoted_utc": "2026-08-23T20:00:36+00:00",
        }), encoding="utf-8")
        import preflight_upload
        self.pf = preflight_upload

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_showdown_file_refuses_the_classic_snapshot_the_pointer_names(self):
        write_classic_salary(self.snapshot)
        sd_salary = self.root / "sd.csv"
        people = write_showdown_salary(sd_salary)
        aster = people["AAA Aster"]
        rostered = [aster["CPT"]] + [people[f"AAA {s}"]["UTIL"] for s in SURNAMES[1:5]]
        rostered.append(people["BBB Aster"]["UTIL"])
        path, why = self.pf.resolve_salary_from_promoted_run(
            self.runs, contest="showdown", rostered=rostered)
        self.assertIsNone(path)
        self.assertIn("classic export", why)
        self.assertIn("showdown geometry", why)

    def test_a_same_geometry_snapshot_from_another_slate_is_refused_by_id(self):
        """The 08-20 shape: right contest type, wrong night."""
        write_classic_salary(self.snapshot)
        other = self.root / "other.csv"
        # write_classic_salary numbers from 1000; shift this slate's ids so the
        # two files describe different draftgroups, which is what a second night
        # actually is.
        lineup = write_classic_salary(other)
        shifted = [str(int(pid) + 90000) for pid in lineup]
        path, why = self.pf.resolve_salary_from_promoted_run(
            self.runs, contest="classic", rostered=shifted)
        self.assertIsNone(path)
        self.assertIn("different slate", why)
        self.assertIn("rostered player ID", why)

    def test_the_matching_snapshot_still_resolves_and_says_nothing(self):
        lineup = write_classic_salary(self.snapshot)
        path, why = self.pf.resolve_salary_from_promoted_run(
            self.runs, contest="classic", rostered=lineup)
        self.assertEqual(path, self.snapshot)
        self.assertEqual(why, "")

    def test_an_unscoped_call_still_resolves_so_the_guard_is_the_callers_job(self):
        """No contest and no ids is 'I have nothing to check it against', which
        is a weaker answer than a refusal, not a wrong one. Both callers in tree
        pass both, and the test below is what keeps that true."""
        write_classic_salary(self.snapshot)
        path, why = self.pf.resolve_salary_from_promoted_run(self.runs)
        self.assertEqual(path, self.snapshot)
        self.assertEqual(why, "")

    def test_a_corrupt_pointer_names_the_pointer_rather_than_returning_a_bare_none(self):
        (self.runs / "latest_valid_run.json").write_text("{not json", encoding="utf-8")
        path, why = self.pf.resolve_salary_from_promoted_run(self.runs)
        self.assertIsNone(path)
        self.assertIn("no readable run pointer", why)

    def test_a_pointer_to_a_run_without_a_snapshot_says_so(self):
        path, why = self.pf.resolve_salary_from_promoted_run(self.runs)
        self.assertIsNone(path)
        self.assertIn("no run carrying", why)

    def test_the_cli_exits_3_naming_the_flag_instead_of_2_on_a_clean_file(self):
        """The whole point. Before R234 this file -- which is legal, and which
        passes with its own salary file -- exited 2 on 'rostered player ID(s)
        absent from the salary file', a hard failure caused entirely by the tool
        picking the wrong input."""
        import contextlib
        import io

        write_classic_salary(self.snapshot)
        sd_salary = self.root / "sd.csv"
        people = write_showdown_salary(sd_salary)
        lineup = ([people["AAA Aster"]["CPT"]]
                  + [people[f"AAA {s}"]["UTIL"] for s in SURNAMES[1:5]]
                  + [people["BBB Aster"]["UTIL"]])
        entries = self.root / "DKEntries.csv"
        write_entries(entries, SHOWDOWN_HEADER,
                      [showdown_entry("900", "5", lineup)])

        saved = self.pf.REPO_ROOT
        self.pf.REPO_ROOT = self.root
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = self.pf.main(["--entries", str(entries), "--no-manifest"])
        finally:
            self.pf.REPO_ROOT = saved
        self.assertEqual(code, 3, err.getvalue())
        self.assertIn("was NOT used", err.getvalue())
        self.assertIn("Pass --salary explicitly", err.getvalue())
        self.assertNotIn("absent from the salary file", err.getvalue())

    def test_both_file_checkers_scope_the_auto_resolve_and_there_is_no_third(self):
        """R233 enumeration. R191 named preflight_upload; the class had two
        members, because verify_export imports the same resolver and had the
        same unguarded call."""
        import re

        sites = []
        for name in sorted(p.name for p in (REPO / "tools").glob("*.py")):
            src = (REPO / "tools" / name).read_text(encoding="utf-8")
            for call in re.findall(
                    r"(?<!def )resolve_salary_from_promoted_run"
                    r"\((?:[^()]|\([^()]*\))*\)", src):
                sites.append((name, call))
        self.assertEqual({name for name, _ in sites},
                         {"preflight_upload.py", "verify_export.py"},
                         f"a third caller appeared: {sites}")
        for name, call in sites:
            self.assertIn("contest=", call, name)
            self.assertIn("rostered=", call, name)


class R266PerContestCaptainDiversityTests(unittest.TestCase):
    """Captains counted against the contest that pays them, not against the file.

    The fixture is the measured 2026-08-28 delivery on ``2215_1g_sd`` (ARI@SF,
    21 entries, 7 contests, sha256 68528791e00d), reduced to the shape that
    matters: a 2-entry contest whose two entries carried the SAME captain, and a
    multi-entry contest carrying repeats under the per-contest bar. Portfolio-wide
    that build read ``realized_max_pct 23.8`` under a 0.25 cap with
    ``cap_relaxed_slots 0`` and ``counted_relaxations.clean true`` -- every number
    true, none of them describing what was entered.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.salary_path = self.root / "DKSalaries.csv"
        self.people = write_showdown_salary(self.salary_path)
        import preflight_upload
        self.pf = preflight_upload
        self.salary = self.pf.load_salary(self.salary_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _entry(self, line_no, contest_id, captain, utils):
        raw = ["90" + str(line_no), f"Contest {contest_id}", str(contest_id),
               "$1", captain] + list(utils)
        return self.pf.EntryRow(line_no, raw + ["", "1. instructions"], 6)

    def _cpt(self, surname, team="AAA"):
        return self.people[f"{team} {surname}"]["CPT"]

    def _utils(self, n=5, team="BBB"):
        return [self.people[f"{team} {s}"]["UTIL"] for s in SURNAMES[:n]]

    def _duplicated_captain_portfolio(self):
        """Contest 111 holds two entries under ONE captain: the 100% case.

        Contest 222 holds four entries with a captain repeated three times, which
        is over its own bar of max(1, floor(0.25 * 4)) = 1.
        """
        return [
            self._entry(1, 111, self._cpt("Aster"), self._utils()),
            self._entry(2, 111, self._cpt("Aster"), self._utils(4) + [
                self.people["AAA Boone"]["UTIL"]]),
            self._entry(3, 222, self._cpt("Boone"), self._utils()),
            self._entry(4, 222, self._cpt("Boone"), self._utils(4) + [
                self.people["AAA Aster"]["UTIL"]]),
            self._entry(5, 222, self._cpt("Boone"), self._utils(3) + [
                self.people["AAA Aster"]["UTIL"],
                self.people["AAA Ellis"]["UTIL"]]),
            self._entry(6, 222, self._cpt("Ellis"), self._utils()),
        ]

    def _clean_portfolio(self):
        """Same six entries, distinct captains inside every contest."""
        return [
            self._entry(1, 111, self._cpt("Aster"), self._utils()),
            self._entry(2, 111, self._cpt("Boone"), self._utils()),
            self._entry(3, 222, self._cpt("Ellis"), self._utils()),
            self._entry(4, 222, self._cpt("Aster"), self._utils()),
            self._entry(5, 222, self._cpt("Boone"), self._utils()),
            self._entry(6, 222, self._cpt("Aster", "BBB"), self._utils()),
        ]

    # -- the arithmetic ----------------------------------------------------
    def test_the_bar_is_max_1_min_m_n_minus_1(self):
        """The ``n - 1`` is the load-bearing part: a flat m permits a 2-entry
        contest to put both entries on one captain, which is the measured 100%
        this whole item exists to catch."""
        self.assertEqual(self.pf.per_contest_captain_cap(1, 2), 1)
        self.assertEqual(self.pf.per_contest_captain_cap(2, 2), 1)
        self.assertEqual(self.pf.per_contest_captain_cap(3, 2), 2)
        self.assertEqual(self.pf.per_contest_captain_cap(7, 2), 2)
        self.assertEqual(self.pf.per_contest_captain_cap(20, 2), 2)
        # A tighter control tightens the bar; a looser one is still bounded by
        # n - 1, so no multi-entry contest can be owned by one captain.
        self.assertEqual(self.pf.per_contest_captain_cap(7, 1), 1)
        self.assertEqual(self.pf.per_contest_captain_cap(3, 99), 2)

    def test_the_checker_bar_equals_the_builder_bar_at_every_size(self):
        """R79(d). Preflight cannot import the engine, so the copy is pinned
        equal rather than left to agree by luck -- and this test is what caught
        the pct-derived bar disagreeing with the named control at n=3.
        """
        from mlb_engine.optimize import showdown as sd
        for m in (1, 2, 3):
            for n in range(1, 25):
                self.assertEqual(
                    self.pf.per_contest_captain_cap(n, m),
                    sd.per_contest_cap_count(n, m),
                    f"n={n} m={m}: the checker and the builder must agree")

    def test_the_mirrored_default_equals_the_engines(self):
        from mlb_engine.optimize import showdown as sd
        self.assertEqual(self.pf.DEFAULT_MAX_CPT_PER_CONTEST,
                         sd.DEFAULT_MAX_CPT_PER_CONTEST)

    # -- the finding -------------------------------------------------------
    def test_one_captain_across_a_two_entry_contest_is_reported_at_100_pct(self):
        adv = self.pf.advisory("showdown", self._duplicated_captain_portfolio(),
                               self.salary)
        blocks = {b["contest_id"]: b for b in adv["per_contest_captains"]}
        self.assertEqual(blocks["111"]["n"], 2)
        self.assertEqual(blocks["111"]["distinct_captains"], 1)
        self.assertEqual(blocks["111"]["cap"], 1)
        self.assertEqual(blocks["111"]["over_cap"][0]["player"], "AAA Aster")
        self.assertEqual(blocks["111"]["over_cap"][0]["n"], 2)
        self.assertEqual(blocks["111"]["over_cap"][0]["pct"], 100.0)

    def test_the_portfolio_captain_line_reads_clean_on_the_same_file(self):
        """The whole point: the flat count cannot see this.

        Aster captains 2 of 6 entries file-wide (33%) and Boone 3 of 6 (50%),
        while inside contest 111 Aster owns 100% of a contest. The per-file line
        is what shipped on 2026-08-28 reading 23.8% under a 0.25 cap.
        """
        adv = self.pf.advisory("showdown", self._duplicated_captain_portfolio(),
                               self.salary)
        flat = {r["player"]: r for r in adv["top_captain_exposure"]}
        self.assertEqual(flat["AAA Aster"]["n"], 2)
        self.assertNotEqual(flat["AAA Aster"]["pct"], 100.0)
        # and the per-contest reading of the SAME captain is 100%.
        blocks = {b["contest_id"]: b for b in adv["per_contest_captains"]}
        self.assertEqual(blocks["111"]["over_cap"][0]["pct"], 100.0)

    def test_a_clean_portfolio_reports_blocks_with_nothing_over_cap(self):
        adv = self.pf.advisory("showdown", self._clean_portfolio(), self.salary)
        self.assertEqual(len(adv["per_contest_captains"]), 2)
        for b in adv["per_contest_captains"]:
            self.assertEqual(b["over_cap"], [])
        # The block still prints: "zero repeats inside a contest" is the
        # reassurance the T-5 reader needs, per R128's own reasoning.
        self.assertTrue(adv["per_contest_captains"])

    def test_single_entry_contests_are_omitted_not_reported_clean(self):
        """One entry cannot duplicate anything; listing it buries the finding."""
        entries = self._clean_portfolio() + [
            self._entry(7, 333, self._cpt("Aster"), self._utils())]
        adv = self.pf.advisory("showdown", entries, self.salary)
        self.assertNotIn("333", {b["contest_id"]
                                 for b in adv["per_contest_captains"]})

    def test_worst_contest_sorts_first_and_the_order_is_deterministic(self):
        adv = self.pf.advisory("showdown", self._duplicated_captain_portfolio(),
                               self.salary)
        ids = [b["contest_id"] for b in adv["per_contest_captains"]]
        self.assertEqual(ids[0], "111")   # 100% beats 75%
        again = self.pf.advisory("showdown",
                                 self._duplicated_captain_portfolio(),
                                 self.salary)
        self.assertEqual(ids, [b["contest_id"] for b in again["per_contest_captains"]])

    def test_classic_gets_no_per_contest_captain_block(self):
        salary_path = self.root / "classic.csv"
        lineup = write_classic_salary(salary_path)
        salary = self.pf.load_salary(salary_path)
        row = ["900", "MLB Test Contest", "5", "$1"] + lineup + ["", "1. inst"]
        adv = self.pf.advisory("classic", [self.pf.EntryRow(1, row, 10)], salary)
        self.assertNotIn("per_contest_captains", adv)

    # -- the severity ------------------------------------------------------
    def test_the_finding_warns_and_does_not_block_by_default(self):
        """A deliberate double-up is a legitimate play and CLAUDE.md reserves
        concentration to Ben, so this must not block on its own judgment."""
        adv = self.pf.advisory("showdown", self._duplicated_captain_portfolio(),
                               self.salary)
        rep = self.pf.Report()
        self.pf.check_contest_captain_diversity(adv, rep)
        self.assertEqual(rep.failures, [])
        self.assertTrue(any("above the per-contest cap" in w for w in rep.warnings))
        self.assertTrue(any("AAA Aster" in w and "111" in w for w in rep.warnings))

    def test_strict_turns_the_same_finding_into_a_failure(self):
        adv = self.pf.advisory("showdown", self._duplicated_captain_portfolio(),
                               self.salary)
        rep = self.pf.Report()
        self.pf.check_contest_captain_diversity(adv, rep, strict=True)
        self.assertTrue(rep.failures)
        self.assertEqual(rep.warnings, [])

    def test_a_clean_file_registers_neither_warning_nor_failure(self):
        adv = self.pf.advisory("showdown", self._clean_portfolio(), self.salary)
        for strict in (False, True):
            rep = self.pf.Report()
            self.pf.check_contest_captain_diversity(adv, rep, strict=strict)
            self.assertEqual(rep.failures, [])
            self.assertEqual(rep.warnings, [])

    # -- end to end --------------------------------------------------------
    def test_the_cli_warns_and_still_exits_zero(self):
        entries = self.root / "DKEntries.csv"
        rows = [showdown_entry("90" + str(i), cid, e.cells) for i, (e, cid) in
                enumerate(zip(self._duplicated_captain_portfolio(),
                              ["111", "111", "222", "222", "222", "222"]), start=1)]
        write_entries(entries, SHOWDOWN_HEADER, rows)
        result = run_preflight("--entries", str(entries),
                               "--salary", str(self.salary_path), "--no-manifest")
        self.assertIn("CPT per contest", result.stdout)
        self.assertIn("OVER CAP", result.stdout)
        self.assertEqual(result.returncode, 0,
                         "R266 is a warning; it must not block an upload")

    def test_strict_flag_makes_the_cli_hard_fail(self):
        entries = self.root / "DKEntries.csv"
        rows = [showdown_entry("90" + str(i), cid, e.cells) for i, (e, cid) in
                enumerate(zip(self._duplicated_captain_portfolio(),
                              ["111", "111", "222", "222", "222", "222"]), start=1)]
        write_entries(entries, SHOWDOWN_HEADER, rows)
        result = run_preflight("--entries", str(entries),
                               "--salary", str(self.salary_path), "--no-manifest",
                               "--strict-contest-diversity")
        self.assertEqual(result.returncode, 2)

    def test_the_strict_failure_is_counted_before_passed_is_evaluated(self):
        """Built inline in the report dict, a --strict failure would land in
        rep.failures after `passed` had already read it as True."""
        entries = self.root / "DKEntries.csv"
        rows = [showdown_entry("90" + str(i), cid, e.cells) for i, (e, cid) in
                enumerate(zip(self._duplicated_captain_portfolio(),
                              ["111", "111", "222", "222", "222", "222"]), start=1)]
        write_entries(entries, SHOWDOWN_HEADER, rows)
        result = run_preflight("--entries", str(entries),
                               "--salary", str(self.salary_path), "--no-manifest",
                               "--strict-contest-diversity", "--json")
        payload = json.loads(result.stdout)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["failures"])


class R192ShowdownExposureCountsThePersonTests(unittest.TestCase):
    """A draftable id is a role. Counting ids splits one human into two."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.salary_path = self.root / "DKSalaries.csv"
        self.people = write_showdown_salary(self.salary_path)
        import preflight_upload
        self.pf = preflight_upload
        self.salary = self.pf.load_salary(self.salary_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _entry(self, line_no, captain, utils):
        raw = ["90" + str(line_no), SD_CONTEST, "5", "$1", captain] + list(utils)
        return self.pf.EntryRow(line_no, raw + ["", "1. instructions"], 6)

    def _portfolio(self):
        """Four entries. Aster captains two and rides UTIL in the other two, so
        the person is in 4 of 4 while each ROLE id is in only 2 of 4."""
        aster = self.people["AAA Aster"]
        bench = [self.people[f"AAA {s}"]["UTIL"] for s in SURNAMES[1:5]]
        opp = [self.people[f"BBB {s}"]["UTIL"] for s in SURNAMES[:5]]
        return [
            self._entry(1, aster["CPT"], bench[:4] + opp[:1]),
            self._entry(2, aster["CPT"], bench[:3] + opp[:2]),
            self._entry(3, self.people["BBB Aster"]["CPT"],
                        [aster["UTIL"]] + bench[:2] + opp[1:3]),
            self._entry(4, self.people["BBB Boone"]["CPT"],
                        [aster["UTIL"]] + bench[2:4] + opp[2:4]),
        ]

    def test_the_captained_player_is_reported_at_his_real_exposure(self):
        adv = self.pf.advisory("showdown", self._portfolio(), self.salary)
        top = {row["player"]: row for row in adv["top_exposure"]}
        self.assertIn("AAA Aster", top)
        self.assertEqual(top["AAA Aster"]["n"], 4)
        self.assertEqual(top["AAA Aster"]["pct"], 100.0)
        # and he is FIRST, which is the finding: the role-keyed count put him
        # at 2 of 4 twice and buried him under UTIL-only bats.
        self.assertEqual(adv["top_exposure"][0]["player"], "AAA Aster")

    def test_a_util_only_bat_is_unchanged_so_the_fix_moved_only_the_captains(self):
        adv = self.pf.advisory("showdown", self._portfolio(), self.salary)
        top = {row["player"]: row for row in adv["top_exposure"]}
        self.assertEqual(top["AAA Boone"]["n"], 3)
        self.assertEqual(top["AAA Ellis"]["n"], 2)
        # Aster is the sole 4, so "first" is a fact and not a tie-break.
        self.assertEqual([r["n"] for r in adv["top_exposure"]].count(4), 1)

    def test_the_captain_distribution_is_reported_on_its_own_line(self):
        """The captain cap (0.25) and the player cap (0.50) are separate
        controls and an operator checking either against the brief had neither."""
        adv = self.pf.advisory("showdown", self._portfolio(), self.salary)
        cpt = {row["player"]: row for row in adv["top_captain_exposure"]}
        self.assertEqual(cpt["AAA Aster"]["n"], 2)
        self.assertEqual(cpt["AAA Aster"]["pct"], 50.0)
        self.assertEqual(cpt["BBB Aster"]["n"], 1)
        self.assertNotIn("AAA Boone", cpt)

    def test_classic_gets_no_captain_line_because_it_has_no_multiplier_role(self):
        salary_path = self.root / "classic.csv"
        lineup = write_classic_salary(salary_path)
        salary = self.pf.load_salary(salary_path)
        row = ["900", "MLB Test Contest", "5", "$1"] + lineup + ["", "1. inst"]
        adv = self.pf.advisory("classic", [self.pf.EntryRow(1, row, 10)], salary)
        self.assertNotIn("top_captain_exposure", adv)
        self.assertEqual(adv["top_exposure"][0]["pct"], 100.0)

    def test_the_printed_lines_say_which_noun_each_one_counts(self):
        entries = self.root / "DKEntries.csv"
        rows = [showdown_entry("90" + str(e.line_no), "5", e.cells)
                for e in self._portfolio()]
        write_entries(entries, SHOWDOWN_HEADER, rows)
        result = run_preflight("--entries", str(entries),
                               "--salary", str(self.salary_path), "--no-manifest")
        self.assertIn("top exposure:", result.stdout)
        self.assertIn("(the PERSON, either role)", result.stdout)
        self.assertIn("top CPT exposure:", result.stdout)
        self.assertIn("AAA Aster 100.0%", result.stdout)


class R234PersonKeyTests(unittest.TestCase):
    """The team half of the key had no assertion anywhere, at any of the four
    hand-written copies R234 unified. A mutation dropping it survived the whole
    suite, which is the R75 class going unmeasured: two players whose names
    normalize identically are one person only if they are also on one team, and
    collapsing them fails a legal lineup on 'the same person occupies two
    slots' while merging their exposures on the line above it."""

    def test_one_name_on_two_teams_is_two_people(self):
        import preflight_upload as pf
        a = pf.person_key({"Name": "Will Smith", "TeamAbbrev": "LAD"})
        b = pf.person_key({"Name": "Will Smith", "TeamAbbrev": "KC"})
        self.assertNotEqual(a, b)
        self.assertEqual(a, "willsmith|LAD")

    def test_the_same_person_priced_twice_is_one_key(self):
        """The Showdown case the key exists for: same human, two roster rows,
        two draftable ids, two salaries."""
        import preflight_upload as pf
        self.assertEqual(
            pf.person_key({"Name": "Shohei Ohtani", "TeamAbbrev": "LAD",
                           "Roster Position": "CPT", "Salary": "17400"}),
            pf.person_key({"Name": "Shohei Ohtani", "TeamAbbrev": "lad",
                           "Roster Position": "UTIL", "Salary": "11600"}))

    def test_a_lineup_holding_both_will_smiths_is_not_a_duplicate_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            import preflight_upload as pf
            root = Path(tmp)
            salary = root / "DKSalaries.csv"
            lineup = write_classic_salary(salary)
            with salary.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
            # Rename one AAA hitter and one CCC hitter to the same person: one
            # name, two teams, one legal lineup.
            need = {"AAA", "CCC"}
            for row in rows[1:]:
                if row[7] in need and row[3] in lineup and row[4] != "P":
                    row[1], row[2] = f"Will Smith ({row[3]})", "Will Smith"
                    need.discard(row[7])
                    if not need:
                        break
            self.assertEqual(need, set())
            with salary.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
            rep = pf.Report()
            pf.check_legality("classic", pf.CLASSIC_SLOTS,
                              [pf.EntryRow(1, [
                                  "900", "MLB Test Contest", "5", "$1"]
                                  + lineup + ["", "1. inst"], 10)],
                              pf.load_salary(salary), rep)
            self.assertEqual(
                [f for f in rep.failures if "same person" in f], [], rep.failures)
