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
from tools.lineups_from_paste import merge_feeds  # noqa: E402

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

    def test_the_zero_network_contract_holds_TRANSITIVELY(self):
        """The single-file import check above is shallow, and that let one through.

        R59 needed `to_dk_abbrev` in lineups_from_paste. The obvious import is
        from `live_data_adapters`, where the team-code maps lived -- and that
        module imports `urllib.request` at module scope, so three lines of dict
        lookup would have pulled a live HTTP client into this tool's import graph
        while the check above stayed green: `live_data_adapters` is not itself in
        the forbidden set. The maps moved to the network-free
        `mlb_engine.team_codes` instead, and this test asks the question the
        contract actually makes, which is about the whole graph and not one file.

        It runs in a FRESH interpreter on purpose. Measuring `sys.modules` in
        this process cannot work: by the time this test runs, the rest of the
        suite has already imported `urllib.request`, so a before/after diff comes
        back empty and the check passes under the very mutation it exists to
        catch. That was observed, not theorized.
        """
        # Only modules that can actually open a connection. `urllib.parse` is
        # pure string work and is already in the graph via the parser's own
        # imports; listing it would fail on something that is not a fetch.
        probe = (
            "import sys, json\n"
            "import tools.lineups_from_paste\n"
            "capable = {'urllib.request', 'http.client', 'requests', 'httpx', 'aiohttp'}\n"
            "print(json.dumps(sorted(capable & set(sys.modules))))\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], cwd=str(REPO),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pulled = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(
            pulled, [],
            f"the paste tool's import graph now reaches {pulled}; the "
            "zero-network contract is a property of the graph, not of one file")


