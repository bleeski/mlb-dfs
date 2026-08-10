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

    def test_the_feed_is_auto_resolved_from_the_slate_date(self):
        """No --feed passed. The fixture's Game Info dates the slate 2026-07-25,
        and the repo carries data/slates/2026-07-25/lineups_feed.json, so the
        resolver finds it without being told and says which file it used."""
        payload = json.loads(self._run("--json").stdout)
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


def write_three_game_feed(path: Path, postponed=(), confirmed=None) -> Path:
    """A lineups feed for the same three games, start times matching the salary.

    ``confirmed`` is {team: [player names]}; those sides read ``confirmed`` with
    that posted lineup and every other side stays ``tbd``. R46's check only fires
    against a CONFIRMED side, so a feed of all-tbd sides exercises nothing.
    """
    posted = {k.upper(): list(v) for k, v in (confirmed or {}).items()}

    def side(team):
        names = posted.get(team.upper())
        if names is None:
            return {"team_abbrev": team, "lineup_status": "tbd",
                    "lineup": [], "probable_pitcher": None}
        return {"team_abbrev": team, "lineup_status": "confirmed",
                "lineup": [{"name": n, "batting_order": i + 1}
                           for i, n in enumerate(names)],
                "probable_pitcher": None}

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

    def _feed(self, confirmed) -> Path:
        return write_three_game_feed(self.dir / "lineups_feed.json",
                                     confirmed=confirmed)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
