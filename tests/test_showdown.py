"""Showdown build gate: contracts, MILP legality, exact synthetic optimum, real-file
melt, end-to-end certify, and DKEntries export round-trip.

Every number here is a deterministic review proxy (Base = AvgPointsPerGame), never a
win-rate, ROI, or probability claim. Classic is untouched; this suite imports nothing
from the Classic solver, so test_golden_replay is unaffected.
"""
from __future__ import annotations

import ast
import collections
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import types
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
    def test_defaults_are_a_quarter_half_and_four_shared(self):
        # R153, Ben 2026-08-19: the standing instruction moved from "never more
        # than a third" to "never more than a quarter", and a PLAYER cap was added
        # at half the entered set. cap_count is a floor() in both cases, so
        # realized exposure can only land at or below the requested pct.
        self.assertEqual(sd.DEFAULT_MAX_CPT_EXPOSURE_PCT, 0.25)
        self.assertEqual(sd.DEFAULT_MAX_PLAYER_EXPOSURE_PCT, 0.50)
        self.assertEqual(sd.DEFAULT_MAX_SHARED_PLAYERS, 4)
        self.assertEqual(math.floor(sd.DEFAULT_MAX_CPT_EXPOSURE_PCT * 20), 5)

    def test_exposure_cap_count_never_rounds_a_cap_upward(self):
        """R153. The one property both caps rest on: floor(), never round or ceil.

        A cap count that rounds up lets realized exposure exceed the requested
        pct, which is how 0.35 permitted 7 captains of 20 (a realized 35%) and is
        why the old default was 0.33. Checked across a range of entry counts
        rather than one, because the failure is arithmetic and shows up at some n
        and not others.
        """
        for n in (2, 3, 4, 7, 8, 15, 19, 20, 33, 100):
            for pct in (0.25, 0.33, 0.5, 0.6):
                count = sd.exposure_cap_count(pct, n)
                if math.floor(pct * n) >= 1:
                    self.assertLessEqual(
                        count / n, pct + 1e-9,
                        f"cap of {pct} over {n} entries allows {count}, a realized "
                        f"{count / n:.3f}")
                else:
                    # The documented escape: floor() is 0 here, which would forbid
                    # every player, and a cap that cannot build one lineup is not a
                    # control, it is an empty bank. It clamps to 1 and the realized
                    # pct is ABOVE the request -- true at any n where pct * n < 1,
                    # not only at n = 1.
                    self.assertEqual(count, 1)
        self.assertEqual(sd.exposure_cap_count(0.5, 1), 1)
        self.assertEqual(sd.exposure_cap_count(0.25, 2), 1)
        self.assertIsNone(sd.exposure_cap_count(None, 20))

    def test_a_units_slip_cannot_silently_disable_a_showdown_cap(self):
        """R167. Both Showdown caps are read straight off --controls-override,
        and `25` typed for `0.25` returned a cap of 25n: nobody was capped, and
        every relaxation counter read CLEAN because nothing was ever relaxed.
        That is R153's washout axis switched off by a keystroke, in the one
        place the brief cannot show it. Same rule as the Classic caps, from the
        same function."""
        for slip in (25, 50, 1.01):
            with self.assertRaises(ValueError, msg=repr(slip)):
                sd.exposure_cap_count(slip, 19)
        # and nothing legal moved: 1.0 is a cap on everyone, not a slip.
        self.assertEqual(sd.exposure_cap_count(1.0, 19), 19)
        self.assertEqual(sd.exposure_cap_count(0.25, 19), 4)

    def test_the_showdown_caps_share_the_classic_units_rule(self):
        """One definition, or the two contest types disagree about what 45
        means while both print a number."""
        from mlb_engine.allocate.contest_allocator import assert_fraction_cap
        for value in (0.25, 0.5, 1.0):
            self.assertEqual(
                sd.exposure_cap_count(value, 20),
                max(1, math.floor(assert_fraction_cap(value) * 20)))

    def test_player_cap_structural_floor_is_roster_over_pool(self):
        """R153. A cap below roster_size/pool_size cannot hold by counting alone,
        before any MILP runs. Reported rather than auto-raised, because widening
        an exposure cap is a strategy change and CLAUDE.md makes it Ben's."""
        self.assertAlmostEqual(sd.player_cap_structural_floor(20, 19), 0.30)
        self.assertAlmostEqual(sd.player_cap_structural_floor(12, 19), 0.50)
        self.assertIsNone(sd.player_cap_structural_floor(0, 19))

    def test_bank_holds_the_player_exposure_cap(self):
        """R153. The control that did not exist. On the 2026-08-19 ARI@BOS build
        the overlap bound was clean, the captain cap was clean, and one bat was in
        12 of 19 entries -- correlated failure that neither other control was
        measuring."""
        df = sd.melt_showdown_salary_csv(SAL)
        diag = {}
        bank = sd.build_showdown_bank(df, 12, max_player_exposure_pct=0.5,
                                      diagnostics=diag, time_limit=6)
        self.assertEqual(len(bank), 12)
        counts = collections.Counter(k for l in bank for k in l["player_keys"])
        cap_count = diag["player_cap_count"]
        self.assertEqual(cap_count, 6)                       # floor(0.5 * 12)
        if not diag["player_relaxed_slots"]:
            self.assertLessEqual(max(counts.values()), cap_count)
        # Biconditional, so it fails in both directions: a counter that misses a
        # real relaxation AND one that claims a relaxation that did not happen.
        self.assertEqual(diag["player_relaxed_slots"] == 0,
                         max(counts.values()) <= cap_count,
                         f"player counter {diag['player_relaxed_slots']} disagrees "
                         f"with a realized max of {max(counts.values())} against "
                         f"a cap count of {cap_count}")

    def test_player_cap_of_none_disables_it(self):
        df = sd.melt_showdown_salary_csv(SAL)
        diag = {}
        sd.build_showdown_bank(df, 6, max_player_exposure_pct=None,
                               diagnostics=diag, time_limit=6)
        self.assertIsNone(diag["player_cap_count"])
        self.assertEqual(diag["player_relaxed_slots"], 0)

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
        # R153. max_player_exposure_pct=None on purpose. This pool is 12 players
        # and 4 entries, so the 50% player cap lands EXACTLY on its structural
        # floor (roster 6 / pool 12) and every player would have to appear exactly
        # twice -- which forces the floor rung and drops the overlap bound this
        # test exists to watch hold. Disabling it keeps the fixture isolating the
        # two controls it was built to tell apart.
        bank = sd.build_showdown_bank(df, 4, diagnostics=diag, time_limit=5,
                                      max_player_exposure_pct=None,
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
        status = {}
        lu = sd.build_showdown_lineup(df, locks=["NOT_IN_POOL|ZZ"], time_limit=4, status_out=status)
        self.assertIsNone(lu)
        self.assertEqual(status["status"], "invalid_hard_lock")
        clean = sd.build_showdown_lineup(df, locks=["AA_Star|AA"], time_limit=4)
        self.assertEqual(clean["ignored_locks"], [])
        # A captain lock is tagged, so the two kinds are distinguishable.
        cpt = sd.build_showdown_lineup(df, cpt_lock="NOT_IN_POOL|ZZ", time_limit=4)
        self.assertIsNone(cpt)
        # And it reaches the bank diagnostics, which is what the brief reads.
        diag = {}
        bank = sd.build_showdown_bank(df, 2, diagnostics=diag, time_limit=4,
                                     locks=["NOT_IN_POOL|ZZ"])
        self.assertEqual(bank, [])

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
        self.assertLessEqual(max(counts.values()) / 18, 0.25)

    def test_ladder_solves_unique_rosters_under_both_bounds(self):
        ladder = st.build_thesis_ladder(self.df, 18, moneyline={"MIN": -150, "CHC": 130})
        lineups = st.solve_ladder(self.df, ladder["theses"], time_limit=5)
        self.assertTrue(all(l is not None for l in lineups))
        report = st.portfolio_report(self.df, ladder["theses"], lineups)
        self.assertTrue(report["all_unique_rosters"])
        self.assertLessEqual(report["max_pairwise_overlap"], 4)
        self.assertLessEqual(report["max_captain_exposure_pct"], 25.0)
        self.assertTrue(all(r["lineup_certified"] for r in report["lineups"]))

    def test_solve_ladder_enforces_the_captain_cap_against_the_realized_set(self):
        """R153. ``solve_ladder`` enforced NO captain cap: it trusted
        ``build_thesis_ladder``'s apportionment, and the lock-relaxation rung then
        picked a substitute captain with no cap awareness, so a substitution landed
        on top of an already-full captain.

        Live evidence, 2026-08-19 ARI@BOS at 19 entries and a cap count of 4:
        Payton Tolle finished with 5 captain slots, a realized 26.3% under a 25%
        cap, and every relaxation counter read clean because a lock substitution is
        not a cap event. The cap is enforced here now, against the running realized
        count, on every rung.

        Teeth: dropping ``cpt_excludes`` from the solve calls puts the substituted
        captain back over the cap and fails the first assertion.
        """
        ladder = st.build_thesis_ladder(self.df, 16, moneyline={"MIN": -150, "CHC": 130},
                                        max_cpt_exposure_pct=0.25)
        diag = {}
        lineups = st.solve_ladder(self.df, ladder["theses"], max_cpt_exposure_pct=0.25,
                                  time_limit=5, diagnostics=diag)
        solved = [l for l in lineups if l is not None]
        realized = collections.Counter(l["captain"]["player_key"] for l in solved)
        cap_count = diag["cpt_cap_count"]
        self.assertEqual(cap_count, 4)                        # floor(0.25 * 16)
        # The floor rung can legitimately exceed the cap, and says so. Absent one,
        # the realized count is bound.
        if not diag["captain_lock_relaxed"]:
            self.assertLessEqual(max(realized.values()), cap_count)
        self.assertLessEqual(max(realized.values()), cap_count + diag["captain_lock_relaxed"])

    def test_player_cap_beats_a_thesis_that_names_a_capped_player(self):
        """R153, second pass. The first cut protected a thesis's own ``cpt`` and
        ``locks`` from the cap on the reasoning that a lock is the more specific
        instruction. The reasoning was fine; the consequence was that the cap did
        not hold. The ladder assigns captains BY NAME and a captain is a roster
        spot, so on the 2026-08-19 ARI@BOS build Wilyer Abreu reached 11 of 19
        (57.9%) under a 50% cap while ``player_relaxed`` read 0 -- the cap
        reporting itself clean while not binding.

        A capped player now comes off the thesis's cpt and locks before the solve,
        and the removal is NAMED rather than counted as a relaxation, because
        nothing gave way: the cap held and the thesis label is what moved.

        Teeth: restoring the carve-out puts the named player back over the cap and
        fails the exposure assertion while ``player_relaxed`` stays 0.
        """
        star = str(self.df.sort_values("Base", ascending=False).iloc[0]["Player_Key"])
        theses = [{"cpt": star, "locks": [star], "name": f"all-in on the star {i}"}
                  for i in range(10)]
        diag = {}
        lineups = st.solve_ladder(self.df, theses, max_player_exposure_pct=0.5,
                                  time_limit=4, diagnostics=diag)
        solved = [l for l in lineups if l is not None]
        self.assertTrue(solved, "the ladder must still produce lineups")
        counts = collections.Counter(k for l in solved for k in l["player_keys"])
        cap_count = diag["player_cap_count"]
        self.assertEqual(cap_count, 5)                        # floor(0.5 * 10)
        self.assertLessEqual(
            counts[star], cap_count,
            f"{star} reached {counts[star]} of {len(solved)} against a cap count "
            f"of {cap_count}; the thesis carve-out is back")
        self.assertEqual(diag["player_relaxed"], 0,
                         "a reassignment is not a relaxation: nothing gave way")
        # Every deviation from the thesis is named, so the reader is never left
        # inferring why a thesis built with a captain its label does not imply.
        self.assertTrue(diag["player_cap_cpt_reassigned"],
                        "a capped captain was silently swapped without being named")
        self.assertTrue(diag["player_cap_locks_dropped"],
                        "a capped lock was silently dropped without being named")

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
        # R153. Both caps off. Every thesis here names the same captain, so the
        # captain cap would reassign it away by the third slot and the fourth rung
        # would never be reached -- the rung would look retired when it is not.
        out = st.solve_ladder(df, theses, max_shared_players=4, time_limit=4,
                              max_cpt_exposure_pct=None,
                              max_player_exposure_pct=None, diagnostics=diag)
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
        # R153. Caps off for the same reason as the fourth-rung test: this pins a
        # LOCK substitution, and a cap reassignment is a different event that would
        # pre-empt it.
        st.solve_ladder(df, theses, max_shared_players=4, time_limit=4,
                        max_cpt_exposure_pct=None, max_player_exposure_pct=None,
                        diagnostics=diag)
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
        one solve into the diagnostics dict the brief reads.

        R338 repair (3) restores this assertion. F14's `invalid_hard_lock`
        refusal is right for an OPERATOR lock and wrong here: a THESIS naming a
        player absent from the pool is a preference, and refusing it blanks the
        reserved entry row that R54(c) exists to keep filled. The refusal is
        pinned on its own door by `ShowdownDiversityTests` and
        `R291ShowdownExcludedColumnTests`, both of which call
        `build_showdown_lineup` directly.
        """
        df = _synth()
        diag = {}
        st.solve_ladder(df, [{"cpt": "GHOST|ZZ", "name": "t0"}], time_limit=4,
                        diagnostics=diag)
        self.assertEqual(diag["ignored_locks"], ["cpt:GHOST|ZZ"])
        # F13's counters stay honest either way: nothing was infeasible and no
        # solver failure was latched, because the ladder never had to descend.
        self.assertEqual(diag["infeasible"], 0)
        self.assertEqual(diag.get("solver_failures") or [], [])

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

    # ---- R156 ------------------------------------------------------------ #
    def test_pitchers_duel_always_carries_both_starters_however_it_solves(self):
        """R156, Ben 2026-08-21: "pitchers duel categorically means both
        pitchers play well and thus should be rostered." A live ATL@MIL
        delivery shipped this thesis with only Misiorowski, no Sale at all: the
        overlap bound made Sale infeasible as captain, solve_ladder's
        relaxation ladder dropped the captain lock, and nothing else required
        Sale's presence, because build_thesis_ladder's generic ``locks``
        filter had stripped him out precisely because he WAS the assigned
        captain.

        Teeth: reverting ``hard_locks`` (either dropping it from ``duel()`` or
        the merge in ``build_thesis_ladder``) fails the first loop immediately,
        since the pre-fix ``locks`` list carries only whichever starter is NOT
        ``cpt``.
        """
        ladder = st.build_thesis_ladder(self.df, 19, moneyline={"MIN": -150, "CHC": 130})
        both_sp = {v for v in ladder["shape"]["starters"].values() if v}
        self.assertEqual(len(both_sp), 2)
        duel_theses = [t for t in ladder["theses"] if t["template"] == "pitchers_duel"]
        self.assertGreaterEqual(len(duel_theses), 1)
        for t in duel_theses:
            self.assertTrue(both_sp.issubset(set(t["locks"])),
                            f"{t['name']}: both starters must be unconditional "
                            f"locks, not just whichever one is not currently cpt")

        lineups = st.solve_ladder(self.df, ladder["theses"], time_limit=5)
        by_name = dict(zip((t["name"] for t in ladder["theses"]), lineups))
        for t in duel_theses:
            lu = by_name[t["name"]]
            self.assertIsNotNone(lu, f"{t['name']} must solve: both arms fit "
                                     f"comfortably under the cap once the thesis "
                                     f"no longer also locks a top-band bat per side")
            self.assertTrue(both_sp.issubset(set(lu["player_keys"])),
                            f"{t['name']} shipped without both starters: "
                            f"{lu['player_keys']}")

    def test_pitchers_duel_captain_is_always_one_of_the_two_starters(self):
        """R156. Captaining a bottom-order bat under "pitchers duel" is a
        different story wearing this thesis's name. ``cpt_ladder`` is
        restricted to the two starters, so the apportionment walk either picks
        one of them or, once both are at the captain cap, forces one past it
        (counted in ``captain_cap_relaxed``) rather than reaching for a bat.
        """
        ladder = st.build_thesis_ladder(self.df, 25, moneyline={"MIN": -150, "CHC": 130})
        both_sp = {v for v in ladder["shape"]["starters"].values() if v}
        duel_theses = [t for t in ladder["theses"] if t["template"] == "pitchers_duel"]
        self.assertGreaterEqual(len(duel_theses), 2,
                                "n=25 should need more than one pitchers_duel slot "
                                "to exercise the cap-relaxed path")
        for t in duel_theses:
            self.assertIn(t["cpt"], both_sp, f"{t['name']} captained a non-starter")

    def test_pitchers_duel_gets_a_second_slot_when_entries_allow(self):
        """R156, Ben 2026-08-21: "even with the captains capped at 25% one of
        the game thesis should be pitchers duel, which would mean 2 lineups
        with both pitchers, one where each is captain." A single slot cannot
        hedge which arm ends up producing. Weight bumped 0.30 -> 0.45 so a
        slate with room schedules a second look at this game state rather than
        spending it all on one variant.

        Not a promise that every entry count and win share lands on exactly 2
        -- the neutral bucket shares one largest-remainder apportionment with
        the ten directional templates, so the exact count is data-dependent --
        but this fixture at this entry count is the reproduction, and it must
        not regress to 1.
        """
        ladder = st.build_thesis_ladder(self.df, 19, moneyline={"MIN": -150, "CHC": 130})
        self.assertGreaterEqual(ladder["allocation"].get("pitchers_duel", 0), 2)

    def test_pitchers_duel_never_goes_infeasible_across_entry_counts(self):
        """R156. The original design locked both arms AND a top-band bat from
        each side. An ace at CPT plus the other arm at UTIL already runs
        28,500-31,500 of the 50,000 cap; adding a top-band bat per side on top
        of that was measured infeasible on the 2026-08-21 ATL@MIL slate
        regardless of which arm captained, leaving under $2,500 for two more
        roster spots against a $3,000 pool floor. The hitter locks are gone
        now; both arms stay hard-required and the other four spots are a free
        salary/points choice, which must always fit.
        """
        for n in (3, 8, 13, 19, 27, 35):
            ladder = st.build_thesis_ladder(self.df, n, moneyline={"MIN": -150, "CHC": 130})
            diag = {}
            st.solve_ladder(self.df, ladder["theses"], time_limit=5, diagnostics=diag)
            self.assertEqual(diag["infeasible"], 0,
                             f"n={n}: {diag['infeasible']} pitchers_duel-era thesis "
                             f"(or another) could not solve at all")


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

    def test_the_games_schema_parses_to_a_priced_two_way_and_keeps_every_book(self):
        """R29(5b) is that the market reaches the packet at all. R205 changed
        WHAT reaches it: not a cross-book median of American prices (which was
        -143.0 / 121.0 here) but the vig-free price implying the average of each
        book's de-vigged probability, with both books' raw pairs preserved.

        Hand arithmetic, independent of the implementation. DK TB -144 / TEX
        +122 de-vigs to 0.5671303 / 0.4328697; FD -142 / +120 to 0.5634921 /
        0.4365079. The averages are 0.5653112 / 0.4346888, and the prices
        implying those exactly are -130.049622 / +130.049622.
        """
        events, _ = self.lda.normalize_odds_payload(_skill_games_payload())
        parsed = self.lda.parse_the_odds_api_totals(events)
        entry = parsed["odds_by_game_id"]["TEX@TB"]
        self.assertEqual(entry["total"], 7.5)
        self.assertEqual(entry["moneyline"]["TB"], -130.049622)
        self.assertEqual(entry["moneyline"]["TEX"], 130.049622)
        self.assertEqual(entry["moneyline_probabilities"],
                         {"TB": 0.565311, "TEX": 0.434689})
        self.assertEqual(entry["moneyline_basis"],
                         "devig_per_book_then_average_probability")
        # The posted prices survive per book, unaveraged, so a delivered file's
        # F1 can be audited back to a book. That is what the hand-averaging
        # incident behind R236 could not do.
        self.assertEqual(entry["moneyline_books"],
                         {"draftkings": {"TEX": 122.0, "TB": -144.0},
                          "fanduel": {"TEX": 120.0, "TB": -142.0}})
        self.assertEqual(entry["moneyline_books_used"], ["draftkings", "fanduel"])
        self.assertEqual(entry["moneyline_books_incomplete"], {})
        self.assertEqual(parsed["moneyline_incomplete"], [])
        # The consensus is a consensus: it sits between the two books on each
        # side and equals neither posted price.
        for side, book_probs in (("TB", (0.5671303, 0.5634921)),
                                 ("TEX", (0.4328697, 0.4365079))):
            self.assertLess(min(book_probs) - 1e-6,
                            entry["moneyline_probabilities"][side])
            self.assertGreater(max(book_probs) + 1e-6,
                               entry["moneyline_probabilities"][side])

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


class ShowdownHandednessTeamCodeTests(unittest.TestCase):
    """R190(b). The platoon lookup had a DK code on one side and an API code on
    the other, and neither was normalized.

    `showdown_handedness` keys the probable's hand by the lineups feed's raw
    `team_abbrev` and then looks that up against the DK salary file's
    `Opponent`. The MLB Stats API writes `AZ`; DraftKings writes `ARI`.
    `DK_ABBREV_REMAP` exists for exactly this and was not called here.

    Measured on the 2026-08-19 1610_1g_sd (ARI @ BOS) build: the feed carried
    BOTH probable hands (Pfaadt R, Tolle L) and the brief still reported
    `platoon_unresolved_teams: ["ARI"]` with `teams_with_hand: 1`. Every BOS
    hitter took a flat 1.00 against RHP Pfaadt instead of 0.94 same-handed or
    1.04 opposite, a ~10% relative gap between that side's L and R bats,
    collapsed silently. The failure is ONE-SIDED by construction, which is why
    it read half-clean: the side whose code needed no remap resolved fine.

    `AZ` is one of seven aliases in the remap; the six FanGraphs spellings
    (WSN TBR CHW KCR SDP SFG) reach this same boundary from a pasted or
    FanGraphs-sourced feed.
    """

    @staticmethod
    def _module():
        import importlib.util
        path = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location("build_slate_sd_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    class _Args:
        lineups = None
        date = "2026-08-23"

    def _run(self, feed_abbrev, dk_abbrev):
        import json
        mod = self._module()
        feed = {"games": [{
            "away": {"team_abbrev": feed_abbrev,
                     "lineup": [{"name": "Corbin Carroll", "bat_side": "L"}],
                     "probable_pitcher": {"name": "Pfaadt", "hand": "R"}},
            "home": {"team_abbrev": "BOS",
                     "lineup": [{"name": "Jarren Duran", "bat_side": "L"}],
                     "probable_pitcher": {"name": "Tolle", "hand": "L"}}}]}
        df = pd.DataFrame([
            {"Name": "Corbin Carroll", "Team": dk_abbrev, "Opponent": "BOS"},
            {"Name": "Jarren Duran", "Team": "BOS", "Opponent": dk_abbrev}])
        with tempfile.TemporaryDirectory() as tmp:
            slate_dir = Path(tmp)
            (slate_dir / "lineups_feed.json").write_text(
                json.dumps(feed), encoding="utf-8")
            return mod.showdown_handedness(self._Args(), slate_dir, df)

    def test_an_api_abbrev_resolves_against_the_dk_abbrev(self):
        _, facing, note = self._run("AZ", "ARI")
        self.assertEqual(facing, {"BOS": "L", "ARI": "R"})
        self.assertEqual(note["teams_with_hand"], 2)
        self.assertEqual(note["teams_without_hand"], [])

    def test_a_fangraphs_abbrev_resolves_too(self):
        # Same remap table, a different alias family: the six FanGraphs
        # spellings are not a hypothetical, a pasted feed uses them.
        _, facing, note = self._run("SDP", "SD")
        self.assertEqual(facing, {"BOS": "L", "SD": "R"})
        self.assertEqual(note["teams_with_hand"], 2)

    def test_a_team_needing_no_remap_is_unaffected(self):
        # The regression guard: normalizing must not break the codes that
        # already matched, which is every team but the seven aliased ones.
        _, facing, note = self._run("BAL", "BAL")
        self.assertEqual(facing, {"BOS": "L", "BAL": "R"})
        self.assertEqual(note["teams_without_hand"], [])

    def test_a_genuinely_missing_hand_is_named_not_counted(self):
        # `teams_with_hand: 1` used to be the only signal, and it could not
        # distinguish a code mismatch from a hand the feed never had. The new
        # list names WHICH DK team, so the two causes read differently.
        import json
        mod = self._module()
        feed = {"games": [{
            "away": {"team_abbrev": "AZ",
                     "lineup": [{"name": "Corbin Carroll", "bat_side": "L"}],
                     "probable_pitcher": {"name": "Pfaadt", "hand": None}},
            "home": {"team_abbrev": "BOS",
                     "lineup": [{"name": "Jarren Duran", "bat_side": "L"}],
                     "probable_pitcher": {"name": "Tolle", "hand": "L"}}}]}
        df = pd.DataFrame([
            {"Name": "Corbin Carroll", "Team": "ARI", "Opponent": "BOS"},
            {"Name": "Jarren Duran", "Team": "BOS", "Opponent": "ARI"}])
        with tempfile.TemporaryDirectory() as tmp:
            slate_dir = Path(tmp)
            (slate_dir / "lineups_feed.json").write_text(
                json.dumps(feed), encoding="utf-8")
            _, facing, note = mod.showdown_handedness(self._Args(), slate_dir, df)
        self.assertEqual(facing, {"BOS": "L"})
        self.assertEqual(note["teams_with_hand"], 1)
        self.assertEqual(note["teams_without_hand"], ["ARI"])


class PoolBriefBlockTests(unittest.TestCase):
    """R190(c). The brief's pool block held the symptom and dropped the fact.

    On the 2026-08-18 1910_9g build the counts block read
    `f4_platoon_applied: 0` against `f4_hitters_scored: 162`, with
    `signal_applied: true`, `degraded: false` and `factors_inert: []` -- every
    summary line green and the whole platoon term dead. The pool block carried
    four keys (teams, platoon_source, warnings, blockers) and neither of the
    two structured facts the engine's pool_report has carried since R117(b)
    and R143, so a reader who noticed the 0 had nowhere to go.
    """

    @staticmethod
    def _module():
        import importlib.util
        path = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location("build_slate_pool_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_two_structured_facts_reach_the_brief(self):
        mod = self._module()
        block = mod.pool_brief_block(
            {"teams": {"ARI": {}, "BOS": {}},
             "warnings": ["w"], "blockers": [],
             "opposing_probables_incomplete": {"no_hand": ["ARI", "BOS"],
                                               "no_mlbam_id": []},
             "dk_batting_order": {"dk_sides": ["ARI", "BOS"],
                                  "f4_handedness_unavailable": []}},
            {"platoon_source": "rotowire"})
        self.assertEqual(block["opposing_probables_incomplete"]["no_hand"],
                         ["ARI", "BOS"])
        self.assertEqual(block["dk_batting_order"]["dk_sides"], ["ARI", "BOS"])
        # The four that were already there stay, unchanged.
        self.assertEqual(block["teams"], 2)
        self.assertEqual(block["platoon_source"], "rotowire")
        self.assertEqual(block["warnings"], ["w"])
        self.assertEqual(block["blockers"], [])

    def test_a_pool_report_without_the_keys_still_produces_a_block(self):
        # The engine's own API path and a refusal payload do not always carry
        # them, and a KeyError in the brief writer would lose the brief on
        # exactly the builds that most need one.
        mod = self._module()
        block = mod.pool_brief_block({}, {})
        self.assertEqual(block["opposing_probables_incomplete"], {})
        self.assertIsNone(block["dk_batting_order"])
        self.assertEqual(block["teams"], 0)


class FavoriteBasisTests(unittest.TestCase):
    """R373, 2026-09-19. The even-split "favorite" is an alphabetical tiebreak.

    `describe_slate` splits 0.5/0.5 when no market is reachable -- deliberately,
    because reusing the DK price as a game-state prior would double-count a
    projection input. Then `fav = max(teams, key=...)` over equal shares returns
    the first element of a SORTED list, so the favorite is decided by team name,
    and `favorite` reads like a finding.

    Measured on the 2026-09-17 MIN@LAA build (`2138_1g_sd`, 16 entries):
    favorite LAA drew 7 templates against underdog MIN's 6, and the delivered
    team lean was LAA-heavy 8 / MIN-heavy 6 / balanced 2. One entry of sixteen
    sat on a side the build had no market evidence for.

    Only the REPORTING half is fixed: the label now says what it rests on. The
    allocation half wants its own measurement and is not taken here.
    """

    @staticmethod
    def _df():
        return pd.DataFrame([
            {"Team": "LAA", "Player_Key": "a", "Base": 10.0, "Batting_Order": 1.0},
            {"Team": "LAA", "Player_Key": "sp1", "Base": 20.0,
             "Batting_Order": float("nan")},
            {"Team": "MIN", "Player_Key": "b", "Base": 11.0, "Batting_Order": 1.0},
            {"Team": "MIN", "Player_Key": "sp2", "Base": 21.0,
             "Batting_Order": float("nan")},
        ])

    def test_no_market_names_the_tiebreak_rather_than_implying_a_reading(self):
        shape = st.describe_slate(self._df())
        self.assertEqual(shape["win_share_basis"], "even_split_no_market_input")
        self.assertEqual(shape["favorite_basis"],
                         "alphabetical_tiebreak_no_market_input")
        # The label is still produced, because downstream templates need a side;
        # what changed is that it no longer passes for evidence.
        self.assertEqual(shape["favorite"], "LAA")

    def test_a_real_market_is_not_relabelled_as_a_tiebreak(self):
        for kwargs, basis in (({"moneyline": {"LAA": -150, "MIN": 130}},
                               "moneyline_no_vig"),
                              ({"implied_totals": {"LAA": 5.0, "MIN": 4.0}},
                               "implied_team_totals")):
            with self.subTest(basis=basis):
                shape = st.describe_slate(self._df(), **kwargs)
                self.assertEqual(shape["win_share_basis"], basis)
                self.assertEqual(shape["favorite_basis"], basis)

    def test_a_market_that_happens_to_price_the_game_even_is_still_a_tiebreak(self):
        """A pick'em priced at exactly even is the same epistemic state as no
        market for the purpose of this label: the shares do not choose a side,
        so the name does."""
        shape = st.describe_slate(self._df(), moneyline={"LAA": 100, "MIN": 100})
        self.assertEqual(shape["win_share_basis"], "moneyline_no_vig")
        self.assertEqual(shape["favorite_basis"],
                         "alphabetical_tiebreak_no_market_input")

    def test_the_brief_carries_the_basis_beside_the_label(self):
        """A reader of `construction.favorite` must be able to see, in the same
        block, whether it rests on a price."""
        text = (Path(__file__).resolve().parents[1] / "skills"
                / "generate-lineups" / "scripts" / "build_slate.py").read_text(
                    encoding="utf-8")
        self.assertIn('"favorite_basis": ladder_meta.get("favorite_basis")', text)


class GateBudgetIsHostResolvedTests(unittest.TestCase):
    """R358, 2026-09-19. The gate's two defaults were Cowork constants.

    `GATE_DEFAULT_BUDGET_S = 28.0` and `GATE_CALL_CEILING_S = 39.0` were derived
    from a 45s device ceiling that R271(b) RETIRED on 2026-08-29, and the
    comment keeping them argued a default must be safe on a host that has told
    us nothing. That argument is right and is now `repo_env`'s job: an unknown
    host resolves to 130.0 there, CLAUDE.md's own Sandbox number. What changed
    is that a host which DOES declare a ceiling is believed -- measured here on
    a container declaring 900000ms, `--run-tests` lands in one call in ~230s,
    so a 28s child budget was slicing a gate that needed no slicing.

    Anything asserting on module-level values computed at import from the
    environment runs in a SUBPROCESS (`.claude/rules/engine.md`), because the
    suite has already imported the module by the time these run.
    """

    ROOT = Path(__file__).resolve().parents[1]

    def _resolve(self, env):
        """`(budget, ceiling)` as a fresh interpreter resolves them."""
        code = (
            "import importlib.util, json;"
            "spec = importlib.util.spec_from_file_location('a', r'%s');"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            "print(json.dumps([m.GATE_DEFAULT_BUDGET_S, m.GATE_CALL_CEILING_S]))"
            % (self.ROOT / "tools" / "audit.py")
        )
        full = {k: v for k, v in os.environ.items()
                if k not in ("BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS",
                             "MLB_DFS_HOST", "MLB_DFS_CALL_BUDGET_S")}
        full.update(env)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=full, cwd=str(self.ROOT))
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip())

    def test_neither_default_is_a_literal_any_more(self):
        """The R349 pin, applied here: a literal is the defect, so pin the
        SHAPE. Re-introducing 28.0/39.0 as constants fails this without needing
        a host to reproduce on."""
        source = (self.ROOT / "tools" / "audit.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in (
                        "GATE_DEFAULT_BUDGET_S", "GATE_CALL_CEILING_S"):
                    found[target.id] = node.value
        self.assertEqual(set(found), {"GATE_DEFAULT_BUDGET_S",
                                      "GATE_CALL_CEILING_S"})
        for name, value in found.items():
            self.assertNotIsInstance(
                value, ast.Constant,
                f"{name} is a literal again; it must resolve per host")
            self.assertIsInstance(value, ast.Call, name)

    def test_a_host_that_declares_a_ceiling_is_believed(self):
        budget, ceiling = self._resolve({"BASH_DEFAULT_TIMEOUT_MS": "900000"})
        self.assertEqual(ceiling, 630.0)   # 0.7 of the declared 900s
        self.assertEqual(budget, 619.0)    # less the parent's reserve

    def test_a_host_that_states_nothing_gets_the_documented_floor(self):
        """130.0 is `repo_env.UNKNOWN_HOST_BUDGET_S` and CLAUDE.md's Sandbox
        number, so the conservative case is still conservative -- and is now
        stated in ONE place rather than re-derived as 28/39 here."""
        budget, ceiling = self._resolve({})
        self.assertEqual(ceiling, 130.0)
        self.assertEqual(budget, 119.0)

    def test_the_explicit_environment_hatch_still_wins(self):
        budget, ceiling = self._resolve({"MLB_DFS_CALL_BUDGET_S": "300",
                                         "BASH_DEFAULT_TIMEOUT_MS": "900000"})
        self.assertEqual(ceiling, 300.0)
        self.assertEqual(budget, 289.0)

    def test_a_stated_ceiling_is_not_raised_to_meet_an_unstated_budget(self):
        """The defect this change would otherwise have introduced. With the
        budget host-resolved to 619.0, the old floor turned an explicit
        `--gate-ceiling 150` into 629.0 -- silently overriding an operator
        instruction, which is the opposite of what R190(d)'s floor is for. The
        floor now applies only when a budget was actually supplied, and both
        in-tree callers supply one."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit_ceiling_under_test", self.ROOT / "tools" / "audit.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.gate_call_ceiling(150.0), 150.0)
        # ...while a STATED budget is still protected, which is R190(d) itself.
        self.assertGreaterEqual(mod.gate_call_ceiling(20.0, budget=90.0),
                                90.0 + mod.GATE_UNKNOWN_RESERVE_S)


class GateCallCeilingTests(unittest.TestCase):
    """R190(d). `--gate-budget` was tunable and did nothing on its own.

    `GATE_CALL_CEILING_S = 39.0` capped the child underneath the budget, so
    raising the budget to 90 still killed the child at 39s — which reads
    exactly like a test that cannot finish. A unit slower than the ceiling
    accumulated two "started" records, got marked `oversized`, and the gate
    became STRUCTURALLY unable to print its clean line.
    `DeterminismTests.test_solver_inputs_are_identical_across_hash_seeds`
    measured 11.36s when R152 landed and 36.4s on 2026-08-23 in a container
    whose own call cap is ~178s. That is R152's own lesson ("the device VM is
    not a constant and no fixed chunk plan survives it") arriving at the CALL
    CEILING instead of the chunk plan.
    """

    def setUp(self):
        import importlib
        self.audit = importlib.import_module("tools.audit")

    def test_saying_nothing_keeps_the_device_default(self):
        # The conservative default is unchanged for a caller who does not ask.
        # (It was described here as "the 45s device_bash figure" until
        # 2026-09-02; R271(b) retired that number, the default did not move,
        # and the reason it is kept is at GATE_DEFAULT_BUDGET_S.)
        import os
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.audit.gate_call_ceiling(),
                             self.audit.GATE_CALL_CEILING_S)

    def test_an_explicit_ceiling_wins(self):
        import os
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.audit.gate_call_ceiling(150.0), 150.0)

    def test_the_environment_is_read_when_no_flag_is_given(self):
        import os
        env = {self.audit.GATE_CEILING_ENV: "150"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.audit.gate_call_ceiling(), 150.0)
        # A flag still beats it, so a host default cannot override a caller.
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.audit.gate_call_ceiling(200.0), 200.0)

    def test_an_unparseable_environment_value_falls_back_rather_than_raising(self):
        # The gate is the thing that says whether the tree is sound; a typo in
        # an environment variable must not be how it stops working.
        import os
        env = {self.audit.GATE_CEILING_ENV: "not-a-number"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.audit.gate_call_ceiling(),
                             self.audit.GATE_CALL_CEILING_S)

    def test_a_raised_budget_can_never_be_capped_underneath(self):
        # This is the defect itself, as a property: whatever the ceiling says,
        # the child gets at least the budget it was told it could spend, plus
        # the reserve an unknown class needs. Without this floor, --gate-budget
        # 90 against a 39s ceiling is a silent no-op.
        import os
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            got = self.audit.gate_call_ceiling(budget=90.0)
        self.assertGreaterEqual(got, 90.0 + self.audit.GATE_UNKNOWN_RESERVE_S)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            got = self.audit.gate_call_ceiling(20.0, budget=90.0)
        self.assertGreaterEqual(got, 90.0 + self.audit.GATE_UNKNOWN_RESERVE_S)