class DoubleheaderPastedLegTests(unittest.TestCase):
    """R58(a). Every pasted leg of a matchup used to get the salary file's one start.

    A DK draftgroup prices ONE leg of a doubleheader and salary_game_times is keyed
    on AWAY@HOME, so both pasted legs carried an identical game_date_utc and
    _select_slate_legs kept whichever was pasted first. Reproduced on a 9:38 PM
    night draftgroup: it confirmed the 1:05 PM leg's batting order, the night-only
    starters were absent from the pool, and the build exited 0.
    """

    AWAY, HOME = "AAA", "BBB"
    SLOTS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
    DK_SLOTS = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "OF"]

    def _salary(self, path, clock="09:38PM"):
        game_info = f"{self.AWAY}@{self.HOME} 08/05/2026 {clock} ET"
        header = ["Position", "Name + ID", "Name", "ID", "Roster Position",
                  "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame"]
        rows, pid = [], 40000
        def add(pos, name, team, sal):
            nonlocal pid
            pid += 1
            rows.append([pos, f"{name} ({pid})", name, str(pid), pos, str(sal),
                         game_info, team, "8.0"])
        add("SP", "Matinee Arm", self.AWAY, 9000)
        add("SP", "Night Arm", self.AWAY, 8800)
        add("SP", "Home Arm", self.HOME, 8600)
        for prefix, team in (("Matinee", self.AWAY), ("Night", self.AWAY),
                             ("Home", self.HOME)):
            for i, slot in enumerate(self.DK_SLOTS, 1):
                add(slot, f"{prefix} {prefix[0]}{i}", team, 3000)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh); writer.writerow(header); writer.writerows(rows)

    def _side(self, prefix):
        return "\n".join(
            f"{i}. [{prefix} {prefix[0]}{i}](https://www.mlb.com/player/x-{i}) (R) {slot}"
            for i, slot in enumerate(self.SLOTS, 1))

    def _paste(self, legs):
        """legs: [(clock, away_arm, away_prefix), ...] in the order mlb.com renders."""
        blocks = []
        for clock, arm, prefix in legs:
            blocks.append("\n".join([
                "[Alphas](https://www.mlb.com/alphas)@[Betas](https://www.mlb.com/betas)",
                "(50-50)", clock, "Some Park", "(50-50)",
                f"[{arm}](https://www.mlb.com/player/arm-1)", "RHP", "0-0, 1.00 ERA, 1 SO",
                "[Home Arm](https://www.mlb.com/player/arm-3)", "RHP", "0-0, 1.00 ERA, 1 SO",
                f"{self.AWAY} Lineup", f"{self.HOME} Lineup", "",
                self._side(prefix), "", self._side("Home"), "",
            ]))
        return "\n".join(blocks)

    BOTH_LEGS = [("1:05 PM", "Matinee Arm", "Matinee"),
                 ("9:38 PM", "Night Arm", "Night")]

    def _resolve(self, legs=None, clock="09:38PM"):
        with tempfile.TemporaryDirectory() as tmp:
            salary = Path(tmp) / "DKSalaries.csv"
            self._salary(salary, clock=clock)
            out = resolve_paste_to_feed(self._paste(legs or self.BOTH_LEGS), str(salary))
            from mlb_engine.intake.live_data_adapters import (
                salary_game_times, _select_slate_legs)
            times = salary_game_times(str(salary))
            return out, times, _select_slate_legs(
                list((out["feed"] or {}).get("games") or []), times)

    def test_each_pasted_leg_gets_its_own_start(self):
        out, _times, (kept, dropped) = self._resolve()
        stamps = [g["game_date_utc"] for g in out["feed"]["games"]]
        self.assertEqual(len(set(stamps)), 2,
                         f"both legs carry the same start: {stamps}")
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)
        first = kept[0]["away"]["lineup"][0]["name"]
        self.assertIn("Night", first,
                      "the 9:38 PM salary file kept the matinee leg's batting order")
        self.assertEqual(kept[0]["away"]["probable_pitcher"]["name"], "Night Arm")

    def test_the_priced_leg_is_named_instead_of_a_false_wrong_slate_warning(self):
        # The matinee's 1:05 PM legitimately differs from the salary start on a
        # doubleheader, so the single-leg wrong-slate warning was firing on the
        # wrong leg. The doubleheader is reported as what it is.
        out, _t, _s = self._resolve()
        warnings = out["report"]["warnings"]
        self.assertTrue(any("doubleheader" in w and "9:38 PM" in w for w in warnings),
                        warnings)
        self.assertFalse(any("wrong slate" in w for w in warnings), warnings)

    def test_indistinguishable_legs_block_and_write_no_feed(self):
        # Two legs the operator pasted with the same clock cannot be told apart,
        # and guessing is what this closes.
        out, _t, _s = self._resolve(legs=[("9:38 PM", "Matinee Arm", "Matinee"),
                                          ("9:38 PM", "Night Arm", "Night")])
        self.assertTrue(any("cannot be told apart by clock" in b
                            for b in out["report"]["blockers"]),
                        out["report"]["blockers"])
        self.assertEqual(out["feed"]["games"], [],
                         "a blocked matchup must contribute no game")

    def test_no_leg_matching_the_salary_start_is_still_reported(self):
        # A real wrong-slate paste: both legs pasted, neither matches the priced
        # start. That has to stay loud.
        out, _t, _s = self._resolve(clock="07:05PM")
        self.assertTrue(any("NONE" in w and "matches the salary file" in w
                            for w in out["report"]["warnings"]),
                        out["report"]["warnings"])

    def test_a_single_leg_still_takes_its_start_from_the_salary_file(self):
        # The contract is unchanged off the doubleheader path: the CSV carries a
        # full dated start and the paste's bare clock stays a cross-check only.
        out, times, _s = self._resolve(legs=[("1:05 PM", "Matinee Arm", "Matinee")])
        game = out["feed"]["games"][0]
        self.assertEqual(game["game_date_utc"], "2026-08-06T01:38:00Z")
        self.assertTrue(any("wrong slate" in w for w in out["report"]["warnings"]),
                        "a single-leg clock disagreement is a wrong-slate signal")


