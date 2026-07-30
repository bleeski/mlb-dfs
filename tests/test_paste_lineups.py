"""R32: the mlb.com paste is the primary lineup source; the API feed is fallback.

Every test here runs against Ben's ACTUAL 2026-07-29 copy/paste
(tests/fixtures/paste/mlb_com_2026-07-29_late3.txt) and that slate's real
DKSalaries.csv. A parser for a pasted format has to be tested against the format
as it really arrives, because the failure mode is not an exception: it is a
plausible-looking lineup attached to the wrong team.

Nothing here reaches the network. Nothing here imports scipy.
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

from mlb_engine.intake.paste_lineups import (  # noqa: E402
    parse_paste, resolve_paste_to_feed,
)

PASTE = REPO / "tests" / "fixtures" / "paste" / "mlb_com_2026-07-29_late3.txt"
SALARY = REPO / "data" / "slates" / "2026-07-29" / "DKSalaries.csv"
# The one ambiguity in the real paste: SEA carries both Will Wilson (IL) and
# Weston Wilson, and 'W Wilson' cannot choose between them.
RESOLVE = {"W Wilson": "Weston Wilson"}


def _text() -> str:
    return PASTE.read_text(encoding="utf-8")


@unittest.skipUnless(SALARY.exists(), "the 2026-07-29 salary file is not staged")
class PasteStructureTests(unittest.TestCase):
    """The paste's real shape, including the trap that would corrupt a build."""

    def setUp(self):
        self.games, self.warnings = parse_paste(_text())

    def test_three_games_parse_with_no_warnings(self):
        self.assertEqual([g.game_id for g in self.games],
                         ["HOU@LAA", "BOS@ATH", "SEA@LAD"])
        self.assertEqual(self.warnings, [])

    def test_the_paired_header_trap_does_not_cross_teams(self):
        """Both '<TEAM> Lineup' headers appear BEFORE either block. A parser that
        tracks 'the last header seen' puts all eighteen hitters on the home team,
        which is a wrong answer with no error: the build would stack the wrong
        side and every gate would pass. Blocks split on the order resetting to 1
        and the Nth block belongs to the Nth header."""
        hou = self.games[0]
        self.assertEqual(hou.away_team, "HOU")
        self.assertEqual(hou.home_team, "LAA")
        self.assertEqual(len(hou.away_lineup), 9)
        self.assertEqual(len(hou.home_lineup), 9)
        self.assertEqual(hou.away_lineup[0].display_name, "J Peña")
        self.assertEqual(hou.home_lineup[0].display_name, "Z Neto")
        # The Astros' cleanup hitter must not appear anywhere on the Angels.
        self.assertNotIn("C Walker", [p.display_name for p in hou.home_lineup])

    def test_handedness_comes_from_the_paste_and_needs_no_lookup(self):
        """The (R)/(L)/(S) token is on the page, so F4's platoon input is fully
        fed by the paste and a paste-primary build needs no handedness fetch."""
        sides = {p.display_name: p.bat_side for p in self.games[0].away_lineup}
        self.assertEqual(sides["J Peña"], "R")
        self.assertEqual(sides["Y Alvarez"], "L")
        switch = {p.display_name: p.bat_side for p in self.games[0].home_lineup}
        self.assertEqual(switch["T Heineman"], "S")
        for game in self.games:
            for player in game.away_lineup + game.home_lineup:
                self.assertIn(player.bat_side, ("L", "R", "S"))

    def test_every_player_carries_its_mlbam_id_from_the_url(self):
        self.assertEqual(self.games[0].away_lineup[0].mlbam_id, "665161")
        self.assertEqual(self.games[2].home_lineup[0].mlbam_id, "660271")
        for game in self.games:
            for player in game.away_lineup + game.home_lineup:
                self.assertTrue((player.mlbam_id or "").isdigit(), player.display_name)

    def test_probable_pitchers_take_hand_and_away_comes_first(self):
        hou = self.games[0]
        self.assertEqual(hou.away_pitcher.display_name, "Hayden Wesneski")
        self.assertEqual(hou.away_pitcher.hand, "R")
        self.assertEqual(hou.home_pitcher.display_name, "Grayson Rodriguez")
        sea = self.games[2]
        self.assertEqual(sea.home_pitcher.display_name, "Eric Lauer")
        self.assertEqual(sea.home_pitcher.hand, "L")

    def test_venue_and_clock_and_gameday_survive(self):
        self.assertEqual(self.games[0].venue, "Angel Stadium")
        self.assertEqual(self.games[0].clock_text, "9:38 PM")
        self.assertEqual(self.games[0].gameday_id, "824002")
        self.assertEqual(self.games[2].venue, "UNIQLO Field at Dodger Stadium")

    def test_the_last_game_needs_no_trailing_gameday_link(self):
        """The real paste ends after the Dodgers' ninth hitter. Game separation
        keys on the 'Club@Club' line, never on the Gameday footer."""
        self.assertIsNone(self.games[2].gameday_id)
        self.assertEqual(len(self.games[2].home_lineup), 9)

    def test_the_seven_remapped_team_codes_normalize_to_dk(self):
        """R33: DK and MLB disagree on seven clubs. The header used to be taken
        verbatim, so a paste rendering CHW/AZ/WSN/TBR/KCR/SDP/SFG produced a
        game_id that matched nothing in the salary file and the whole game was
        SKIPPED -- a Classic slate quietly short one game. The first real paste
        contained none of the seven, which is why the original tests passed."""
        from mlb_engine.intake.paste_lineups import _dk_team
        cases = {("CHW", "White Sox"): "CWS", ("AZ", "Diamondbacks"): "ARI",
                 ("WSN", "Nationals"): "WSH", ("TBR", "Rays"): "TB",
                 ("KCR", "Royals"): "KC", ("SDP", "Padres"): "SD",
                 ("SFG", "Giants"): "SF"}
        for (code, club), expected in cases.items():
            warnings = []
            with self.subTest(code=code):
                self.assertEqual(_dk_team(code, club, warnings), expected)
                self.assertEqual(warnings, [])

    def test_the_club_link_is_a_real_second_read_not_an_inert_one(self):
        """The club nickname is the independent check on the header code. It was
        captured but unusable, because the name map held only full names, so
        every nickname resolved to None and the cross-check never fired."""
        from mlb_engine.intake.live_data_adapters import team_name_to_dk_abbrev
        for club, expected in (("Astros", "HOU"), ("Dodgers", "LAD"),
                               ("White Sox", "CWS"), ("Cubs", "CHC"),
                               ("Angels", "LAA"), ("Athletics", "ATH")):
            self.assertEqual(team_name_to_dk_abbrev(club), expected, club)

    def test_a_header_that_disagrees_with_the_club_link_warns_and_trusts_the_link(self):
        from mlb_engine.intake.paste_lineups import _dk_team
        warnings = []
        self.assertEqual(_dk_team("XYZ", "Dodgers", warnings), "LAD")
        self.assertTrue(any("club link" in w for w in warnings))

    def test_stat_lines_and_records_are_not_mistaken_for_players(self):
        names = [p.display_name for g in self.games
                 for p in g.away_lineup + g.home_lineup]
        self.assertEqual(len(names), 54)
        for name in names:
            self.assertNotIn("ERA", name)
            self.assertFalse(name.startswith("("))