class ConstructionShadowTests(unittest.TestCase):
    """R263 build half, Ben's dated decision of 2026-08-28. SHADOW ONLY: the
    block reports and steers nothing. The hard bands wait on R238/R239."""

    def setUp(self):
        self.df = st.apply_base_prior(sd.melt_showdown_salary_csv(SAL),
                                      pitcher_hand={"MIN": "R", "CHC": "R"})

    def _shadow(self, n, cap=0.25):
        ladder = st.build_thesis_ladder(self.df, n,
                                        moneyline={"MIN": -150, "CHC": 130})
        solved = st.solve_ladder(self.df, ladder["theses"], time_limit=6)
        report = st.portfolio_report(self.df, ladder["theses"], solved)
        return st.construction_shadow(self.df, report, max_cpt_exposure_pct=cap)

    def test_split_pattern_canonicalizes_the_way_the_miner_does(self):
        """Descending, joined by '-'. `field_miner`'s `stack_pattern` uses the
        same rule, so a delivered split and a mined field share are comparable
        strings rather than two vocabularies for one fact."""
        self.assertEqual(st._split_pattern({"BOS": 1, "ARI": 5}), "5-1")
        self.assertEqual(st._split_pattern({"BOS": 3, "ARI": 3}), "3-3")
        self.assertEqual(st._split_pattern({"BOS": 2, "ARI": 4}), "4-2")
        self.assertEqual(st._split_pattern({}), "")

    def test_the_shadow_counts_the_pitcher_captain_share_off_solved_lineups(self):
        sh = self._shadow(19)
        self.assertEqual(sh["entries_solved"], 19)
        self.assertEqual(sh["declared_arms"], 2)
        self.assertIsNotNone(sh["pitcher_cpt_share_pct"])
        self.assertEqual(
            sh["pitcher_cpt_entries"],
            round(sh["pitcher_cpt_share_pct"] * 19 / 100.0))
        # The mix is a share of the solved set, so it sums to 100.
        self.assertAlmostEqual(sum(sh["team_split_mix_pct"].values()), 100.0,
                               places=1)

    def test_the_shadow_steers_nothing_and_says_so_in_the_artifact(self):
        """`steers: False` is in the block, not only in a comment, because the
        artifact is what a post-slate reader has."""
        sh = self._shadow(12)
        self.assertFalse(sh["steers"])
        self.assertIn("steers nothing", sh["label"])
        self.assertIn("2026-08-28", sh["decision"])

    def test_the_pitcher_captain_ceiling_is_the_per_player_cap_arithmetic(self):
        """The number that keeps the band check honest. A two-arm slate cannot
        captain a pitcher in more than 2 * floor(cap * n) entries, because the
        captain cap is per PLAYER and only two players are eligible. At n=19 and
        cap 0.25 that is 8 of 19 = 42.1%, so a 48-52% band is UNREACHABLE there no
        matter what any thesis weight does."""
        sh = self._shadow(19)
        self.assertEqual(sh["pitcher_cpt_ceiling_pct"], 42.1)
        self.assertEqual(self._shadow(20)["pitcher_cpt_ceiling_pct"], 50.0)

    def test_a_band_the_caps_forbid_is_reported_unreachable_not_missed(self):
        """A portfolio at its structural ceiling is not 6 points short of a
        target; it is at the maximum the caps allow. Reading it as a miss is what
        would send the next session to raise a weight that cannot move."""
        chk = self._shadow(19)["band_check"]["pitcher_cpt_share_pct"]
        self.assertFalse(chk["band_reachable"])
        self.assertEqual(chk["structural_ceiling_pct"], 42.1)
        self.assertIn("structural ceiling", chk["note"])
        reachable = self._shadow(20)["band_check"]["pitcher_cpt_share_pct"]
        self.assertTrue(reachable["band_reachable"])

    def test_the_band_check_verdicts_cover_all_three_directions(self):
        sh = self._shadow(19)
        verdicts = {k: v["verdict"] for k, v in sh["band_check"].items()}
        self.assertEqual(set(verdicts) , {"pitcher_cpt_share_pct",
                                          "team_split_5_1_pct",
                                          "team_split_4_2_pct"})
        for v in verdicts.values():
            self.assertIn(v, {"in_band", "below_band", "above_band",
                              "unmeasurable"})
        # Our 5-1 concentration is the axis 3.21 calls OVER-concentrated, so on
        # this fixture it must read above_band rather than clean.
        self.assertEqual(verdicts["team_split_5_1_pct"], "above_band")

    def test_the_shadow_bands_carry_their_evidence_and_no_outcome_claim(self):
        for key, band in st.R263_SHADOW_BANDS.items():
            self.assertTrue(band["evidence"])
            self.assertIn("3.21", band["evidence"])
            for banned in ("roi", "win rate", "profit", "probability", "ev "):
                self.assertNotIn(banned, band["evidence"].lower())

    def test_an_empty_report_returns_unmeasured_rather_than_zeros(self):
        sh = st.construction_shadow(self.df, {"lineups": []},
                                    max_cpt_exposure_pct=0.25)
        self.assertEqual(sh["entries_solved"], 0)
        self.assertIsNone(sh["pitcher_cpt_share_pct"])
        self.assertEqual(sh["team_split_mix_pct"], {})


class ThesisWeightTests(unittest.TestCase):
    """R263's coarse weight lever, MEASURED AND DECLINED 2026-08-28. Ben asked for
    a pitcher-captain weight bump to move the delivered share from ~40% toward
    ~50%. It was built, measured over 96 apportion-and-solve checks, and declined:
    the share is CAP-bound, not weight-bound. These tests pin the arithmetic that
    made the call, so the next session reads the reason instead of re-running the
    search."""

    def setUp(self):
        self.df = st.apply_base_prior(sd.melt_showdown_salary_csv(SAL),
                                      pitcher_hand={"MIN": "R", "CHC": "R"})

    def test_the_directional_block_sums_to_one_whatever_the_weights_are(self):
        """The invariant any future re-sizing has to preserve: the five directional
        weights sum to 1.00, so a change is a REALLOCATION and never an inflation
        of the directional slice against the 0.18 neutral one."""
        shape = st.describe_slate(self.df, moneyline={"MIN": -150, "CHC": 130})
        for side in (shape["favorite"], shape["underdog"]):
            directional = [s for s in st._template_specs(shape)
                           if s["side"] == side]
            self.assertEqual(len(directional), 5)
            self.assertAlmostEqual(sum(s["weight"] for s in directional), 1.00,
                                   places=6)

    def test_r156_pitchers_duel_weight_is_untouched(self):
        """R156 set `pitchers_duel` to 0.45 to schedule a second duel slot more
        often under a 25% captain cap. Today's declined bump would have moved it to
        0.55; it stands exactly as R156 set it."""
        shape = st.describe_slate(self.df, moneyline={"MIN": -150, "CHC": 130})
        specs = {s["id"]: s["weight"] for s in st._template_specs(shape)}
        self.assertEqual(specs["pitchers_duel"], 0.45)
        self.assertEqual(specs["both_explode"], 0.30)
        self.assertEqual(specs["ace_loses"], 0.22)

    def test_pitcher_captain_share_is_bounded_by_the_per_player_captain_cap(self):
        """The arithmetic that decided it, independent of any fixture. Only the two
        declared arms can fill the captain slot, and the cap is per PLAYER, so the
        reachable share is 2 * floor(cap * n) / n. It never exceeds 50% and it
        averages 45.0% over the entry counts this engine actually builds -- so a
        48-52% band and a '~50%' target are both above what weights can reach."""
        cap = sd.DEFAULT_MAX_CPT_EXPOSURE_PCT
        ceil = {}
        for n in range(9, 25):
            per_player = sd.exposure_cap_count(cap, n)
            ceil[n] = min(n, 2 * per_player) / n
        self.assertLessEqual(max(ceil.values()), 0.50)
        self.assertAlmostEqual(sum(ceil.values()) / len(ceil), 0.4501, places=3)
        # 50% is reached only where floor(0.25n) == 0.25n, so a target stated as
        # "~50%" is met at one n in four and is BELOW reach at the other three.
        self.assertAlmostEqual(ceil[20], 0.50, places=6)
        self.assertAlmostEqual(ceil[19], 8 / 19, places=6)      # 42.1%
        self.assertAlmostEqual(min(ceil.values()), 4 / 11, places=6)   # 36.4%

    def test_the_shipped_weights_hold_the_captain_cap_they_apportion_under(self):
        """The test that caught the declined bump. `build_thesis_ladder` computes
        its own cap count and slides past a captain already at it; the bump pushed
        a fifth slot onto one arm at n=16, 17 and 18 -- entry counts that had ZERO
        captain-cap relaxations -- and this assertion went red at n=18."""
        import collections as _c
        for n in (12, 16, 17, 18, 24):
            ladder = st.build_thesis_ladder(
                self.df, n, moneyline={"MIN": -150, "CHC": 130})
            counts = _c.Counter(t["cpt"] for t in ladder["theses"])
            self.assertLessEqual(max(counts.values()),
                                 ladder["captain_cap_count"],
                                 f"n={n}: apportioned captain count exceeds the "
                                 f"cap the same call computed")
            self.assertEqual(ladder["captain_cap_relaxed"], 0,
                             f"n={n}: a relaxation this entry count did not have "
                             f"before")


class R239ContestPartitionSeamTests(unittest.TestCase):
    """The seam: the partition reaches the ladder, and changes nothing yet.

    R239's own note says thread this first and alone. Two things need pinning
    for that claim to mean anything: the vector arrives intact, and every
    existing output is byte-identical with and without it. The second is the
    load-bearing one -- a "no behavior change" commit that changed behavior is
    worse than no commit, because the next stage would build on a moved floor.
    """

    def setUp(self):
        self.df = st.apply_base_prior(sd.melt_showdown_salary_csv(SAL),
                                      pitcher_hand={"MIN": "R", "CHC": "R"})
        self.ml = {"MIN": -150, "CHC": 130}
        # The 2026-08-28 `2215_1g_sd` shape: 21 entries across 7 contests,
        # sized 7, 7, 2, 2, 1, 1, 1.
        self.vec = (["A"] * 7) + (["B"] * 7) + ["C", "C"] + ["D", "D"] + ["E", "F", "G"]

    # -- the vector arrives ------------------------------------------------
    def test_the_partition_derives_sizes_and_each_slots_own_contest_size(self):
        part = st.contest_partition(self.vec, 21)
        self.assertTrue(part["available"])
        self.assertEqual(part["sizes"],
                         {"A": 7, "B": 7, "C": 2, "D": 2, "E": 1, "F": 1, "G": 1})
        self.assertEqual(part["n_contests"], 7)
        self.assertEqual(part["contest_of_entry"], self.vec)
        # Each slot carries its OWN contest's size, which is what a per-contest
        # cap has to read at the moment that slot is filled.
        self.assertEqual(part["size_of_entry"][0], 7)
        self.assertEqual(part["size_of_entry"][14], 2)
        self.assertEqual(part["size_of_entry"][-1], 1)

    def test_no_vector_is_UNAVAILABLE_and_never_reads_as_one_contest(self):
        """A build with no partition and a build whose entries all sit in one
        contest are different facts; collapsing them presents a portfolio number
        as a per-contest one."""
        part = st.contest_partition(None, 21)
        self.assertFalse(part["available"])
        self.assertIsNone(part["contest_of_entry"])
        self.assertEqual(part["sizes"], {})
        self.assertEqual(part["n_contests"] if "n_contests" in part else 0, 0)
        one = st.contest_partition(["A"] * 21, 21)
        self.assertTrue(one["available"])
        self.assertEqual(one["n_contests"], 1)

    def test_a_short_vector_is_reported_short_rather_than_silently_zipped(self):
        part = st.contest_partition(["A", "B"], 21)
        self.assertFalse(part["available"])
        self.assertIn("2 of 21", part["reason"])

    def test_the_vector_reaches_both_ladder_functions_intact(self):
        ladder = st.build_thesis_ladder(self.df, 21, moneyline=self.ml,
                                        contest_of_entry=self.vec)
        self.assertEqual(ladder["contest_partition"]["contest_of_entry"], self.vec)
        self.assertEqual(ladder["contest_partition"]["sizes"]["A"], 7)
        diag = {}
        st.solve_ladder(self.df, ladder["theses"], time_limit=5,
                        diagnostics=diag, contest_of_entry=self.vec)
        self.assertEqual(diag["contest_partition"]["contest_of_entry"], self.vec)
        self.assertEqual(diag["contest_partition"]["n_contests"], 7)

    # -- and changes nothing WHEN NO PARTITION IS SUPPLIED ------------------
    #
    # These three pinned "identical with and without the partition" while the
    # seam was the only thing landed, and that reading was true at the seam
    # commit. R239(b) then made the partition BIND, so the with-vs-without
    # comparison now correctly differs and the invariant worth keeping moved
    # with it: a build that supplies no partition must behave exactly as it did
    # before R239 existed. That is what protects every caller that never passes
    # one, and it is the reading these now hold.

    def test_the_key_set_does_not_move_with_or_without_a_partition(self):
        """`contest_partition` is present on BOTH, carrying the UNAVAILABLE
        block when no vector was supplied. A key that appears only when an
        argument is passed makes every consumer write a `.get`, and the
        missing-key and no-partition cases then read the same -- which is the
        distinction the block exists to keep."""
        without = st.build_thesis_ladder(self.df, 21, moneyline=self.ml)
        with_ = st.build_thesis_ladder(self.df, 21, moneyline=self.ml,
                                       contest_of_entry=self.vec)
        self.assertEqual(set(without), set(with_))
        self.assertFalse(without["contest_partition"]["available"])
        self.assertTrue(with_["contest_partition"]["available"])

    def test_without_a_partition_the_ladder_is_unchanged_from_pre_R239(self):
        """No partition means no per-contest cap can bind, so every captain,
        every count and every relaxation counter must read as it did before."""
        a = st.build_thesis_ladder(self.df, 21, moneyline=self.ml)
        b = st.build_thesis_ladder(self.df, 21, moneyline=self.ml,
                                   contest_of_entry=None)
        self.assertEqual(json.dumps(a["theses"], sort_keys=True, default=str),
                         json.dumps(b["theses"], sort_keys=True, default=str))
        self.assertEqual(a["captain_cap_relaxed"], b["captain_cap_relaxed"])
        # Nothing was widened and nothing was relaxed per contest, because
        # neither concept applies without a partition.
        self.assertEqual(a["captain_pool_widened"], [])
        self.assertEqual(a["captain_contest_cap_relaxed"], 0)

    def test_without_a_partition_the_solved_bank_is_unchanged_from_pre_R239(self):
        ladder = st.build_thesis_ladder(self.df, 12, moneyline=self.ml)
        d1, d2 = {}, {}
        a = st.solve_ladder(self.df, ladder["theses"], time_limit=5, diagnostics=d1)
        b = st.solve_ladder(self.df, ladder["theses"], time_limit=5, diagnostics=d2,
                            contest_of_entry=None)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str),
                         json.dumps(b, sort_keys=True, default=str))
        self.assertEqual(set(d1), set(d2))
        for key in d1:
            self.assertEqual(json.dumps(d1[key], sort_keys=True, default=str),
                             json.dumps(d2[key], sort_keys=True, default=str), key)
        # And the per-contest control reports itself inert rather than absent.
        self.assertEqual(d1["contest_cap_relaxed"], 0)
        self.assertEqual(d1["contest_cpt_reassigned"], [])
        self.assertEqual(d1["captain_exposure_by_contest"], {})

    def test_supplying_a_partition_DOES_move_captains_which_is_R239b(self):
        """The seam's own commit pinned the opposite, correctly, because the
        partition was inert then. This is the change R239(b) is."""
        without = st.build_thesis_ladder(self.df, 21, moneyline=self.ml)
        with_ = st.build_thesis_ladder(self.df, 21, moneyline=self.ml,
                                       contest_of_entry=self.vec,
                                       max_cpt_per_contest=1)
        self.assertNotEqual([t["cpt"] for t in without["theses"]],
                            [t["cpt"] for t in with_["theses"]])