class MergeFeedsTeamCodeAndFieldTests(unittest.TestCase):
    """R59. merge_feeds is a pure function on two feed dicts, tested at that grain.

    It had NO coverage of any kind before this, which is how both halves shipped:
    the merge key was the only place in the pipeline not normalizing team codes,
    and the side fill replaced a whole side dict instead of merging fields.
    """

    @staticmethod
    def _side(abbr, *, hitters=0, probable=None, status="tbd", **extra):
        side = {
            "team_abbrev": abbr,
            "lineup": [{"order": i + 1, "name": f"{abbr} bat {i + 1}"}
                       for i in range(hitters)],
            "lineup_status": status,
            "probable_pitcher": probable,
        }
        side.update(extra)
        return side

    @staticmethod
    def _game(away, home, pk=1, utc="2026-08-05T23:10:00Z"):
        return {"game_pk": pk, "game_date_utc": utc, "status": "Scheduled",
                "away": away, "home": home}

    def _feed(self, *games):
        return {"date": "2026-08-05", "games": list(games)}

    def test_a_raw_api_team_code_matches_the_dk_coded_paste(self):
        # The filed case. StatsAPI ships AZ; the paste is DK-coded ARI. Unnormalized,
        # the same game was keyed twice, the API copy was APPENDED, and
        # games_added_from_api reported that as a success. _select_slate_legs
        # normalizes, so it then saw one matchup twice and dropped one leg -- the
        # API's real confirmed lineup went with it, looking like leg selection.
        pasted = self._feed(self._game(
            self._side("SD", hitters=9, status="confirmed"), self._side("ARI")))
        api = self._feed(self._game(
            self._side("SD", hitters=9, status="confirmed"),
            self._side("AZ", hitters=9, status="confirmed",
                       probable={"name": "AZ Arm", "hand": "R"})))
        out = merge_feeds(pasted, api)
        self.assertEqual(len(out["games"]), 1, "the API copy was appended as a phantom game")
        game = out["games"][0]
        self.assertEqual(game["home"]["team_abbrev"], "ARI",
                         "the merged side must keep the paste's DK code")
        self.assertEqual(len(game["home"]["lineup"]), 9,
                         "the API's confirmed lineup never reached the pasted side")
        self.assertEqual(out["merge_report"]["games_added_from_api"], [])
        self.assertEqual(out["merge_report"]["sides_filled_from_api"], ["SD@ARI home"])
        self.assertEqual(out["merge_report"]["api_keys_normalized"],
                         ["SD@AZ -> SD@ARI"])

    def test_every_remapped_code_matches(self):
        for raw, dk in (("AZ", "ARI"), ("WSN", "WSH"), ("TBR", "TB"),
                        ("CHW", "CWS"), ("KCR", "KC"), ("SDP", "SD"), ("SFG", "SF")):
            with self.subTest(raw=raw):
                pasted = self._feed(self._game(
                    self._side("NYY", hitters=9, status="confirmed"), self._side(dk)))
                api = self._feed(self._game(
                    self._side("NYY", hitters=9, status="confirmed"),
                    self._side(raw, hitters=9, status="confirmed")))
                out = merge_feeds(pasted, api)
                self.assertEqual(len(out["games"]), 1, f"{raw} did not match {dk}")

    def test_a_pasted_probable_survives_a_side_fill(self):
        # R59b, the late-scratch case: Ben pasted the replacement starter by name
        # and that side has no order yet. The old code replaced the whole side
        # dict, so the API's stale probable displaced the pasted one in silence --
        # R32 paste-primacy inverted.
        pasted = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"),
            self._side("BOS", probable={"name": "Replacement SP", "hand": "R"})))
        api = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"),
            self._side("BOS", hitters=9, status="confirmed",
                       probable={"name": "Scratched SP", "hand": "L"})))
        out = merge_feeds(pasted, api)
        bos = out["games"][0]["home"]
        self.assertEqual(bos["probable_pitcher"]["name"], "Replacement SP")
        self.assertEqual(bos["probable_pitcher"]["hand"], "R")
        self.assertEqual(len(bos["lineup"]), 9, "the API's order should still fill")
        self.assertEqual(bos["lineup_status"], "confirmed")
        report = out["merge_report"]
        self.assertEqual(report["fields_filled_from_api"], ["NYY@BOS home: lineup"])
        self.assertEqual(
            report["probables_kept_from_paste"],
            ["NYY@BOS home: kept pasted 'Replacement SP' over API 'Scratched SP'"],
            "keeping the pasted arm over a disagreeing API must be reported, not silent")

    def test_an_uncovered_side_takes_the_api_probable(self):
        # The fallback still works where the paste said nothing at all.
        pasted = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"), self._side("BOS")))
        api = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"),
            self._side("BOS", probable={"name": "API Arm", "hand": "L"})))
        out = merge_feeds(pasted, api)
        bos = out["games"][0]["home"]
        self.assertEqual(bos["probable_pitcher"]["name"], "API Arm")
        self.assertEqual(bos["source"], "api_feed_fallback")
        self.assertEqual(out["merge_report"]["fields_filled_from_api"],
                         ["NYY@BOS home: probable_pitcher"])
        self.assertEqual(out["merge_report"]["probables_kept_from_paste"], [])

    def test_a_covered_side_is_never_touched(self):
        pasted = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed",
                       probable={"name": "Pasted Arm", "hand": "R"}),
            self._side("BOS", hitters=9, status="confirmed")))
        api = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed",
                       probable={"name": "Other Arm", "hand": "L"}),
            self._side("BOS", hitters=9, status="confirmed")))
        out = merge_feeds(pasted, api)
        nyy = out["games"][0]["away"]
        self.assertEqual(nyy["probable_pitcher"]["name"], "Pasted Arm")
        self.assertEqual(nyy["lineup"][0]["name"], "NYY bat 1")
        self.assertEqual(out["merge_report"]["sides_filled_from_api"], [])
        self.assertTrue(out["merge_report"]["paste_is_complete"])

    def test_an_api_only_field_fills_an_empty_slot_and_is_named(self):
        pasted = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"), self._side("BOS")))
        api = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"),
            self._side("BOS", hitters=9, status="confirmed", batting_park_factor=104)))
        out = merge_feeds(pasted, api)
        bos = out["games"][0]["home"]
        self.assertEqual(bos["batting_park_factor"], 104)
        self.assertEqual(out["merge_report"]["fields_filled_from_api"],
                         ["NYY@BOS home: batting_park_factor+lineup"])

    def test_a_game_the_paste_never_mentioned_is_still_added_whole(self):
        pasted = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"),
            self._side("BOS", hitters=9, status="confirmed")))
        api = self._feed(
            self._game(self._side("NYY", hitters=9), self._side("BOS", hitters=9)),
            self._game(self._side("LAD", hitters=9, status="confirmed"),
                       self._side("SFG", hitters=9, status="confirmed"), pk=2))
        out = merge_feeds(pasted, api)
        self.assertEqual(len(out["games"]), 2)
        added = out["games"][1]
        self.assertEqual(added["source"], "api_feed_fallback")
        self.assertEqual(added["away"]["source"], "api_feed_fallback")
        # keyed on the normalized code even when the whole game is new
        self.assertEqual(out["merge_report"]["games_added_from_api"], ["LAD@SF"])
        self.assertEqual(out["merge_report"]["api_keys_normalized"],
                         ["LAD@SFG -> LAD@SF"])

    def test_a_side_with_a_missing_team_code_is_skipped_not_crashed(self):
        pasted = self._feed(self._game(
            self._side("NYY", hitters=9, status="confirmed"), self._side("BOS")))
        api = self._feed({"game_pk": 5, "game_date_utc": "2026-08-05T23:10:00Z",
                          "away": {"team_abbrev": ""}, "home": {"team_abbrev": "BOS"}})
        out = merge_feeds(pasted, api)
        self.assertEqual(len(out["games"]), 1)
        self.assertEqual(out["merge_report"]["games_added_from_api"], [])