@unittest.skipUnless(SALARY.exists(), "the 2026-07-29 salary file is not staged")
class PasteResolutionTests(unittest.TestCase):
    """Abbreviated first names against DK's full names, and the failure rules."""

    def test_abbreviated_names_resolve_to_dk_canonical_names(self):
        """'J Peña' is not 'Jeremy Pena' under an exact normalized match, which is
        why the pre-existing reconciler fails on every hitter in a real paste."""
        out = resolve_paste_to_feed(_text(), str(SALARY), resolve_overrides=RESOLVE)
        self.assertEqual(out["report"]["blockers"], [])
        self.assertEqual(out["report"]["resolved"], 60)
        first = out["feed"]["games"][0]["away"]["lineup"][0]
        self.assertEqual(first["name"], "Jeremy Pena")
        self.assertEqual(first["pasted_as"], "J Peña")
        self.assertTrue(first["dk_player_id"])

    def test_every_team_in_the_paste_is_confirmed(self):
        out = resolve_paste_to_feed(_text(), str(SALARY), resolve_overrides=RESOLVE)
        self.assertEqual(out["report"]["confirmed_teams"],
                         ["ATH", "BOS", "HOU", "LAA", "LAD", "SEA"])
        self.assertEqual(out["report"]["partial_teams"], [])

    def test_an_ambiguous_name_blocks_and_names_both_candidates_with_status(self):
        """Without the override, SEA's 'W Wilson' matches Will Wilson (IL) and
        Weston Wilson. Guessing would put an IL player in a confirmed lineup, so
        it refuses and prints the DK Status that decides it."""
        out = resolve_paste_to_feed(_text(), str(SALARY))
        blockers = out["report"]["blockers"]
        self.assertEqual(len(blockers), 1)
        self.assertIn("W Wilson", blockers[0])
        self.assertIn("Weston Wilson", blockers[0])
        self.assertIn("Will Wilson", blockers[0])
        self.assertIn("DK Status IL", blockers[0])
        self.assertIn("--resolve", blockers[0])

    def test_a_side_short_because_of_a_blocker_says_so_not_partial_posted(self):
        """Two different reasons for a short side, and the report must not blur
        them: this tool failing to resolve a name is a blocker, while mlb.com
        posting eight is a labelled projection."""
        out = resolve_paste_to_feed(_text(), str(SALARY))
        rows = {r["team"]: r for r in out["report"]["partial_teams"]}
        self.assertIn("unresolved", rows["SEA"]["reason"])

    def test_a_genuinely_partial_paste_is_projected_never_confirmed(self):
        """Ben's call: a short block is partial, which the status builder reads as
        Projected_Starter and reports. Calling eight-of-nine 'confirmed' would be
        the labels rule broken at the front door."""
        text = _text().replace(
            "9. [T Heineman](https://www.mlb.com/player/tyler-heineman-623168) (S) C\n", "")
        out = resolve_paste_to_feed(text, str(SALARY), resolve_overrides=RESOLVE)
        rows = {r["team"]: r for r in out["report"]["partial_teams"]}
        self.assertEqual(rows["LAA"]["hitters_posted"], 8)
        self.assertIn("mlb.com posted a partial", rows["LAA"]["reason"])
        self.assertNotIn("LAA", out["report"]["confirmed_teams"])
        laa = out["feed"]["games"][0]["home"]
        self.assertEqual(laa["lineup_status"], "partial")

    def test_a_starter_absent_from_the_dk_pool_is_reported_never_fatal(self):
        """DK's file is authoritative for eligibility, so a starter DK did not
        list is unrosterable whatever the paste says. That is a fact to report,
        not a parse failure."""
        text = _text().replace("[M Trout](https://www.mlb.com/player/mike-trout-545361)",
                               "[Q Nobody](https://www.mlb.com/player/quinn-nobody-999999)")
        out = resolve_paste_to_feed(text, str(SALARY), resolve_overrides=RESOLVE)
        self.assertEqual(out["report"]["blockers"], [])
        absent = {r["pasted_name"] for r in out["report"]["unrostered_starters"]}
        self.assertIn("Q Nobody", absent)

    def test_lock_times_come_from_the_salary_file_not_the_paste(self):
        """The paste carries a bare clock with no date and no stated zone; the CSV
        carries a full dated Eastern start and is authoritative for the slate."""
        out = resolve_paste_to_feed(_text(), str(SALARY), resolve_overrides=RESOLVE)
        by_id = {f"{g['away']['team_abbrev']}@{g['home']['team_abbrev']}":
                 g["game_date_utc"] for g in out["feed"]["games"]}
        self.assertEqual(by_id["HOU@LAA"], "2026-07-30T01:38:00Z")
        self.assertEqual(by_id["SEA@LAD"], "2026-07-30T02:10:00Z")

    def test_a_clock_disagreement_is_reported_as_a_wrong_slate_signal(self):
        text = _text().replace("9:38 PM", "1:05 PM")
        out = resolve_paste_to_feed(text, str(SALARY), resolve_overrides=RESOLVE)
        self.assertTrue(any("wrong slate" in w for w in out["report"]["warnings"]))

    def test_a_game_not_on_this_slate_is_skipped_never_merged(self):
        # Both the header AND the club link have to move: since R33 the club link
        # is the authoritative read, so changing only the header describes a
        # self-contradictory paste (which is now caught as such) rather than an
        # off-slate game.
        text = (_text()
                .replace("HOU Lineup", "NYY Lineup").replace("LAA Lineup", "CWS Lineup")
                .replace("[Astros](https://www.mlb.com/astros)",
                         "[Yankees](https://www.mlb.com/yankees)")
                .replace("[Angels](https://www.mlb.com/angels)",
                         "[White Sox](https://www.mlb.com/whitesox)"))
        out = resolve_paste_to_feed(text, str(SALARY), resolve_overrides=RESOLVE)
        self.assertTrue(any("absent from the salary file" in w
                            for w in out["report"]["warnings"]))
        used = {f"{g['away']['team_abbrev']}@{g['home']['team_abbrev']}"
                for g in out["feed"]["games"]}
        self.assertNotIn("NYY@CWS", used)

    def test_a_missing_header_attaches_no_lineup_to_anyone(self):
        """Better no lineup than one on the wrong team."""
        text = _text().replace("LAA Lineup\n", "")
        games, _ = parse_paste(text)
        self.assertEqual(games[0].away_lineup, [])
        self.assertEqual(games[0].home_lineup, [])
        self.assertTrue(any("wrong team" in w for w in games[0].warnings))

    def test_the_feed_is_tagged_operator_paste_at_every_grain(self):
        out = resolve_paste_to_feed(_text(), str(SALARY), resolve_overrides=RESOLVE)
        self.assertEqual(out["feed"]["source"], "operator_paste")
        for game in out["feed"]["games"]:
            self.assertEqual(game["source"], "operator_paste")
            for side in ("away", "home"):
                self.assertEqual(game[side]["source"], "operator_paste")


