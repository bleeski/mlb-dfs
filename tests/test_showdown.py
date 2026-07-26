"""Showdown build gate: contracts, MILP legality, exact synthetic optimum, real-file
melt, end-to-end certify, and DKEntries export round-trip.

Every number here is a deterministic review proxy (Base = AvgPointsPerGame), never a
win-rate, ROI, or probability claim. Classic is untouched; this suite imports nothing
from the Classic solver, so test_golden_replay is unaffected.
"""
from __future__ import annotations

import collections
import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from mlb_engine.optimize import showdown as sd
from mlb_engine.optimize import showdown_theses as st
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


# --------------------------------------------------------------------------- #
# Portfolio diversity: overlap bound and captain cap
# --------------------------------------------------------------------------- #
def _max_pairwise_overlap(bank):
    sets = [set(l["player_keys"]) for l in bank]
    return max((len(a & b) for i, a in enumerate(sets) for b in sets[i + 1:]),
               default=0)


class ShowdownDiversityTests(unittest.TestCase):
    def test_defaults_are_a_third_and_four_shared(self):
        # 0.33 not 0.35: cap_count is a floor(), and 0.35 * 20 = 7, which is a
        # realized 35%. The standing instruction is "never more than a third".
        self.assertEqual(sd.DEFAULT_MAX_CPT_EXPOSURE_PCT, 0.33)
        self.assertEqual(sd.DEFAULT_MAX_SHARED_PLAYERS, 4)
        self.assertEqual(math.floor(sd.DEFAULT_MAX_CPT_EXPOSURE_PCT * 20), 6)

    def test_bank_respects_the_overlap_bound(self):
        df = sd.melt_showdown_salary_csv(SAL)
        bank = sd.build_showdown_bank(df, 12, time_limit=6)
        self.assertEqual(len(bank), 12)
        self.assertLessEqual(_max_pairwise_overlap(bank), 4)

    def test_exact_set_forbidding_permits_five_shared_and_the_bound_does_not(self):
        """The reason the bound exists: a one-player swap passes exact-set."""
        df = sd.melt_showdown_salary_csv(SAL)
        loose = sd.build_showdown_bank(df, 6, max_shared_players=None, time_limit=6)
        tight = sd.build_showdown_bank(df, 6, max_shared_players=4, time_limit=6)
        self.assertEqual(_max_pairwise_overlap(loose), 5)
        self.assertLessEqual(_max_pairwise_overlap(tight), 4)

    def test_overlap_counts_the_player_not_the_role(self):
        """Promoting a UTIL to CPT is not a differentiated lineup."""
        df = sd.melt_showdown_salary_csv(SAL)
        first = sd.build_showdown_lineup(df, time_limit=6)
        self.assertIsNotNone(first)
        keys = list(first["player_keys"])
        again = sd.build_showdown_lineup(df, forbidden_sets=[keys],
                                         max_shared_players=5, time_limit=6)
        self.assertIsNotNone(again)
        # 5 shared is allowed; all 6 in any role arrangement is not.
        self.assertLessEqual(len(set(again["player_keys"]) & set(keys)), 5)

    def test_captain_cap_holds_at_a_third_of_the_bank(self):
        df = sd.melt_showdown_salary_csv(SAL)
        diag = {}
        bank = sd.build_showdown_bank(df, 18, diagnostics=diag, time_limit=6)
        self.assertEqual(len(bank), 18)
        counts = collections.Counter(l["captain"]["player_key"] for l in bank)
        self.assertLessEqual(max(counts.values()) / len(bank), 1.0 / 3.0)
        self.assertEqual(diag["relaxed_slots"], 0)

    def test_cap_relaxes_rather_than_returning_a_short_bank(self):
        """A short bank leaves a blank reserved row, and a blank row blocks
        certification. Relaxing a diversity control is the lesser failure."""
        df = _synth()                       # 7 players, almost no legal variety
        diag = {}
        bank = sd.build_showdown_bank(df, 6, diagnostics=diag, time_limit=4)
        self.assertGreater(len(bank), 0)
        self.assertIn("overlap_relaxed_slots", diag)
        self.assertIn("relaxed_slots", diag)