PLAINTEXT = REPO / "tests" / "fixtures" / "paste" / "mlb_com_2026-07-30_1910_6g_plaintext.txt"
HOME_ONLY = REPO / "tests" / "fixtures" / "paste" / "mlb_com_2026-07-30_home_side_only.txt"
SALARY_0730 = REPO / "data" / "slates" / "2026-07-30" / "DKSalaries_1910_6g.csv"


def _side(feed, game_id, side):
    away, home = game_id.split("@")
    for game in feed["games"]:
        if (game["away"]["team_abbrev"], game["home"]["team_abbrev"]) == (away, home):
            return game[side]
    raise AssertionError(f"{game_id} not in feed")


class SinglePostedSideAlignmentTests(unittest.TestCase):
    """R32 round 2, the P0: a half-posted game must not swap the sides.

    The fixture is two real 2026-07-30 games rendered the way mlb.com renders a
    game whose HOME side has posted and whose away side has not. Pre-fix, on this
    exact input, Elly De La Cruz's CIN nine attached to PIT and Tatis's SD nine
    attached to SF, with no error and a warning that stated the wrong thing
    confidently. The existing fixture could never catch it: every side in it
    posted, which is why 29 tests passed over this bug.
    """

    def setUp(self):
        self.text = HOME_ONLY.read_text(encoding="utf-8")
        self.games, self.warnings = parse_paste(self.text)

    def test_the_posted_nine_goes_to_the_home_team_that_posted_it(self):
        pit_cin = next(g for g in self.games if g.game_id == "PIT@CIN")
        self.assertEqual([p.display_name for p in pit_cin.home_lineup][:1],
                         ["E De La Cruz"])
        self.assertEqual(len(pit_cin.home_lineup), 9)
        self.assertEqual(pit_cin.away_lineup, [],
                         "the away side posted nothing; a nine here is the "
                         "wrong-team bug back")

    def test_the_second_half_posted_game_lands_the_same_way(self):
        sf_sd = next(g for g in self.games if g.game_id == "SF@SD")
        self.assertEqual([p.display_name for p in sf_sd.home_lineup][:1],
                         ["F Tatis Jr."])
        self.assertEqual(sf_sd.away_lineup, [])

    def test_a_bare_tbd_holds_the_pitcher_slot_too(self):
        # The same shift, one field over: with SF's probable unannounced, the one
        # named arm used to slide into the away slot and become SF's.
        sf_sd = next(g for g in self.games if g.game_id == "SF@SD")
        self.assertIsNone(sf_sd.away_pitcher)
        self.assertIsNotNone(sf_sd.home_pitcher)
        self.assertEqual(sf_sd.home_pitcher.display_name, "JP Sears")

    def test_both_probables_still_attach_when_both_are_named(self):
        pit_cin = next(g for g in self.games if g.game_id == "PIT@CIN")
        self.assertEqual(pit_cin.away_pitcher.display_name, "Yohan Ramírez")
        self.assertEqual(pit_cin.home_pitcher.display_name, "Rhett Lowder")

    def test_a_half_posted_game_raises_no_warning_at_all(self):
        self.assertEqual(self.warnings, [],
                         "a placeholder is the page working normally, not a "
                         "shape worth warning about")

    def test_the_venue_survives_a_plain_text_pitcher_line(self):
        venues = {g.game_id: g.venue for g in self.games}
        self.assertEqual(venues["PIT@CIN"], "Great American Ball Park")
        self.assertEqual(venues["SF@SD"], "Petco Park")

    def test_a_repeated_placeholder_does_not_open_a_third_block(self):
        text = self.text.replace("1. TBD", "1. TBD\n2. TBD", 1)
        games, _ = parse_paste(text)
        pit_cin = next(g for g in games if g.game_id == "PIT@CIN")
        self.assertEqual(len(pit_cin.home_lineup), 9)
        self.assertEqual(pit_cin.away_lineup, [])

    def test_a_missing_placeholder_refuses_instead_of_guessing(self):
        # If the page ever stops rendering '1. TBD', the count no longer matches
        # and the old code's guess is what put the nine on the wrong team. The
        # rule is now 0 or exactly 2, the same rule the headers already had.
        text = self.text.replace("\n1. TBD\n", "\n", 1)
        games, warnings = parse_paste(text)
        pit_cin = next(g for g in games if g.game_id == "PIT@CIN")
        self.assertEqual(pit_cin.away_lineup, [])
        self.assertEqual(pit_cin.home_lineup, [])
        self.assertTrue(any("no lineup is attached to either side" in w
                            for w in warnings), warnings)

    def test_one_pitcher_line_for_two_headers_refuses(self):
        text = self.text.replace("TBD\nJP Sears", "JP Sears", 1)
        games, warnings = parse_paste(text)
        sf_sd = next(g for g in games if g.game_id == "SF@SD")
        self.assertIsNone(sf_sd.away_pitcher, "an unpaired arm must not be "
                                              "assumed to be the away side")
        self.assertIsNone(sf_sd.home_pitcher)
        self.assertTrue(any("neither is attached" in w for w in warnings), warnings)

    def test_end_to_end_the_confirmed_team_is_the_one_that_posted(self):
        report = resolve_paste_to_feed(self.text, str(SALARY_0730))
        feed = report["feed"]
        self.assertEqual(sorted(report["report"]["confirmed_teams"]), ["CIN", "SD"])
        self.assertEqual(_side(feed, "PIT@CIN", "home")["lineup_status"], "confirmed")
        self.assertEqual(_side(feed, "PIT@CIN", "away")["lineup_status"], "tbd")
        self.assertEqual(_side(feed, "PIT@CIN", "home")["lineup"][0]["name"],
                         "Elly De La Cruz")

    def test_the_real_slate_paste_stops_misreporting_its_single_block(self):
        # BOS@ATH on the real 1910_6g paste: BOS posted, ATH rendered '1. TBD'.
        # It was right pre-fix only because the posted side happened to be the
        # away one, and it carried a warning that has no reason to exist.
        games, warnings = parse_paste(PLAINTEXT.read_text(encoding="utf-8"))
        bos_ath = next(g for g in games if g.game_id == "BOS@ATH")
        self.assertEqual(len(bos_ath.away_lineup), 9)
        self.assertEqual(bos_ath.home_lineup, [])
        self.assertFalse([w for w in warnings if "only one lineup block" in w])


