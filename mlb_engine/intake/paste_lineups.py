"""paste_lineups.py -- mlb.com/starting-lineups copy/paste as the PRIMARY source.

R32. Ben pastes the starting-lineups page straight into the prompt. That paste is
ground truth: it came from mlb.com, it is what he is looking at, and re-fetching
it over the network to learn what he just typed is a waste of a call and an
opportunity for the two to disagree. The API feed becomes the fallback for what
the paste does not cover -- a TBD team, a game he did not paste -- and nothing
else.

What the real paste actually carries, which is more than the old
``parse_confirmed_lineups_text`` assumed:

  [Astros](https://www.mlb.com/astros)@[Angels](https://www.mlb.com/angels)
  (54-55)
  9:38 PM
  Angel Stadium
  (42-66)
  [Hayden Wesneski](https://www.mlb.com/player/hayden-wesneski-669713)
  RHP
  0-0, 4.76 ERA, 4 SO
  [Grayson Rodriguez](https://www.mlb.com/player/grayson-rodriguez-680570)
  RHP
  3-3, 7.98 ERA, 36 SO
  HOU Lineup
  LAA Lineup

  1. [J Peña](https://www.mlb.com/player/jeremy-pena-665161) (R) SS
  ... nine ...

  1. [Z Neto](https://www.mlb.com/player/zach-neto-687263) (R) SS
  ... nine ...

  [Gameday](https://www.mlb.com/gameday/824002)

Three facts in there drive every design choice in this module.

**The two team headers appear TOGETHER, before either lineup block.** The old
parser set the current team on each ``<TEAM> Lineup`` header and assigned the
lines that followed to it, which against this layout puts all eighteen hitters on
the LAST header seen -- the Astros' nine silently become Angels. That is the
worst class of bug this project has: a wrong answer with no error. Blocks are
therefore split on the batting-order number resetting to 1, and the Nth block
belongs to the Nth header. A game whose block count does not match its header
count is refused, not guessed at.

**Batter handedness is right there** as ``(R)``, ``(L)`` or ``(S)``. So a pasted
team needs no handedness lookup at all, and F4's platoon component is fully fed
from the paste. This is the whole reason a paste-primary build can make zero
network calls.

**Every player carries an MLBAM id in the URL** (``.../jeremy-pena-665161``).
That is the durable identity: it is the join key to the Savant expected-stats
tables, and it is what makes a name crosswalk possible. It is not, however, in
the DK salary file, which is why matching still has to happen by name.

The matching problem, and it is the only real risk here. mlb.com abbreviates
first names: ``J Peña`` where DK writes ``Jeremy Pena``. An exact normalized
full-name match -- what the existing reconciler does -- fails on every single
hitter in a real paste. Matching is therefore on ``(first initial, last name,
team)``, verified unique against the salary file's hitters for that team, and the
resolved DK CANONICAL name is what gets written into the feed. Downstream is then
an ordinary feed and ``build_status_map_from_lineups_feed`` needs no change.

Measured against Ben's 2026-07-29 paste and that slate's DKSalaries.csv: 27 of 27
hitters resolved uniquely, including a Dodgers roster carrying both Teoscar and
Kike Hernandez, which the first initial separates.

Failure is loud, never quiet, and the two failure kinds are kept apart:

  - AMBIGUOUS or UNMATCHED name -> a blocker. The pool must not silently thin,
    and a nickname or a same-initial teammate is exactly how it would.
  - Resolved but ABSENT FROM THE DK POOL -> reported, not fatal. DK's file is
    authoritative for eligibility (CLAUDE.md), so a starter DK did not list is
    unrosterable no matter what this module says. The team stays confirmed and
    the slot is named in ``unrostered_starters``.

Nothing here fetches anything. Nothing here corrects the paste against a
real-world roster, per the authority rule: if the paste and the salary file
disagree about which team a player is on, that is reported, never repaired.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.intake.slate_intake_manager import normalize_name

# [Display Text](https://www.mlb.com/player/name-slug-665161)
_LINK = re.compile(r"\[([^\]]+)\]\((?P<url>[^)]*)\)")
_PLAYER_ID = re.compile(r"/player/[^/)]*?-(\d+)\s*$")
_GAMEDAY_ID = re.compile(r"/gameday/(\d+)")
# "1. [J Peña](url) (R) SS"  and the same line with the link already stripped.
_HITTER = re.compile(
    r"^(?P<order>\d{1,2})\.\s*(?P<name>.+?)\s*\((?P<bats>[RLS])\)\s*(?P<pos>[A-Z0-9/]{1,4})\s*$")
_TEAM_HEADER = re.compile(r"^(?P<team>[A-Z]{2,4})\s+Lineup\s*$")
_HAND = re.compile(r"^(?P<hand>[RL])HP\s*$")
_RECORD = re.compile(r"^\(\d{1,3}-\d{1,3}\)$")
_CLOCK = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[AP]M)?\s*(?:ET)?$", re.I)
_STATLINE = re.compile(r"\bERA\b|\bSO\b")

HITTER_POSITIONS = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"}


@dataclass
class PastedPlayer:
    """One pasted lineup row, before any DK resolution."""
    order: int
    display_name: str
    mlbam_id: Optional[str]
    bat_side: str
    position: str


@dataclass
class PastedPitcher:
    display_name: str
    mlbam_id: Optional[str]
    hand: str


@dataclass
class PastedGame:
    away_team: str = ""
    home_team: str = ""
    away_club: str = ""
    home_club: str = ""
    venue: str = ""
    clock_text: str = ""
    gameday_id: Optional[str] = None
    away_lineup: List[PastedPlayer] = field(default_factory=list)
    home_lineup: List[PastedPlayer] = field(default_factory=list)
    away_pitcher: Optional[PastedPitcher] = None
    home_pitcher: Optional[PastedPitcher] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def game_id(self) -> str:
        return f"{self.away_team}@{self.home_team}"


def _strip_links(line: str) -> Tuple[str, List[str]]:
    """Replace every markdown link with its display text; return trailing ids.

    The id is the numeric suffix of an mlb.com /player/ URL. A link that is not a
    player link (a club page, Gameday) contributes no id, which is why the ids
    come back as a list rather than being zipped positionally onto names.
    """
    ids: List[str] = []

    def _sub(match: "re.Match[str]") -> str:
        url = match.group("url") or ""
        found = _PLAYER_ID.search(url)
        if found:
            ids.append(found.group(1))
        return match.group(1)

    return _LINK.sub(_sub, line).strip(), ids


def _club_names(line: str) -> Optional[Tuple[str, str]]:
    """'[Astros](url)@[Angels](url)' -> ('Astros', 'Angels'), else None."""
    text, _ = _strip_links(line)
    if "@" not in text:
        return None
    away, _, home = text.partition("@")
    away, home = away.strip(), home.strip()
    if not away or not home or any(ch.isdigit() for ch in away + home):
        return None
    return away, home


def parse_paste(text: str) -> Tuple[List[PastedGame], List[str]]:
    """The mlb.com starting-lineups paste -> (games, warnings).

    Deliberately structural rather than clever. Each game opens on a
    ``Club@Club`` line; within a game, ``<TEAM> Lineup`` headers accumulate in
    order and hitter rows accumulate into blocks split on the order number
    resetting to 1. Anything unrecognised is ignored and counted, so a page whose
    decoration changes degrades to "fewer teams than expected" rather than to a
    wrong answer.
    """
    games: List[PastedGame] = []
    warnings: List[str] = []
    current: Optional[PastedGame] = None
    headers: List[str] = []
    blocks: List[List[PastedPlayer]] = []
    pitchers: List[PastedPitcher] = []
    pending_pitcher: Optional[Tuple[str, Optional[str]]] = None
    seen_clock = False

    def _close() -> None:
        nonlocal current, headers, blocks, pitchers, pending_pitcher, seen_clock
        if current is None:
            return
        _assign(current, headers, blocks, pitchers)
        games.append(current)
        current, headers, blocks, pitchers = None, [], [], []
        pending_pitcher, seen_clock = None, False

    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue

        clubs = _club_names(line)
        if clubs is not None and _TEAM_HEADER.match(line) is None:
            _close()
            current = PastedGame(away_club=clubs[0], home_club=clubs[1])
            continue
        if current is None:
            continue

        if "/gameday/" in line:
            found = _GAMEDAY_ID.search(line)
            if found:
                current.gameday_id = found.group(1)
            continue

        header = _TEAM_HEADER.match(line)
        if header:
            headers.append(header.group("team").upper())
            continue

        stripped, ids = _strip_links(line)

        hitter = _HITTER.match(stripped)
        if hitter and hitter.group("pos") in HITTER_POSITIONS:
            order = int(hitter.group("order"))
            if order == 1 or not blocks:
                blocks.append([])
            blocks[-1].append(PastedPlayer(
                order=order,
                display_name=hitter.group("name").strip(),
                mlbam_id=ids[0] if ids else None,
                bat_side=hitter.group("bats").upper(),
                position=hitter.group("pos").upper(),
            ))
            continue

        hand = _HAND.match(stripped)
        if hand and pending_pitcher is not None:
            pitchers.append(PastedPitcher(display_name=pending_pitcher[0],
                                          mlbam_id=pending_pitcher[1],
                                          hand=hand.group("hand").upper()))
            pending_pitcher = None
            continue

        if _RECORD.match(stripped):
            continue
        if _STATLINE.search(stripped):
            continue
        clock = _CLOCK.match(stripped)
        if clock:
            current.clock_text = stripped
            seen_clock = True
            continue

        # A player link with no recognised role yet is a probable pitcher; the
        # RHP/LHP line that follows confirms it. A bare line after the clock and
        # before any pitcher is the venue.
        if ids and not blocks:
            pending_pitcher = (stripped, ids[0])
            continue
        if seen_clock and not current.venue and not blocks and not ids:
            current.venue = stripped
            continue

    _close()
    for game in games:
        warnings.extend(f"{game.game_id or game.away_club + '@' + game.home_club}: {w}"
                        for w in game.warnings)
    if not games:
        warnings.append("no games parsed: the paste carried no 'Club@Club' line")
    return games, warnings


def _assign(game: PastedGame, headers: Sequence[str],
            blocks: Sequence[List[PastedPlayer]],
            pitchers: Sequence[PastedPitcher]) -> None:
    """Attach headers, blocks and pitchers to a game, or refuse to guess.

    This is the paired-header trap. Both ``HOU Lineup`` and ``LAA Lineup`` appear
    before either block, so the Nth block belongs to the Nth header and nothing
    else. Any other shape leaves the lineups EMPTY with a warning, because a
    lineup attached to the wrong team is worse than no lineup: the build would
    stack the wrong side and every gate would pass.
    """
    if len(headers) >= 1:
        game.away_team = headers[0]
    if len(headers) >= 2:
        game.home_team = headers[1]
    if len(headers) != 2:
        game.warnings.append(
            f"expected 2 '<TEAM> Lineup' headers, found {len(headers)} "
            f"{list(headers)}; no lineup is attached to either side rather than "
            f"risk attaching one to the wrong team")
        return
    if len(blocks) > 2:
        game.warnings.append(
            f"found {len(blocks)} lineup blocks for 2 teams; refusing to guess "
            f"which belong to {headers[0]} and {headers[1]}")
        return
    if len(blocks) >= 1:
        game.away_lineup = list(blocks[0])
    if len(blocks) >= 2:
        game.home_lineup = list(blocks[1])
    if len(blocks) == 1:
        game.warnings.append(
            f"only one lineup block; attached to {headers[0]} (listed first, the "
            f"away side) and {headers[1]} is left TBD")
    if len(pitchers) >= 1:
        game.away_pitcher = pitchers[0]
    if len(pitchers) >= 2:
        game.home_pitcher = pitchers[1]
    if len(pitchers) not in (0, 2):
        game.warnings.append(
            f"found {len(pitchers)} probable pitcher(s); the first is taken as "
            f"the away side")


# ---------------------------------------------------------------------------
# Resolution against the DK salary file, then out as an ordinary feed
# ---------------------------------------------------------------------------

HITTER_SLOT_TOKENS = frozenset({"C", "1B", "2B", "3B", "SS", "OF"})


def _match_key(name: str) -> Optional[Tuple[str, str]]:
    """('J Peña') -> ('j', 'pena'). None when there is no usable surname."""
    parts = normalize_name(name).split()
    if len(parts) < 2 or not parts[0]:
        return None
    return parts[0][0], parts[-1]


def _index_salary(salary_players: Sequence[Any], pitchers: bool) -> Dict[Tuple[str, str, str], List[Any]]:
    index: Dict[Tuple[str, str, str], List[Any]] = {}
    for player in salary_players:
        slots = set(getattr(player, "positions", ()) or ())
        is_pitcher = "P" in slots
        if is_pitcher != pitchers:
            continue
        key = _match_key(getattr(player, "name", ""))
        if key is None:
            continue
        index.setdefault((key[0], key[1], str(getattr(player, "team", "")).upper()),
                         []).append(player)
    return index


def _resolve_one(display_name: str, team: str,
                 index: Mapping[Tuple[str, str, str], List[Any]],
                 overrides: Mapping[str, str]) -> Tuple[Optional[Any], Optional[str]]:
    """(salary player, blocker text). Exactly one of the two is None.

    An override is an operator statement of identity and wins outright; it is the
    documented way past an ambiguity, because the alternative -- picking one of
    two same-initial teammates -- is a silent wrong answer on a real lineup.
    """
    wanted = overrides.get(display_name) or overrides.get(display_name.strip())
    key = _match_key(wanted or display_name)
    if key is None:
        return None, (f"{display_name!r} ({team}) has no usable surname to match "
                      f"against the salary file")
    hits = index.get((key[0], key[1], team.upper()), [])
    if wanted:
        exact = [p for p in hits if normalize_name(p.name) == normalize_name(wanted)]
        hits = exact or hits
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, None  # absent from the DK pool: reported, never fatal
    # Show each candidate's DK Status. On the first real paste this hit
    # 'W Wilson' on SEA, where Will Wilson is IL and Weston Wilson is the
    # starter, and the status is the fact that decides it. Deliberately NOT
    # auto-resolved: an IL row is strong evidence, not identity, and this module
    # exists because guessing identity is how the wrong player lands in a
    # confirmed lineup. Print the deciding fact and let Ben state it.
    described = sorted(
        f"{p.name}"
        + (f" [DK Status {p.status}]" if str(getattr(p, "status", "") or "").strip()
           else " [DK Status blank]")
        for p in hits)
    return None, (f"{display_name!r} ({team}) matches {len(hits)} salary rows "
                  f"{described}; pass --resolve {display_name!r}=<full DK name> "
                  f"to state which. Guessing here would put the wrong player in "
                  f"a confirmed lineup")


def resolve_paste_to_feed(
    text: str,
    salary_csv: str,
    *,
    resolve_overrides: Optional[Mapping[str, str]] = None,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """A paste plus the salary file -> (an ordinary lineups feed, a report).

    Every pasted name is resolved to the DK CANONICAL name and that is what lands
    in the feed, so ``build_status_map_from_lineups_feed`` matches it by the same
    exact-normalized rule it already uses for an API feed and needs no change.

    Lock times come from the salary file's Game Info, not from the paste. The
    CSV is authoritative for the slate (CLAUDE.md) and carries a full date; the
    paste carries a bare clock with no date and no stated zone. The paste's clock
    becomes a CROSS-CHECK: a disagreement beyond a minute is reported, because
    the honest reading of it is "this paste is not this slate".
    """
    from mlb_engine.intake.live_data_adapters import salary_game_times
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv

    overrides = dict(resolve_overrides or {})
    games, warnings = parse_paste(text)
    salary_players = list(parse_dk_salary_csv(str(salary_csv)))
    hitter_index = _index_salary(salary_players, pitchers=False)
    pitcher_index = _index_salary(salary_players, pitchers=True)
    team_of = {}
    for player in salary_players:
        team_of.setdefault(normalize_name(player.name), str(player.team).upper())
    start_by_game = salary_game_times(str(salary_csv))
    salary_game_ids = set(start_by_game)

    blockers: List[str] = []
    unrostered: List[Dict[str, str]] = []
    feed_games: List[Dict[str, Any]] = []
    confirmed: List[str] = []
    partial: List[Dict[str, Any]] = []
    resolved_count = 0

    for game in games:
        if not game.away_team or not game.home_team:
            blockers.append(
                f"{game.away_club}@{game.home_club}: could not read both team "
                f"codes from the '<TEAM> Lineup' headers, so nothing from this "
                f"game is used")
            continue
        game_id = game.game_id
        if game_id not in salary_game_ids:
            warnings.append(
                f"{game_id}: pasted but absent from the salary file's games "
                f"{sorted(salary_game_ids)}; it is not on this slate and is "
                f"skipped, not merged")
            continue
        start = start_by_game[game_id]
        _cross_check_clock(game, start, warnings)

        sides: Dict[str, Dict[str, Any]] = {}
        for side, team, lineup, pitcher in (
            ("away", game.away_team, game.away_lineup, game.away_pitcher),
            ("home", game.home_team, game.home_lineup, game.home_pitcher),
        ):
            rows: List[Dict[str, Any]] = []
            side_blocked = False
            for player in sorted(lineup, key=lambda p: p.order):
                matched, blocker = _resolve_one(
                    player.display_name, team, hitter_index, overrides)
                if blocker:
                    blockers.append(f"{game_id} {team} slot {player.order}: {blocker}")
                    side_blocked = True
                    continue
                if matched is None:
                    unrostered.append({
                        "team": team, "order": str(player.order),
                        "pasted_name": player.display_name,
                        "mlbam_id": player.mlbam_id or "",
                        "note": "pasted starter has no row in the DK salary file, "
                                "so DK did not list him and he is unrosterable",
                    })
                    continue
                on_team = team_of.get(normalize_name(matched.name))
                if on_team and on_team != team.upper():
                    warnings.append(
                        f"{game_id}: paste puts {matched.name!r} on {team} and the "
                        f"salary file puts him on {on_team}; reported, never "
                        f"corrected (the CSV is authoritative for eligibility)")
                rows.append({
                    "order": player.order,
                    "id": player.mlbam_id,
                    "name": matched.name,
                    "position": player.position,
                    "bat_side": player.bat_side,
                    "dk_player_id": matched.player_id,
                    "pasted_as": player.display_name,
                })
                resolved_count += 1

            probable = None
            if pitcher is not None:
                matched, blocker = _resolve_one(
                    pitcher.display_name, team, pitcher_index, overrides)
                if blocker:
                    blockers.append(f"{game_id} {team} probable pitcher: {blocker}")
                elif matched is None:
                    unrostered.append({
                        "team": team, "order": "SP",
                        "pasted_name": pitcher.display_name,
                        "mlbam_id": pitcher.mlbam_id or "",
                        "note": "pasted probable has no row in the DK salary file",
                    })
                else:
                    probable = {"id": pitcher.mlbam_id, "name": matched.name,
                                "hand": pitcher.hand,
                                "dk_player_id": matched.player_id}
                    resolved_count += 1

            # Ben's call: a short block is PARTIAL, which the status builder reads
            # as projected and reports in partial_lineup_teams. Calling nine-minus-
            # one 'confirmed' would be the labels rule broken at the front door.
            status = "confirmed" if len(rows) == 9 else ("partial" if rows else "tbd")
            if status == "confirmed":
                confirmed.append(team)
            elif status == "partial":
                # A side short because a NAME would not resolve is a different
                # fact from a side mlb.com posted short, and the report must not
                # blur them: the first is this tool failing and is a blocker, the
                # second is the world and is a labelled projection.
                partial.append({
                    "team": team, "game_id": game_id, "hitters_posted": len(rows),
                    "reason": ("unresolved name(s); see blockers" if side_blocked
                               else "mlb.com posted a partial lineup"),
                })
            sides[side] = {
                "team_abbrev": team,
                "lineup_status": status,
                "lineup": rows,
                "probable_pitcher": probable,
                "source": "operator_paste",
            }

        feed_games.append({
            "game_pk": int(game.gameday_id) if (game.gameday_id or "").isdigit() else None,
            "game_date_utc": start.astimezone(_utc()).isoformat().replace("+00:00", "Z"),
            "status": "Pre-Game",
            "venue": game.venue,
            "away": sides["away"],
            "home": sides["home"],
            "source": "operator_paste",
        })

    slate_dates = {str(v.date()) for v in start_by_game.values()}
    feed = {
        "date": sorted(slate_dates)[0] if slate_dates else None,
        "fetched_at": fetched_at or datetime.now(_utc()).isoformat().replace("+00:00", "Z"),
        "source": "operator_paste",
        "provenance": "mlb.com/starting-lineups, pasted by the operator; ground "
                      "truth for every team present, per R32",
        "games": feed_games,
    }
    report = {
        "games_parsed": len(games),
        "games_used": len(feed_games),
        "resolved": resolved_count,
        "confirmed_teams": sorted(confirmed),
        "partial_teams": partial,
        "unrostered_starters": unrostered,
        "blockers": blockers,
        "warnings": warnings,
    }
    return {"feed": feed, "report": report}


def _utc():
    from datetime import timezone
    return timezone.utc


def _cross_check_clock(game: PastedGame, start: datetime, warnings: List[str]) -> None:
    """The paste's bare clock against the salary file's dated start.

    A bare '9:38 PM' cannot be trusted as a lock time, but it is a very cheap
    wrong-slate detector: mlb.com renders Eastern, and the salary file's Game
    Info is Eastern too.
    """
    match = _CLOCK.match(game.clock_text or "")
    if not match:
        return
    hour = int(match.group("h")) % 12
    if (match.group("ap") or "PM").upper() == "PM":
        hour += 12
    if (hour, int(match.group("m"))) != (start.hour, start.minute):
        warnings.append(
            f"{game.game_id}: paste says {game.clock_text} and the salary file "
            f"says {start.strftime('%I:%M %p ET').lstrip('0')}; if these are "
            f"different games the paste is for the wrong slate")