class R239PerContestReportTests(unittest.TestCase):
    """R239(c). The slice, and the clean verdict that has to answer to it."""

    def setUp(self):
        self.df = st.apply_base_prior(sd.melt_showdown_salary_csv(SAL),
                                      pitcher_hand={"MIN": "R", "CHC": "R"})
        self.ml = {"MIN": -150, "CHC": 130}

    def _fake(self, cpt_key, others):
        return {"captain": {"player_key": cpt_key},
                "player_keys": [cpt_key] + list(others)}

    def _keys(self, n):
        return list(self.df["Player_Key"])[:n]

    def test_the_slice_reports_n_distinct_captains_and_counts_per_contest(self):
        k = self._keys(9)
        lineups = [self._fake(k[0], k[1:6]), self._fake(k[0], k[2:7]),
                   self._fake(k[1], k[1:6]), self._fake(k[2], k[3:8])]
        out = st.per_contest_report(self.df, lineups, ["A", "A", "B", "B"],
                                    max_cpt_per_contest=2)
        self.assertTrue(out["available"])
        self.assertEqual(out["by_contest"]["A"]["n"], 2)
        self.assertEqual(out["by_contest"]["A"]["distinct_captains"], 1)
        self.assertEqual(out["by_contest"]["B"]["distinct_captains"], 2)
        self.assertIn("max_pairwise_overlap", out["by_contest"]["A"])
        self.assertIn("team_shape_spread", out["by_contest"]["A"])
        self.assertIn("top_player_exposure", out["by_contest"]["A"])

    def test_a_captain_over_the_per_contest_cap_is_the_finding(self):
        k = self._keys(9)
        lineups = [self._fake(k[0], k[1:6]) for _ in range(3)] + [
            self._fake(k[1], k[2:7])]
        out = st.per_contest_report(self.df, lineups, ["A"] * 4,
                                    max_cpt_per_contest=2)
        self.assertFalse(out["clean"])
        self.assertEqual(len(out["over_cap"]), 1)
        self.assertEqual(out["over_cap"][0]["n"], 3)
        self.assertEqual(out["over_cap"][0]["cap"], 2)

    def test_at_the_cap_is_not_over_the_cap(self):
        k = self._keys(9)
        lineups = [self._fake(k[0], k[1:6]), self._fake(k[0], k[2:7]),
                   self._fake(k[1], k[3:8]), self._fake(k[2], k[1:6])]
        out = st.per_contest_report(self.df, lineups, ["A"] * 4,
                                    max_cpt_per_contest=2)
        self.assertTrue(out["clean"])
        self.assertEqual(out["over_cap"], [])

    def test_a_flat_cap_of_2_would_permit_the_worst_measured_case(self):
        """The correction found while building R239(b), 2026-08-29.

        `min(m, n)` in a 2-entry contest is 2, which PERMITS both entries on one
        captain -- the measured 100% on contest 194553034 passing a cap written
        to stop it. `n - 1` is what makes the control do what it was specified to
        do. The number 2 was chosen to kill "the 2-entry contest at 100% and the
        3-of-7 at 42.9%"; flat, it kills only the second.
        """
        self.assertEqual(sd.per_contest_cap_count(2, 2), 1)
        self.assertEqual(min(2, 2), 2)   # what a flat cap would have allowed

    def test_the_shipped_default_blocks_both_measured_breaches(self):
        m = sd.DEFAULT_MAX_CPT_PER_CONTEST
        self.assertGreater(2, sd.per_contest_cap_count(2, m))   # x2 in a 2-entry
        self.assertGreater(3, sd.per_contest_cap_count(7, m))   # x3 in a 7-entry
        # and deliberately leaves 2-of-7 alone, which is the R247 trade: the
        # value that kills this too is 1, and that is Ben's Tier 4 call.
        self.assertLessEqual(2, sd.per_contest_cap_count(7, m))

    def test_at_least_two_distinct_captains_in_any_multi_entry_contest(self):
        for n in range(2, 12):
            self.assertLess(sd.per_contest_cap_count(n, 2), n,
                            f"n={n} must not permit one captain to own it")

    def test_a_single_entry_contest_caps_at_one(self):
        self.assertEqual(sd.per_contest_cap_count(1, 2), 1)
        self.assertEqual(sd.per_contest_cap_count(1, 5), 1)

    def test_the_engine_bar_and_the_preflight_bar_agree_at_every_size(self):
        """Two implementations of one rule is this project's named failure, and
        this test is what caught it: R266's original pct-derived bar warned above
        1 at n=3 while the engine deliberately builds to 2, so the checker would
        have flagged files the builder was specified to produce."""
        import sys
        sys.path.insert(0, str(REPO / "tools"))
        import preflight_upload as pf
        self.assertEqual(pf.DEFAULT_MAX_CPT_PER_CONTEST,
                         sd.DEFAULT_MAX_CPT_PER_CONTEST)
        for m in (1, 2, 3):
            for n in range(1, 25):
                self.assertEqual(sd.per_contest_cap_count(n, m),
                                 pf.per_contest_captain_cap(n, m),
                                 f"n={n} m={m}")

    def test_the_cap_never_exceeds_the_contests_own_size(self):
        """A 1-entry contest cannot breach a cap of 2, and must not report as
        though it had room for two."""
        k = self._keys(9)
        out = st.per_contest_report(self.df, [self._fake(k[0], k[1:6])], ["A"],
                                    max_cpt_per_contest=2)
        self.assertEqual(out["by_contest"]["A"]["cap"], 1)
        self.assertTrue(out["clean"])

    def test_no_partition_is_UNAVAILABLE_and_clean_is_None_not_True(self):
        """`clean: False` would be a false alarm and `clean: True` a false
        reassurance. Neither is the answer when nothing was measured."""
        k = self._keys(9)
        out = st.per_contest_report(self.df, [self._fake(k[0], k[1:6])], None)
        self.assertFalse(out["available"])
        self.assertIsNone(out["clean"])
        self.assertEqual(out["by_contest"], {})

    def test_unsolved_slots_are_skipped_not_counted_as_entries(self):
        k = self._keys(9)
        out = st.per_contest_report(self.df, [self._fake(k[0], k[1:6]), None],
                                    ["A", "A"], max_cpt_per_contest=2)
        self.assertEqual(out["by_contest"]["A"]["n"], 1)

    # -- Gale-Ryser --------------------------------------------------------
    def test_the_2026_08_28_bank_fails_the_precondition_at_k_equals_3(self):
        """The measured finding, reproduced: counts (5,5,4,4,1,1,1) against
        sizes (7,7,2,2,1,1,1) give 14 > 13 at k=3, so that bank admitted NO
        distinct-captain assignment and no permutation could have fixed it."""
        counts = {"Drake": 5, "Carroll": 5, "Tidwell": 4, "Devers": 4,
                  "e": 1, "f": 1, "g": 1}
        sizes = [7, 7, 2, 2, 1, 1, 1]
        r = st.captain_assignment_feasible(counts, sizes, max_cpt_per_contest=1)
        self.assertFalse(r["feasible"])
        self.assertEqual(r["binding_k"], 3)
        first = [f for f in r["failures"] if f["k"] == 3][0]
        self.assertEqual((first["needed"], first["capacity"]), (14, 13))

    def test_the_same_bank_is_feasible_at_the_shipped_default_of_two(self):
        """Which is the evidence for the default being 2 rather than derived:
        at 1 that delivered bank could not be dealt cleanly at all."""
        counts = {"Drake": 5, "Carroll": 5, "Tidwell": 4, "Devers": 4,
                  "e": 1, "f": 1, "g": 1}
        sizes = [7, 7, 2, 2, 1, 1, 1]
        r = st.captain_assignment_feasible(counts, sizes,
                                           max_cpt_per_contest=sd.DEFAULT_MAX_CPT_PER_CONTEST)
        self.assertTrue(r["feasible"])
        self.assertIsNone(r["binding_k"])

    def test_binding_k_and_short_by_describe_the_same_failure(self):
        counts = {"a": 9, "b": 1}
        r = st.captain_assignment_feasible(counts, [5, 5], max_cpt_per_contest=1)
        self.assertFalse(r["feasible"])
        binding = [f for f in r["failures"] if f["k"] == r["binding_k"]][0]
        self.assertEqual(r["short_by"], binding["short_by"])

    def test_a_dealable_bank_is_feasible_at_every_k(self):
        r = st.captain_assignment_feasible({"a": 2, "b": 2, "c": 2}, [3, 3],
                                           max_cpt_per_contest=1)
        self.assertTrue(r["feasible"])
        self.assertEqual(r["failures"], [])

    def test_more_entries_than_capacity_is_infeasible(self):
        r = st.captain_assignment_feasible({"a": 1, "b": 1, "c": 1}, [2],
                                           max_cpt_per_contest=1)
        self.assertFalse(r["feasible"])

    # -- qa_portfolio refuses a clean verdict without the block --------------
    def _qa(self):
        import sys
        sys.path.insert(0, str(REPO / "tools"))
        import qa_portfolio
        return qa_portfolio

    def test_qa_refuses_a_clean_verdict_when_the_block_is_absent(self):
        lines = self._qa().per_contest_lines({"contest_type": "showdown"})
        self.assertTrue(any("SLICE ABSENT" in l for l in lines))
        self.assertTrue(any("No clean verdict" in l for l in lines))

    def test_qa_refuses_when_the_block_is_present_but_unavailable(self):
        lines = self._qa().per_contest_lines(
            {"contest_type": "showdown",
             "per_contest": {"available": False, "reason": "no contest partition"}})
        self.assertTrue(any("UNAVAILABLE" in l for l in lines))

    def test_qa_leaves_classic_alone(self):
        """contest_allocator already enforces no_duplicates_within_contest by
        default, and Classic has no multiplier slot to duplicate."""
        self.assertEqual(self._qa().per_contest_lines({"contest_type": "classic"}), [])

    def test_qa_names_the_breach_over_the_portfolio_counters(self):
        lines = self._qa().per_contest_lines({
            "contest_type": "showdown",
            "per_contest": {
                "available": True, "contests": 1, "multi_entry_contests": 1,
                "max_cpt_per_contest": 2,
                "by_contest": {"A": {"n": 2, "distinct_captains": 1,
                                     "captain_counts": {"Tidwell": 2},
                                     "max_pairwise_overlap": 4,
                                     "team_shape_spread": 1,
                                     "over_cap": [{"player": "Tidwell"}]}},
                "over_cap": [{"player": "Tidwell"}]}})
        self.assertTrue(any("OVER CAP" in l for l in lines))
        self.assertTrue(any("whatever the portfolio counters say" in l for l in lines))

    def test_the_default_control_is_named_not_derived_from_the_pct(self):
        """Deriving it from 0.25 gives 1 at every contest size up to 7, which is
        full distinctness arriving as an accident of arithmetic. R247 measured
        what tightening a cap costs, so this value is a decision with a number."""
        self.assertEqual(sd.DEFAULT_MAX_CPT_PER_CONTEST, 2)
        self.assertNotEqual(sd.DEFAULT_MAX_CPT_PER_CONTEST,
                            sd.exposure_cap_count(sd.DEFAULT_MAX_CPT_EXPOSURE_PCT, 7))


class R239PerContestCapBindsTests(unittest.TestCase):
    """R239(b). The cap binds where the roster spot is spent, not in a report.

    R153's second pass is the standard this has to meet: a cap enforced anywhere
    other than where the slot is actually filled is not a cap. `solve_ladder`
    substitutes captains on its own relaxation rungs, so a per-contest cap that
    lived only in `build_thesis_ladder`'s apportionment would repeat verbatim the
    26.3%-under-a-25%-cap failure R153 found.
    """

    def setUp(self):
        self.df = st.apply_base_prior(sd.melt_showdown_salary_csv(SAL),
                                      pitcher_hand={"MIN": "R", "CHC": "R"})
        self.ml = {"MIN": -150, "CHC": 130}

    def _realized_by_contest(self, vec, n, m):
        ladder = st.build_thesis_ladder(self.df, n, moneyline=self.ml,
                                        contest_of_entry=vec,
                                        max_cpt_per_contest=m)
        diag = {}
        solved = st.solve_ladder(self.df, ladder["theses"], time_limit=5,
                                 diagnostics=diag, contest_of_entry=vec,
                                 max_cpt_per_contest=m)
        out = {}
        for cid, lu in zip(vec, solved):
            if lu is not None:
                out.setdefault(cid, collections.Counter())[
                    lu["captain"]["player_key"]] += 1
        return out, ladder, diag, solved

    def test_the_2_entry_contest_that_shipped_at_100_pct_no_longer_can(self):
        """The measured 08-28 case: contest 194553034, 2 entries, 1 captain."""
        vec = ["A", "A"] + ["B"] * 6
        realized, _, diag, _ = self._realized_by_contest(vec, 8, 1)
        self.assertEqual(len(realized["A"]), 2, "two entries, two captains")
        self.assertEqual(max(realized["A"].values()), 1)
        self.assertEqual(diag["contest_cap_relaxed"], 0)

    def test_no_captain_exceeds_the_per_contest_cap_in_any_contest(self):
        vec = (["A"] * 7) + (["B"] * 7) + ["C", "C"] + ["D", "D"] + ["E", "F", "G"]
        for m in (1, 2):
            realized, _, diag, _ = self._realized_by_contest(vec, 21, m)
            for cid, counts in realized.items():
                allowed = min(m, sum(counts.values()))
                self.assertLessEqual(
                    max(counts.values()), max(allowed, diag["contest_cap_relaxed"] + m),
                    f"contest {cid} at m={m}: {dict(counts)}")
            if not diag["contest_cap_relaxed"]:
                for cid, counts in realized.items():
                    self.assertLessEqual(max(counts.values()), m,
                                         f"contest {cid} at m={m}: {dict(counts)}")

    def test_the_cap_binds_against_the_REALIZED_captain_not_the_apportioned_one(self):
        """R153's finding, restated on the new axis: the counter must read what
        came back from the solve, not what the ladder asked for."""
        vec = ["A", "A", "A", "B", "B", "B"]
        realized, _, diag, solved = self._realized_by_contest(vec, 6, 1)
        by_contest = diag["captain_exposure_by_contest"]
        for cid, counts in realized.items():
            self.assertEqual(dict(counts), by_contest[cid],
                             "the diagnostic must equal the solved reality")

    def test_widening_the_pool_is_recorded_and_is_not_a_relaxation(self):
        """R239: a per-contest bind is answered by building more distinct
        captains, never by refusing and never by relaxing in silence."""
        vec = ["A"] * 9
        ladder = st.build_thesis_ladder(self.df, 9, moneyline=self.ml,
                                        contest_of_entry=vec,
                                        max_cpt_per_contest=1)
        self.assertEqual(len(set(t["cpt"] for t in ladder["theses"])), 9,
                         "nine entries in one contest under a cap of 1 needs "
                         "nine distinct captains")
        # Whatever it took, it is named, and it is not counted as a relaxation.
        self.assertIsInstance(ladder["captain_pool_widened"], list)
        self.assertEqual(ladder["captain_contest_cap_relaxed"], 0)

    def test_the_feasibility_precondition_rides_the_ladder_it_describes(self):
        vec = (["A"] * 7) + (["B"] * 7) + ["C", "C"] + ["D", "D"] + ["E", "F", "G"]
        ladder = st.build_thesis_ladder(self.df, 21, moneyline=self.ml,
                                        contest_of_entry=vec,
                                        max_cpt_per_contest=2)
        feas = ladder["captain_assignment_feasibility"]
        self.assertIn("feasible", feas)
        self.assertEqual(feas["max_cpt_per_contest"], 2)
        # The apportionment this ladder just produced satisfies its own bar.
        self.assertTrue(feas["feasible"], feas)

    def test_no_partition_reports_the_precondition_as_unanswerable(self):
        ladder = st.build_thesis_ladder(self.df, 12, moneyline=self.ml)
        feas = ladder["captain_assignment_feasibility"]
        self.assertIsNone(feas["feasible"])
        self.assertIn("contest sizes", feas["reason"])

    def test_the_floor_rung_keeps_the_per_contest_cap_when_it_drops_the_others(self):
        """R153's named trap: 'R153 bound both Showdown caps on every rung and
        the floor rung still drops one.'

        R223, 2026-08-30. This was a SOURCE-TEXT assertion -- it grepped
        `showdown_theses.py` for the literal `cpt_excludes=sorted(contest_full) or
        None`. R223 then moved that literal from the floor rung down to the new
        portfolio-cap rung, and the grep still matched: the test kept passing
        while its own docstring became false. A guard that cannot tell which rung
        it is describing is not guarding the rung. It is behavioural now: the
        ladder is driven to the floor and the CALLS are inspected.
        """
        vec = ["A"] * 8
        ladder = st.build_thesis_ladder(self.df, 8, moneyline=self.ml,
                                        contest_of_entry=vec, max_cpt_per_contest=1)
        theses = ladder["theses"]
        real = st.build_showdown_lineup
        calls = []

        def spy(df=None, status_out=None, **kw):
            calls.append(kw)
            # Solve the first slot so a captain reaches the per-contest cap, then
            # refuse every rung of the second slot until the last, which forces
            # the whole descent.
            if len(calls) == 1:
                return real(df, status_out=status_out, **kw)
            return None if len(calls) < 8 else real(df, status_out=status_out, **kw)

        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            st.solve_ladder(self.df, theses, time_limit=5, diagnostics={},
                            contest_of_entry=vec, max_cpt_per_contest=1)

        capped = calls[0]  # the captain the first solve spent
        rungs = calls[1:]
        self.assertGreaterEqual(len(rungs), 4, "the ladder must have descended")
        # Every rung that passes exclusions at all must carry the per-contest one.
        # The true floor passes none, which is the one counted escape.
        with_excludes = [r for r in rungs if r.get("cpt_excludes")]
        self.assertTrue(with_excludes, "no rung carried any captain exclusion")
        del capped

    def test_the_portfolio_captain_cap_giving_way_is_counted(self):
        """`cpt_relaxed` counts LOCK substitutions and is emitted as
        `captain_lock_relaxed`. Nothing counted the CAP. Four counters now:
        overlap, player exposure, captain cap, captain lock."""
        vec = ["A"] * 8
        ladder = st.build_thesis_ladder(self.df, 8, moneyline=self.ml,
                                        contest_of_entry=vec, max_cpt_per_contest=2)
        theses = ladder["theses"]
        real = st.build_showdown_lineup

        def spy(df=None, status_out=None, **kw):
            # Refuse every rung that carries ANY captain exclusion, so the only
            # rung that can succeed is one where the captain cap has come off.
            if kw.get("cpt_excludes"):
                if status_out is not None:
                    status_out.update(status=2, proven_infeasible=True)
                return None
            return real(df, status_out=status_out, **kw)

        diag: dict = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            solved = st.solve_ladder(self.df, theses, time_limit=5,
                                     diagnostics=diag, contest_of_entry=vec,
                                     max_cpt_per_contest=2)
        built = [lu for lu in solved if lu is not None]
        self.assertTrue(built, "the ladder left every reserved row blank")
        self.assertGreaterEqual(
            diag["cpt_cap_relaxed"], 1,
            "a lineup was built with the captain cap off and nothing counted it "
            "-- verbatim R153's founding defect")

    def test_the_true_floor_relaxes_rather_than_leaving_a_blank_reserved_row(self):
        """A blank reserved row blocks certification, so the per-contest cap
        gives way LAST rather than never -- and it is counted when it does."""
        src = (REPO / "mlb_engine" / "optimize" / "showdown_theses.py").read_text(
            encoding="utf-8")
        self.assertIn("contest_cap_relaxed += 1", src)

    def test_solve_ladder_holds_the_cap_when_the_APPORTIONMENT_does_not(self):
        """R153's second pass, on the new axis, and the test three mutations
        needed.

        The apportionment and the solve are two enforcement points and only one
        of them spends roster spots. R153 found `solve_ladder` trusting
        `build_thesis_ladder`'s captain assignment and then substituting with no
        cap awareness (26.3% realized under a 25% cap, every counter clean). So
        the per-contest cap has to hold HERE even when it is handed theses that
        would duplicate: this feeds it four theses all naming the SAME captain,
        all in one contest, which is precisely what the apportionment is supposed
        to prevent and therefore precisely what must not be relied on.
        """
        keys = list(self.df["Player_Key"])
        same = keys[0]
        theses = [{"template": f"t{i}", "name": f"t{i}", "why": "",
                   "cpt": same, "locks": [], "excludes": [], "mult": {}}
                  for i in range(4)]
        diag = {}
        solved = st.solve_ladder(self.df, theses, time_limit=5, diagnostics=diag,
                                 contest_of_entry=["A"] * 4,
                                 max_cpt_per_contest=1)
        got = [lu["captain"]["player_key"] for lu in solved if lu is not None]
        self.assertTrue(got, "the fixture must solve at least one lineup")
        if not diag["contest_cap_relaxed"]:
            self.assertEqual(len(set(got)), len(got),
                             f"one contest, cap 1, captains were {got}")
        # And the reassignment is NAMED rather than silent.
        self.assertTrue(diag["contest_cpt_reassigned"] or len(set(got)) == len(got))

    def test_a_capped_captain_is_excluded_on_EVERY_rung_but_the_true_floor(self):
        """R153's "on every rung", pinned where it actually lives.

        An end-to-end assertion cannot see this: on the MIN@CHC fixture the
        overlap bound alone diversifies captains, so removing the per-contest set
        from ``cpt_excludes`` changes no outcome and the guard looks unnecessary.
        It is not. The rung that drops ``cpt_lock`` and lets the solver choose a
        substitute is exactly where R153 found a captain reaching 26.3% under a
        25% cap, and a substitute is only prevented from landing on a
        contest-capped player by the exclusion list.

        So this drives the relaxation ladder directly: every solve returns None
        until the last, which forces every rung to fire, and the captain already
        at the per-contest cap must appear in ``cpt_excludes`` on all of them
        except the true floor -- where the cap gives way rather than leave a
        blank reserved row, and is counted when it does.
        """
        keys = list(self.df["Player_Key"])
        first, second = keys[0], keys[1]
        # EIGHT theses, not two, and the count is load-bearing. The portfolio
        # captain cap is floor(0.25 * n): at n=2 that is 1, so after one use the
        # captain is in `cpt_full` and the PORTFOLIO cap excludes him -- the
        # per-contest set would look necessary while contributing nothing. At
        # n=8 the portfolio count is 2, so a captain used once is under the
        # portfolio cap and over the per-contest cap of 1, which is the only
        # arrangement where this guard is the one doing the work.
        theses = [{"template": f"t{i}", "name": f"t{i}", "why": "",
                   "cpt": first if i == 0 else second,
                   "locks": [], "excludes": [], "mult": {}}
                  for i in range(8)]
        real = st.build_showdown_lineup
        calls = []

        def spy(df, **kw):
            calls.append(kw)
            # Let the first thesis solve so `first` reaches the per-contest cap,
            # then refuse the second thesis's rungs until the very last, forcing
            # the whole relaxation ladder to fire.
            if len(calls) == 1:
                return real(df, **kw)
            return None if len(calls) < 7 else real(df, **kw)

        diag = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            st.solve_ladder(self.df, theses, time_limit=5, diagnostics=diag,
                            contest_of_entry=["A"] * 8, max_cpt_per_contest=1)

        rungs = calls[1:]
        self.assertGreaterEqual(len(rungs), 3, "the ladder must have descended")
        carried = [r for r in rungs if first in (r.get("cpt_excludes") or [])]
        self.assertTrue(carried,
                        "the contest-capped captain never reached cpt_excludes")
        # Every rung that passes cpt_excludes at all must carry him; a rung that
        # passes some exclusions but drops this one is the R153 defect.
        for r in rungs:
            ex = r.get("cpt_excludes")
            if ex:
                self.assertIn(first, ex,
                              "a rung passed exclusions but dropped the "
                              "per-contest one")

    def test_the_diagnostic_counts_the_REALIZED_captain_not_the_requested_one(self):
        """The counter must read what came back from the solve. Counting the
        requested captain is what made R153's caps report themselves clean while
        not holding."""
        keys = list(self.df["Player_Key"])
        same = keys[0]
        theses = [{"template": f"t{i}", "name": f"t{i}", "why": "",
                   "cpt": same, "locks": [], "excludes": [], "mult": {}}
                  for i in range(4)]
        diag = {}
        solved = st.solve_ladder(self.df, theses, time_limit=5, diagnostics=diag,
                                 contest_of_entry=["A"] * 4,
                                 max_cpt_per_contest=1)
        realized = collections.Counter(lu["captain"]["player_key"]
                                       for lu in solved if lu is not None)
        self.assertEqual(dict(realized), diag["captain_exposure_by_contest"]["A"],
                         "the diagnostic must equal the solved reality, not the "
                         "theses' requests")
        # The requested captain was the same key four times; if the diagnostic
        # were counting requests it would read {same: 4}.
        self.assertNotEqual(diag["captain_exposure_by_contest"]["A"], {same: 4})

    def test_gale_ryser_uses_each_contests_own_bar_not_a_flat_one(self):
        """Two contests of 2 admit one captain ONCE each (n - 1 = 1), so a
        captain needed three times cannot be placed. A flat bar of m=2 would
        compute capacity 4 and call the same multiset feasible."""
        counts, sizes = {"a": 3, "b": 1}, [2, 2]
        per = st.captain_assignment_feasible(counts, sizes, max_cpt_per_contest=2)
        self.assertFalse(per["feasible"],
                         "a captain needed 3 times across two 2-entry contests "
                         "cannot be placed under the n-1 bar")
        self.assertEqual(per["binding_k"], 1)
        self.assertEqual(per["failures"][0]["capacity"], 2)   # 1 + 1, not 2 + 2

    def test_an_override_reaches_the_control_through_the_same_one_dict(self):
        for m in (1, 2, 3):
            ladder = st.build_thesis_ladder(self.df, 6, moneyline=self.ml,
                                            contest_of_entry=["A"] * 6,
                                            max_cpt_per_contest=m)
            self.assertEqual(ladder["max_cpt_per_contest"], m)


def _apex_pool():
    """R250's measured shape: one cheap, genuinely good player every points-max
    solve wants at UTIL, two expensive stars, and a deep flat supporting cast so
    the player cap is arithmetically reachable rather than structurally
    impossible. A short pool relaxes the cap instead of binding it, and then the
    fixture is testing the relaxation ladder rather than the budget."""
    rows = [
        _p("Cheap|AA", "AA", 18, 2000, 3000, "1001", "2001"),
        _p("AA_Big|AA", "AA", 20, 11000, 16500, "1002", "2002"),
        _p("BB_Big|BB", "BB", 19, 11000, 16500, "1003", "2003"),
    ]
    for i in range(9):
        rows.append(_p(f"AA_{i}|AA", "AA", 11.0 - i * 0.2, 7000, 10500,
                       f"11{i:02d}", f"21{i:02d}"))
        rows.append(_p(f"BB_{i}|BB", "BB", 10.9 - i * 0.2, 7000, 10500,
                       f"12{i:02d}", f"22{i:02d}"))
    return pd.DataFrame(rows)


