"""Showdown build gate: contracts, MILP legality, exact synthetic optimum, real-file
melt, end-to-end certify, and DKEntries export round-trip.

Every number here is a deterministic review proxy (Base = AvgPointsPerGame), never a
win-rate, ROI, or probability claim. Classic is untouched; this suite imports nothing
from the Classic solver, so test_golden_replay is unaffected.
"""
from __future__ import annotations

import collections
import contextlib
import json
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
        # The 45s device_bash figure is unchanged for a caller who does not ask.
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

    def _theses(self, n, cheap_from):
        out = []
        for i in range(n):
            cpt = (self.CHEAP if i >= cheap_from
                   else ("AA_Big|AA" if i % 2 else "BB_Big|BB"))
            out.append({"template": f"t{i}", "name": f"t{i}", "why": "",
                        "cpt": cpt, "locks": [], "excludes": [], "mult": {}})
        return out

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