@unittest.skipUnless(SALARY.exists(), "the 2026-07-29 salary file is not staged")
class PasteFeedIsAnOrdinaryFeedTests(unittest.TestCase):
    """The engine must not be able to tell the feed was typed rather than fetched."""

    def test_the_status_builder_reads_it_with_no_engine_change(self):
        from mlb_engine.intake.live_data_adapters import (
            build_status_map_from_lineups_feed,
        )
        out = resolve_paste_to_feed(_text(), str(SALARY), resolve_overrides=RESOLVE)
        status = build_status_map_from_lineups_feed(out["feed"], str(SALARY))
        self.assertEqual(status["confirmed_teams"],
                         ["ATH", "BOS", "HOU", "LAA", "LAD", "SEA"])
        self.assertEqual(len(status["confirmed_hitter_ids"]), 54)
        self.assertEqual(len(status["probable_pitcher_ids"]), 6)
        self.assertEqual(status["unmatched_feed_players"], [],
                         "a name this tool resolved must match downstream too")
        self.assertEqual(status["partial_lineup_teams"], [])

    def test_a_fully_pasted_slate_leaves_no_tbd_team_and_no_platoon_read(self):
        """The consequence worth having: the 7-day platoon staleness blocker
        exists to gate the reference that fills TBD teams. With none, the
        reference is never read and the blocker has nothing to gate."""
        from mlb_engine.intake.live_data_adapters import build_slate_pool
        out = resolve_paste_to_feed(_text(), str(SALARY), resolve_overrides=RESOLVE)
        pool = build_slate_pool(str(SALARY), out["feed"], stale_platoon_policy="block")
        self.assertEqual(pool["pool_report"].get("blockers"), [])
        self.assertIsNone(pool.get("platoon_source"))