# --------------------------------------------------------------------------- #
# Thesis ladder
# --------------------------------------------------------------------------- #
class ShowdownThesisLadderTests(unittest.TestCase):
    def setUp(self):
        self.df = st.apply_base_prior(sd.melt_showdown_salary_csv(SAL),
                                      pitcher_hand={"MIN": "R", "CHC": "R"})

    def test_platoon_applies_against_right_handed_starters(self):
        """Regression: an earlier prior only modeled LHP starters, so a slate
        with two RHP starters got a flat 1.00 while prior_note still claimed a
        platoon factor. A same-handed bat must be marked down, not ignored."""
        raw = sd.melt_showdown_salary_csv(SAL)
        hitters = raw[raw["Batting_Order"].notna()]
        name = str(hitters.iloc[0]["Name"])
        opp = str(hitters.iloc[0]["Opponent"])
        righty = st.apply_base_prior(raw, bat_side={name: "R"},
                                     pitcher_hand={opp: "R"})
        lefty = st.apply_base_prior(raw, bat_side={name: "L"},
                                    pitcher_hand={opp: "R"})
        r = float(righty.loc[righty["Name"] == name, "Base"].iloc[0])
        l = float(lefty.loc[lefty["Name"] == name, "Base"].iloc[0])
        self.assertLess(r, l)               # RHB vs RHP is the penalty side

    def test_unresolved_platoon_teams_are_reported_not_silently_flattened(self):
        raw = sd.melt_showdown_salary_csv(SAL)
        out = st.apply_base_prior(raw, bat_side={}, pitcher_hand={})
        self.assertEqual(set(out.attrs["platoon_unresolved_teams"]), {"MIN", "CHC"})

    def test_ladder_spans_game_states_and_holds_the_captain_cap(self):
        ladder = st.build_thesis_ladder(self.df, 18, moneyline={"MIN": -150, "CHC": 130})
        self.assertEqual(len(ladder["theses"]), 18)
        self.assertGreaterEqual(len(ladder["allocation"]), 8)
        self.assertEqual(ladder["win_share_basis"], "moneyline_no_vig")
        counts = collections.Counter(t["cpt"] for t in ladder["theses"])
        self.assertLessEqual(max(counts.values()) / 18, 1.0 / 3.0)

    def test_ladder_solves_unique_rosters_under_both_bounds(self):
        ladder = st.build_thesis_ladder(self.df, 18, moneyline={"MIN": -150, "CHC": 130})
        lineups = st.solve_ladder(self.df, ladder["theses"], time_limit=5)
        self.assertTrue(all(l is not None for l in lineups))
        report = st.portfolio_report(self.df, ladder["theses"], lineups)
        self.assertTrue(report["all_unique_rosters"])
        self.assertLessEqual(report["max_pairwise_overlap"], 4)
        self.assertLessEqual(report["max_captain_exposure_pct"], 100.0 / 3.0)
        self.assertTrue(all(r["lineup_certified"] for r in report["lineups"]))

    def test_ladder_scales_below_and_above_the_template_count(self):
        for n in (1, 3, 25):
            ladder = st.build_thesis_ladder(self.df, n)
            self.assertEqual(len(ladder["theses"]), n, f"n={n}")
            self.assertTrue(all(t["name"] for t in ladder["theses"]), f"n={n}")

    def test_repeated_templates_get_distinct_thesis_names(self):
        """Two rows sharing a thesis name read as a duplicate when they are not."""
        ladder = st.build_thesis_ladder(self.df, 25)
        names = [t["name"] for t in ladder["theses"]]
        self.assertEqual(len(set(names)), len(names))

    def test_no_market_input_splits_evenly_and_says_so(self):
        ladder = st.build_thesis_ladder(self.df, 10)
        self.assertEqual(ladder["win_share_basis"], "even_split_no_market_input")
        self.assertEqual(set(ladder["shape"]["win_share"].values()), {0.5})

    def test_ace_loses_pairs_the_ace_with_the_bats_facing_him(self):
        """The one shape a points-max solve never builds on its own."""
        ladder = st.build_thesis_ladder(self.df, 18, moneyline={"MIN": -150, "CHC": 130})
        thesis = next(t for t in ladder["theses"] if t["template"] == "ace_loses")
        lineups = st.solve_ladder(self.df, [thesis], time_limit=5)
        self.assertIsNotNone(lineups[0])
        teams = collections.Counter(
            self.df.set_index("Player_Key").loc[k, "Team"]
            for k in lineups[0]["player_keys"])
        ace_team = self.df.set_index("Player_Key").loc[thesis["cpt"], "Team"]
        # The ace's own side contributes the ace and little else.
        self.assertLessEqual(teams[ace_team], 2)

    def test_bullpen_template_appears_only_without_a_declared_starter(self):
        both = st.describe_slate(self.df)
        self.assertEqual(both["bullpen_teams"], [])
        ladder = st.build_thesis_ladder(self.df, 18)
        self.assertNotIn("bullpen_game", ladder["allocation"])

        no_sp = self.df[~((self.df["Team"] == "CHC")
                          & (self.df["Batting_Order"].isna()))].reset_index(drop=True)
        self.assertEqual(st.describe_slate(no_sp)["bullpen_teams"], ["CHC"])
        self.assertIn("bullpen_game", st.build_thesis_ladder(no_sp, 18)["allocation"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
