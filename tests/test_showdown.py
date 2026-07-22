"""Showdown build gate: contracts, MILP legality, exact synthetic optimum, real-file
melt, end-to-end certify, and DKEntries export round-trip.

Every number here is a deterministic review proxy (Base = AvgPointsPerGame), never a
win-rate, ROI, or probability claim. Classic is untouched; this suite imports nothing
from the Classic solver, so test_golden_replay is unaffected.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from mlb_engine.optimize import showdown as sd
from mlb_engine.optimize.roster_contracts import CLASSIC, SHOWDOWN, get_contract
from mlb_engine.entries.dk_entries_manager import ROSTER_SLOTS

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "showdown"
SAL = FIX / "DKSalaries_showdown_MIN_CHC.csv"
ENT = FIX / "DKEntries_showdown_MIN_CHC.csv"


def _p(key, team, base, util_sal, cpt_sal, util_id, cpt_id):
    return {
        "Player_Key": key, "Name": key, "Team": team,
        "Opponent": "BB" if team == "AA" else "AA", "Position": "OF",
        "Game_ID": "AA@BB", "Base": base,
        "CPT_ID": cpt_id, "CPT_Salary": cpt_sal, "UTIL_ID": util_id, "UTIL_Salary": util_sal,
    }


def _synth():
    rows = [
        _p("AA_Star|AA", "AA", 100, 5000, 7500, "1001", "2001"),  # dominant -> captain
        _p("AA_2|AA", "AA", 5, 3000, 4500, "1002", "2002"),
        _p("AA_3|AA", "AA", 5, 3000, 4500, "1003", "2003"),
        _p("BB_1|BB", "BB", 5, 3000, 4500, "1004", "2004"),
        _p("BB_2|BB", "BB", 5, 3000, 4500, "1005", "2005"),
        _p("BB_3|BB", "BB", 5, 3000, 4500, "1006", "2006"),
        _p("BB_4|BB", "BB", 5, 3000, 4500, "1007", "2007"),
    ]
    return pd.DataFrame(rows)


class ShowdownContractTests(unittest.TestCase):
    def test_classic_contract_matches_engine(self):
        self.assertEqual(CLASSIC.roster_size, len(ROSTER_SLOTS))
        self.assertEqual(CLASSIC.salary_cap, 50000)
        self.assertEqual(CLASSIC.export_header[4:14],
                         ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"))
        self.assertEqual(get_contract("showdown").name, "SHOWDOWN")

    def test_showdown_contract_geometry(self):
        self.assertEqual(SHOWDOWN.slots, ("CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL"))
        self.assertEqual(SHOWDOWN.roster_size, 6)
        self.assertEqual(SHOWDOWN.multiplier_for("CPT"), 1.5)
        self.assertEqual(SHOWDOWN.min_players_per_team, 1)


class ShowdownSolverTests(unittest.TestCase):
    def test_synthetic_optimum_and_constraints(self):
        df = _synth()
        lu = sd.build_showdown_lineup(df)
        self.assertIsNotNone(lu)
        self.assertEqual(lu["captain"]["player_key"], "AA_Star|AA")
        self.assertEqual(len(lu["players"]), 6)
        self.assertEqual(sum(1 for p in lu["players"] if p["role"] == "CPT"), 1)
        self.assertEqual(sum(1 for p in lu["players"] if p["role"] == "UTIL"), 5)
        self.assertEqual(set(lu["teams"]), {"AA", "BB"})
        self.assertLessEqual(lu["salary"], SHOWDOWN.salary_cap)
        keys = [p["player_key"] for p in lu["players"]]
        self.assertEqual(len(set(keys)), 6)
        self.assertTrue(sd.certify_showdown(lu, df)["passed"])

    def test_captain_uses_cpt_id_and_salary(self):
        lu = sd.build_showdown_lineup(_synth())
        self.assertEqual(lu["captain"]["draftable_id"], "2001")  # CPT id, not the UTIL id 1001
        self.assertEqual(lu["captain"]["salary"], 7500)          # CPT salary
        self.assertAlmostEqual(lu["captain"]["points"], 150.0)   # 1.5 x 100

    def test_both_teams_forced(self):
        # If AA has the six best players, the both-teams rule still pulls in one BB.
        rows = [_p("AA_Star|AA", "AA", 100, 5000, 7500, "1001", "2001")]
        rows += [_p(f"AA_{i}|AA", "AA", 50 - i, 3000, 4500, f"10{i}", f"20{i}") for i in range(2, 8)]
        rows += [_p("BB_1|BB", "BB", 1, 3000, 4500, "1099", "2099")]
        lu = sd.build_showdown_lineup(pd.DataFrame(rows))
        self.assertIn("BB", lu["teams"])
        self.assertEqual(set(lu["teams"]), {"AA", "BB"})

    def test_melt_real_pool(self):
        df = sd.melt_showdown_salary_csv(SAL, starters_only=False)
        self.assertGreaterEqual(len(df), 40)
        self.assertEqual(set(df.Team.unique()), {"MIN", "CHC"})
        self.assertTrue((df["CPT_ID"] != df["UTIL_ID"]).all())
        self.assertTrue((df["CPT_Salary"] >= df["UTIL_Salary"]).all())

    def test_melt_restricts_to_declared_starters(self):
        """AvgPointsPerGame does not know who is playing, so an unrestricted pool
        captains relievers and rosters bench bats. DK publishes the answer in the
        salary file's Starting column and the pool has to honor it."""
        full = sd.melt_showdown_salary_csv(SAL, starters_only=False)
        pool = sd.melt_showdown_salary_csv(SAL)
        self.assertLess(len(pool), len(full))
        self.assertEqual(pool["Pool_Basis"].iloc[0], "declared_starters")
        # Two declared starting pitchers, nine posted hitters per side.
        self.assertEqual(int(pool["Is_Declared_Starter"].sum()), 2)
        self.assertEqual(int(pool["Batting_Order"].notna().sum()), 18)
        self.assertEqual(set(pool.Team.unique()), {"MIN", "CHC"})
        starters = set(pool.loc[pool["Is_Declared_Starter"], "Name"])
        self.assertEqual(starters, {"Taj Bradley", "Matthew Boyd"})
        # A rostered arm who is not starting must not survive the filter.
        self.assertIn("Joe Ryan", set(full["Name"]))
        self.assertNotIn("Joe Ryan", set(pool["Name"]))

    def test_melt_falls_back_when_nothing_posted(self):
        """Before lineups post, Starting is blank for everyone. Filtering then would
        empty the pool, so the basis is reported instead of silently restricting."""
        import csv as _csv
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(SAL)
            dest = Path(tmp) / "blank_starting.csv"
            with src.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(_csv.reader(fh))
            head, body = rows[0], rows[1:]
            col = head.index("Starting")
            for row in body:
                if len(row) > col:
                    row[col] = ""
            with dest.open("w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh); w.writerow(head); w.writerows(body)
            pool = sd.melt_showdown_salary_csv(dest)
            self.assertGreaterEqual(len(pool), 40)
            self.assertEqual(pool["Pool_Basis"].iloc[0], "all_healthy")

    def test_build_and_certify_real(self):
        df = sd.melt_showdown_salary_csv(SAL)
        lu = sd.build_showdown_lineup(df)
        self.assertIsNotNone(lu)
        cert = sd.certify_showdown(lu, df)
        self.assertTrue(cert["passed"], cert["errors"])
        self.assertLessEqual(lu["salary"], 50000)
        self.assertEqual(set(lu["teams"]), {"MIN", "CHC"})

    def test_bank_distinct(self):
        df = sd.melt_showdown_salary_csv(SAL)
        bank = sd.build_showdown_bank(df, 3)
        self.assertEqual(len(bank), 3)
        self.assertEqual(len({tuple(l["player_keys"]) for l in bank}), 3)


class ShowdownExportTests(unittest.TestCase):
    def test_export_roundtrip_and_template_preserved(self):
        df = sd.melt_showdown_salary_csv(SAL)
        lu = sd.build_showdown_lineup(df)
        parsed = sd.read_showdown_reserved_rows(ENT)
        blanks = [r for r in parsed["reserved"] if r["is_blank"]]
        self.assertTrue(blanks, "fixture should carry a blank reserved row")
        eid = blanks[0]["entry_id"]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "candidate.csv"
            res = sd.write_showdown_entries(ENT, out, [{"entry_id": eid, "roster_ids": lu["roster_ids"]}])
            self.assertTrue(res["passed"], res["errors"])
            self.assertTrue(sd.verify_template_preserved(ENT, out)["passed"])
            reparsed = {r["entry_id"]: r for r in sd.read_showdown_reserved_rows(out)["reserved"]}
            self.assertEqual(reparsed[eid]["cells"], lu["roster_ids"])
            self.assertFalse(reparsed[eid]["is_blank"])

    def test_completed_rows_are_immutable(self):
        # Self-contained template: one blank reservation and one already-submitted row.
        header = "Entry ID,Contest Name,Contest ID,Entry Fee,CPT,UTIL,UTIL,UTIL,UTIL,UTIL,,Instructions"
        blank = "111,Test SD,900,$1,,,,,,,,1. blank reservation"
        filled = "222,Test SD,900,$1,10,20,30,40,50,60,,2. already submitted"
        with tempfile.TemporaryDirectory() as tmp:
            tpl = Path(tmp) / "template.csv"
            tpl.write_text("\n".join([header, blank, filled]) + "\n", encoding="utf-8")
            out = Path(tmp) / "candidate.csv"
            bad = sd.write_showdown_entries(tpl, out, [{"entry_id": "222", "roster_ids": list("123456")}])
            self.assertFalse(bad["passed"])
            self.assertTrue(any("immutable" in e for e in bad["errors"]))
            ok = sd.write_showdown_entries(tpl, out, [{"entry_id": "111", "roster_ids": ["7", "8", "9", "10", "11", "12"]}])
            self.assertTrue(ok["passed"], ok["errors"])
            reparsed = {r["entry_id"]: r for r in sd.read_showdown_reserved_rows(out)["reserved"]}
            self.assertEqual(reparsed["111"]["cells"], ["7", "8", "9", "10", "11", "12"])
            self.assertTrue(reparsed["222"]["is_complete"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