@unittest.skipUnless(SALARY.exists(), "the 2026-07-29 salary file is not staged")
class PasteWinsOverTheApiFeedTests(unittest.TestCase):
    """The fallback rule: a pasted side is never fetched and never overwritten."""

    @staticmethod
    def _api_feed(path: Path) -> Path:
        path.write_text(json.dumps({
            "date": "2026-07-29", "fetched_at": "2026-07-29T20:00:00Z",
            "games": [
                {"game_pk": 9001, "game_date_utc": "2026-07-30T01:38:00Z",
                 "status": "Pre-Game",
                 "away": {"team_abbrev": "HOU", "lineup_status": "confirmed",
                          "lineup": [{"order": 1, "name": "Somebody Else"}],
                          "probable_pitcher": {"name": "Wrong Arm", "hand": "L"}},
                 "home": {"team_abbrev": "LAA", "lineup_status": "tbd",
                          "lineup": [], "probable_pitcher": None}},
                {"game_pk": 9002, "game_date_utc": "2026-07-29T23:05:00Z",
                 "status": "Pre-Game",
                 "away": {"team_abbrev": "NYY", "lineup_status": "confirmed",
                          "lineup": [{"order": 1, "name": "Aaron Judge"}],
                          "probable_pitcher": {"name": "Carlos Rodon", "hand": "L"}},
                 "home": {"team_abbrev": "CWS", "lineup_status": "tbd",
                          "lineup": [], "probable_pitcher": None}},
            ]}), encoding="utf-8")
        return path

    def _run(self, *extra, expect=0):
        with tempfile.TemporaryDirectory() as tmp:
            api = self._api_feed(Path(tmp) / "api.json")
            out = Path(tmp) / "feed.json"
            result = subprocess.run(
                [sys.executable, str(REPO / "tools" / "lineups_from_paste.py"),
                 "--salary", str(SALARY), "--paste", str(PASTE),
                 "--resolve", "W Wilson=Weston Wilson",
                 "--merge-feed", str(api), "--out", str(out), *extra],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, expect,
                             result.stdout + result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
            return result, payload

    def test_the_api_cannot_overwrite_a_pasted_side(self):
        _result, feed = self._run()
        hou = next(g for g in feed["games"]
                   if g["away"]["team_abbrev"] == "HOU")
        self.assertEqual(hou["away"]["lineup"][0]["name"], "Jeremy Pena")
        self.assertEqual(hou["away"]["source"], "operator_paste")
        self.assertEqual(hou["away"]["probable_pitcher"]["name"], "Hayden Wesneski")
        self.assertEqual(feed["merge_report"]["sides_filled_from_api"], [])

    def test_a_game_the_paste_never_mentioned_comes_from_the_api(self):
        _result, feed = self._run()
        nyy = next((g for g in feed["games"]
                    if g["away"]["team_abbrev"] == "NYY"), None)
        self.assertIsNotNone(nyy)
        self.assertEqual(nyy["source"], "api_feed_fallback")
        self.assertEqual(nyy["away"]["source"], "api_feed_fallback")
        self.assertEqual(feed["merge_report"]["games_added_from_api"], ["NYY@CWS"])

    def test_a_complete_paste_reports_the_fallback_as_unneeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Path(tmp) / "api.json"
            api.write_text(json.dumps({"date": "2026-07-29", "games": []}),
                           encoding="utf-8")
            out = Path(tmp) / "feed.json"
            result = subprocess.run(
                [sys.executable, str(REPO / "tools" / "lineups_from_paste.py"),
                 "--salary", str(SALARY), "--paste", str(PASTE),
                 "--resolve", "W Wilson=Weston Wilson",
                 "--merge-feed", str(api), "--out", str(out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Zero lineup fetches", result.stdout)

    def test_a_blocker_writes_no_feed_at_all(self):
        """A half-resolved lineup would arrive downstream looking like a posted
        partial, which is the pool reduction the contract forbids."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "feed.json"
            result = subprocess.run(
                [sys.executable, str(REPO / "tools" / "lineups_from_paste.py"),
                 "--salary", str(SALARY), "--paste", str(PASTE), "--out", str(out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertFalse(out.exists(), "a blocked run must write nothing")
            self.assertIn("BLOCKER", result.stderr)

    def test_the_tool_reaches_no_network(self):
        """Checked on the import graph, not on substrings: the docstrings name
        mlb.com, which is the whole point of the module, so a text search for
        'http' flags the documentation rather than a fetch."""
        import ast

        forbidden = {"urllib", "urllib.request", "requests", "http",
                     "http.client", "socket", "aiohttp", "httpx"}
        for path in ((REPO / "tools" / "lineups_from_paste.py"),
                     (REPO / "mlb_engine" / "intake" / "paste_lineups.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertEqual(imported & forbidden, set(),
                             f"{path.name} imports a network library")
            # The import graph is the whole check: nothing in Python reaches the
            # network without importing something. Screening call names by hand
            # is worse than useless here, because `.get` is dict.get on nearly
            # every line of a parser.
            called = {node.func.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute)}
            self.assertNotIn("urlopen", called, f"{path.name} opens a URL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