class LinkFreePitcherResolutionTests(unittest.TestCase):
    """R32 round 2, the P1: a plain-text paste must resolve its probables.

    The fixture is Ben's real 2026-07-30 paste, which arrived with zero markdown
    links. The pitcher path required the MLBAM id that only a link carries, so
    this exact file resolved every hitter and no pitcher at all, and the build
    took five hard pool blockers for starters the paste plainly named.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = PLAINTEXT.read_text(encoding="utf-8")
        cls.result = resolve_paste_to_feed(cls.text, str(SALARY_0730))
        cls.feed, cls.report = cls.result["feed"], cls.result["report"]

    def test_the_fixture_really_is_link_free(self):
        self.assertNotIn("](http", self.text,
                         "this fixture exists to prove the id is not required")

    def test_every_side_on_the_slate_gets_a_probable(self):
        missing = [f"{g['away']['team_abbrev']}@{g['home']['team_abbrev']} {side}"
                   for g in self.feed["games"] for side in ("away", "home")
                   if not (g[side].get("probable_pitcher") or {}).get("name")]
        self.assertEqual(missing, [], "these are the five pool blockers the "
                                      "1910_6g build took")

    def test_a_pasted_pitcher_resolves_to_the_dk_canonical_name(self):
        self.assertEqual(_side(self.feed, "BOS@ATH", "away")["probable_pitcher"]["name"],
                         "Sonny Gray")

    def test_a_pasted_pitcher_keeps_its_handedness(self):
        sears = _side(self.feed, "SF@SD", "home")["probable_pitcher"]
        self.assertEqual(sears["hand"], "L")
        self.assertEqual(sears["source"], "operator_paste")

    def test_the_venue_is_not_swallowed_as_a_pitcher_name(self):
        venues = {g.game_id: g.venue for g in parse_paste(self.text)[0]}
        self.assertEqual(venues["BOS@ATH"], "Sutter Health Park")
        self.assertEqual(venues["PIT@CIN"], "Great American Ball Park")

    def test_the_linked_paste_still_resolves_its_pitchers(self):
        # The regression guard: the id path must survive the name path landing.
        result = resolve_paste_to_feed(
            PASTE.read_text(encoding="utf-8"), str(SALARY),
            resolve_overrides={"W Wilson": "Weston Wilson"})
        hou = _side(result["feed"], "HOU@LAA", "away")["probable_pitcher"]
        self.assertEqual(hou["name"], "Hayden Wesneski")
        self.assertEqual(hou["id"], "669713", "the MLBAM id still comes off the link")


class DkStartingColumnTests(unittest.TestCase):
    """R32 round 2: DK's Starting column is a probable source, not a patch.

    On 2026-07-30 DK declared Robbie Ray for SF while mlb.com and the StatsAPI
    both still showed SF as TBD. The CSV was ahead of both feeds, and CLAUDE.md
    already makes it authoritative.
    """

    @classmethod
    def setUpClass(cls):
        cls.result = resolve_paste_to_feed(
            PLAINTEXT.read_text(encoding="utf-8"), str(SALARY_0730))

    def test_dk_fills_a_side_the_paste_left_unnamed(self):
        sf = _side(self.result["feed"], "SF@SD", "away")["probable_pitcher"]
        self.assertEqual(sf["name"], "Robbie Ray")
        self.assertEqual(sf["source"], "dk_starting_column")

    def test_the_fill_is_reported_rather_than_silent(self):
        rows = self.result["report"]["dk_declared_probables"]
        self.assertEqual([(r["team"], r["name"]) for r in rows],
                         [("SF", "Robbie Ray")])

    def test_a_dk_derived_probable_states_no_handedness(self):
        # The salary file has none. An invented hand would feed the platoon view
        # a fact nobody stated; extract_opp_throws_from_lineups skips a blank.
        sf = _side(self.result["feed"], "SF@SD", "away")["probable_pitcher"]
        self.assertEqual(sf["hand"], "")

    def test_the_paste_wins_and_the_disagreement_is_reported(self):
        text = PLAINTEXT.read_text(encoding="utf-8").replace(
            "Sonny Gray", "Garrett Crochet", 1)
        report = resolve_paste_to_feed(text, str(SALARY_0730))
        bos = _side(report["feed"], "BOS@ATH", "away")["probable_pitcher"]
        self.assertEqual(bos["name"], "Garrett Crochet")
        self.assertEqual(bos["source"], "operator_paste")
        self.assertTrue(any("the paste is the primary source per R32" in w
                            for w in report["report"]["warnings"]),
                        report["report"]["warnings"])


class AbsentFromDkPoolPolicyTests(unittest.TestCase):
    """R32 round 2, the P2: one absent name is a call-up, eighteen is a mistake.

    The code shipped absent-from-DK as reported-not-fatal and the docs said an
    unresolvable name blocks with no feed written. Both are defensible per name;
    neither survives 18 of them, which is one wrong-pairing signal.
    """

    def _misfiled(self):
        """The real CIN nine attributed to PIT: what the P0 bug produced."""
        raw = HOME_ONLY.read_text(encoding="utf-8")
        return raw.replace("CIN Lineup\n\n1. TBD\n\n1. E De La Cruz",
                           "CIN Lineup\n\n1. E De La Cruz").replace(
            "9. M McLain (R) 2B", "9. M McLain (R) 2B\n\n1. TBD")

    def test_one_absent_name_is_reported_and_ships(self):
        text = PLAINTEXT.read_text(encoding="utf-8").replace(
            "2. C Rafaela (R) CF", "2. Q Nonesuch (R) CF", 1)
        report = resolve_paste_to_feed(text, str(SALARY_0730))["report"]
        self.assertEqual(report["blockers"], [],
                         "DK owns eligibility; one name it never listed is not "
                         "a reason to refuse the whole paste")
        self.assertEqual(
            [r["pasted_name"] for r in report["unrostered_starters"]],
            ["Q Nonesuch"])

    def test_a_side_past_half_absent_blocks(self):
        report = resolve_paste_to_feed(self._misfiled(), str(SALARY_0730))["report"]
        self.assertTrue(any("PIT: 9 of 9 pasted starters" in b
                            for b in report["blockers"]), report["blockers"])

    def test_the_slate_threshold_blocks_on_its_own_terms(self):
        report = resolve_paste_to_feed(self._misfiled(), str(SALARY_0730))["report"]
        self.assertTrue(report["unrostered_policy"]["slate_threshold_tripped"])
        self.assertTrue(any("across the whole paste" in b
                            for b in report["blockers"]), report["blockers"])

    def test_the_policy_and_its_thresholds_are_in_the_report(self):
        report = resolve_paste_to_feed(
            PLAINTEXT.read_text(encoding="utf-8"), str(SALARY_0730))["report"]
        policy = report["unrostered_policy"]
        self.assertEqual(policy["hitters_absent_from_dk"], 0)
        self.assertEqual(policy["side_ratio"], 0.5)
        self.assertEqual(policy["slate_floor"], 6)
        self.assertFalse(policy["slate_threshold_tripped"])

    def test_the_tool_writes_no_feed_when_a_threshold_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            paste = Path(tmp) / "misfiled.txt"
            paste.write_text(self._misfiled(), encoding="utf-8")
            out = Path(tmp) / "feed.json"
            result = subprocess.run(
                [sys.executable, str(REPO / "tools" / "lineups_from_paste.py"),
                 "--salary", str(SALARY_0730), "--paste", str(paste),
                 "--out", str(out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(out.exists(), "a blocker never writes the feed")
            self.assertIn("BLOCKER", result.stderr)

    def test_a_clean_paste_still_writes_its_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "feed.json"
            result = subprocess.run(
                [sys.executable, str(REPO / "tools" / "lineups_from_paste.py"),
                 "--salary", str(SALARY_0730), "--paste", str(PLAINTEXT),
                 "--out", str(out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(out.exists())
            self.assertIn("DK STARTING  SF: Robbie Ray", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
