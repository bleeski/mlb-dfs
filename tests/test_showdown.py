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
import unittest.mock
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
            # Deliberately partial: this test is about the round trip, not the
            # delivery gate, so it opts out of the all-rows-filled requirement.
            res = sd.write_showdown_entries(
                ENT, out, [{"entry_id": eid, "roster_ids": lu["roster_ids"]}],
                require_all_filled=False)
            self.assertTrue(res["passed"], res["errors"])
            self.assertTrue(sd.verify_template_preserved(ENT, out)["passed"])
            reparsed = {r["entry_id"]: r for r in sd.read_showdown_reserved_rows(out)["reserved"]}
            self.assertEqual(reparsed[eid]["cells"], lu["roster_ids"])
            self.assertFalse(reparsed[eid]["is_blank"])

    def test_blank_reserved_rows_block_the_write(self):
        """F6(c): a short bank used to leave trailing reserved rows blank and ship."""
        df = sd.melt_showdown_salary_csv(SAL)
        lu = sd.build_showdown_lineup(df)
        parsed = sd.read_showdown_reserved_rows(ENT)
        blanks = [r for r in parsed["reserved"] if r["is_blank"]]
        self.assertGreater(len(blanks), 1, "fixture needs more than one blank row")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "candidate.csv"
            res = sd.write_showdown_entries(
                ENT, out, [{"entry_id": blanks[0]["entry_id"],
                            "roster_ids": lu["roster_ids"]}])
            self.assertFalse(res["passed"])
            self.assertIn("would ship blank", " ".join(res["errors"]))
            self.assertIsNone(res["candidate_path"])
            # and nothing was left at the delivered name
            self.assertFalse(out.exists())

    def test_single_team_pool_is_refused_at_the_melt(self):
        """F6(a): the both-teams check used to read its teams out of the pool."""
        import csv as _csv
        with open(SAL, newline="", encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        keep_team = rows[0]["TeamAbbrev"]
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "one_team.csv"
            with one.open("w", newline="", encoding="utf-8") as fh:
                writer = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows([r for r in rows if r["TeamAbbrev"] == keep_team])
            with self.assertRaises(ValueError) as ctx:
                sd.melt_showdown_salary_csv(str(one))
            self.assertIn("single-team pool", str(ctx.exception))

    def test_certify_recomputes_salary_and_rejects_a_missing_key(self):
        """F6(b): lineup.get('salary', 0) skipped the cap check when absent."""
        df = sd.melt_showdown_salary_csv(SAL)
        lu = dict(sd.build_showdown_lineup(df))
        self.assertTrue(sd.certify_showdown(lu, df)["passed"])
        checks = sd.certify_showdown(lu, df)["checks"]
        self.assertAlmostEqual(float(checks["recomputed_salary"]),
                               float(lu["salary"]), delta=1.0)
        self.assertEqual(len(checks["required_teams"]), 2)
        no_key = {k: v for k, v in lu.items() if k != "salary"}
        result = sd.certify_showdown(no_key, df)
        self.assertFalse(result["passed"])
        self.assertIn("no salary key", " ".join(result["errors"]))
        lying = {**lu, "salary": 1.0}
        self.assertFalse(sd.certify_showdown(lying, df)["passed"])

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


def _one_captain_pool():
    """A pool where the captain cap binds and the overlap bound need not.

    Only AA_Star is affordable at CPT salary -- everyone else's captain price
    alone busts the 50000 cap -- so from the second slot on the captain cap must
    relax. Twelve players leave room for overlap-distinct rosters underneath,
    which is what makes this pool able to tell the two relaxations apart. That
    separation is the whole point: on a pool where both must give way at once,
    a counter that credits the wrong control looks correct.
    """
    rows = [_p("AA_Star|AA", "AA", 40, 5000, 7500, "1001", "2001")]
    for i in range(5):
        rows.append(_p(f"AA_{i}|AA", "AA", 10 - i * 0.5, 3000, 49000,
                       f"11{i:02d}", f"21{i:02d}"))
    for i in range(6):
        rows.append(_p(f"BB_{i}|BB", "BB", 10 - i * 0.4, 3000, 49000,
                       f"12{i:02d}", f"22{i:02d}"))
    return pd.DataFrame(rows)


def _assert_counts_match_the_bank(case, bank, diag, share_cap):
    """R54/R79(c). The counters, checked against the artifact they describe.

    Key-presence assertions are what let the uncounted overlap drop survive: both
    ``+= 1`` lines could be deleted and the suite stayed green. These are
    biconditionals, so they fail in both directions -- a counter that under-counts
    a real relaxation AND a counter that claims one that did not happen.
    """
    counts = collections.Counter(l["captain"]["player_key"] for l in bank)
    case.assertEqual(diag["overlap_relaxed_slots"] == 0,
                     _max_pairwise_overlap(bank) <= share_cap,
                     f"overlap counter {diag['overlap_relaxed_slots']} disagrees "
                     f"with a delivered max overlap of "
                     f"{_max_pairwise_overlap(bank)} against a cap of {share_cap}")
    cap_count = diag.get("cap_count")
    if cap_count:
        case.assertEqual(diag["relaxed_slots"] == 0,
                         max(counts.values(), default=0) <= cap_count,
                         f"captain counter {diag['relaxed_slots']} disagrees with "
                         f"a realized max of {max(counts.values(), default=0)} "
                         f"against a cap count of {cap_count}")


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
        certification. Relaxing a diversity control is the lesser failure.

        R54/R79(c): this used to assert only that the counter KEYS existed, so
        deleting both ``+= 1`` lines kept it green. The counts are asserted
        against the delivered bank now, by _assert_counts_match_the_bank.
        """
        df = _synth()                       # 7 players, almost no legal variety
        diag = {}
        bank = sd.build_showdown_bank(df, 6, diagnostics=diag, time_limit=4,
                                      max_shared_players=4)
        self.assertGreater(len(bank), 0)
        _assert_counts_match_the_bank(self, bank, diag, share_cap=4)

    # ---- R54 ----------------------------------------------------------- #
    def test_the_captain_relax_rung_no_longer_drops_the_overlap_bound(self):
        """R54(a). The reproduced lie, pinned as an invariant.

        The old rung 3 re-solved without ``max_shared_players`` AND without the
        captain cap while incrementing only the captain counter, so a bank
        shipped at 5-of-6 pairwise overlap reporting
        ``overlap_relaxed_slots: 0``. Measured on this pool 2026-08-10: old code
        max overlap 5 with ovl 0; new code max overlap 4 with ovl 0.

        Teeth: dropping ``max_shared_players=max_shared_players`` from the
        captain-relax call restores overlap 5 and fails the bound assertion,
        while the counter still reads 0 and fails the invariant.
        """
        df = _one_captain_pool()
        diag = {}
        bank = sd.build_showdown_bank(df, 4, diagnostics=diag, time_limit=5,
                                      max_shared_players=4)
        self.assertEqual(len(bank), 4)
        # The captain cap genuinely binds here: only one player is affordable at
        # CPT salary, so the cap must relax and the relaxation must be counted.
        self.assertEqual(diag["cap_count"], 1)
        self.assertGreater(diag["relaxed_slots"], 0)
        # And the control that was NOT relaxed held.
        self.assertLessEqual(_max_pairwise_overlap(bank), 4)
        self.assertEqual(diag["overlap_relaxed_slots"], 0)
        _assert_counts_match_the_bank(self, bank, diag, share_cap=4)

    def test_the_bank_ladder_counts_a_both_relaxed_solve_in_every_true_place(self):
        """R54(a). The fourth rung exists and is counted honestly.

        ``both_relaxed_slots`` is a subset of the other two, because those answer
        "how many lineups were built WITHOUT this control" rather than "which
        rung fired" -- the first question is the one the brief's clean/relaxed
        claim rests on.
        """
        df = _synth()
        diag = {}
        bank = sd.build_showdown_bank(df, 8, diagnostics=diag, time_limit=4,
                                      max_shared_players=4)
        self.assertGreater(len(bank), 0)
        both = diag["both_relaxed_slots"]
        self.assertLessEqual(both, diag["overlap_relaxed_slots"])
        self.assertLessEqual(both, diag["relaxed_slots"])
        self.assertLessEqual(diag["overlap_relaxed_slots"], len(bank))
        self.assertLessEqual(diag["relaxed_slots"], len(bank))
        _assert_counts_match_the_bank(self, bank, diag, share_cap=4)

    def test_a_lock_the_pool_does_not_carry_is_reported_not_swallowed(self):
        """R54(c). A typo'd or melt-dropped lock used to no-op in total silence:
        the whole bank built without the player and the ladder's cpt_counts
        accounted against captains that were never enforced.

        Teeth: an assertion on the LINEUP would pass with the lock silently
        dropped, because the lineup is legal either way. The fact under test is
        that the engine SAID so.
        """
        df = _synth()
        lu = sd.build_showdown_lineup(df, locks=["NOT_IN_POOL|ZZ"], time_limit=4)
        self.assertIsNotNone(lu)
        self.assertEqual(lu["ignored_locks"], ["NOT_IN_POOL|ZZ"])
        clean = sd.build_showdown_lineup(df, locks=["AA_Star|AA"], time_limit=4)
        self.assertEqual(clean["ignored_locks"], [])
        # A captain lock is tagged, so the two kinds are distinguishable.
        cpt = sd.build_showdown_lineup(df, cpt_lock="NOT_IN_POOL|ZZ", time_limit=4)
        self.assertEqual(cpt["ignored_locks"], ["cpt:NOT_IN_POOL|ZZ"])
        # And it reaches the bank diagnostics, which is what the brief reads.
        diag = {}
        sd.build_showdown_bank(df, 2, diagnostics=diag, time_limit=4,
                               locks=["NOT_IN_POOL|ZZ"])
        self.assertEqual(diag["ignored_locks"], ["NOT_IN_POOL|ZZ"])

    def test_the_out_status_vocabulary_is_shared_with_preflight(self):
        """R54(d). The melt shelved IL/O/OUT/NA while preflight also shelved
        IL10/IL15/IL60/PUP/SUSP, so an IL60 player built into the bank and died
        at preflight -- two implementations of one rule, the class R34 pinned
        elsewhere. Preflight imports nothing from the engine by contract, so this
        is a mirror pinned in sync rather than a shared import."""
        from tools.preflight_upload import OUT_STATUSES as preflight_set
        self.assertEqual(sd.OUT_STATUSES, preflight_set)
        for shelved in ("IL60", "PUP", "SUSP", "IL10", "IL15"):
            self.assertIn(shelved, sd.OUT_STATUSES)


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

    def test_the_thesis_ladder_has_the_bank_ladder_s_fourth_rung(self):
        """R54(b). ``solve_ladder`` never tried overlap+captain relaxed together
        while ``build_showdown_bank`` did, so a thesis solvable only under both
        returned None and left a blank reserved row -- write-blocked at T-5 -- on
        a pool the bank path fills. Two ladders over one solver disagreeing about
        how far they will bend is the same defect class as two readers of one
        token set.

        Teeth: deleting the fourth rung takes ``both_relaxed`` to 0 and pushes
        that thesis into ``infeasible``, failing both assertions. Deleting only
        the three counter increments fails the accounting assertion, which is
        the R79(c) hole this closes.
        """
        df = _synth()                       # 7 players, almost no legal variety
        theses = [{"cpt": "AA_Star|AA", "name": f"t{i}"} for i in range(8)]
        diag = {}
        out = st.solve_ladder(df, theses, max_shared_players=4, time_limit=4,
                              diagnostics=diag)
        self.assertGreaterEqual(diag["both_relaxed"], 1,
                                "the fourth rung never fired on a pool built to "
                                "need it; the scenario, not the fix, is stale")
        solved = [l for l in out if l is not None]
        self.assertEqual(len(solved) + diag["infeasible"], len(theses))
        # Counted in every place it is true, matching build_showdown_bank.
        self.assertLessEqual(diag["both_relaxed"], diag["overlap_relaxed"])
        self.assertLessEqual(diag["both_relaxed"], diag["captain_lock_relaxed"])

    def test_lock_relaxation_detail_names_the_thesis_and_substituted_captain(self):
        """R113. The caution built from this counter has to say WHICH thesis
        lost its assigned captain and to WHOM -- a count alone reads exactly
        like a captain-CAP relaxation, and ``captain_exposure.by_player``
        cannot show a lock substitution because it is not an exposure event.
        """
        df = _synth()
        theses = [{"cpt": "AA_Star|AA", "name": f"t{i}"} for i in range(8)]
        diag = {}
        st.solve_ladder(df, theses, max_shared_players=4, time_limit=4, diagnostics=diag)
        self.assertGreaterEqual(diag["captain_lock_relaxed"], 1)
        detail = diag["lock_relaxation_detail"]
        self.assertEqual(len(detail), diag["captain_lock_relaxed"])
        for entry in detail:
            self.assertTrue(entry["thesis"].startswith("t"), entry)
            self.assertEqual(entry["requested"], "AA_Star|AA")
            self.assertNotIn(entry["actual"], ("AA_Star|AA", "?"),
                             "a lock relaxation that kept the requested captain "
                             "or recorded no substitute pins nothing real")

    def test_a_thesis_lock_outside_the_pool_reaches_the_ladder_diagnostics(self):
        """R54(c), the ladder half: the ignored lock has to survive the trip from
        one solve into the diagnostics dict the brief reads."""
        df = _synth()
        diag = {}
        st.solve_ladder(df, [{"cpt": "GHOST|ZZ", "name": "t0"}], time_limit=4,
                        diagnostics=diag)
        self.assertEqual(diag["ignored_locks"], ["cpt:GHOST|ZZ"])

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


# --------------------------------------------------------------------------
# R29(5): the odds fetch reported "no moneyline matched" on a priced game
# --------------------------------------------------------------------------

def _skill_games_payload():
    """The mlb-game-odds skill's DEFAULT output shape (no --raw).

    TEX@TB from 2026-07-29, the build that reported no moneyline while the
    market had it TB -144 / TEX +122 the whole time.
    """
    return {
        "fetched_at": "2026-07-29T22:00:00Z",
        "date": "2026-07-29",
        "sport": "baseball_mlb",
        "games": [{
            "event_id": "abc123",
            "commence_time_utc": "2026-07-29T22:40:00Z",
            "commence_time_et": "2026-07-29T18:40:00-04:00",
            "home_team": "Tampa Bay Rays",
            "away_team": "Texas Rangers",
            "books": {
                "draftkings": {
                    "last_update": "2026-07-29T21:59:00Z",
                    "moneyline": {"home": -144, "away": 122},
                    "spread": {"home_line": -1.5, "home_price": 130,
                               "away_line": 1.5, "away_price": -155},
                    "total": {"line": 7.5, "over": -105, "under": -115},
                },
                "fanduel": {
                    "last_update": "2026-07-29T21:58:00Z",
                    "moneyline": {"home": -142, "away": 120},
                    "total": {"line": 7.5, "over": -104, "under": -116},
                },
            },
        }],
        "quota": {"remaining": 480},
    }


class OddsPayloadShapeTests(unittest.TestCase):
    """R29(5b): every shape this project produces feeds one parser.

    Teeth: load_odds_packet recognised a bare list plus odds_raw_totals / raw /
    events / odds, and the skill's default output is keyed ``games``. It fell
    through silently and the caller reported the same "no moneyline matched this
    game's teams" that an unposted market produces, so a 50/50 thesis allocation
    looked like missing data instead of a parsing bug.
    """

    def setUp(self):
        from mlb_engine.intake import live_data_adapters as lda
        self.lda = lda

    def test_the_skill_default_games_schema_is_recognised(self):
        events, shape = self.lda.normalize_odds_payload(_skill_games_payload())
        self.assertEqual(shape, "mlb_game_odds_games")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["home_team"], "Tampa Bay Rays")

    def test_the_games_schema_parses_to_the_same_moneyline_the_market_had(self):
        events, _ = self.lda.normalize_odds_payload(_skill_games_payload())
        parsed = self.lda.parse_the_odds_api_totals(events)
        entry = parsed["odds_by_game_id"]["TEX@TB"]
        self.assertEqual(entry["total"], 7.5)
        # Median across DK -144 and FD -142; TEX median of 122 and 120.
        self.assertEqual(entry["moneyline"]["TB"], -143.0)
        self.assertEqual(entry["moneyline"]["TEX"], 121.0)

    def test_the_raw_flag_output_still_parses_identically(self):
        """--raw wraps the API's own events under 'raw'. Both routes must agree,
        or one of them is a second answer to the same question."""
        payload = _skill_games_payload()
        converted, _ = self.lda.normalize_odds_payload(payload)
        wrapped, shape = self.lda.normalize_odds_payload({"raw": converted})
        self.assertEqual(shape, "wrapped:raw")
        self.assertEqual(
            self.lda.parse_the_odds_api_totals(converted)["odds_by_game_id"],
            self.lda.parse_the_odds_api_totals(wrapped)["odds_by_game_id"])

    def test_a_bare_events_list_and_every_wrapper_key_still_work(self):
        events, _ = self.lda.normalize_odds_payload(_skill_games_payload())
        self.assertEqual(self.lda.normalize_odds_payload(events)[1],
                         "raw_events_list")
        for key in ("odds_raw_totals", "raw", "events", "odds"):
            self.assertEqual(
                self.lda.normalize_odds_payload({key: events})[1], f"wrapped:{key}")

    def test_an_unrecognised_shape_raises_naming_what_it_found(self):
        with self.assertRaises(ValueError) as caught:
            self.lda.normalize_odds_payload({"lines": [], "fetched_at": "x"})
        message = str(caught.exception)
        self.assertIn("lines", message)
        self.assertIn("games", message)
        self.assertNotIn("no moneyline", message)

    def test_a_game_with_no_total_market_keeps_its_moneyline_out_of_the_packet(self):
        """Documented, not desired: parse_the_odds_api_totals drops an event with
        no totals market, moneyline included. The converter must not paper over
        that, because the packet's contract is keyed on the total."""
        payload = _skill_games_payload()
        for book in payload["games"][0]["books"].values():
            book.pop("total", None)
        events, _ = self.lda.normalize_odds_payload(payload)
        parsed = self.lda.parse_the_odds_api_totals(events)
        self.assertEqual(parsed["odds_by_game_id"], {})

    def test_a_malformed_games_entry_raises_ValueError_and_nothing_else(self):
        """The caller on the Classic path catches ValueError only, so anything
        else escaping here is a traceback out of a live build. Every one of
        these raised AttributeError or TypeError before the guards."""
        cases = {
            "books is a list": {"books": []},
            "books is a string": {"books": "draftkings"},
            "moneyline is a string": {"books": {"dk": {"moneyline": "-144"}}},
            "moneyline is a list": {"books": {"dk": {"moneyline": [-144, 122]}}},
            "spread is a number": {"books": {"dk": {"spread": 1.5}}},
            "total is a string": {"books": {"dk": {"total": "7.5"}}},
        }
        for label, overrides in cases.items():
            payload = _skill_games_payload()
            payload["games"][0].update(overrides)
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    self.lda.normalize_odds_payload(payload)

    def test_a_games_entry_missing_teams_degrades_rather_than_raising(self):
        """Absent is not malformed. A game with no team names converts to an
        event the parser simply cannot map, which it already reports."""
        payload = _skill_games_payload()
        payload["games"][0].pop("home_team")
        payload["games"][0].pop("away_team")
        events, _ = self.lda.normalize_odds_payload(payload)
        parsed = self.lda.parse_the_odds_api_totals(events)
        self.assertEqual(parsed["odds_by_game_id"], {})

    def test_an_empty_or_absent_books_object_is_not_an_error(self):
        for value in ({}, None):
            payload = _skill_games_payload()
            payload["games"][0]["books"] = value
            events, _ = self.lda.normalize_odds_payload(payload)
            self.assertEqual(events[0]["bookmakers"], [])

    def test_mixed_type_book_keys_sort_deterministically_rather_than_raising(self):
        """A non-string book key is odd but harmless, and sorting tuples of mixed
        types raises TypeError, which the caller does not catch. Sort on str."""
        payload = _skill_games_payload()
        payload["games"][0]["books"] = {
            "draftkings": {"moneyline": {"home": -144, "away": 122},
                           "total": {"line": 7.5, "over": -105, "under": -115}},
            7: {"total": {"line": 8.0, "over": -110, "under": -110}},
        }
        events, _ = self.lda.normalize_odds_payload(payload)
        self.assertEqual([b["key"] for b in events[0]["bookmakers"]],
                         ["7", "draftkings"])

    def test_spreads_survive_the_round_trip(self):
        events, _ = self.lda.normalize_odds_payload(_skill_games_payload())
        dk = next(b for b in events[0]["bookmakers"] if b["key"] == "draftkings")
        spreads = next(m for m in dk["markets"] if m["key"] == "spreads")
        by_name = {o["name"]: o for o in spreads["outcomes"]}
        self.assertEqual(by_name["Tampa Bay Rays"]["point"], -1.5)
        self.assertEqual(by_name["Texas Rangers"]["price"], -155)


class OddsKeyResolutionTests(unittest.TestCase):
    """R29(5a): the key resolves from REPO/.env, not the environment alone."""

    def setUp(self):
        from mlb_engine import repo_env
        self.repo_env = repo_env

    def test_the_environment_wins_when_it_is_set(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("THE_ODDS_API_KEY=from_file\n", encoding="utf-8")
            with unittest.mock.patch.dict(
                    os.environ, {"THE_ODDS_API_KEY": "from_env"}, clear=False):
                self.assertEqual(
                    self.repo_env.resolve_odds_api_key(env_file), "from_env")

    def test_the_repo_dotenv_is_the_fallback(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                '# a comment\n\nTHE_ODDS_API_KEY="from_file"\nOTHER=x\n',
                encoding="utf-8")
            environ = dict(os.environ)
            environ.pop("THE_ODDS_API_KEY", None)
            with unittest.mock.patch.dict(os.environ, environ, clear=True):
                self.assertEqual(
                    self.repo_env.resolve_odds_api_key(env_file), "from_file")

    def test_an_empty_environment_value_does_not_mask_the_file(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("THE_ODDS_API_KEY=real\n", encoding="utf-8")
            with unittest.mock.patch.dict(
                    os.environ, {"THE_ODDS_API_KEY": "   "}, clear=False):
                self.assertEqual(
                    self.repo_env.resolve_odds_api_key(env_file), "real")

    def test_a_missing_file_resolves_to_none_rather_than_raising(self):
        import os
        environ = dict(os.environ)
        environ.pop("THE_ODDS_API_KEY", None)
        with unittest.mock.patch.dict(os.environ, environ, clear=True):
            self.assertIsNone(
                self.repo_env.resolve_odds_api_key(Path("/nonexistent/.env")))

    def test_loading_returns_names_never_values(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("A_SECRET_NAME=supersecret\n", encoding="utf-8")
            environ = dict(os.environ)
            environ.pop("A_SECRET_NAME", None)
            with unittest.mock.patch.dict(os.environ, environ, clear=True):
                loaded = self.repo_env.load_repo_dotenv(env_file)
            self.assertEqual(loaded, ["A_SECRET_NAME"])
            self.assertNotIn("supersecret", repr(loaded))

    def test_the_repo_env_is_where_the_key_lives_and_both_tools_use_it(self):
        bundle = (REPO / "tools" / "fetch_slate_bundle.py").read_text(encoding="utf-8")
        build = (REPO / "skills" / "generate-lineups" / "scripts"
                 / "build_slate.py").read_text(encoding="utf-8")
        self.assertIn("from mlb_engine.repo_env import load_repo_dotenv", bundle)
        self.assertIn("resolve_odds_api_key", build)
        self.assertNotIn('os.environ.get("THE_ODDS_API_KEY")', build,
                         "the environment-only read is what made the key invisible")


class OddsFailureMessageTests(unittest.TestCase):
    """R29(5): four different causes used to produce one sentence."""

    def test_the_generic_unmatched_message_is_gone(self):
        build = (REPO / "skills" / "generate-lineups" / "scripts"
                 / "build_slate.py").read_text(encoding="utf-8")
        self.assertNotIn('warning="no moneyline matched this game\'s teams; entries "',
                         build)
        self.assertIn("no moneyline for this game ({reason})", build)

    def test_each_cause_names_itself(self):
        build = (REPO / "skills" / "generate-lineups" / "scripts"
                 / "build_slate.py").read_text(encoding="utf-8")
        for phrase in ("odds file shape not recognised", "REPO/.env",
                       "resolved to zero games", "none had a moneyline"):
            self.assertIn(phrase, build)


if __name__ == "__main__":
    unittest.main(verbosity=2)