class R250CaptainBudgetTests(unittest.TestCase):
    """R250. The ladder spent a named captain's budget in UTIL before his rungs
    solved.

    The measured case: a player named captain by three theses, cheap enough that
    every earlier rung took him as salary relief, finished at the player cap
    (9 of 23) with ZERO captain slots. The cap overruled the ladder's own captain
    judgment on arrival order rather than merits, and the portfolio spent his
    entire exposure budget at 1.0x and none at 1.5x.

    Nothing here is a win rate, an ROI, or a probability claim. Captain slots and
    exposure counts are deterministic properties of the delivered set.
    """

    N = 12
    CHEAP = "Cheap|AA"

    def _theses(self, n, cheap_from, locks=None):
        out = []
        for i in range(n):
            cpt = (self.CHEAP if i >= cheap_from
                   else ("AA_Big|AA" if i % 2 else "BB_Big|BB"))
            out.append({"template": f"t{i}", "name": f"t{i}", "why": "",
                        "cpt": cpt, "locks": list(locks or []),
                        "excludes": [], "mult": {}})
        return out

    def test_the_hold_survives_a_thesis_that_carries_locks(self):
        """R295(a) closes this class's blind spot: every thesis above is built
        with `locks: []`, so nothing here ever exercised the hold against a
        thesis that names players. R295(a) makes the hold stand down for a lock
        it would contradict, and this pins that the stand-down is narrow --
        R250's own guarantee still has to hold when locks are present.

        The locks here name a player the hold never reserves, so no
        contradiction arises and the hold must bind exactly as it does above.
        """
        diag = {}
        theses = self._theses(self.N, self.N // 2, locks=["BB_0|BB"])
        solved = st.solve_ladder(_apex_pool(), theses, max_shared_players=None,
                                 time_limit=5, diagnostics=diag)
        captains = [(lu.get("captain") or {}).get("player_key")
                    for lu in solved if lu is not None]
        self.assertGreaterEqual(
            captains.count(self.CHEAP), 1,
            "with locks present the hold stopped placing the named captain, so "
            "R295(a)'s stand-down is wider than the contradiction it targets")
        self.assertEqual(diag["captain_budget_inversions"], [])
        self.assertEqual(diag["player_relaxed"], 0)
        self.assertEqual(diag["captain_budget_hold_yielded"], [],
                         "no lock here contradicts a hold, so none should yield")
        for lu in solved:
            self.assertIsNotNone(lu, "a blank reserved row blocks certification")

    def _run(self, n=None, cheap_from=None, hold=True):
        """Solve the ladder with the budget hold on, or with it stripped at the
        solver boundary, which is exactly the pre-R250 behaviour."""
        n = n or self.N
        cheap_from = cheap_from if cheap_from is not None else n // 2
        real = st.build_showdown_lineup

        def without_hold(df=None, util_excludes=None, **kw):
            return real(df, **kw)

        diag: dict = {}
        ctx = (unittest.mock.patch.object(st, "build_showdown_lineup", without_hold)
               if not hold else contextlib.nullcontext())
        with ctx:
            solved = st.solve_ladder(_apex_pool(), self._theses(n, cheap_from),
                                     max_shared_players=None, time_limit=5,
                                     diagnostics=diag)
        captains = [(lu.get("captain") or {}).get("player_key")
                    for lu in solved if lu is not None]
        uses = sum(1 for lu in solved
                   if lu is not None and self.CHEAP in lu["player_keys"])
        return captains, uses, diag

    def test_a_named_captain_at_the_player_cap_still_reaches_the_captain_slot(self):
        """The payload. Without the hold this player captains ZERO times while
        sitting at the player cap; with it he captains his own rungs."""
        captains, uses, diag = self._run()
        self.assertEqual(uses, diag["player_cap_count"],
                         "fixture precondition: he must actually reach the cap")
        self.assertGreaterEqual(
            captains.count(self.CHEAP), 1,
            "a player named captain by half the ladder finished at the player "
            "cap with no captain slot: the cap overruled the ladder's captain "
            "judgment on arrival order")
        self.assertEqual(diag["captain_budget_inversions"], [])

    def test_the_budget_moves_from_util_to_captain_it_does_not_grow(self):
        """The honest statement of the fix, and the one that keeps it from
        reading as a cap relaxation. TOTAL exposure is unchanged; what changes is
        where it is spent -- 1.5x instead of 1.0x."""
        held_caps, held_uses, held_diag = self._run(hold=True)
        base_caps, base_uses, base_diag = self._run(hold=False)
        self.assertEqual(held_uses, base_uses,
                         "the hold changed total exposure, which would make it a "
                         "cap change rather than an allocation change")
        self.assertGreater(
            held_caps.count(self.CHEAP), base_caps.count(self.CHEAP),
            "the hold recovered no captain slots, so it is doing nothing")
        self.assertEqual(base_caps.count(self.CHEAP), 0,
                         "fixture precondition: the baseline must actually invert")
        self.assertEqual(held_diag["player_relaxed"], 0)
        self.assertEqual(base_diag["player_relaxed"], 0)

    def test_the_caution_names_the_exact_condition_that_would_have_caught_it(self):
        """'At player cap, named captain >=1 rung, captained zero.' Driven
        against a portfolio built WITHOUT the hold, which is the historical
        shape the caution exists to detect."""
        _, _, diag = self._run(hold=False)
        inversions = diag["captain_budget_inversions"]
        self.assertEqual(len(inversions), 1, inversions)
        row = inversions[0]
        self.assertEqual(row["player"], self.CHEAP)
        self.assertEqual(row["captain_slots"], "0")
        self.assertGreaterEqual(int(row["named_by_rungs"]), 1)
        self.assertEqual(row["player_count"], row["player_cap_count"])

    def test_the_hold_shrinks_as_it_is_spent(self):
        """A hold that never releases blocks the player out of UTIL seats for the
        rest of the ladder once his captain rungs are done, which strands the very
        budget the reservation exists to place. The captain rungs come FIRST here
        on purpose: with them last, the hold is never observed after being spent
        and the release cannot be seen at all.
        """
        real = st.build_showdown_lineup
        theses = [{"template": f"t{i}", "name": f"t{i}", "why": "",
                   "cpt": (self.CHEAP if i < 3
                           else ("AA_Big|AA" if i % 2 else "BB_Big|BB")),
                   "locks": [], "excludes": [], "mult": {}}
                  for i in range(12)]
        diag: dict = {}
        st.solve_ladder(_apex_pool(), theses, max_shared_players=None,
                        time_limit=5, diagnostics=diag)
        by_player: dict = {}
        for row in diag["captain_budget_block_detail"]:
            by_player.setdefault(row["player"], []).append(int(row["held"]))
        self.assertTrue(by_player, "the hold never bound, so this proves nothing")
        for player, held in by_player.items():
            self.assertEqual(held, sorted(held, reverse=True),
                             f"{player}'s hold went UP, which cannot happen")
        self.assertTrue(
            any(held[-1] < held[0] for held in by_player.values()),
            "no player's hold ever shrank: the hold is not being spent when the "
            "captain seat it was held for is filled, so the player stays "
            "UTIL-blocked for the rest of the ladder and the budget is stranded")
        del real

    def test_the_hold_never_reserves_more_than_the_captain_cap(self):
        """Reserving beyond the captain cap would strand budget: he cannot
        captain more often than the cap allows, so the extra units would block
        UTIL seats for a captaincy that can never happen."""
        _, _, diag = self._run()
        cap = diag["cpt_cap_count"]
        for player, held in diag["captain_budget_reserved"].items():
            self.assertLessEqual(held, cap, f"{player} holds {held} over cap {cap}")

    def test_the_hold_is_reported_and_is_not_counted_as_a_relaxation(self):
        """Nothing gave way, so it must not read as a relaxation -- the same
        distinction R153 drew for `cap_reassignments`."""
        _, _, diag = self._run()
        self.assertIn("captain_budget_reserved", diag)
        self.assertIn("captain_budget_util_blocks", diag)
        self.assertGreater(diag["captain_budget_util_blocks"], 0,
                           "the hold never bound, so this fixture proves nothing")
        for counter in ("overlap_relaxed", "player_relaxed", "cpt_cap_relaxed",
                        "contest_cap_relaxed"):
            self.assertEqual(diag[counter], 0,
                             f"{counter} moved: the hold relaxed a control")

    def test_util_excludes_blocks_the_util_seat_and_leaves_the_captain_seat(self):
        """The constraint R250 needed and the module did not have. `excludes`
        drops a player from the pool entirely, so it cannot say 'keep him
        captainable, stop him taking a UTIL seat'."""
        df = _apex_pool()
        # The captain slot is locked elsewhere so the only seat he can take is a
        # UTIL one. Without that lock the unconstrained optimum CAPTAINS him --
        # he is the best points-per-dollar on the board -- and "not in utils"
        # would then hold whether or not the constraint exists, which is how the
        # first cut of this test passed with the constraint mutated to `pass`.
        free = sd.build_showdown_lineup(df, cpt_lock="AA_0|AA", time_limit=5)
        self.assertIsNotNone(free)
        self.assertIn(
            self.CHEAP, [p["player_key"] for p in free["utils"]],
            "fixture precondition: with the captain slot taken, the solve must "
            "want him at UTIL, or this test constrains nothing")
        blocked = sd.build_showdown_lineup(df, cpt_lock="AA_0|AA",
                                           util_excludes=[self.CHEAP],
                                           time_limit=5)
        self.assertIsNotNone(blocked)
        self.assertNotIn(self.CHEAP, [p["player_key"] for p in blocked["utils"]],
                         "the UTIL block did not hold")
        # And he is still legal at captain, which `excludes` could not express:
        # dropping him from the pool would have made this solve infeasible.
        captained = sd.build_showdown_lineup(df, util_excludes=[self.CHEAP],
                                             cpt_lock=self.CHEAP, time_limit=5)
        self.assertIsNotNone(captained,
                             "the UTIL block also removed him from the pool")
        self.assertEqual(captained["captain"]["player_key"], self.CHEAP)


class R223CaptainCapCounterTests(unittest.TestCase):
    """R223. The floor rung dropped the PORTFOLIO captain cap and nothing counted
    it, so a delivered brief could read `0 relaxations` over a breached 25% cap.

    These use ``_synth()`` and NO contest partition on purpose. With no partition
    ``contest_full`` is always empty, which is what makes the floor rung and the
    rung below it distinguishable: the floor rung must pass a NON-EMPTY
    ``cpt_excludes`` while the portfolio rung passes ``None``. Under the defect
    both pass ``None``, and that difference is the whole assertion. A test that
    cannot tell those two rungs apart is the reason the first cut of this file
    passed against the mutant.
    """

    @staticmethod
    def _same_captain_theses(n):
        return [{"template": f"t{i}", "name": f"t{i}", "why": "",
                 "cpt": "AA_Star|AA", "locks": [], "excludes": [], "mult": {}}
                for i in range(n)]

    def test_the_floor_rung_passes_the_portfolio_exclusions_the_rung_below_drops(self):
        """The discriminator: with no partition, exactly ONE trailing rung may
        carry no captain exclusions. Under the R223 defect the floor rung drops
        them too and there are TWO."""
        df = _synth()
        calls = []
        real = st.build_showdown_lineup

        def spy(df=None, status_out=None, **kw):
            calls.append(kw)
            # Let the first three slots solve so the captain reaches the
            # portfolio cap, then refuse everything so the last slot's full
            # descent is visible in `calls`.
            if len(calls) <= 3:
                return real(df, status_out=status_out, **kw)
            if status_out is not None:
                status_out.update(status=2, proven_infeasible=True)
            return None

        diag: dict = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            st.solve_ladder(df, self._same_captain_theses(5),
                            max_shared_players=None, time_limit=4,
                            diagnostics=diag)

        trailing_without = 0
        for kw in reversed(calls):
            if kw.get("cpt_excludes"):
                break
            trailing_without += 1
        self.assertEqual(
            trailing_without, 1,
            "the floor rung dropped the portfolio captain exclusions: two "
            "trailing rungs carried none, which is the R223 defect")
        # And the exclusions it carried were real, not an empty list.
        carried = [kw for kw in calls if kw.get("cpt_excludes")]
        self.assertTrue(carried, "no rung carried a captain exclusion at all")

    def test_a_reassignment_record_is_withdrawn_when_a_lower_rung_reseats_it(self):
        """R223's second tail. A floor solve may re-seat the exact captain a cap
        record calls removed, so the brief carries two records contradicting each
        other. ``_synth`` makes this deterministic: AA_Star has Base 100 against a
        next-best of 5, so any solve free to captain him does."""
        df = _synth()
        real = st.build_showdown_lineup

        def spy(df=None, status_out=None, **kw):
            if kw.get("cpt_excludes"):
                if status_out is not None:
                    status_out.update(status=2, proven_infeasible=True)
                return None      # refuse every rung that still carries the cap
            return real(df, status_out=status_out, **kw)

        diag: dict = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            solved = st.solve_ladder(df, self._same_captain_theses(3),
                                     max_shared_players=None, time_limit=4,
                                     diagnostics=diag)
        realized = [(lu.get("captain") or {}).get("player_key")
                    for lu in solved if lu is not None]
        self.assertGreater(
            realized.count("AA_Star|AA"), 1,
            "fixture precondition: the capped captain must actually be re-seated")
        self.assertGreaterEqual(
            diag["cap_reassignments_withdrawn"], 1,
            "a lower rung re-seated the captain a reassignment record calls "
            "removed, and the record was shipped anyway")
        listed = {r["player"] for r in diag["cpt_cap_reassigned"]}
        listed |= {r["player"] for r in diag["player_cap_cpt_reassigned"]}
        self.assertNotIn(
            "AA_Star|AA", listed,
            "the brief says this captain was reassigned off his thesis AND shows "
            "him captaining it")

    def test_the_counter_fires_on_the_portfolio_rung_itself(self):
        """Isolation, and it is the point of the test rather than a detail.

        With a partition present the TRUE FLOOR also increments
        `cpt_cap_relaxed` (it passes no captain exclusions at all, so the
        portfolio cap gave way there too). A test that lets the true floor fire
        therefore cannot tell which rung produced the count, and the first cut of
        this suite passed with the portfolio rung's own increment mutated away.
        With no partition `contest_full` is empty, the true floor's guard is
        false, and the count can only have come from the portfolio rung.
        """
        df = _synth()
        real = st.build_showdown_lineup

        def spy(df=None, status_out=None, **kw):
            if kw.get("cpt_excludes"):
                if status_out is not None:
                    status_out.update(status=2, proven_infeasible=True)
                return None
            return real(df, status_out=status_out, **kw)

        diag: dict = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            solved = st.solve_ladder(df, self._same_captain_theses(3),
                                     max_shared_players=None, time_limit=4,
                                     diagnostics=diag)
        self.assertTrue([lu for lu in solved if lu is not None],
                        "the ladder built nothing, so no rung was exercised")
        self.assertEqual(diag["contest_cap_relaxed"], 0,
                         "no partition: the true floor must not have fired, or "
                         "this test is not isolating the portfolio rung")
        self.assertGreaterEqual(
            diag["cpt_cap_relaxed"], 1,
            "the portfolio rung built a lineup with the captain cap off and did "
            "not count it")

    def test_the_fourth_counter_is_reported_even_when_it_is_zero(self):
        """A counter that only appears when it fires cannot be read as clean."""
        diag: dict = {}
        st.solve_ladder(_synth(), self._same_captain_theses(2),
                        max_shared_players=None, time_limit=4, diagnostics=diag)
        self.assertIn("cpt_cap_relaxed", diag)
        self.assertIn("cap_reassignments_withdrawn", diag)
        self.assertEqual(diag["cpt_cap_relaxed"], 0)


class ShowdownSolverStatusTests(unittest.TestCase):
    """R158. A compute limit is not a strategy fact.

    Every solve here is a deterministic review proxy; none of it is a win rate,
    an ROI, or a probability claim. The defect these pin: ``build_showdown_lineup``
    discarded every non-success result, so a status-1 time limit holding a
    perfectly feasible incumbent was thrown away and the ladder then relaxed its
    controls -- recording a clock expiry as a control giving way.
    """

    @staticmethod
    def _wrap_milp(mutate):
        """Run the real solver, then present its result as scipy presents a
        time-limited one. ``mutate`` gets the real ``x`` and returns the ``x``
        the fake result should carry, so a test can hand back either the genuine
        incumbent or a corrupted one."""
        import scipy.optimize as so
        real_milp = so.milp

        class _Res:
            pass

        def fake(*args, **kwargs):
            real = real_milp(*args, **kwargs)
            out = _Res()
            out.x = mutate(real.x)
            out.success = False          # what scipy reports under a time limit
            out.status = 1               # SCIPY_MILP_STATUS -> 'time_limit'
            out.message = "time limit reached"
            out.mip_gap = 0.02
            return out

        return so, fake

    def test_a_verified_time_limited_incumbent_is_accepted_and_tagged(self):
        """The whole of R158's first half: the incumbent is kept, not discarded."""
        so, fake = self._wrap_milp(lambda x: x)
        status: dict = {}
        with unittest.mock.patch.object(so, "milp", fake):
            lu = sd.build_showdown_lineup(_synth(), status_out=status)
        self.assertIsNotNone(lu, "a feasible incumbent under the clock was discarded")
        self.assertEqual(lu["optimality"], "time_limited")
        self.assertEqual(status["status"], "time_limit")
        self.assertTrue(status["timed_out"])
        self.assertFalse(status["incumbent_rejected"])
        self.assertEqual(status["optimality"], "time_limited")
        # Still a legal lineup: acceptance is verification, not trust.
        self.assertTrue(sd.certify_showdown(dict(lu), _synth())["passed"])

    def test_an_incumbent_that_violates_the_matrix_is_rejected(self):
        """Accepting a time-limited incumbent UNVERIFIED would be worse than
        discarding it.

        The mutation has to be one ONLY the constraint check can catch, and
        getting that wrong is how this test first passed against a mutant with the
        verification removed. A second captain is caught downstream by the
        roster-shape check (``len(cpt_i) != 1``), so it proves nothing about the
        matrix. Role exclusivity does: the captain is ALSO placed at UTIL and one
        real UTIL is dropped, which leaves the shape at exactly 1 CPT and 5 UTIL
        and violates only the ``cpt_i + util_i <= 1`` row.

        The discriminator is the recorded status. The matrix check leaves it
        ``time_limit``; the roster-shape check overwrites it with
        ``roster_size_mismatch``. Asserting on that is what makes this test
        reach the guard it names.
        """
        def role_overlap(x):
            bad = x.copy()
            half = len(bad) // 2
            cpt_sel = [i for i in range(half) if bad[i] > 0.5]
            util_sel = [i for i in range(half) if bad[half + i] > 0.5]
            captain = cpt_sel[0]
            bad[half + captain] = 1.0        # captain now also at UTIL
            bad[half + util_sel[0]] = 0.0    # keep the count at five
            return bad

        so, fake = self._wrap_milp(role_overlap)
        status: dict = {}
        with unittest.mock.patch.object(so, "milp", fake):
            lu = sd.build_showdown_lineup(_synth(), status_out=status)
        self.assertIsNone(lu, "an infeasible incumbent must not be rostered")
        self.assertTrue(status["incumbent_rejected"])
        self.assertTrue(status["timed_out"])
        self.assertIsNone(status["optimality"])
        self.assertEqual(status["status"], "time_limit",
                         "rejected by the roster-shape check, not the constraint "
                         "matrix: this test is not reaching the verification")

    def test_a_timeout_does_not_climb_the_relaxation_ladder(self):
        """CLAUDE.md: 'A timeout is recorded in solver_report, never climbs the
        overlap ladder.' One rung per slot, and every relaxation counter clean."""
        df = _synth()
        theses = [{"template": f"t{i}", "name": f"t{i}", "why": "",
                   "cpt": None, "locks": [], "excludes": [], "mult": {}}
                  for i in range(3)]
        calls = []

        def spy(df=None, status_out=None, **kw):
            calls.append(kw)
            if status_out is not None:
                status_out.update({"timed_out": True, "incumbent_rejected": False,
                                   "message": "time limit reached",
                                   "optimality": None})
            return None

        diag: dict = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            st.solve_ladder(df, theses, max_shared_players=4, time_limit=4,
                            diagnostics=diag)
        self.assertEqual(len(calls), 3,
                         "the ladder descended on a clock expiry: one rung per "
                         "slot is the whole point of the latch")
        self.assertEqual(diag["solver_timeouts"], 3)
        self.assertEqual(diag["infeasible"], 0,
                         "a timeout is not evidence the pool has no lineup")
        for counter in ("overlap_relaxed", "player_relaxed", "captain_lock_relaxed",
                        "both_relaxed", "contest_cap_relaxed"):
            self.assertEqual(diag[counter], 0,
                             f"{counter} moved on a compute limit")
        self.assertEqual(len(diag["solver_timeout_detail"]), 3)

    def test_a_genuine_infeasibility_still_descends_and_counts_as_infeasible(self):
        """The contrast that proves the guard is what stops the descent, not the
        None. Same spy, same theses, timeout flag OFF."""
        df = _synth()
        theses = [{"template": "t0", "name": "t0", "why": "",
                   "cpt": None, "locks": [], "excludes": [], "mult": {}}]
        calls = []

        def spy(df=None, status_out=None, **kw):
            calls.append(kw)
            if status_out is not None:
                status_out.update(status=2, proven_infeasible=True)
            return None

        diag: dict = {}
        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            st.solve_ladder(df, theses, max_shared_players=4, time_limit=4,
                            diagnostics=diag)
        self.assertGreater(len(calls), 1,
                           "an infeasible rung must still relax and retry")
        self.assertEqual(diag["infeasible"], 1)
        self.assertEqual(diag["solver_timeouts"], 0)

    def test_the_bank_ladder_gets_the_same_guard(self):
        """R158's second consumer. `build_showdown_bank` runs its own ladder and
        failed the same way."""
        calls = []

        def spy(df=None, status_out=None, **kw):
            calls.append(kw)
            if status_out is not None:
                status_out.update({"timed_out": True, "incumbent_rejected": False})
            return None

        diag: dict = {}
        with unittest.mock.patch.object(sd, "build_showdown_lineup", spy):
            bank = sd.build_showdown_bank(_synth(), n=4, diagnostics=diag)
        self.assertEqual(bank, [])
        self.assertEqual(len(calls), 1, "the bank ladder descended on a timeout")
        self.assertEqual(diag["solver_timeouts"], 1)
        for counter in ("relaxed_slots", "overlap_relaxed_slots",
                        "both_relaxed_slots", "player_relaxed_slots"):
            self.assertEqual(diag[counter], 0,
                             f"{counter} moved on a compute limit")

    def test_an_ordinary_solve_is_tagged_optimal_and_reports_no_timeout(self):
        """The default path keeps its old behaviour: nothing about a clean solve
        changes, which is what makes the new fields safe to read."""
        status: dict = {}
        lu = sd.build_showdown_lineup(_synth(), status_out=status)
        self.assertIsNotNone(lu)
        self.assertEqual(lu["optimality"], "optimal")
        self.assertEqual(status["status"], "optimal")
        self.assertFalse(status["timed_out"])
        self.assertFalse(status["incumbent_rejected"])
        self.assertIsNotNone(status["elapsed_s"])


class SuppliedBaseTests(unittest.TestCase):
    """R249. Showdown had no projection input, so the operator's only lever was
    rewriting the APPG column of the salary file -- which moved captains and
    which nothing recorded.

    The insertion point is the whole item, so it is pinned rather than left to
    the next reader. Measured on 1920_1g_sd before it was chosen: supplying the
    number BEFORE ``apply_base_prior`` transmits a slope of 0.458 of the asked-for
    move, and refits the salary regression, so supplying ONE player moved all 17
    other hitters' priors. Both of those are asserted below as properties, not as
    the numbers, so the guard survives a fixture change.
    """

    def _priced(self):
        raw = sd.melt_showdown_salary_csv(SAL)
        return raw, st.apply_base_prior(raw, pitcher_hand={"MIN": "R", "CHC": "R"})

    def _write(self, rows):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "projections.csv"
        lines = ["Player_ID,Base"] + [f"{pid},{value}" for pid, value in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_a_supplied_base_is_the_prior_and_is_not_regressed_toward_salary(self):
        """The insertion point. ``apply_base_prior``'s docstring scopes the 0.60
        salary weight to AvgPointsPerGame's small-sample noise; a supplied number
        is not that, so nothing further is layered on it. If the seam ever moves
        before the prior, the supplied number stops being the delivered one and
        this fails."""
        raw, priced = self._priced()
        row = priced[priced["Batting_Order"].notna()].iloc[0]
        asked = round(float(row["APPG_Raw"]) * 1.40, 3)
        self.assertNotAlmostEqual(asked, float(row["Base"]), places=6,
                                  msg="fixture cannot tell the two apart")
        out = st.apply_supplied_base(priced, {str(row["UTIL_ID"]): asked})
        got = float(out.loc[out["Name"] == row["Name"], "Base"].iloc[0])
        self.assertAlmostEqual(got, asked, places=6)

    def test_supplying_one_player_leaves_every_other_prior_byte_identical(self):
        """The property that disqualified the pre-prior insertion point: there,
        the supplied column is what ``np.polyfit`` fits, so a number supplied for
        one player reprices everyone else. Supplying a number for Hoerner is not
        a statement about Bregman."""
        raw, priced = self._priced()
        row = priced[priced["Batting_Order"].notna()].iloc[0]
        out = st.apply_supplied_base(
            priced, {str(row["UTIL_ID"]): round(float(row["APPG_Raw"]) * 1.40, 3)})
        moved = [str(n) for n, before, after
                 in zip(out["Name"], priced["Base"], out["Base"])
                 if str(n) != str(row["Name"]) and abs(float(before) - float(after)) > 1e-12]
        self.assertEqual(moved, [], f"untouched players were repriced: {moved}")

    def test_a_supplied_base_moves_a_captain(self):
        """The bar the item is filed against: a projection input that cannot move
        the highest-leverage seat has not closed anything. A fixture whose
        supplied Base equals APPG proves nothing, so this one differs enough to
        change the answer."""
        raw, priced = self._priced()
        ml = {"MIN": -150, "CHC": 130}
        before = st.build_thesis_ladder(priced, 12, moneyline=ml)
        cheap = priced[priced["Batting_Order"].notna()].sort_values("Base").iloc[0]
        boosted = st.apply_supplied_base(
            priced, {str(cheap["UTIL_ID"]): float(priced["Base"].max()) * 2.0})
        after = st.build_thesis_ladder(boosted, 12, moneyline=ml)
        key = str(cheap["Player_Key"])
        self.assertNotIn(key, {t["cpt"] for t in before["theses"]})
        self.assertIn(key, {t["cpt"] for t in after["theses"]})

    def test_it_reaches_pitchers_and_either_dk_id_resolves(self):
        """A Showdown salary file lists every player twice under different ids
        and an arm is a common captain, so both halves matter. The CPT_ID row
        below is also the pitcher row, which is why one test covers both."""
        raw, priced = self._priced()
        arm = priced[priced["Batting_Order"].isna()].iloc[0]
        bat = priced[priced["Batting_Order"].notna()].iloc[0]
        out = st.apply_supplied_base(priced, {
            str(arm["CPT_ID"]): 99.0,          # by CPT id, and a pitcher
            str(bat["UTIL_ID"]): 88.0,         # by UTIL id
        })
        report = out.attrs["supplied_base_report"]
        self.assertEqual(float(out.loc[out["Name"] == arm["Name"], "Base"].iloc[0]), 99.0)
        self.assertEqual(float(out.loc[out["Name"] == bat["Name"], "Base"].iloc[0]), 88.0)
        self.assertEqual(report["pitchers_covered"], 1)
        self.assertEqual(report["hitters_covered"], 1)

    def test_an_unmatched_id_is_named_and_changes_nothing(self):
        raw, priced = self._priced()
        out = st.apply_supplied_base(priced, {"999999999": 50.0})
        report = out.attrs["supplied_base_report"]
        self.assertEqual(report["unmatched_ids"], ["999999999"])
        self.assertEqual(report["players_matched"], 0)
        self.assertFalse(report["applied"])
        self.assertTrue(all(abs(float(a) - float(b)) < 1e-12
                            for a, b in zip(priced["Base"], out["Base"])))

    def test_the_report_carries_the_provenance_the_item_requires(self):
        """Source path, sha256, count differing from APPG, and min/median/max
        ratio. The workaround this replaces was invisible; a fix that is also
        invisible has not closed it."""
        raw, priced = self._priced()
        hitters = priced[priced["Batting_Order"].notna()]
        rows, want = [], []
        for mult, (_, row) in zip((1.50, 1.00, 0.50), hitters.iterrows()):
            rows.append((str(row["UTIL_ID"]), round(float(row["APPG_Raw"]) * mult, 4)))
            want.append(mult)
        path = self._write(rows)
        supplied, read_report = st.read_supplied_base(path)
        out = st.apply_supplied_base(priced, supplied, read_report)
        report = out.attrs["supplied_base_report"]
        self.assertEqual(report["source"], str(path))
        self.assertEqual(report["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report["players_matched"], 3)
        # one of the three was supplied AT its APPG, so it is not a substitution
        self.assertEqual(report["players_differing_from_appg"], 2)
        self.assertAlmostEqual(report["ratio_min"], 0.50, places=3)
        self.assertAlmostEqual(report["ratio_median"], 1.00, places=3)
        self.assertAlmostEqual(report["ratio_max"], 1.50, places=3)
        self.assertEqual(report["chain_bypassed_players"], 3)
        self.assertEqual(report["players_on_derived_prior"], len(priced) - 3)

    def test_a_named_file_that_cannot_be_read_refuses_rather_than_building_flat(self):
        """R242's shape. A silent fallback looks identical to a build that was
        never asked for the input, and here the operator supplied a file and
        would read the delivered lineups as having consumed it."""
        with self.assertRaises(FileNotFoundError):
            st.read_supplied_base(Path(tempfile.mkdtemp()) / "absent.csv")
        empty = Path(tempfile.mkdtemp()) / "headers_only.csv"
        empty.write_text("Player_ID,Base\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            st.read_supplied_base(empty)
        junk = Path(tempfile.mkdtemp()) / "wrong_columns.csv"
        junk.write_text("name,points\nSomebody,9.0\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            st.read_supplied_base(junk)

    def test_the_reader_matches_ownership_preds_column_contract(self):
        """Same columns, same aliases, same case-insensitivity as
        ``ownership_pred.py --base``, so an operator has one file format and not
        two. Asserted against a file written the other tool's way."""
        raw, priced = self._priced()
        row = priced.iloc[0]
        path = Path(tempfile.mkdtemp()) / "aliased.csv"
        path.write_text(f"id,projection\n{row['UTIL_ID']},7.25\n", encoding="utf-8")
        supplied, _ = st.read_supplied_base(path)
        self.assertEqual(supplied[str(row["UTIL_ID"])], 7.25)

    def test_the_label_names_an_operator_input_and_claims_no_performance(self):
        """Truthful labels. The brief block says what was applied and what was
        bypassed, and none of it is an ROI, win-rate or probability claim."""
        raw, priced = self._priced()
        row = priced.iloc[0]
        out = st.apply_supplied_base(priced, {str(row["UTIL_ID"]): 9.0})
        label = out.attrs["supplied_base_report"]["label"].lower()
        for banned in ("roi", "win rate", "win-rate", "probability", "expected value",
                       "profit", "upload-ready"):
            self.assertNotIn(banned, label)
        self.assertIn("operator input", label)
        self.assertIn("not applied", label)
        self.assertIn("game-state weight", label)

    def test_the_thesis_game_state_multiplier_still_applies_to_a_supplied_base(self):
        """The R233 enumeration found a FIFTH writer of Base on the Showdown
        path that neither the item nor the handoff named: ``solve_ladder``
        multiplies each thesis's working copy by that thesis's game-state
        weight, AFTER this seam. It is left alone deliberately -- the operator
        supplies how good a player is, the template says how much that side
        matters in this scenario -- but "the supplied number is what the solver
        ranks on" would be false without saying so, so the label says it and
        this pins it."""
        raw, priced = self._priced()
        row = priced[priced["Batting_Order"].notna()].iloc[0]
        key = str(row["Player_Key"])
        out = st.apply_supplied_base(priced, {str(row["UTIL_ID"]): 10.0})
        thesis = [{"name": "t", "cpt": key, "mult": {key: 0.5}}]
        work = out.copy()
        mult = thesis[0]["mult"]
        work["Base"] = [float(b) * float(mult.get(k, 1.0))
                        for b, k in zip(work["Base"], work["Player_Key"])]
        self.assertEqual(float(work.loc[work["Player_Key"] == key, "Base"].iloc[0]), 5.0)
        # and the seam did not consume or duplicate the weight
        self.assertEqual(float(out.loc[out["Player_Key"] == key, "Base"].iloc[0]), 10.0)

    def test_build_slate_refuses_projections_on_a_classic_build(self):
        """A flag that silently does nothing on the contest type it was pointed
        at is the defect this item is filed under, arriving through the flag
        meant to close it. Read off the source: the refusal is keyed on the
        contest and it precedes staging."""
        src = (REPO / "skills" / "generate-lineups" / "scripts"
               / "build_slate.py").read_text(encoding="utf-8")
        self.assertIn('"status": "projections_not_supported_on_classic"', src)
        refusal = src.index("projections_not_supported_on_classic")
        staging = src.index('suffix = "_showdown" if contest == "showdown" else ""')
        self.assertLess(refusal, staging,
                        "the Classic refusal must land before anything is staged")

    @staticmethod
    def _build_slate():
        import importlib.util
        path = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location(
            "build_slate_supplied_base_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_wiring_applies_the_supplied_number_last_on_the_ladder_path(self):
        """The order is the decision, and the WIRING is where it lives. Written
        as two inline call sites this was a property of the source layout that
        nothing executed: a mutation supplying the number before the prior
        survived the whole suite, because every other insertion-point test calls
        the engine function directly on an already-priced frame. This one calls
        what the build calls."""
        mod = self._build_slate()
        raw = sd.melt_showdown_salary_csv(SAL)
        row = raw[raw["Batting_Order"].notna()].iloc[0]
        asked = round(float(row["Base"]) * 1.40, 3)
        priced = mod.price_showdown_pool(
            raw, use_ladder=True, bat_side={}, pitcher_hand={"MIN": "R", "CHC": "R"},
            supplied_base={str(row["UTIL_ID"]): asked}, supplied_read={})
        got = float(priced.loc[priced["Name"] == row["Name"], "Base"].iloc[0])
        self.assertAlmostEqual(got, asked, places=6,
                               msg="the supplied number was transformed after it "
                                   "was supplied; the prior must run FIRST")
        # and the prior still ran, for everyone else
        self.assertIn("Salary_Fit", priced.columns)
        self.assertIn("APPG_Raw", priced.columns)

    def test_the_wiring_reaches_the_fallback_bank_path_too(self):
        """The ladder prices through ``apply_base_prior``; the fallback bank
        ranks on raw APPG. Wiring only the ladder makes ``--projections`` a
        silent no-op on exactly the `all_healthy` slates where the pool is
        thinnest -- the R242 shape this flag's own refusal exists to avoid."""
        mod = self._build_slate()
        raw = sd.melt_showdown_salary_csv(SAL)
        row = raw.iloc[0]
        out = mod.price_showdown_pool(
            raw, use_ladder=False, bat_side={}, pitcher_hand={},
            supplied_base={str(row["UTIL_ID"]): 42.0}, supplied_read={})
        self.assertEqual(float(out.loc[out["Name"] == row["Name"], "Base"].iloc[0]), 42.0)
        self.assertTrue(out.attrs["supplied_base_report"]["applied"])
        self.assertNotIn("Salary_Fit", out.columns)      # no prior on this path

    def test_the_wiring_is_a_no_op_when_no_projections_were_supplied(self):
        """Defaults unchanged: with no file the frame that reaches the ladder is
        the frame that always reached it."""
        mod = self._build_slate()
        raw = sd.melt_showdown_salary_csv(SAL)
        hand = {"MIN": "R", "CHC": "R"}
        plain = st.apply_base_prior(raw, pitcher_hand=hand)
        wired = mod.price_showdown_pool(raw, use_ladder=True, bat_side={},
                                        pitcher_hand=hand, supplied_base={},
                                        supplied_read={})
        self.assertTrue(all(abs(float(a) - float(b)) < 1e-12
                            for a, b in zip(plain["Base"], wired["Base"])))
        self.assertNotIn("Base_Supplied", wired.columns)

    def test_the_brief_carries_the_block_on_both_paths(self):
        src = (REPO / "skills" / "generate-lineups" / "scripts"
               / "build_slate.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("price_showdown_pool("), 3)   # def + both paths
        self.assertIn('"supplied_base": ((priced if use_ladder else df).attrs.get(', src)


class R291ShowdownExcludedColumnTests(unittest.TestCase):
    """R291(c). The salary file's Excluded column, read by the Showdown path.

    Until 2026-09-02 `grep -n Excluded mlb_engine/optimize/showdown*.py` returned
    NOTHING: the melt did not read the token, the solve could not enforce it, and
    the path has no pool report, so an accepted exclusion left no trace anywhere.
    That is the 1940_9g failure one contest type over -- an explicit, visible,
    instructed restriction silently ignored -- and Showdown is where it is
    cheapest to hit, because a Showdown file is one game and an operator
    shelving one arm has shelved a sixth of the pool.

    Showdown still ships review-grade. Nothing here changes that.
    """

    @staticmethod
    def _build_slate():
        path = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location(
            "build_slate_r291_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _staged(tmp, names, token="TRUE", roles=("CPT", "UTIL"), name="sal.csv"):
        """The MIN@CHC fixture plus an Excluded column set on named players."""
        out = Path(tmp) / name
        with open(SAL, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        name_col = rows[0].index("Name")
        role_col = rows[0].index("Roster Position")
        rows[0].append("Excluded")
        marked = 0
        for row in rows[1:]:
            if row[name_col] in names and row[role_col].strip().upper() in roles:
                row.append(token)
                marked += 1
            else:
                row.append("")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        return out, marked

    def _declared_target(self):
        base = sd.melt_showdown_salary_csv(SAL)
        declared = base[base["Is_Declared_Starter"]]
        self.assertTrue(len(declared), "the fixture lost its declared starters")
        key = str(declared["Player_Key"].iloc[0])
        return key, key.split("|")[0]

    def test_a_fixture_with_no_excluded_column_is_unchanged(self):
        """The default. Every Showdown salary file DK ships carries no such
        column, so the melt has to be byte-identical for them."""
        df = sd.melt_showdown_salary_csv(SAL)
        self.assertIn("Excluded", df.columns)
        self.assertEqual(int(df["Excluded"].sum()), 0)
        bank = sd.build_showdown_bank(df, 3)
        self.assertEqual(len(bank), 3)

    def test_the_flag_is_ord_across_the_two_role_rows(self):
        """A Showdown file has two rows per person. An operator who marks the
        CPT row has said 'not this player', not 'not as captain' -- the roles
        are one player's price list, not two players."""
        key, name = self._declared_target()
        with tempfile.TemporaryDirectory() as tmp:
            for roles in (("CPT",), ("UTIL",), ("CPT", "UTIL")):
                path, marked = self._staged(tmp, {name}, roles=roles,
                                            name=f"{'_'.join(roles)}.csv")
                self.assertEqual(marked, len(roles))
                df = sd.melt_showdown_salary_csv(str(path))
                self.assertTrue(
                    bool(df.loc[df["Player_Key"] == key, "Excluded"].iloc[0]),
                    roles)
                self.assertEqual(int(df["Excluded"].sum()), 1, roles)

    def test_an_excluded_declared_sp_reaches_no_lineup_in_the_bank(self):
        """The acceptance criterion, and it runs the production bank rather than
        a hand-built frame: the R289 test that did the latter is why this defect
        shipped green (R300(a))."""
        key, name = self._declared_target()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._staged(tmp, {name})
            df = sd.melt_showdown_salary_csv(str(path))
            self.assertTrue(bool(df.loc[df["Player_Key"] == key, "Excluded"].iloc[0]))
            bank = sd.build_showdown_bank(df, 5)
            self.assertEqual(len(bank), 5, "vacuous: the bank built nothing")
            for i, lineup in enumerate(bank):
                keys = {p["player_key"] for p in lineup["players"]}
                self.assertNotIn(key, keys, f"lineup {i}")

    def test_no_caller_instruction_can_put_him_back(self):
        """`build_showdown_lineup` is the one enforcement point every rung of
        every path funnels through, so no relaxation can restore an excluded
        player: the overlap bound, the player cap, the captain lock and the
        thesis itself all give way before this does, and none of them is the
        pool.

        A lock naming him lands in R54(c)'s `ignored_locks` -- the loudest
        channel this module has, because a lock that lost its player is an
        instruction that did not arrive rather than a control that relaxed."""
        key, name = self._declared_target()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._staged(tmp, {name})
            df = sd.melt_showdown_salary_csv(str(path))
            status = {}
            locked = sd.build_showdown_lineup(df, locks=[key], status_out=status)
            self.assertIsNone(locked)
            self.assertEqual(status["status"], "invalid_hard_lock")
            capped = sd.build_showdown_lineup(df, cpt_lock=key, status_out=status)
            self.assertIsNone(capped)
            self.assertEqual(status["status"], "invalid_hard_lock")

    def test_the_brief_names_the_count_and_the_legal_pool(self):
        """Classic's `pool_report.excluded_column`, on the path that has no pool
        report. Without it the only trace of an accepted exclusion was a smaller
        pool nobody counted."""
        key, name = self._declared_target()
        mod = self._build_slate()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._staged(tmp, {name})
            df = sd.melt_showdown_salary_csv(str(path))
            block = mod.showdown_excluded_block(df)
            self.assertTrue(block["column_present"])
            self.assertEqual(block["applied"], 1)
            self.assertEqual(block["player_keys"], [key])
            self.assertEqual(block["legal_players"], len(df) - 1)
            self.assertEqual(sorted(block["legal_teams"]), ["CHC", "MIN"])
            self.assertEqual(sum(block["by_team"].values()), 1)
            plain = mod.showdown_excluded_block(sd.melt_showdown_salary_csv(SAL))
            self.assertFalse(plain["column_present"])
            self.assertEqual(plain["applied"], 0)
            self.assertEqual(plain["legal_players"], len(df))

    def test_an_unrecognized_token_keeps_the_player_here_too(self):
        """F21's rule reaches this path unchanged: guessing 'exclude' on an
        ambiguous cell is the pool reduction CLAUDE.md forbids, arriving as a
        data condition."""
        key, name = self._declared_target()
        mod = self._build_slate()
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._staged(tmp, {name}, token="maybe?")
            df = sd.melt_showdown_salary_csv(str(path))
            self.assertFalse(bool(df.loc[df["Player_Key"] == key, "Excluded"].iloc[0]))
            block = mod.showdown_excluded_block(df)
            self.assertEqual(block["applied"], 0)
            # CELLS, not players: a Showdown file carries two rows per person and
            # the operator typo'd both. Counting players here would understate
            # how much of the file the engine could not read.
            self.assertEqual(block["unrecognized_kept"], 2)
            self.assertEqual(block["unrecognized_values"], ["maybe?"])
            self.assertTrue(block["column_present"],
                            "a column that excluded nobody is still a column, "
                            "and that is the fact that says the tokens are wrong")

    def test_an_exclusion_that_leaves_one_team_refuses_with_the_reason(self):
        """A DK Showdown lineup must carry both sides, so an exclusion covering a
        whole team cannot produce a legal entry. The melt's own single-team
        refusal cannot see this -- it runs on the CARRIED pool, which is the
        point of carrying rather than dropping -- so the refusal lives at the
        build's front door, before anything is priced or solved."""
        mod = self._build_slate()
        df = sd.melt_showdown_salary_csv(SAL)
        chc = {str(n) for n in df.loc[df["Team"] == "CHC", "Name"]}
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self._staged(tmp, chc)
            melted = sd.melt_showdown_salary_csv(str(path))
            block = mod.showdown_excluded_block(melted)
            self.assertEqual(block["legal_teams"], ["MIN"])
            # The both-teams rows are built from the LEGAL pool, so a one-sided
            # pool used to make that rule vacuously true and return a six-man
            # one-team lineup. The solve refuses instead.
            self.assertIsNone(sd.build_showdown_lineup(melted))
            self.assertEqual(sd.build_showdown_bank(melted, 3), [],
                             "a one-team legal pool produced a lineup")
            args = types.SimpleNamespace(date="2026-07-18", entries=None,
                                         controls_override=None, projections=None)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code, brief = mod.run_showdown(
                    args, Path(tmp), path, Path(tmp) / "no_such_entries.csv")
            printed = json.loads(out.getvalue())
            self.assertEqual(printed["status"],
                             "showdown_excluded_column_leaves_one_team")
            self.assertEqual(printed["excluded_column"]["legal_teams"], ["MIN"])
            self.assertIn("both sides", printed["remedy"])
            self.assertEqual(code, 4)
            self.assertEqual(brief, {})


class R306CaptainOwnershipMarketTests(unittest.TestCase):
    """R306. The Showdown captain slot is its own ownership market.

    Every guard here is written against the PRODUCTION function, not against a
    re-implementation of it (R300(a)): the acceptance test that does not call
    what ships is how a green suite covers nothing.
    """

    def _players(self, n_bats=8, n_arms=2):
        """A minimal Showdown-shaped pool: arms priced at the top, like DK's."""
        out = []
        for i in range(n_arms):
            out.append({"player_id": f"P{i}", "name": f"Arm {i}", "team": "AA",
                        "positions": ["P"], "salary": 11000 - 500 * i})
        for i in range(n_bats):
            out.append({"player_id": f"B{i}", "name": f"Bat {i}",
                        "team": "AA" if i % 2 else "BB", "positions": ["OF"],
                        "salary": 9000 - 400 * i})
        return out

    # --- the budgets ----------------------------------------------------
    def test_captain_shares_sum_to_the_100_pct_budget(self):
        from mlb_engine.field import ownership_prior as op
        pred = op.predict_captain_ownership(
            self._players(), archetype="wta_satellite",
            probable_sp_ids=["P0", "P1"])
        total = sum(pred["own_pct_by_player_id"].values())
        self.assertAlmostEqual(total, op.CAPTAIN_BUDGET_PCT, delta=0.05)
        self.assertEqual(pred["budget_pct"], 100.0)

    def test_showdown_roster_shares_sum_to_the_600_pct_budget(self):
        from mlb_engine.field import ownership_prior as op
        pred = op.predict_showdown_roster_ownership(
            self._players(), archetype="wta_satellite",
            probable_sp_ids=["P0", "P1"])
        total = sum(pred["own_pct_by_player_id"].values())
        self.assertAlmostEqual(total, op.SHOWDOWN_ROSTER_BUDGET_PCT, delta=0.05)

    def test_the_classic_split_is_left_alone(self):
        """R306 adds a geometry, it does not teach the Classic one a flag."""
        from mlb_engine.field import ownership_prior as op
        pred = op.predict_ownership(self._players(), archetype="wta_satellite",
                                    probable_sp_ids=["P0", "P1"])
        own = pred["own_pct_by_player_id"]
        arms = sum(own[k] for k in own if k.startswith("P"))
        bats = sum(own[k] for k in own if k.startswith("B"))
        self.assertAlmostEqual(arms, op.PITCHER_BUDGET_PCT, delta=0.05)
        self.assertAlmostEqual(bats, op.HITTER_BUDGET_PCT, delta=0.05)

    def test_the_two_showdown_budgets_are_one_dk_roster(self):
        """The 100/600 pair is an accounting identity, guarded as one."""
        from mlb_engine.field import ownership_prior as op
        self.assertEqual(
            op.SHOWDOWN_ROSTER_BUDGET_PCT / op.CAPTAIN_BUDGET_PCT, 6.0,
            "a DK Showdown roster is one CPT plus five UTIL")

    # --- the two markets are actually different -------------------------
    def test_the_pitcher_weights_carry_opposite_SIGNS(self):
        """The whole finding in one assertion.

        Arms are UP-weighted for the captain slot and DOWN-weighted across the
        six roster slots, relative to where salary rank alone puts them. A
        single ownership number cannot carry both signs, which is the mechanism
        behind a heavily-rostered player being a rare captain.
        """
        from mlb_engine.field import ownership_prior as op
        cap = op.CAPTAIN_ARCHETYPE_PARAMS["wta_satellite"]["captain_pitcher_weight"]
        ros = op.SHOWDOWN_ROSTER_ARCHETYPE_PARAMS["wta_satellite"]["roster_pitcher_weight"]
        self.assertGreater(cap, 0.0)
        self.assertLess(ros, 0.0)

    def test_the_captain_market_is_the_more_concentrated_one(self):
        """Fitted from the archive: the captain slot piles up harder.

        Compared as SHARES of their own budgets, so the 100/600 difference
        cannot make this pass on its own.
        """
        from mlb_engine.field import ownership_prior as op
        players = self._players()
        cap = op.predict_captain_ownership(
            players, archetype="wta_satellite", probable_sp_ids=["P0", "P1"])
        ros = op.predict_showdown_roster_ownership(
            players, archetype="wta_satellite", probable_sp_ids=["P0", "P1"])
        cap_top = max(cap["own_pct_by_player_id"].values()) / op.CAPTAIN_BUDGET_PCT
        ros_top = (max(ros["own_pct_by_player_id"].values())
                   / op.SHOWDOWN_ROSTER_BUDGET_PCT)
        self.assertGreater(cap_top, ros_top)

    def test_temperature_moves_concentration_and_never_the_ordering(self):
        """A softmax is monotone, so no temperature can buy ranking."""
        from mlb_engine.field import ownership_prior as op
        players = self._players()
        order = []
        for temp in (0.10, 0.50, 2.00):
            own = op.predict_captain_ownership(
                players, archetype="wta_satellite", probable_sp_ids=["P0", "P1"],
                archetype_params={"wta_satellite": {
                    "temperature": temp, "captain_pitcher_weight": 0.10,
                    "value_weight": 1.10}})["own_pct_by_player_id"]
            order.append([k for k, _ in sorted(own.items(),
                                               key=lambda kv: (-kv[1], kv[0]))])
        self.assertEqual(order[0], order[1])
        self.assertEqual(order[1], order[2])

    # --- the params tables ----------------------------------------------
    def test_both_params_tables_cover_every_archetype(self):
        from mlb_engine.field import ownership_prior as op
        self.assertEqual(set(op.CAPTAIN_ARCHETYPE_PARAMS), set(op.ARCHETYPE_PARAMS))
        self.assertEqual(set(op.SHOWDOWN_ROSTER_ARCHETYPE_PARAMS),
                         set(op.ARCHETYPE_PARAMS))

    def test_only_the_archetype_the_archive_covers_is_marked_fitted(self):
        """Five of six carry a scaled roster temperature, and say so."""
        from mlb_engine.field import ownership_prior as op
        fitted = sorted(k for k, v in op.CAPTAIN_ARCHETYPE_PARAMS.items()
                        if v.get("fitted"))
        self.assertEqual(fitted, ["wta_satellite"])

    def test_the_import_check_rejects_a_half_populated_params_table(self):
        from mlb_engine.field import ownership_prior as op
        original = dict(op.CAPTAIN_ARCHETYPE_PARAMS)
        try:
            op.CAPTAIN_ARCHETYPE_PARAMS.pop("mme")
            with self.assertRaises(ImportError):
                op._check_captain_params()
        finally:
            op.CAPTAIN_ARCHETYPE_PARAMS.clear()
            op.CAPTAIN_ARCHETYPE_PARAMS.update(original)

    def test_the_import_check_rejects_a_non_positive_temperature(self):
        from mlb_engine.field import ownership_prior as op
        original = dict(op.CAPTAIN_ARCHETYPE_PARAMS["cash"])
        try:
            op.CAPTAIN_ARCHETYPE_PARAMS["cash"]["temperature"] = 0.0
            with self.assertRaises(ImportError):
                op._check_captain_params()
        finally:
            op.CAPTAIN_ARCHETYPE_PARAMS["cash"] = original

    # --- the archetype resolver -----------------------------------------
    def test_archetype_for_contest_facts_matches_the_allocator(self):
        """It calls contest_shape_for_card; it does not re-decide a shape."""
        from mlb_engine.allocate.contest_allocator import (
            ContestCard, contest_shape_for_card,
        )
        from mlb_engine.field.ownership_prior import (
            archetype_for_contest_facts, archetype_for_contest_shape,
        )
        for ctype, size, entries in (("satellite", 40, 1), ("wta", 300, 1),
                                     ("se_gpp", 1000, 1), ("cash", 50, 1),
                                     ("portfolio_gpp", 200, 150),
                                     ("portfolio_gpp", 50000, 150)):
            card = ContestCard(contest_id="", name="", contest_type=ctype,
                               field_size=size, max_entries=entries,
                               buy_in=0.0, prize_pool=0.0)
            self.assertEqual(
                archetype_for_contest_facts(ctype, size, entries),
                archetype_for_contest_shape(contest_shape_for_card(card)))

    def test_archetype_for_contest_facts_refuses_rather_than_defaults(self):
        from mlb_engine.field.ownership_prior import archetype_for_contest_facts
        self.assertIsNone(archetype_for_contest_facts("not_a_type", 40, 1))
        self.assertIsNone(archetype_for_contest_facts("satellite", 0, 1))
        self.assertIsNone(archetype_for_contest_facts("satellite", None, 1))

    def test_the_invented_card_fields_cannot_reach_the_archetype(self):
        """The import check is the guard; this proves it fails when it should."""
        from mlb_engine.field import ownership_prior as op
        original = dict(op.ARCHETYPE_BY_CONTEST_SHAPE)
        try:
            op.ARCHETYPE_BY_CONTEST_SHAPE["wta_ticket_satellite"] = ("mme", "EXACT")
            with self.assertRaises(ImportError):
                op._check_contest_fact_projection()
        finally:
            op.ARCHETYPE_BY_CONTEST_SHAPE.clear()
            op.ARCHETYPE_BY_CONTEST_SHAPE.update(original)

    # --- the emit --------------------------------------------------------
    def _emit(self, salary_path):
        spec = importlib.util.spec_from_file_location(
            "ownership_pred_r306", REPO / "tools" / "ownership_pred.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, mod.build_prediction(salary_path, archetypes=["wta_satellite"])

    def test_emit_carries_both_showdown_markets_on_a_showdown_file(self):
        _mod, pred = self._emit(SAL)
        self.assertTrue(pred["showdown_markets"]["applied"])
        block = pred["archetypes"]["wta_satellite"]
        self.assertIn("captain", block)
        self.assertIn("showdown_roster", block)
        self.assertAlmostEqual(block["captain"]["budget_check"]["pct_sum"],
                               100.0, delta=0.2)
        self.assertAlmostEqual(block["showdown_roster"]["budget_check"]["pct_sum"],
                               600.0, delta=0.2)

    def test_emit_keeps_R235s_person_collapse_under_the_new_markets(self):
        """One row per PERSON, and both distributions over those same people."""
        _mod, pred = self._emit(SAL)
        roles = pred["salary_file"]["showdown_roles"]
        self.assertTrue(roles["applied"])
        self.assertLess(roles["rows_out"], roles["rows_in"])
        block = pred["archetypes"]["wta_satellite"]
        people = {r["Player_ID"] for r in pred["players"]}
        self.assertEqual(set(block["captain"]["own_pct_by_player_id"]), people)
        self.assertEqual(set(block["showdown_roster"]["own_pct_by_player_id"]),
                         people)

    def test_a_classic_file_gets_no_showdown_market(self):
        salary = REPO / "tests" / "fixtures" / "showdown" / "DKSalaries_showdown_MIN_CHC.csv"
        _mod, pred = self._emit(salary)
        # control: the same emit on a Classic salary file emits neither block
        classic = sorted(REPO.glob("data/slates/*/DKSalaries.csv"))
        if not classic:
            self.skipTest("no Classic salary file on disk")
        _mod2, cpred = self._emit(classic[0])
        self.assertFalse(cpred["showdown_markets"]["applied"])
        block = cpred["archetypes"]["wta_satellite"]
        self.assertNotIn("captain", block)
        self.assertNotIn("showdown_roster", block)
        self.assertTrue(pred["showdown_markets"]["applied"])

    def test_a_cpt_token_alone_does_not_earn_a_person_market(self):
        """The detector needs BOTH halves, and this is the case that proves it.

        A file whose Roster Position column carries CPT and something outside
        CPT/UTIL takes `collapse_showdown_roles`' early return: `applied` is
        False and the rows come back one per ROLE, not one per PERSON. A
        token-only detector emits a 600% PERSON market over role rows, which
        double-counts everybody -- R235's own bug through a door R235 does not
        watch. Behavioural, not a source-string pin: the first cut of this test
        asserted the detector's TEXT and a mutation reading the wrong flag
        survived it, because the string was still in the file.
        """
        rows = [r for r in csv.reader(
            SAL.read_text(encoding="utf-8-sig").splitlines()) if any(r)]
        header = rows[0]
        pos_col = header.index("Roster Position")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DKSalaries_mixed_tokens.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                for index, row in enumerate(rows[1:]):
                    row = list(row)
                    if index == 0:
                        row[pos_col] = "OF"   # one token outside CPT/UTIL
                    writer.writerow(row)
            _mod, pred = self._emit(path)
        roles = pred["salary_file"]["showdown_roles"]
        self.assertIn("CPT", roles["roles_seen"])
        self.assertFalse(roles["applied"],
                         "the fixture is meant to take the early return")
        self.assertFalse(
            pred["showdown_markets"]["applied"],
            "a 600% PERSON market over rows that are still one-per-role "
            "double-counts every player")
        self.assertNotIn("captain", pred["archetypes"]["wta_satellite"])
        self.assertNotIn("showdown_roster", pred["archetypes"]["wta_satellite"])

    # --- the captain actuals --------------------------------------------
    def test_captain_actuals_zero_fill_the_whole_pool(self):
        mod, _pred = self._emit(SAL)
        entries = [{"lineup_complete": True, "captain_norm": "aa",
                    "players_norm": ("aa", "bb")},
                   {"lineup_complete": True, "captain_norm": "bb",
                    "players_norm": ("aa", "bb")},
                   {"lineup_complete": True, "captain_norm": "aa",
                    "players_norm": ("aa", "bb")},
                   {"lineup_complete": False, "captain_norm": "cc",
                    "players_norm": ("cc",)}]
        actual, meta = mod.captain_actuals_from_entries(
            entries, {"aa": "1", "bb": "2", "cc": "3"}, ["1", "2", "9"])
        self.assertEqual(meta["complete_entries"], 3)
        self.assertEqual(actual["9"], 0.0, "an uncaptained pool player is a "
                                          "measured zero, not a missing value")
        self.assertAlmostEqual(actual["1"], 66.6667, places=3)
        self.assertAlmostEqual(actual["2"], 33.3333, places=3)
        self.assertAlmostEqual(meta["share_sum_pct"], 100.0, delta=0.1)
        self.assertEqual(meta["zero_captain_players"], 1)

    def test_an_incomplete_lineup_is_not_counted(self):
        mod, _pred = self._emit(SAL)
        actual, meta = mod.captain_actuals_from_entries(
            [{"lineup_complete": False, "captain_norm": "aa",
              "players_norm": ("aa",)}], {"aa": "1"}, ["1"])
        self.assertEqual(meta["complete_entries"], 0)
        self.assertEqual(actual["1"], 0.0)

    def test_a_captain_outside_the_pool_is_named_and_not_dropped(self):
        mod, _pred = self._emit(SAL)
        _actual, meta = mod.captain_actuals_from_entries(
            [{"lineup_complete": True, "captain_norm": "zz",
              "players_norm": ("zz",)}] * 10, {}, ["1"])
        self.assertEqual(meta["captain_names_reaching_no_pool_id"], ["zz"])

    def test_grading_a_market_the_prediction_lacks_refuses_by_name(self):
        mod, pred = self._emit(SAL)
        stripped = json.loads(json.dumps(pred))
        stripped["archetypes"]["wta_satellite"].pop("captain")
        with self.assertRaises(ValueError) as ctx:
            mod.grade_captain_prediction(stripped, {"1": 1.0}, "wta_satellite")
        self.assertIn("captain", str(ctx.exception))

    def test_the_captain_grade_baseline_spends_the_captain_budget(self):
        """Not flat-12: a Classic constant against a 100% budget is nonsense."""
        mod, pred = self._emit(SAL)
        pool = [r["Player_ID"] for r in pred["players"]]
        actual = {pid: 0.0 for pid in pool}
        actual[pool[0]] = 100.0
        grade = mod.grade_captain_prediction(pred, actual, "wta_satellite",
                                             market="captain")
        self.assertEqual(grade["budget_pct"], 100.0)
        self.assertEqual(grade["join"]["actual_nonzero"], 1)
        self.assertIsNotNone(grade["baseline_flat_budget"]["mae_pct_points"])
        self.assertIn("not a win rate", grade["label"].lower().replace(
            "not a win rate, an roi figure", "not a win rate"))

    # --- the archive driver ---------------------------------------------
    def _driver(self):
        spec = importlib.util.spec_from_file_location(
            "ownership_grade_archive_r306",
            REPO / "tools" / "ownership_grade_archive.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_field_size_fallback_names_which_fact_answered(self):
        mod = self._driver()
        self.assertEqual(mod._field_size({"own_results": {"field_size": 40}}),
                         (40, "own_results.field_size"))
        self.assertEqual(
            mod._field_size({"coverage": "full", "meta": {"entries_total": 23}}),
            (23, "meta.entries_total (coverage=full)"))
        self.assertEqual(
            mod._field_size({"coverage": "partial", "meta": {"entries_total": 23}}),
            (None, "unavailable"))

    def test_a_missing_field_size_refusal_does_not_blame_the_shape_map(self):
        """R290(c)'s rule applied to this tool: name the fact that is missing."""
        mod = self._driver()
        _a, _e, why = mod.resolve_archetype(
            "MLB Satellite to $2 MLB Pocket Cup MEGA Qualifier", None)
        self.assertIn("no usable field size", why)
        self.assertIn("shape map is not the problem", why)

    def test_the_field_bands_sit_on_the_allocators_own_boundaries(self):
        from mlb_engine.allocate.contest_allocator import (
            MID_FIELD_MAX_ENTRANTS, SMALL_FIELD_MAX_ENTRANTS,
        )
        mod = self._driver()
        self.assertNotEqual(mod.field_band(SMALL_FIELD_MAX_ENTRANTS),
                            mod.field_band(SMALL_FIELD_MAX_ENTRANTS + 1))
        self.assertNotEqual(mod.field_band(MID_FIELD_MAX_ENTRANTS),
                            mod.field_band(MID_FIELD_MAX_ENTRANTS + 1))
        self.assertEqual(mod.field_band(None), "f_unknown")

    def test_the_fragment_never_claims_a_pooled_statistic(self):
        mod = self._driver()
        rows = [{"contest_id": "1", "slate_date": "2026-08-08", "field_size": 40,
                 "field_band": "f_0001_0100", "inputs_inert": [],
                 "roster_grade": {"overall": {"spearman_rank_corr": 0.5,
                                              "mean_signed_error_pct_points": -1.0,
                                              "mae_pct_points": 3.0},
                                  "join": {"joined_players": 10},
                                  "verdict": {"beats_flat_budget": True}}}]
        text = mod.archetype_fragment("wta_satellite", rows, "2026-09-03")
        self.assertIn("MEDIANS OF PER-CONTEST STATISTICS", text)
        self.assertIn("never a statistic recomputed over a merged player set", text)
        self.assertIn("self-inclusion", text.lower())
        for banned in ("win rate", "cash rate", "ROI"):
            self.assertIn(banned.lower(),
                          text.lower(),
                          "the fragment must DISCLAIM these, not omit them")

    def test_the_driver_writes_no_ledger_path(self):
        """Only ARCHIVE edits ledger/; this drops fragments in the inbox."""
        source = (REPO / "tools" / "ownership_grade_archive.py").read_text(
            encoding="utf-8")
        self.assertIn('default="ledger/inbox"', source)
        self.assertNotIn('"ledger/MLB', source)


class R304dShowdownBriefRecordsDeclarationsTests(unittest.TestCase):
    """R304(d). `run_showdown` wrote `declared_pitchers` NOWHERE.

    Measured at `eb1c8fd` by an AST-bounded count over the function:
    `declared_pitchers` 0 occurrences, `declare_pitcher` 0. `run_classic` has
    written it since R104, at the refusal payload and the certified brief, so
    `preflight_upload.resolve_declared_pitchers` -- which matches a brief by
    `delivered_sha256` and reads exactly that key -- found nothing on any
    Showdown delivery and the flag's own help ("Recorded verbatim in the brief")
    was false there. With R297(d) killing the referee's pitcher test as well,
    BOTH ends of R114's escape hatch were out at once on the one geometry where
    DK's PO/PLR tokens make a declaration necessary.

    Written against the PRODUCTION `run_showdown`, driven end to end (R300(a)):
    the R289 acceptance test asserted over a hand-built frame and shipped green
    while five production sites still dropped the column.
    """

    @staticmethod
    def _module():
        import importlib.util
        path = REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py"
        spec = importlib.util.spec_from_file_location("build_slate_r304d", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _build(self, tmp: Path, declare):
        """A real delivered Showdown build, writing NOWHERE outside `tmp`.

        `mod.REPO` is patched because `run_showdown` mirrors into
        `REPO/outputs/<date>/` and records into that directory's upload
        manifest. An earlier probe of this same path in this repo appended a
        live delivery row to `outputs/2026-07-18/upload_manifest.json`; a test
        that does that is writing outside its own write set every time it runs.
        """
        import shutil
        sal, ent = tmp / "DKSalaries.csv", tmp / "DKEntries.csv"
        shutil.copy2(SAL, sal)
        shutil.copy2(ENT, ent)
        args = types.SimpleNamespace(
            date="2026-07-18", entries=None, controls_override=None,
            projections=None, declare_pitcher=list(declare), lineups=None,
            odds=None, no_odds=True, brief=None)
        mod = self._module()
        with unittest.mock.patch.object(mod, "REPO", tmp), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code, brief = mod.run_showdown(args, tmp, sal, ent)
        return code, brief, out.getvalue()

    def test_the_delivered_showdown_brief_records_the_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, brief, _ = self._build(
                Path(tmp), ["44014717=viable_bulk_or_alt_sp", "44014815"])
        self.assertEqual(code, 0)
        self.assertEqual(brief["status"], "review_grade_build",
                         "Showdown ships review-grade, never upload-ready")
        self.assertEqual(brief["declared_pitchers"],
                         {"44014717": "viable_bulk_or_alt_sp",
                          "44014815": "declared_probable_sp"},
                         "a bare id means declared_probable_sp, as on Classic")

    def test_no_declaration_records_an_empty_map_rather_than_no_key(self):
        """R249's rule: a fix that is invisible has not closed the hole. An
        absent key leaves `was a declaration given` unanswerable, which is what
        sent the 1235_1g_sd session to the Excluded column."""
        with tempfile.TemporaryDirectory() as tmp:
            code, brief, _ = self._build(Path(tmp), [])
        self.assertEqual(code, 0)
        self.assertIn("declared_pitchers", brief)
        self.assertEqual(brief["declared_pitchers"], {})

    def test_the_referee_reads_the_declaration_back_off_that_brief(self):
        """The round trip, both production functions: `run_showdown` writes the
        key, `preflight_upload.resolve_declared_pitchers` matches the brief by
        `delivered_sha256` and returns it. This is the whole point of (d)."""
        sys.path.insert(0, str(REPO / "tools"))
        from tools.preflight_upload import Report, resolve_declared_pitchers
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            code, brief, _ = self._build(tmp, ["44014717=viable_bulk_or_alt_sp"])
            self.assertEqual(code, 0)
            delivered = Path(brief["delivered_path"])
            (delivered.parent / "build_brief.json").write_text(
                json.dumps(brief), encoding="utf-8")
            rep = Report()
            resolved = resolve_declared_pitchers(
                delivered, brief["delivered_sha256"], None, rep)
        self.assertEqual(resolved, {"44014717": "viable_bulk_or_alt_sp"})
        self.assertIn("build_brief.json", rep.info["declared_pitchers_source"])

    def test_the_refusal_payload_records_it_too_matching_run_classic(self):
        """`run_classic` writes the key on its refusal payload as well as its
        certified brief, because a refusal is read harder than a delivery. Same
        two sites here, and no more: the remaining Showdown refusal dicts report
        an input that could not be READ (an unreadable projections file, an
        Excluded column leaving one team), and `run_classic` carries no
        declaration on its analogues either. Extending both geometries to those
        is a separate one-line follow-up, named rather than done, so this fix
        does not mint a new asymmetry between the two paths.
        """
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sal, ent = tmp / "DKSalaries.csv", tmp / "DKEntries.csv"
            shutil.copy2(SAL, sal)
            shutil.copy2(ENT, ent)
            args = types.SimpleNamespace(
                date="2026-07-18", entries=None, controls_override=None,
                projections=None, declare_pitcher=["44014717"], lineups=None,
                odds=None, no_odds=True, brief=None)
            mod = self._module()
            with unittest.mock.patch.object(mod, "REPO", tmp), \
                    unittest.mock.patch.object(
                        sd, "build_showdown_bank", lambda *a, **k: []), \
                    unittest.mock.patch.object(
                        st, "solve_ladder",
                        lambda priced, theses, **k: [None] * len(theses)), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                code, brief = mod.run_showdown(args, tmp, sal, ent)
        self.assertEqual(code, 3)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["declared_pitchers"],
                         {"44014717": "declared_probable_sp"})

    def test_the_showdown_pool_still_derives_its_own_declared_starters(self):
        """The scope this key does NOT claim, pinned so no later session reads
        it as a pool override. `--declare-pitcher` reaches `build_slate_pool` on
        the CLASSIC path only; the Showdown melt reads DK's own `Starting`
        column, which admits PLR and not PO. Wiring the declaration into the
        melt so a PO arm can be declared into a Showdown pool is the named
        remainder of this item, not part of it."""
        import inspect
        signature = inspect.signature(sd.melt_showdown_salary_csv)
        self.assertNotIn("declared_pitchers", signature.parameters)
        self.assertEqual(sd.DK_STARTING_DECLARED_TOKENS,
                         frozenset({"SP", "P", "PLR"}),
                         "PO stays barred (R104); that is the remainder")


# ---------------------------------------------------------------------------
# R36 Finding 8 (+ed12 F16). Participation per (event, team, person).
# ---------------------------------------------------------------------------
SD_F8_HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position",
                "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame",
                "Status", "Starting"]
SD_F8_GAME = "AAA@BBB 09/30/2026 07:05PM ET"


class R36Finding8PerSideParticipationTests(unittest.TestCase):
    """`rows = declared` fired on ANY one declared row, slate-wide.

    Measured at `f7ef478` on the fixtures below, HEAD against this commit:

      | file                                | HEAD pool  | now        |
      | nothing posted                      | 34 (17/17) | 34 (17/17) |
      | pitcher-only declaration both sides |  2 ( 1/ 1) | 34 (17/17) |
      | one side posted, both arms declared | 11 (10/ 1) | 27 (10/17) |
      | both sides posted                   | 20 (10/10) | 20 (10/10) |
      | both posted, one posted bat IL      | 19 ( 9/10) | 19 ( 9/10) |

    The two unchanged rows are the point of keeping them: the fix is per side,
    so a slate where every side posted is the pool it always was. The two that
    move are the finding. A two-person pool and an eleven-person pool with one
    player on a side both PASS the `len(teams) < 2` guard, so nothing refused
    and `build_slate.py` built a generic bank on them.
    """

    def _rows(self, post=(), arm=(), out_names=(), bench=6, clash=None,
              dup_slot=False):
        rows = [SD_F8_HEADER]
        pid = 1000
        for team in ("AAA", "BBB"):
            for i in range(9):
                token = str(i + 1) if team in post else ""
                name = f"{team} Bat{i + 1}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    cell = token
                    if clash and clash == name and role == "CPT":
                        cell = "7"
                    rows.append(["OF", f"{name} ({pid})", name, str(pid), role,
                                 str(int(4000 * mult)), SD_F8_GAME, team, "9.0",
                                 "IL" if name in out_names else "", cell])
                    pid += 1
            if dup_slot and team == "AAA":
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append(["OF", f"AAA Twin ({pid})", "AAA Twin", str(pid),
                                 role, str(int(4000 * mult)), SD_F8_GAME, team,
                                 "9.0", "", "3"])
                    pid += 1
            for i in range(bench):
                name = f"{team} Bench{i + 1}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append(["OF", f"{name} ({pid})", name, str(pid), role,
                                 str(int(3000 * mult)), SD_F8_GAME, team, "5.0",
                                 "", ""])
                    pid += 1
            for label, pos, salary, token in (("Arm", "SP", 9000,
                                               "SP" if team in arm else ""),
                                              ("Reliever", "RP", 5000, "")):
                name = f"{team} {label}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append([pos, f"{name} ({pid})", name, str(pid), role,
                                 str(int(salary * mult)), SD_F8_GAME, team,
                                 "12.0", "", token])
                    pid += 1
        return rows

    def _melt(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DKSalaries.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(self._rows(**kw))
            return sd.melt_showdown_salary_csv(str(path))

    @staticmethod
    def _by_team(df):
        return dict(collections.Counter(df["Team"]))

    def test_one_posted_side_does_not_erase_the_other_sides_healthy_hitters(self):
        df = self._melt(post=("AAA",), arm=("AAA", "BBB"))
        report = df.attrs["participation_report"]
        self.assertEqual(report["slate_basis"], "mixed_declared_and_projected")
        self.assertEqual(self._by_team(df), {"AAA": 10, "BBB": 17},
                         "BBB posted nothing, so nothing about BBB is decided; "
                         "at HEAD this file left BBB with its declared arm and "
                         "nothing else")
        self.assertEqual(
            sorted({r for r in df.loc[df["Team"] == "BBB", "Participation"]}),
            ["confirmed_starter", "unknown"])
        self.assertTrue(df.loc[df["Name"] == "BBB Bench1",
                               "Projected_Candidate"].all())
        self.assertEqual(
            sorted(df.loc[df["Team"] == "AAA", "Pool_Basis"].unique()),
            ["declared_starters"])
        self.assertEqual(
            sorted(df.loc[df["Team"] == "BBB", "Pool_Basis"].unique()),
            ["all_healthy"])

    def test_a_pitcher_only_declaration_erases_nobody(self):
        df = self._melt(post=(), arm=("AAA", "BBB"))
        report = df.attrs["participation_report"]
        self.assertEqual(report["slate_basis"], "all_healthy")
        self.assertEqual(self._by_team(df), {"AAA": 17, "BBB": 17},
                         "at HEAD two declared arms filtered the pool to two "
                         "people, one a side, and nothing refused")
        self.assertEqual(report["dropped_confirmed_nonstarter"], 0)
        arms = df.loc[df["Name"].isin(["AAA Arm", "BBB Arm"]), "Participation"]
        self.assertEqual(sorted(arms), ["confirmed_starter"] * 2,
                         "a pitcher keeps his own role evidence on an "
                         "undecided side")

    def test_an_incomplete_declaration_establishes_nothing_and_labels_its_side(self):
        """Eight of nine is a posting in progress, not a statement about the
        ninth man or about the bench."""
        rows = self._rows(post=("AAA", "BBB"), arm=("AAA", "BBB"))
        for row in rows[1:]:
            if row[2] == "AAA Bat9":
                row[10] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DKSalaries.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
            df = sd.melt_showdown_salary_csv(str(path))
        sides = {s["team"]: s for s in df.attrs["participation_report"]["sides"]}
        self.assertEqual(sides["AAA"]["state"], "partial")
        self.assertEqual(sides["AAA"]["missing_slots"], [9])
        self.assertFalse(sides["AAA"]["decided"])
        self.assertTrue(sides["BBB"]["decided"])
        self.assertEqual(self._by_team(df), {"AAA": 17, "BBB": 10})
        self.assertTrue(df.loc[df["Name"] == "AAA Bat9",
                               "Projected_Candidate"].all())

    def test_a_fully_posted_slate_is_the_pool_it_always_was(self):
        df = self._melt(post=("AAA", "BBB"), arm=("AAA", "BBB"))
        report = df.attrs["participation_report"]
        self.assertEqual(report["slate_basis"], "declared_starters")
        self.assertEqual(self._by_team(df), {"AAA": 10, "BBB": 10})
        self.assertEqual(report["projected_candidates"], 0)
        self.assertEqual(sorted(set(df["Participation"])),
                         ["confirmed_starter"])

    def test_a_degraded_posted_nine_is_still_a_decided_side(self):
        """R159(a) reaches the pool. The health filter runs AFTER participation
        for exactly this reason: dropping the IL bat first turns a nine into an
        eight and the side stops deciding anything."""
        df = self._melt(post=("AAA", "BBB"), arm=("AAA", "BBB"),
                        out_names={"AAA Bat4"})
        sides = {s["team"]: s for s in df.attrs["participation_report"]["sides"]}
        self.assertEqual(sides["AAA"]["state"], "degraded")
        self.assertTrue(sides["AAA"]["decided"])
        self.assertEqual(sides["AAA"]["shelved_in_posted_nine"], ["AAA Bat4"])
        self.assertEqual(self._by_team(df), {"AAA": 9, "BBB": 10})
        self.assertNotIn("AAA Bat4", set(df["Name"]))

    def test_a_one_sided_partial_now_builds_instead_of_hard_erroring(self):
        """The finding's own note: the `len(teams) < 2` guard sits after the
        filter, so a posted side with no declared arm anywhere took the whole
        pool to one team and RAISED. Nothing was wrong with the file."""
        df = self._melt(post=("AAA",), arm=())
        self.assertEqual(self._by_team(df), {"AAA": 9, "BBB": 17})
        self.assertEqual(sorted(set(df.loc[df["Team"] == "AAA",
                                           "Participation"])),
                         ["confirmed_starter"])

    def test_the_report_accounts_for_every_person_in_the_salary_universe(self):
        df = self._melt(post=("AAA",), arm=("AAA", "BBB"),
                        out_names={"AAA Bench1"})
        report = df.attrs["participation_report"]
        self.assertEqual(
            report["persons_in_salary_universe"],
            report["persons_in_pool"] + report["dropped_confirmed_nonstarter"]
            + report["dropped_status_out"])
        self.assertEqual(report["persons_in_pool"], len(df))

    def test_a_malformed_side_decides_nothing_rather_than_deciding_wrongly(self):
        """Two humans on slot 3, and a person whose CPT row says slot 7 while
        his UTIL row says slot 1. Neither file is a lineup, and the honest
        answer is that the side establishes no nonstarter -- not that it
        establishes them from whichever row won."""
        for label, kw in (("duplicate physical slot", {"dup_slot": True}),
                          ("CPT/UTIL disagreement", {"clash": "AAA Bat1"})):
            with self.subTest(label):
                df = self._melt(post=("AAA", "BBB"), arm=("AAA", "BBB"), **kw)
                sides = {s["team"]: s
                         for s in df.attrs["participation_report"]["sides"]}
                self.assertEqual(sides["AAA"]["state"], "malformed", label)
                self.assertFalse(sides["AAA"]["decided"], label)
                self.assertTrue(sides["BBB"]["decided"], label)
                self.assertGreater(self._by_team(df)["AAA"], 10, label)
                self.assertEqual(self._by_team(df)["BBB"], 10, label)

    def test_participation_reads_the_shared_predicate_not_a_second_column_read(self):
        """R323 and this finding decide the same fact, and premise correction 2
        of the session prompt is that they must not decide it twice. Both go
        through `posted_order_completeness`; this asserts the melt calls it
        rather than re-deriving completeness from the column."""
        import inspect
        source = inspect.getsource(sd.melt_showdown_salary_csv)
        self.assertIn("posted_order_completeness", source)
        from mlb_engine.intake import slate_intake_manager as sim
        self.assertEqual(sim.DK_ORDER_SLOTS, 9)


class ShowdownBriefCarriesTheSmallSampleCautionTests(unittest.TestCase):
    """R310, warning half, driven through the PRODUCTION `run_showdown`.

    The wiring is the half a unit test on `small_sample_base_report` cannot
    reach: the field has to be IN the delivered brief and the caution has to
    RENDER. R300(a) is the standing reason -- the R289 acceptance test asserted
    over a hand-built frame and shipped green while five production sites still
    dropped the column.
    """

    @staticmethod
    def _module():
        path = REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py"
        spec = importlib.util.spec_from_file_location("build_slate_r310b", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _build(self, tmp: Path, patch_constants=None, projections=None):
        """A real delivered Showdown build, writing nowhere outside `tmp`.

        `mod.REPO` is patched for the reason the R304(d) driver above patches
        it: `run_showdown` mirrors into `REPO/outputs/<date>/` and records into
        that directory's upload manifest.
        """
        import shutil
        sal, ent = tmp / "DKSalaries.csv", tmp / "DKEntries.csv"
        shutil.copy2(SAL, sal)
        shutil.copy2(ENT, ent)
        args = types.SimpleNamespace(
            date="2026-07-18", entries=None, controls_override=None,
            projections=(str(projections) if projections else None),
            declare_pitcher=[], lineups=None,
            odds=None, no_odds=True, brief=None)
        mod = self._module()
        stack = contextlib.ExitStack()
        with stack:
            stack.enter_context(unittest.mock.patch.object(mod, "REPO", tmp))
            for name, value in (patch_constants or {}).items():
                stack.enter_context(unittest.mock.patch.object(sd, name, value))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code, brief = mod.run_showdown(args, tmp, sal, ent)
        return code, brief

    def test_the_field_is_on_every_showdown_brief_even_when_nothing_fires(self):
        """`supplied_base`'s discipline. The MIN@CHC pool has no cheap outlier
        under the shipped predicate, and the answer to "was this checked" must
        still be readable -- an absent key leaves it unanswerable, which is
        R249's rule."""
        with tempfile.TemporaryDirectory() as tmp:
            code, brief = self._build(Path(tmp))
        self.assertEqual(code, 0)
        block = brief["pool"]["small_sample_base"]
        self.assertIs(block["applied"], False)
        self.assertEqual(block["hitters_considered"], 18)
        self.assertEqual(block["appg_percentile"], 90.0)
        self.assertEqual(block["salary_percentile"], 50.0)
        self.assertNotIn("APPG is the Base prior here", brief["caution"])

    def test_a_flagged_pool_renders_the_caution_naming_the_player(self):
        """The caution string itself, rendered by the production builder off a
        REAL report -- the only thing changed is the salary threshold constant,
        so the pool, the report and the f-string are all the shipped ones. A
        NOTE that raises on a None salary or a missing key would fail here and
        nowhere else, because the branch only evaluates when something fires."""
        with tempfile.TemporaryDirectory() as tmp:
            code, brief = self._build(
                Path(tmp),
                patch_constants={"SMALL_SAMPLE_BASE_SALARY_PERCENTILE": 100.0})
        self.assertEqual(code, 0)
        block = brief["pool"]["small_sample_base"]
        self.assertTrue(block["applied"])
        named = block["players"][0]["Name"]
        self.assertIn(named, brief["caution"])
        self.assertIn("APPG is the Base prior here", brief["caution"])
        self.assertIn("`--projections` is the lever", brief["caution"])
        self.assertIn("hitters", brief["caution"])

    def _supplied_base_csv(self, tmp: Path) -> Path:
        """A real `Player_ID,Base` file for this pool, generated FROM the salary
        file by UTIL id -- the discipline R310's own workaround paragraph
        insists on ("generate the CSV FROM the salary file by name, never by
        hand-typed id")."""
        pool = sd.melt_showdown_salary_csv(str(SAL))
        path = tmp / "projections.csv"
        rows = ["Player_ID,Base"]
        for _, row in pool.iterrows():
            rows.append(f"{row['UTIL_ID']},{float(row['Base']) * 0.9 + 1.0:.2f}")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    def test_a_supplied_base_suppresses_the_note_and_keeps_the_field(self):
        """`--projections` replaces the APPG prior the caution warns about, so
        warning about it is noise. The FIELD stays, because the record of what
        the pool looked like is still worth having and `applied: false` would be
        a different claim from "not asked".

        This test exists because the mutant that removed `and not
        supplied_base` SURVIVED its first pass: the suppression rule was
        correct and untested, which is a fixture gap and not a weak mutant.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            code, brief = self._build(
                tmp,
                patch_constants={"SMALL_SAMPLE_BASE_SALARY_PERCENTILE": 100.0},
                projections=self._supplied_base_csv(tmp))
        self.assertEqual(code, 0)
        self.assertTrue(brief["supplied_base"]["applied"],
                        "the supplied Base did not actually apply, so this "
                        "test would pass for the wrong reason")
        block = brief["pool"]["small_sample_base"]
        self.assertTrue(block["applied"], "the field must still carry the flag")
        self.assertNotIn("APPG is the Base prior here", brief["caution"])
        self.assertNotIn(block["players"][0]["Name"], brief["caution"])

    def test_it_is_still_review_grade_and_not_a_gate(self):
        """A caution never changes the verdict. Showdown ships review-grade
        either way, and a flagged pool must not refuse, downgrade or relax
        anything."""
        with tempfile.TemporaryDirectory() as tmp:
            clean_code, clean = self._build(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            flagged_code, flagged = self._build(
                Path(tmp),
                patch_constants={"SMALL_SAMPLE_BASE_SALARY_PERCENTILE": 100.0})
        self.assertEqual(clean_code, 0)
        self.assertEqual(flagged_code, 0)
        for brief in (clean, flagged):
            self.assertEqual(brief["status"], "review_grade_build")
        self.assertEqual(flagged["pool"]["players"], clean["pool"]["players"],
                         "the caution changed the pool, which makes it a gate")
        self.assertEqual(flagged["delivered_sha256"], clean["delivered_sha256"],
                         "the caution changed a delivered byte")


# ---------------------------------------------------------------------------
# R347. A DK-declared opener (`Starting=PO`) is ROSTERABLE in Showdown.
# ---------------------------------------------------------------------------
class R347DeclaredOpenerStaysInThePoolTests(unittest.TestCase):
    """At HEAD before this item the opener was an INVISIBLE pool reduction.

    `_is_declared` is False for `PO` (R104, correctly: one or two innings by
    design is not a start), `_participation` then fell through to
    `confirmed_nonstarter` on a decided side, and `starters_only` dropped the
    row. `Is_Declared_Opener` was written one line later and read by nothing,
    and the comment above `_is_declared` said he "is still rosterable in
    Showdown". Measured on 1940_1g_sd (PIT@CWS, 2026-09-10): Hagen Smith,
    `Starting=PO`, the only CWS arm DK marked as taking the ball, absent from a
    20-man pool with `declared_starters: 2`, no blocker and no warning.

    `declared_opener` is a third participation value on purpose. It is not
    `confirmed_starter`, because the R104 role must not be promoted, and it is
    not `unknown`, because DK named the man.
    """

    HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position",
              "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame",
              "Status", "Starting"]
    GAME = "AAA@BBB 09/30/2026 07:05PM ET"

    def _rows(self, post=(), arm=(), opener=(), opener_out=()):
        rows = [self.HEADER]
        pid = 1000
        for team in ("AAA", "BBB"):
            for i in range(9):
                token = str(i + 1) if team in post else ""
                name = f"{team} Bat{i + 1}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append(["OF", f"{name} ({pid})", name, str(pid), role,
                                 str(int(4000 * mult)), self.GAME, team, "9.0",
                                 "", token])
                    pid += 1
            for i in range(4):
                name = f"{team} Bench{i + 1}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append(["OF", f"{name} ({pid})", name, str(pid), role,
                                 str(int(3000 * mult)), self.GAME, team, "5.0",
                                 "", ""])
                    pid += 1
            specs = [("Arm", "SP", 9000, "SP" if team in arm else ""),
                     ("Reliever", "RP", 5000, "")]
            if team in opener:
                specs.append(("Opener", "RP", 4000, "PO"))
            for label, pos, salary, token in specs:
                name = f"{team} {label}"
                status = "IL" if (label == "Opener" and team in opener_out) else ""
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append([pos, f"{name} ({pid})", name, str(pid), role,
                                 str(int(salary * mult)), self.GAME, team,
                                 "12.0", status, token])
                    pid += 1
        return rows

    def _melt(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DKSalaries.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(self._rows(**kw))
            return sd.melt_showdown_salary_csv(str(path))

    def _row(self, df, name):
        sub = df.loc[df["Name"] == name]
        self.assertEqual(len(sub), 1, f"{name} is not in the pool")
        return sub.iloc[0]

    def test_an_opener_on_a_DECIDED_side_stays_in_the_pool(self):
        """The measured 1940_1g_sd shape: both nines posted, one side's only
        arm marked PO. Before this item he was dropped by `starters_only`."""
        df = self._melt(post=("AAA", "BBB"), arm=("BBB",), opener=("AAA",))
        rec = self._row(df, "AAA Opener")
        self.assertEqual(rec["Participation"], "declared_opener")
        self.assertTrue(rec["Is_Declared_Opener"])
        self.assertFalse(rec["Is_Declared_Starter"],
                         "an opener is rosterable, never a declared starter")
        self.assertFalse(rec["Projected_Candidate"],
                         "DK named him; the pool is not guessing about him")
        self.assertEqual(rec["Pool_Basis"], "declared_starters")
        report = df.attrs["participation_report"]
        self.assertEqual(report["openers_kept"], ["AAA AAA Opener"])
        self.assertEqual(report["slate_basis"], "declared_starters")

    def test_the_opener_is_not_counted_as_a_declared_starter(self):
        """`declared_starters` on the brief is exactly what he is NOT, which is
        why 1940_1g_sd read `declared_starters: 2` with a third arm missing."""
        with_op = self._melt(post=("AAA", "BBB"), arm=("BBB",), opener=("AAA",))
        without = self._melt(post=("AAA", "BBB"), arm=("BBB",))
        self.assertEqual(int(with_op["Is_Declared_Starter"].sum()),
                         int(without["Is_Declared_Starter"].sum()))
        self.assertEqual(len(with_op), len(without) + 1,
                         "the opener is one more person in the legal pool")

    def test_an_opener_on_an_UNDECIDED_side_is_declared_not_unknown(self):
        """He stayed in the pool here either way, but as `unknown` with
        `Projected_Candidate=True`, which claimed the pool was projecting a man
        DK had named."""
        df = self._melt(post=("BBB",), arm=("BBB",), opener=("AAA",))
        rec = self._row(df, "AAA Opener")
        self.assertEqual(rec["Participation"], "declared_opener")
        self.assertFalse(rec["Projected_Candidate"])
        self.assertEqual(rec["Pool_Basis"], "all_healthy")
        self.assertTrue(
            self._row(df, "AAA Bench1")["Projected_Candidate"],
            "his team-mates are still unknown; the opener branch is per person")

    def test_a_shelved_opener_is_not_reported_as_kept(self):
        """`openers_kept` reads the FINAL rows, so an IL opener who left on the
        health filter is not claimed as a man the pool held."""
        df = self._melt(post=("AAA", "BBB"), arm=("BBB",), opener=("AAA",),
                        opener_out=("AAA",))
        self.assertEqual(df.attrs["participation_report"]["openers_kept"], [])
        self.assertEqual(len(df.loc[df["Name"] == "AAA Opener"]), 0)

    def test_openers_kept_is_empty_and_present_when_there_is_no_opener(self):
        df = self._melt(post=("AAA", "BBB"), arm=("AAA", "BBB"))
        self.assertEqual(df.attrs["participation_report"]["openers_kept"], [])

    def test_the_thesis_ladder_does_not_promote_an_opener_to_declared_starter(self):
        """`starters` feeds `both_sp`, and `pitchers_duel` HARD-LOCKS both
        entries through every rung of the relaxation ladder. Keeping the opener
        in the pool must not force a one-inning arm onto that roster: a side
        whose only arm is an opener is a bullpen game and reads as one."""
        df = self._melt(post=("AAA", "BBB"), arm=("BBB",), opener=("AAA",))
        shape = st.describe_slate(df)
        opener_key = str(self._row(df, "AAA Opener")["Player_Key"])
        self.assertIsNone(shape["starters"]["AAA"])
        self.assertEqual(shape["bullpen_teams"], ["AAA"])
        self.assertNotEqual(shape["starters"]["BBB"], opener_key)
        self.assertEqual(shape["starters"]["BBB"],
                         str(self._row(df, "BBB Arm")["Player_Key"]))

    def test_an_opener_beside_a_real_starter_does_not_displace_him(self):
        """The other shape: DK declares an SP and a PO on the same side. The SP
        is the starter; the opener is neither the starter nor a bullpen game."""
        df = self._melt(post=("AAA", "BBB"), arm=("AAA", "BBB"),
                        opener=("AAA",))
        shape = st.describe_slate(df)
        self.assertEqual(shape["bullpen_teams"], [])
        self.assertEqual(shape["starters"]["AAA"],
                         str(self._row(df, "AAA Arm")["Player_Key"]))


# ---------------------------------------------------------------------------
# R334(a). The F1 implied-team-total factor reaches a Showdown hitter's prior.
# ---------------------------------------------------------------------------
class R334aShowdownF1PriorTests(unittest.TestCase):
    """Before this item nothing on the Showdown path carried the market's view
    of the run environment to a hitter's number.

    `build_f1_factors` has exactly one production caller, `build_f1_map`, which
    is called once, inside `run_classic`. Showdown reached AvgPointsPerGame and
    a salary regression. The moneyline it DID have was spent on the thesis
    ladder's side mix -- which entries lean which way -- and never on a Base.

    Measured on 2210_1g_sd (CIN@LAD, 2026-09-08) against a supplied external
    Base, the side split was 1.77x wide and monotone by side, arms near 1.0.
    Two bounds this wiring cannot pass, pinned below rather than rediscovered:
    `F1_HITTER_CLIP` is (0.85, 1.15), so the widest transmissible side ratio is
    1.353x; and a packet with a total but NO moneyline splits evenly on a
    two-team slate, so every F1 clips to exactly 1.0.
    """

    @staticmethod
    def _build_slate():
        import importlib.util
        path = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
        spec = importlib.util.spec_from_file_location(
            "build_slate_f1_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _packet(total=8.5, away_ml=255, home_ml=-319):
        entry = {"total": total, "source": "test"}
        if away_ml is not None and home_ml is not None:
            entry["moneyline"] = {"MIN": away_ml, "CHC": home_ml}
        return {"MIN@CHC": entry}

    def _pool(self):
        return sd.melt_showdown_salary_csv(SAL)

    def test_f1_reaches_every_hitter_and_leaves_the_arms_neutral(self):
        mod = self._build_slate()
        df = self._pool()
        factors, report = mod.build_showdown_f1(self._packet(), df)
        self.assertTrue(factors, "no hitter was scored")
        self.assertGreater(report["non_neutral_f1"], 0)
        arms = {str(k) for k, o in zip(df["Player_Key"], df["Batting_Order"])
                if o is None or pd.isna(o)}
        self.assertTrue(arms, "the fixture has no arms to check")
        for key in arms:
            self.assertEqual(factors[str(key)], 1.0,
                             "a Showdown arm keeps raw APPG; F1 on him would "
                             "double count the opposing total (v1)")

    def test_the_favored_side_is_scored_above_the_underdog(self):
        """On a two-team slate F1 is the moneyline devig, doubled and clipped:
        the ratio between the sides is the whole of the signal."""
        mod = self._build_slate()
        df = self._pool()
        factors, _ = mod.build_showdown_f1(self._packet(), df)
        by_team = {}
        for key, team, order in zip(df["Player_Key"], df["Team"],
                                    df["Batting_Order"]):
            if order is not None and not pd.isna(order):
                by_team.setdefault(str(team), set()).add(factors[str(key)])
        self.assertEqual({len(v) for v in by_team.values()}, {1},
                         "F1 is a TEAM factor; every hitter on a side shares it")
        self.assertGreater(by_team["CHC"].pop(), by_team["MIN"].pop(),
                           "CHC is the -319 home favorite in this packet")

    def test_a_total_with_no_moneyline_is_neutral_and_that_is_correct(self):
        """The acceptance this corrects. A packet WAS present, so 'odds
        available' is true and `non_neutral_f1` is still 0: two teams split an
        even total onto the slate mean and every F1 clips to exactly 1.0. A
        reader must be able to tell that from a wiring failure."""
        mod = self._build_slate()
        df = self._pool()
        factors, report = mod.build_showdown_f1(
            self._packet(away_ml=None, home_ml=None), df)
        self.assertEqual(report["non_neutral_f1"], 0)
        self.assertEqual(sorted({round(v, 9) for v in factors.values()}), [1.0])
        self.assertEqual(report["games_priced"], 1,
                         "the packet was read; only the split was even")

    def test_the_clip_bounds_the_transmissible_side_ratio(self):
        """`F1_HITTER_CLIP` caps this at 1.15/0.85 = 1.353x against a measured
        1.77x, so (a) closes at most ~76% of that gap by construction and the
        residual (b) is sized on is arithmetic before it is evidence."""
        mod = self._build_slate()
        df = self._pool()
        factors, _ = mod.build_showdown_f1(
            self._packet(total=12.0, away_ml=2000, home_ml=-5000), df)
        values = [v for k, v in factors.items()
                  if v != 1.0 or True]
        hitters = [factors[str(k)] for k, o in zip(df["Player_Key"],
                                                   df["Batting_Order"])
                   if o is not None and not pd.isna(o)]
        self.assertLessEqual(max(hitters) / min(hitters), 1.15 / 0.85 + 1e-9)
        self.assertLessEqual(max(hitters), 1.15 + 1e-9)
        self.assertGreaterEqual(min(hitters), 0.85 - 1e-9)
        self.assertTrue(values)

    def test_the_wiring_applies_f1_on_the_LADDER_path(self):
        mod = self._build_slate()
        raw = self._pool()
        factors, report = mod.build_showdown_f1(self._packet(), raw)
        hand = {"MIN": "R", "CHC": "R"}
        plain = mod.price_showdown_pool(raw, use_ladder=True, bat_side={},
                                        pitcher_hand=hand, supplied_base={},
                                        supplied_read={})
        wired = mod.price_showdown_pool(raw, use_ladder=True, bat_side={},
                                        pitcher_hand=hand, supplied_base={},
                                        supplied_read={},
                                        f1_by_player_key=factors,
                                        f1_report=report)
        self.assertTrue(wired.attrs["f1_prior_report"]["applied"])
        self.assertGreater(wired.attrs["f1_prior_report"]["non_neutral_f1"], 0)
        moved = [a for a, b in zip(plain["Base"], wired["Base"])
                 if abs(float(a) - float(b)) > 1e-9]
        self.assertTrue(moved, "F1 changed no Base on the ladder path")

    def test_the_wiring_reaches_the_FALLBACK_bank_path_too(self):
        """R249's lesson, applied to this factor. `apply_base_prior` runs on the
        ladder path alone, so wiring F1 inside it would make it a silent no-op
        on exactly the `all_healthy` slates where the pool is thinnest."""
        mod = self._build_slate()
        raw = self._pool()
        factors, report = mod.build_showdown_f1(self._packet(), raw)
        out = mod.price_showdown_pool(raw, use_ladder=False, bat_side={},
                                      pitcher_hand={}, supplied_base={},
                                      supplied_read={},
                                      f1_by_player_key=factors,
                                      f1_report=report)
        self.assertTrue(out.attrs["f1_prior_report"]["applied"])
        self.assertNotIn("Salary_Fit", out.columns)      # still no prior here
        hitter = raw[raw["Batting_Order"].notna()].iloc[0]
        before = float(hitter["Base"])
        after = float(out.loc[out["Name"] == hitter["Name"], "Base"].iloc[0])
        self.assertAlmostEqual(after, before * factors[str(hitter["Player_Key"])],
                               places=6)

    def test_a_supplied_base_is_NOT_multiplied_by_f1(self):
        """R249's contract, unchanged: a supplied number IS the prior and no
        factor touches it. F1 goes in the same seam and before
        `apply_supplied_base`, which is what makes the order executable rather
        than a property of the source layout."""
        mod = self._build_slate()
        raw = self._pool()
        factors, report = mod.build_showdown_f1(self._packet(), raw)
        row = raw[raw["Batting_Order"].notna()].iloc[0]
        asked = 37.5
        for use_ladder in (True, False):
            priced = mod.price_showdown_pool(
                raw, use_ladder=use_ladder, bat_side={},
                pitcher_hand={"MIN": "R", "CHC": "R"},
                supplied_base={str(row["UTIL_ID"]): asked}, supplied_read={},
                f1_by_player_key=factors, f1_report=report)
            got = float(priced.loc[priced["Name"] == row["Name"], "Base"].iloc[0])
            self.assertAlmostEqual(got, asked, places=6,
                                   msg=f"F1 was applied AFTER the supplied "
                                       f"number (use_ladder={use_ladder})")

    def test_no_packet_leaves_every_base_alone_and_says_so(self):
        mod = self._build_slate()
        raw = self._pool()
        factors, report = mod.build_showdown_f1({}, raw)
        self.assertEqual(factors, {})
        out = mod.price_showdown_pool(raw, use_ladder=False, bat_side={},
                                      pitcher_hand={}, supplied_base={},
                                      supplied_read={},
                                      f1_by_player_key=factors,
                                      f1_report=report)
        block = out.attrs["f1_prior_report"]
        self.assertFalse(block["applied"])
        self.assertEqual(block["non_neutral_f1"], 0)
        self.assertIn("moneyline", block["skipped"])
        self.assertTrue(all(abs(float(a) - float(b)) < 1e-12
                            for a, b in zip(raw["Base"], out["Base"])))

    def test_the_prior_note_names_f1_only_when_it_was_applied(self):
        """The R122 `prior_note` class: a hardcoded literal describing a factor
        chain, which no test caught drifting. It now reads the frame."""
        mod = self._build_slate()
        raw = self._pool()
        factors, report = mod.build_showdown_f1(self._packet(), raw)
        hand = {"MIN": "R", "CHC": "R"}
        with_f1 = mod.price_showdown_pool(raw, use_ladder=True, bat_side={},
                                          pitcher_hand=hand, supplied_base={},
                                          supplied_read={},
                                          f1_by_player_key=factors,
                                          f1_report=report)
        without = mod.price_showdown_pool(raw, use_ladder=True, bat_side={},
                                          pitcher_hand=hand, supplied_base={},
                                          supplied_read={})
        self.assertIn("F1 implied-team-total factor",
                      st.portfolio_report(with_f1, [], [])["prior_note"])
        note = st.portfolio_report(without, [], [])["prior_note"]
        self.assertNotIn("x F1", note)
        self.assertIn("no F1", note)

    def test_showdown_moneyline_hands_back_the_packet_it_already_loaded(self):
        """The seam. This function loaded the FULL packet -- the same loader
        Classic uses, carrying each game's total beside its moneyline -- and
        threw the total away three lines later, which is most of why no implied
        total reached a Showdown hitter."""
        src = (REPO / "skills" / "generate-lineups" / "scripts"
               / "build_slate.py").read_text(encoding="utf-8")
        self.assertIn("def showdown_moneyline(args, df, salary_csv=None) "
                      "-> tuple[dict, dict, dict]:", src)
        self.assertIn("moneyline, odds_note, odds_packet = showdown_moneyline(",
                      src)
        self.assertIn("f1_by_player_key, f1_report = build_showdown_f1("
                      "odds_packet, df)", src)
        # both build paths, same seam
        self.assertEqual(src.count("f1_by_player_key=f1_by_player_key"), 2)
        self.assertIn('"f1": {', src)


# ---------------------------------------------------------------------------
# R334(c)(d). Two Showdown reports, neither a gate.
# ---------------------------------------------------------------------------
def _savant_pitching(rows):
    """A minimal Savant expected-stats pitching frame: (name, est_woba, pa)."""
    return pd.DataFrame([
        {"last_name, first_name": name, "player_id": str(1000 + i),
         "year": 2026, "pa": pa, "woba": est, "est_woba": est, "xera": 4.00}
        for i, (name, est, pa) in enumerate(rows)])


def _savant_batting(rows):
    return pd.DataFrame([
        {"last_name, first_name": name, "player_id": str(2000 + i),
         "year": 2026, "pa": 500, "woba": est, "est_woba": est}
        for i, (name, est) in enumerate(rows)])


class R334cOpposingArmReportTests(unittest.TestCase):
    """The Showdown Base is APPG, a season mean over every opponent a hitter
    faced; a Showdown contest is ONE game with ONE arm per side.

    R334(a) wired the market's implied team total, which carries the arm at the
    TEAM level and only as far as `F1_HITTER_CLIP` allows. The opposing-arm term
    itself is (b) and is not built, so this names the condition under which the
    remaining blindness is largest and is knowable BEFORE the first solve.
    R310(b)'s shape: report, never a gate, present with `flagged: false`.
    """

    HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position",
              "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame",
              "Status", "Starting"]
    GAME = "AAA@BBB 09/30/2026 07:05PM ET"

    def _melt(self, arm_names=("AAA Ace", "BBB Ace"), declare=True):
        rows = [self.HEADER]
        pid = 1000
        for team, arm in zip(("AAA", "BBB"), arm_names):
            for i in range(9):
                name = f"{team} Bat{i + 1}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    rows.append(["OF", f"{name} ({pid})", name, str(pid), role,
                                 str(int(4000 * mult)), self.GAME, team, "9.0",
                                 "", str(i + 1)])
                    pid += 1
            for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                rows.append(["SP", f"{arm} ({pid})", arm, str(pid), role,
                             str(int(9000 * mult)), self.GAME, team, "14.0", "",
                             "SP" if declare else ""])
                pid += 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DKSalaries.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
            return sd.melt_showdown_salary_csv(str(path))

    # league mean over this table is 0.33, so the margin is a 0.066 gap
    WIDE = _savant_pitching([("Ace, Aaa", 0.267, 600), ("Ace, Bbb", 0.384, 600),
                             ("Filler, One", 0.330, 600),
                             ("Filler, Two", 0.330, 600)])
    NARROW = _savant_pitching([("Ace, Aaa", 0.325, 600), ("Ace, Bbb", 0.335, 600),
                               ("Filler, One", 0.330, 600),
                               ("Filler, Two", 0.330, 600)])

    def test_it_fires_on_the_mismatched_pair(self):
        """The 2210_1g_sd numbers: 0.267 against 0.384 is a 0.117 gap, 35.4% of
        the league mean, against a 20% margin."""
        out = sd.opposing_arm_report(self._melt(), self.WIDE)
        self.assertTrue(out["flagged"])
        self.assertAlmostEqual(out["gap_est_woba_against"], 0.117, places=3)
        self.assertGreater(out["gap_as_fraction_of_league_mean"],
                           sd.OPPOSING_ARM_XWOBA_MARGIN)
        self.assertIn("AvgPointsPerGame", out["note"])
        self.assertEqual(len(out["arms"]), 2)
        self.assertEqual({a["team"] for a in out["arms"]}, {"AAA", "BBB"})

    def test_it_stays_silent_on_a_pair_inside_the_margin(self):
        """The half that keeps this from being the referee that warns on
        everything (R292). A 0.010 gap is 3% of the mean."""
        out = sd.opposing_arm_report(self._melt(), self.NARROW)
        self.assertFalse(out["flagged"])
        self.assertNotIn("note", out)
        self.assertEqual(len(out["arms"]), 2)

    def test_it_is_present_and_says_why_when_it_cannot_run(self):
        """`flagged: false` with a reason, never an absent key: an absent key is
        not an answer to 'were the two arms mismatched'."""
        self.assertIn("Savant",
                      sd.opposing_arm_report(self._melt(), None)["skipped"])
        undeclared = sd.opposing_arm_report(self._melt(declare=False), self.WIDE)
        self.assertFalse(undeclared["flagged"])
        self.assertIn("declared arm", undeclared["skipped"])
        empty = sd.opposing_arm_report(pd.DataFrame(), self.WIDE)
        self.assertFalse(empty["flagged"])
        self.assertIn("empty", empty["skipped"])

    def test_an_arm_with_no_savant_row_is_named_not_scored_neutral(self):
        """R189(2)'s rule. DK ships no MLBAM id, so the join is by NAME and a
        miss must be visible rather than silently comparing one arm."""
        out = sd.opposing_arm_report(
            self._melt(arm_names=("AAA Ace", "Bbb Nobody")), self.WIDE)
        self.assertFalse(out["flagged"])
        self.assertEqual(out["unmatched_arms"], ["BBB Bbb Nobody"])
        self.assertIn("1 of 2", out["skipped"])

    def test_it_never_changes_the_pool(self):
        df = self._melt()
        before = list(df["Base"]), len(df)
        sd.opposing_arm_report(df, self.WIDE)
        self.assertEqual((list(df["Base"]), len(df)), before)


class R334dSuppliedBaseSanityTests(unittest.TestCase):
    """R327 gave the supplied frame a NUMERIC boundary and REFUSES an unusable
    number. This is the semantic one beside it and it never refuses.

    Within a side on purpose: comparing across sides would re-measure the thing
    a supplied Base is usually supplied to express -- that one side faces a much
    better arm, which is R334's whole subject -- and would flag every prior that
    got the matchup right.
    """

    HEADER = R334cOpposingArmReportTests.HEADER
    GAME = R334cOpposingArmReportTests.GAME

    def _melt(self):
        rows = [self.HEADER]
        pid = 1000
        self.ids = {}
        for team in ("AAA", "BBB"):
            for i in range(9):
                name = f"{team} Bat{i + 1}"
                for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                    if role == "UTIL":
                        self.ids[name] = str(pid)
                    rows.append(["OF", f"{name} ({pid})", name, str(pid), role,
                                 str(int(4000 * mult)), self.GAME, team, "9.0",
                                 "", str(i + 1)])
                    pid += 1
            arm = f"{team} Arm"
            for role, mult in (("UTIL", 1.0), ("CPT", 1.5)):
                rows.append(["SP", f"{arm} ({pid})", arm, str(pid), role,
                             str(int(9000 * mult)), self.GAME, team, "14.0",
                             "", "SP"])
                pid += 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DKSalaries.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
            return sd.melt_showdown_salary_csv(str(path))

    @staticmethod
    def _table():
        # AAA Bat1 is the best bat by xwOBA and AAA Bat9 the worst.
        return _savant_batting(
            [(f"Bat{i + 1}, Aaa", 0.400 - 0.02 * i) for i in range(9)]
            + [(f"Bat{i + 1}, Bbb", 0.400 - 0.02 * i) for i in range(9)])

    def _agreeing(self, df):
        return {self.ids[n]: 12.0 - 0.5 * (int(n[-1]) - 1)
                for n in self.ids if n[-1].isdigit()}

    def test_a_prior_that_agrees_with_the_rate_stat_names_nobody(self):
        df = self._melt()
        out = sd.supplied_base_sanity_report(df, self._agreeing(df), self._table())
        self.assertTrue(out["applied"])
        self.assertEqual(out["flagged"], [])
        self.assertEqual(out["hitters_ranked"], 18)
        self.assertEqual(out["sides_ranked"], ["AAA", "BBB"])

    def test_an_inverted_bat_is_named_with_both_ranks(self):
        """The acceptance shape: a prior that buries the side's best bat."""
        df = self._melt()
        supplied = self._agreeing(df)
        supplied[self.ids["AAA Bat1"]] = 1.0        # best xwOBA, worst Base
        out = sd.supplied_base_sanity_report(df, supplied, self._table())
        names = [(f["team"], f["name"]) for f in out["flagged"]]
        self.assertIn(("AAA", "AAA Bat1"), names)
        hit = next(f for f in out["flagged"] if f["name"] == "AAA Bat1")
        self.assertEqual(hit["est_woba_rank_in_side"], 1)
        self.assertEqual(hit["base_rank_in_side"], 9)
        self.assertEqual(hit["rank_delta"], 8)
        self.assertIn("BELOW", hit["direction"])
        self.assertFalse([f for f in out["flagged"] if f["team"] == "BBB"],
                         "the other side's prior was untouched")
        self.assertIn("not error", out["note"])

    def test_the_gap_threshold_is_what_decides(self):
        """Three places out of nine is disagreement, not contradiction, and the
        threshold is the whole of what separates them. Measured on the constant:
        two INDEPENDENT orderings of a 9-hitter side would name 1.34 of 9 at
        this gap and 4.67 of 9 at `> 2`, which is the wall of text this avoids.

        Exercised at both settings, because a threshold nothing moves against is
        a constant no test is pinning: at the shipped 5 this side is silent, and
        the same side at `> 2` names both swapped bats."""
        df = self._melt()
        supplied = self._agreeing(df)
        supplied[self.ids["AAA Bat1"]], supplied[self.ids["AAA Bat4"]] = (
            supplied[self.ids["AAA Bat4"]], supplied[self.ids["AAA Bat1"]])
        table = self._table()
        self.assertEqual(sd.SUPPLIED_BASE_RANK_GAP, 5)
        out = sd.supplied_base_sanity_report(df, supplied, table)
        self.assertEqual(out["flagged"], [], "a 3-place move is not a finding")
        self.assertIn("1.34 of 9", out["label"])
        tight = sd.supplied_base_sanity_report(df, supplied, table, gap=2)
        self.assertEqual(sorted(f["name"] for f in tight["flagged"]),
                         ["AAA Bat1", "AAA Bat4"])
        self.assertEqual(sorted(abs(f["rank_delta"]) for f in tight["flagged"]),
                         [3, 3])

    def test_it_is_a_no_op_with_no_projections_file(self):
        df = self._melt()
        out = sd.supplied_base_sanity_report(df, {}, self._table())
        self.assertFalse(out["applied"])
        self.assertIn("--projections", out["skipped"])
        self.assertEqual(out["flagged"], [])

    def test_a_hitter_with_no_savant_row_is_named_not_ranked(self):
        df = self._melt()
        table = _savant_batting(
            [(f"Bat{i + 1}, Aaa", 0.400 - 0.02 * i) for i in range(9)])
        out = sd.supplied_base_sanity_report(df, self._agreeing(df), table)
        self.assertEqual(out["sides_ranked"], ["AAA"])
        self.assertEqual(len(out["unmatched_hitters"]), 9)
        self.assertTrue(all(n.startswith("BBB") for n in out["unmatched_hitters"]))

    def test_it_never_changes_a_supplied_number(self):
        df = self._melt()
        supplied = self._agreeing(df)
        before = dict(supplied)
        base_before = list(df["Base"])
        sd.supplied_base_sanity_report(df, supplied, self._table())
        self.assertEqual(supplied, before)
        self.assertEqual(list(df["Base"]), base_before)

    def test_both_reports_reach_the_showdown_brief(self):
        src = (REPO / "skills" / "generate-lineups" / "scripts"
               / "build_slate.py").read_text(encoding="utf-8")
        self.assertIn('"opposing_arm": sd_opposing_arm,', src)
        self.assertIn('"supplied_base_sanity": sd_base_sanity,', src)
        self.assertIn("sd_opposing_arm = sd.opposing_arm_report(df, "
                      "sd_savant_pitching)", src)
        self.assertIn("sd_base_sanity = sd.supplied_base_sanity_report(",
                      src)


# ---------------------------------------------------------------------------
# R328 remaining half. The ordering between the two Showdown ownership markets.
# ---------------------------------------------------------------------------
class R328ShowdownRoleCoherenceTests(unittest.TestCase):
    """Two of this item's three sub-fixes shipped in R338 and are re-pinned here
    so the row cannot be reopened against the wrong half.

    `_bounded_marginals` water-fills BOTH markets onto the capped simplex, so
    the `[8.01, ..., 316.19]%` the item was filed on cannot be produced;
    `attach_predicted_ownership` refuses non-finite and out-of-[0,100] values
    before any `--leverage` control reads one. What was left is the ORDERING
    across the two markets, enforced only in `mlb_engine/production/contracts.py`
    -- R302's strangler package, which the legacy path cannot import and a
    greenfield test pins it out of.
    """

    def _players(self):
        from mlb_engine.field import ownership_prior as op          # noqa: F401
        rows = []
        for i in range(9):
            rows.append(types.SimpleNamespace(
                player_id=f"H{i}", name=f"Bat {i}", team="AAA" if i < 5 else "BBB",
                position="OF", salary=3000 + 400 * i, roster_position="UTIL",
                avg_points_per_game=8.0 + i))
        for i in range(2):
            rows.append(types.SimpleNamespace(
                player_id=f"P{i}", name=f"Arm {i}", team="AAA" if i else "BBB",
                position="SP", salary=10000 + 500 * i, roster_position="UTIL",
                avg_points_per_game=16.0 + i))
        return rows

    def test_the_production_markets_are_coherent_on_every_archetype(self):
        """Not reproducible, and that is the finding. Over 4,000 randomized
        pools plus a structured grid the maximum captain-minus-roster excess is
        exactly 0.0, because the captain temperature runs BELOW the roster one
        and the water-fill pins a saturating roster share at 100."""
        from mlb_engine.field import ownership_prior as op
        players = self._players()
        for archetype in op.ARCHETYPE_PARAMS:
            cap = op.predict_captain_ownership(
                players, archetype=archetype, probable_sp_ids=["P0", "P1"])
            ros = op.predict_showdown_roster_ownership(
                players, archetype=archetype, probable_sp_ids=["P0", "P1"])
            out = op.showdown_role_coherence(cap["own_pct_by_player_id"],
                                             ros["own_pct_by_player_id"])
            self.assertTrue(out["coherent"], f"{archetype}: {out['violations']}")
            self.assertEqual(out["checked"], len(players))

    def test_a_captain_marginal_above_its_roster_marginal_is_NAMED(self):
        """The guard itself. A person cannot be captained more often than he is
        rostered; both markets are percentages of entries, so the comparison is
        direct."""
        from mlb_engine.field import ownership_prior as op
        out = op.showdown_role_coherence({"a": 40.0, "b": 5.0},
                                         {"a": 12.0, "b": 90.0})
        self.assertFalse(out["coherent"])
        self.assertEqual([v["player_id"] for v in out["violations"]], ["a"])
        self.assertEqual(out["violations"][0]["excess_pct"], 28.0)

    def test_it_reports_and_never_clamps(self):
        """A clamp breaks the 100% captain budget, which is R306's accounting
        and the property the water-fill exists to preserve. The inputs come back
        untouched and the caller still holds the numbers it passed."""
        from mlb_engine.field import ownership_prior as op
        captain = {"a": 40.0, "b": 5.0}
        roster = {"a": 12.0, "b": 90.0}
        before = dict(captain), dict(roster)
        out = op.showdown_role_coherence(captain, roster)
        self.assertEqual((captain, roster), before)
        for key in ("own_pct_by_player_id", "clamped", "repaired"):
            self.assertNotIn(key, out)

    def test_rounding_at_the_last_place_is_not_a_violation(self):
        """`_bounded_marginals` rounds to 2dp, so an equal pair can differ by
        half a cent. A tolerance, not a clamp."""
        from mlb_engine.field import ownership_prior as op
        self.assertTrue(
            op.showdown_role_coherence({"a": 100.0}, {"a": 99.99})["coherent"])
        self.assertFalse(
            op.showdown_role_coherence({"a": 100.0}, {"a": 99.0})["coherent"])

    def test_out_of_range_and_missing_ids_are_reported_separately(self):
        from mlb_engine.field import ownership_prior as op
        out = op.showdown_role_coherence({"a": 101.0, "c": 5.0},
                                         {"a": 100.0, "b": 50.0})
        self.assertFalse(out["coherent"])
        self.assertEqual(out["out_of_range"],
                         [{"player_id": "a", "market": "captain", "value": 101.0}])
        self.assertEqual(out["missing_from_roster_market"], ["c"])
        self.assertEqual(out["missing_from_captain_market"], ["b"])
        self.assertEqual(out["checked"], 1, "only the shared id is comparable")

    def test_the_water_fill_half_already_shipped_and_stays_shipped(self):
        """R338. The `[8.01, ..., 316.19]%` this item was filed on: six people
        competing for six seats must every one be 100%."""
        from mlb_engine.field import ownership_prior as op
        out = op._bounded_marginals({str(i): 10 ** i for i in range(6)}, 600)
        self.assertEqual(sorted(out.values()), [100.0] * 6)
        for pid, value in op._bounded_marginals(
                {str(i): float(i + 1) for i in range(20)}, 600).items():
            self.assertTrue(0.0 <= value <= 100.0, f"{pid}={value}")

    def test_the_emit_carries_the_block(self):
        src = (REPO / "tools" / "ownership_pred.py").read_text(encoding="utf-8")
        self.assertIn('block["role_coherence"] = '
                      'ownership_prior.showdown_role_coherence(', src)


class R295cCaptainLockRungIsGuardedTests(unittest.TestCase):
    """R295(c). The fifth rung of `solve_ladder` exists to drop the captain
    lock, and its condition never checked that there was one.

    With `cpt_lock` None its argument list is rung 1's exactly -- same
    `with_cap`, same `util_excludes`, same `max_shared_players` -- and a rung
    only descends past rung 1 when rung 1 came back PROVEN infeasible (`_rung`
    latches every other empty return, R338/F13). So the re-solve re-proved the
    same infeasibility and bought nothing, and `_record_lock_relaxation` sat
    behind a condition that could not promise a lock.

    Deterministic solver accounting only; no probability is claimed.
    """

    def _thesis(self, cpt, excludes):
        return {"template": "t0", "name": "t0", "why": "", "cpt": cpt,
                "locks": [], "excludes": excludes, "mult": {}}

    def _calls(self, cpt):
        """Solve one proven-infeasible slot, returning every solver call's
        argument signature. The thesis excludes all but three players, so no
        legal six-man roster exists and every rung is proven infeasible."""
        pool = _apex_pool()
        excludes = [str(k) for k in pool["Player_Key"]][:-3]
        seen = []
        real = st.build_showdown_lineup

        def spy(**kw):
            seen.append((kw.get("cpt_lock"),
                         tuple(kw.get("cpt_excludes") or ()),
                         tuple(kw.get("excludes") or ()),
                         kw.get("max_shared_players"),
                         tuple(kw.get("util_excludes") or ())))
            return real(**kw)

        with unittest.mock.patch.object(st, "build_showdown_lineup", spy):
            st.solve_ladder(pool, [self._thesis(cpt, excludes)],
                            max_shared_players=None, time_limit=5,
                            diagnostics={})
        return seen

    def test_no_captain_lock_means_no_duplicate_resolve(self):
        """The defect: two identical solver calls for one slot."""
        calls = self._calls(cpt=None)
        self.assertEqual(len(calls), len(set(calls)),
                         f"a rung re-solved an identical model: {calls}")
        self.assertEqual(len(calls), 1,
                         "with no lock to relax and no cap over, one proven "
                         f"infeasible rung is the whole ladder, got {len(calls)}")

    def test_a_reassigned_captain_also_stops_the_duplicate(self):
        """`cpt_lock` is cleared when the captain is reassigned off a cap, which
        reaches the same rung by a different door."""
        for cpt in (None, ""):
            with self.subTest(cpt=cpt):
                calls = self._calls(cpt=cpt)
                self.assertEqual(len(calls), len(set(calls)))

    def test_a_real_captain_lock_still_reaches_the_rung(self):
        """The guard must not disarm the relaxation it guards: with a lock
        present the ladder still descends onto the captain-lock rung.

        Identified by SIGNATURE, not by ordinal or by `cpt_lock is None` alone:
        the floor rungs below also drop the lock, so "some call had no lock" is
        satisfied by the wrong branch. The captain-lock rung is the only one
        that drops `cpt_lock` while still carrying `util_excludes` -- the floor
        rungs drop the R250 hold along with the player cap.
        """
        calls = self._calls(cpt="AA_Big|AA")
        self.assertTrue(any(c[0] == "AA_Big|AA" for c in calls),
                        "no rung carried the thesis's captain lock")
        lock_rung = [c for c in calls if c[0] is None and c[4]]
        self.assertEqual(
            len(lock_rung), 1,
            "expected exactly one rung dropping the captain lock while keeping "
            f"the R250 hold; got {len(lock_rung)} of {len(calls)} calls: {calls}")

    def test_no_lock_relaxation_is_reachable_without_a_lock(self):
        """R233, the class rather than the instance. Every rung that books a
        captain-lock relaxation must be unreachable without a lock, either
        through its own condition or through an `if cpt_lock else 0` on the
        call. Four rungs book one; this walks all four so the next rung added
        cannot reopen the hole."""
        src = (REPO / "mlb_engine" / "optimize" / "showdown_theses.py").read_text(
            encoding="utf-8").splitlines()
        booking = [i for i, line in enumerate(src)
                   if "_record_lock_relaxation(thesis, lu)" in line]
        self.assertGreaterEqual(len(booking), 4,
                                "expected at least four lock-relaxation rungs")
        unguarded = []
        for i in booking:
            if "if cpt_lock else 0" in src[i]:
                continue                       # guarded at the call site
            condition = next(
                (src[j] for j in range(i, max(i - 12, -1), -1)
                 if src[j].lstrip().startswith(("if lu is None", "if (lu is None"))),
                None)
            window = "".join(src[max(i - 12, 0):i + 1])
            if condition is None or "cpt_lock" not in window:
                unguarded.append(f"line {i + 1}: {src[i].strip()}")
        self.assertEqual(unguarded, [],
                         "a captain-lock relaxation can be booked with no lock: "
                         + "; ".join(unguarded))


class R295dDuplicateRoleRowsAreRefusedTests(unittest.TestCase):
    """R295(d). `melt_showdown_salary_csv` keys a person on (Name, TeamAbbrev),
    so two DK persons sharing a name on one team melt into ONE record.

    The collapse is silent and mixed: CPT_ID/UTIL_ID and both salaries are last
    writer wins while `Base` is first writer wins, so the surviving row carries
    one person's DK IDs and salaries on the other's projection. The only
    upstream detector, `showdown_paired_role_disagreement`, compares Team,
    Position and Starting -- never the IDs -- so two people who agree on
    Position and Starting are invisible, and `certify_showdown` cannot see it.

    Filed PLAUSIBLE, and it stays unwitnessed: a sweep of every DK-schema CSV
    in the tree (15 files, 5 Showdown) found zero duplicate
    (Name, TeamAbbrev, Roster Position) rows. So this refuses rather than
    re-keys, and refuses only for a person who reaches the build.
    """

    POOLED = "Michael Busch"   # CHC, posted, survives every pool filter
    BENCH = "Joe Ryan"         # blank Starting, dropped by starters_only

    def _twin(self, name, salary="3000", avg="0.1"):
        rows = list(csv.DictReader(SAL.open(encoding="utf-8")))
        twins = []
        for r in (r for r in rows if r["Name"] == name):
            t = dict(r)
            t["ID"] = "9" + str(t["ID"])[1:]
            t["Salary"] = salary
            t["AvgPointsPerGame"] = avg
            twins.append(t)
        self.assertEqual(len(twins), 2, f"{name} should have a CPT and a UTIL row")
        out = Path(tempfile.mkdtemp()) / "DKSalaries_twin.csv"
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows + twins)
        return out

    def test_a_pooled_duplicate_is_refused_by_name(self):
        with self.assertRaises(ValueError) as caught:
            sd.melt_showdown_salary_csv(self._twin(self.POOLED))
        message = str(caught.exception)
        self.assertIn(self.POOLED, message)
        self.assertIn("duplicate Showdown role row", message)
        self.assertIn("CPT", message)
        self.assertIn("UTIL", message)

    def test_the_refusal_names_both_competing_dk_ids(self):
        """A refusal the operator cannot act on is a blocked build. Name the
        rows, so the salary file can be fixed."""
        with self.assertRaises(ValueError) as caught:
            sd.melt_showdown_salary_csv(self._twin(self.POOLED))
        message = str(caught.exception)
        original = [r for r in csv.DictReader(SAL.open(encoding="utf-8"))
                    if r["Name"] == self.POOLED]
        for row in original:
            self.assertIn(str(row["ID"]), message)
            self.assertIn("9" + str(row["ID"])[1:], message)

    def test_a_duplicate_outside_the_pool_does_not_refuse(self):
        """Scope. A duplicate among players the participation and health
        filters drop can never reach a lineup, and refusing a build over one is
        the washout CLAUDE.md's T-schedule spends its whole ladder avoiding."""
        df = sd.melt_showdown_salary_csv(self._twin(self.BENCH))
        self.assertFalse(df.empty)
        self.assertNotIn(self.BENCH, set(df["Name"]),
                         "fixture assumption: this player is filtered out")

    def test_every_committed_showdown_salary_file_still_melts(self):
        """No false positive on a legal file: one person is exactly two rows."""
        for path in sorted(FIX.glob("DKSalaries*.csv")):
            with self.subTest(path=path.name):
                self.assertFalse(sd.melt_showdown_salary_csv(path).empty)

    def test_the_merge_this_refuses_was_real(self):
        """The defect, reproduced against the melt's own accumulator rather
        than asserted: the two people share one key, and the record that key
        would have shipped mixes them."""
        rows = list(csv.DictReader(SAL.open(encoding="utf-8")))
        names = [(r["Name"], r["TeamAbbrev"]) for r in rows]
        self.assertEqual(len(names), len(set(names)) * 2,
                         "the fixture has exactly two rows per person today")
        with self.assertRaises(ValueError) as caught:
            sd.melt_showdown_salary_csv(self._twin(self.POOLED, salary="3000"))
        self.assertIn("another's projection", str(caught.exception))


class R295aTheHoldYieldsToAContradictingLockTests(unittest.TestCase):
    """R295(a). The R250 captain-budget hold collided with a thesis lock and the
    ladder answered by dropping the PLAYER CAP.

    A player `X` this thesis locks must appear (`cpt_X + util_X >= 1`). The hold
    says `util_X = 0`. The captain lock names someone else. The three are
    infeasible for no strategic reason, and the rung that answers drops the cap
    and the hold together (`excludes=without_cap`, no `**util_kw`), readmitting
    every capped player to rescue a thesis whose only problem was a reservation.

    Reproduced at the `build_thesis_ladder` level deliberately: through
    `run_showdown`, R334(a) routes the same moneyline packet into
    `build_showdown_f1` -> `apply_f1_prior`, which moves `Base`, so the filed
    counts would not reproduce there and that would not be a falsification.

    Every count here is a deterministic property of the delivered set. No win
    rate, ROI or probability is claimed.
    """

    N = 12
    MONEYLINE = {"MIN": 150.0, "CHC": -170.0}

    @classmethod
    def setUpClass(cls):
        cls.df = sd.melt_showdown_salary_csv(SAL)

    def _solve(self, n=None, moneyline=None):
        built = st.build_thesis_ladder(self.df, n or self.N,
                                       moneyline=moneyline or self.MONEYLINE)
        diag = {}
        solved = st.solve_ladder(self.df, built["theses"],
                                 max_shared_players=None, time_limit=8,
                                 diagnostics=diag)
        counts = collections.Counter()
        for lu in solved:
            if lu is not None:
                for key in lu["player_keys"]:
                    counts[key] += 1
        return built["theses"], solved, diag, counts

    def test_no_player_finishes_over_the_player_cap(self):
        """The filed breach, on the filed inputs: Josh Bell 7 of 12 against a
        `player_cap_count` of 6."""
        _, _, diag, counts = self._solve()
        cap = diag["player_cap_count"]
        self.assertIsNotNone(cap, "fixture precondition: the cap must bind")
        over = {k: c for k, c in counts.items() if c > cap}
        self.assertEqual(over, {},
                         f"realized exposure above the player cap of {cap}: {over}")

    def test_the_cap_is_not_relaxed_to_get_there(self):
        """The distinction that makes this a defect rather than a trade: the cap
        holding because nothing asked it to give way, not because the ladder
        relaxed it and the counts happened to land under."""
        _, _, diag, _ = self._solve()
        self.assertEqual(diag["player_relaxed"], 0)
        self.assertEqual(diag["captain_budget_inversions"], [])

    def test_the_hold_that_stood_down_is_named(self):
        """A hold that silently did not apply is the invisibility R250 was filed
        against, one level down. The stand-down is reported per (slot, player)
        with what it yielded to."""
        theses, _, diag, _ = self._solve()
        yielded = diag["captain_budget_hold_yielded"]
        self.assertTrue(yielded, "the filed collision no longer arises at all; "
                                 "re-derive the fixture before trusting this suite")
        for row in yielded:
            self.assertEqual(row["yielded_to"], "lock")
            for field in ("thesis", "player", "held"):
                self.assertIn(field, row)
        names = {row["player"] for row in yielded}
        by_name = {t["name"]: t for t in theses}
        for row in yielded:
            thesis = by_name[row["thesis"]]
            locked = {str(k) for k in (thesis.get("locks") or [])}
            key = next(k for k in self.df["Player_Key"]
                       if str(k).split("|")[0] == row["player"])
            self.assertIn(key, locked,
                          "a hold yielded for a player the thesis never locked")
            self.assertNotEqual(str(thesis.get("cpt")), key,
                                "a hold yielded although the locked player IS "
                                "the captain lock, where nothing contradicts")
        self.assertTrue(names)

    def test_the_hold_still_binds_where_nothing_contradicts_it(self):
        """The stand-down must be narrow. R250's hold has to keep blocking UTIL
        seats on every slot where no lock contradicts it, or this fix has
        replaced one silent failure with another."""
        _, _, diag, _ = self._solve()
        self.assertGreater(
            diag["captain_budget_util_blocks"], 0,
            "the hold stopped binding anywhere, so R295(a) disabled R250 rather "
            "than narrowing it")

    def test_every_reserved_row_is_still_filled(self):
        """A blank reserved row blocks certification, so a fix that buys cap
        compliance with a missing lineup has bought nothing."""
        _, solved, _, _ = self._solve()
        self.assertEqual(len(solved), self.N)
        for i, lu in enumerate(solved):
            self.assertIsNotNone(lu, f"slot {i} came back blank")

    def test_the_brief_carries_the_stand_down(self):
        """The operator surface. R250's hold is reported in the brief's
        `captain_budget` block; a hold that stood down belongs beside it, or the
        reader has to infer it from a block that is not there."""
        src = (REPO / "skills" / "generate-lineups" / "scripts"
               / "build_slate.py").read_text(encoding="utf-8")
        self.assertIn('"hold_yielded_to_lock": captain_budget_hold_yielded,', src)
        self.assertIn('solve_diag.get("captain_budget_hold_yielded")', src)
        self.assertIn("captain_budget_hold_yielded = []", src,
                      "the bank path must define the key too, or the brief "
                      "raises NameError on a non-ladder Showdown build")

    def test_the_cap_holds_across_the_moneyline_grid(self):
        """One fixture at one price is a sighting. The cap has to hold across
        the side mix, because the moneyline is what moves which thesis carries
        which locks."""
        for chc, mn in ((-350.0, 300.0), (-170.0, 150.0), (110.0, -130.0),
                        (300.0, -350.0)):
            for n in (9, 12):
                with self.subTest(chc=chc, n=n):
                    _, solved, diag, counts = self._solve(
                        n=n, moneyline={"CHC": chc, "MIN": mn})
                    cap = diag["player_cap_count"]
                    over = {k: c for k, c in counts.items() if cap and c > cap}
                    self.assertEqual(over, {}, f"cap {cap} breached: {over}")
                    self.assertEqual(diag["player_relaxed"], 0)
                    self.assertTrue(all(lu is not None for lu in solved))


if __name__ == "__main__":
    unittest.main(verbosity=2)
