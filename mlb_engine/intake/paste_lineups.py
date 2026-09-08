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

**An MLBAM id MAY ride in the URL** (``.../jeremy-pena-665161``), and where it
does it is the durable identity: the join key to the Savant expected-stats
tables. It is not in the DK salary file, which is why matching still has to
happen by name.

**R189(1), 2026-08-24: this used to read "EVERY player carries an MLBAM id",
and that is false for the pastes Ben actually makes.** Verified on the archived
``paste_1910_6g.txt``: all six games parse ``mlbam_id=None``, because a
plain-text browser copy keeps the link TEXT and drops the href. So the id is
optional here and downstream must not assume it. What that assumption cost is
R189(2), landed the same day: ``compute_f4_factors`` bucketed only probables
with no NAME, so a named-but-id-less probable scored a silent 1.0 and the F4
SP-quality term was dead on every plain-text-paste slate while the report read
``sp_quality_available: True``. It now joins by the Savant
``last_name, first_name`` key and names whatever it still cannot resolve.

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

Failure is loud, never quiet, and the failure kinds are kept apart:

  - AMBIGUOUS or UNMATCHED name -> a blocker. The pool must not silently thin,
    and a nickname or a same-initial teammate is exactly how it would.
  - Resolved but ABSENT FROM THE DK POOL, in ones -> reported, not fatal. DK's
    file is authoritative for eligibility (CLAUDE.md), so a starter DK did not
    list is unrosterable no matter what this module says, and the slot is named
    in ``unrostered_starters``.
    **R133 correction, 2026-08-18: this paragraph used to end "the team stays
    confirmed", and the code has never done that.** ``lineup_status`` is
    ``confirmed`` only at nine RESOLVED-AND-ROSTERED rows, so a side mlb.com
    posted complete with one starter DK did not list goes PARTIAL and routes
    through the TBD path. That is deliberate at the label layer -- see Ben's
    call below -- but the docstring said the opposite for three slates, and it
    is what told the 2026-08-12 reader not to look. Whether such a side SHOULD
    be confirmed is a selection question (it changes F2 stamping and whether a
    ninth is seeded at all); it sits with R133(2) and is Ben's or
    MLB_Classic.md's, not this module's.
  - Resolved but ABSENT FROM THE DK POOL, in bulk -> a blocker. R32 round 2.
    Eighteen of these arrived on one 2026-07-30 build and the feed was still
    written, because each was judged on its own. They are not eighteen facts.
    Past half of one posted side, or ``SLATE_ABSENT_BLOCK_RATIO`` of the whole
    paste with at least ``SLATE_ABSENT_BLOCK_FLOOR`` of them, the reading is one
    fact: the paste and the salary file are not the same slate. A genuine
    call-up stays non-fatal; a wrong pairing stops.

Nothing here fetches anything. Nothing here corrects the paste against a
real-world roster, per the authority rule: if the paste and the salary file
disagree about which team a player is on, that is reported, never repaired.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
# R117. The SAME fact with the statline appended on one line:
# "RHP 8-7, 3.87 ERA, 144 SO". mlb.com renders the hand alone on 2026-07-29's
# paste and with the record trailing it on 2026-08-13's, and only the first
# shape was ever matched, so every probable on three slates fell through to the
# `_STATLINE` branch and was consumed as decoration. Deliberately NOT
# `[RL]HP\b.*`: the rest has to look like a pitcher's line (a W-L record, or an
# ERA/SO statline) or this stops being structural and starts guessing that any
# line opening with those three letters names a hand.
_HAND_STATLINE = re.compile(
    r"^(?P<hand>[RL])HP[\s,]+(?P<stats>\d{1,3}-\d{1,3}\b.*|.*\b(?:ERA|SO)\b.*)$")
_RECORD = re.compile(r"^\(\d{1,3}-\d{1,3}\)$")
_CLOCK = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[AP]M)?\s*(?:ET)?$", re.I)
_STATLINE = re.compile(r"\bERA\b|\bSO\b")
# R32 round 2. "1. TBD" under a header, and a bare "TBD" where a probable's name
# would go, are POSITIVE information that the side is unposted. Both hold a slot.
_TBD_SLOT = re.compile(r"^(?P<order>\d{1,2})\.\s*TBD\.?\s*$", re.I)
_BARE_TBD = re.compile(r"^TBD\.?$", re.I)

# R133(1). A posted MLB side is nine batting slots. The module used the literal
# in one place and now needs it in three, and `tools/preflight_upload.py` holds
# its own copy under the same name -- a mirror, not a merge, for the reason
# `_HAND` is here rather than shared: this module carries a pinned zero-network
# contract and must not import a tool to reach a number. Kept in sync by test.
POSTED_LINEUP_SLOTS = 9

HITTER_POSITIONS = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"}

# Resolved-but-absent-from-DK is non-fatal per name and fatal in bulk; see
# ``resolve_paste_to_feed``. Past half of one posted side, or a quarter of the
# whole paste, the honest reading is one wrong-pairing fact rather than N
# independent call-ups.
SIDE_ABSENT_BLOCK_RATIO = 0.5
SLATE_ABSENT_BLOCK_RATIO = 0.25
SLATE_ABSENT_BLOCK_FLOOR = 6


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


def _match_hand(text: str) -> Optional[str]:
    """'RHP' or 'RHP 8-7, 3.87 ERA, 144 SO' -> 'R'; anything else -> None.

    R117. Two renders of one fact. Keeping them as two named patterns rather
    than one loose one is the point: the bare form is exact, and the statline
    form has to carry a W-L record or an ERA/SO line, so a stray line beginning
    'LHP' cannot silently become a handedness claim.
    """
    for pattern in (_HAND, _HAND_STATLINE):
        found = pattern.match(text)
        if found:
            return found.group("hand").upper()
    return None


def _looks_like_name(text: str) -> bool:
    """A bare line that could be a venue or a person's name, not decoration."""
    if not text or len(text) > 60:
        return False
    if text.endswith(":"):
        return False
    return any(ch.isalpha() for ch in text)


def parse_paste(text: str) -> Tuple[List[PastedGame], List[str]]:
    """The mlb.com starting-lineups paste -> (games, warnings).

    Deliberately structural rather than clever. Each game opens on a
    ``Club@Club`` line; within a game, ``<TEAM> Lineup`` headers accumulate in
    order and hitter rows accumulate into blocks split on the order number
    resetting to 1. Anything unrecognised is ignored and counted, so a page whose
    decoration changes degrades to "fewer teams than expected" rather than to a
    wrong answer.

    R32 round 2 changed two things, both the same idea. A placeholder is
    POSITIONAL INFORMATION and has to occupy its slot:

    - ``1. TBD`` under a header opens an EMPTY block, so a game with one posted
      side yields two blocks and positional assignment works as designed. It
      previously matched nothing, so the posted nine became ``block[0]`` and was
      handed to ``headers[0]``, the away team. See ``_assign``.
    - A bare ``TBD`` where a probable's name would go appends ``None`` to the
      pitcher list. The same shift otherwise moved the one announced starter into
      the away slot, which is the away/home swap again, one field over.

    And the probable's name no longer has to arrive as a markdown link. A pasted
    line is held as ``pending_name`` and promoted to a pitcher by the ``RHP``/
    ``LHP`` line that follows it; the venue is whatever bare line was displaced
    without ever being promoted. Requiring the link meant a plain-text paste
    resolved every hitter and zero pitchers, because the id lives only in the URL.

    R117. The hand line has TWO renders and only the bare one was matched. The
    2026-07-29 paste put ``RHP`` alone on its line with ``0-0, 4.76 ERA, 4 SO``
    below it; the 2026-08-13 paste put both on one line as
    ``RHP 8-7, 3.87 ERA, 144 SO``. ``_HAND`` anchored on ``$``, so the second
    shape fell past it into the ``_STATLINE`` branch and was consumed as
    decoration -- every probable dropped, on three slates in two days, with no
    warning anywhere. ``_match_hand`` now reads both. The two ways that silence
    was expensive are recorded on the failure branch below and in
    ``_assign``: a held name became the VENUE, and a pitcher count of zero is
    the same shape as "no pitcher lines were pasted", which ``_assign`` does not
    warn about by design.
    """
    games: List[PastedGame] = []
    warnings: List[str] = []
    current: Optional[PastedGame] = None
    headers: List[str] = []
    blocks: List[List[PastedPlayer]] = []
    # A None entry is an unannounced side holding its position in the ordering.
    pitchers: List[Optional[PastedPitcher]] = []
    pending_name: Optional[Tuple[str, Optional[str]]] = None
    seen_clock = False

    def _flush_pending() -> None:
        """The held line was never promoted to a pitcher, so it was the venue."""
        nonlocal pending_name
        if pending_name is None:
            return
        if current is not None and seen_clock and not current.venue:
            current.venue = pending_name[0]
        pending_name = None

    def _close() -> None:
        nonlocal current, headers, blocks, pitchers, seen_clock
        if current is None:
            return
        _flush_pending()
        _assign(current, headers, blocks, pitchers)
        games.append(current)
        current, headers, blocks, pitchers = None, [], [], []
        seen_clock = False

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
            _flush_pending()
            headers.append(header.group("team").upper())
            continue

        stripped, ids = _strip_links(line)

        hitter = _HITTER.match(stripped)
        if hitter and hitter.group("pos") in HITTER_POSITIONS:
            _flush_pending()
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

        # "1. TBD": the side is unposted and SAYS SO. One empty block per side,
        # so a second placeholder row ("2. TBD") is absorbed rather than opening
        # another block.
        slot_tbd = _TBD_SLOT.match(stripped)
        if slot_tbd:
            _flush_pending()
            if int(slot_tbd.group("order")) == 1 or not blocks:
                blocks.append([])
            continue

        hand = _match_hand(stripped)
        if hand and pending_name is not None:
            pitchers.append(PastedPitcher(display_name=pending_name[0],
                                          mlbam_id=pending_name[1],
                                          hand=hand))
            pending_name = None
            continue

        if _RECORD.match(stripped):
            continue
        if _STATLINE.search(stripped):
            # R117. A statline arriving while a NAME is still held means the line
            # that should have promoted that name to a pitcher was a shape this
            # parser does not know. Say so and DROP the name: letting it fall
            # through to `_flush_pending` wrote a pitcher's name into
            # `game.venue` (measured: a paste with no venue line came back
            # venue='Hayden Wesneski') and left the pitcher count at 0, which
            # `_assign` reads as "nothing was pasted" and does not warn about.
            # A named parse failure is the floor here; a wrong venue plus a
            # dead F4 is what the silence cost three times.
            if pending_name is not None and current is not None:
                current.warnings.append(
                    f"held {pending_name[0]!r} as a probable's name and the next "
                    f"line was a statline ({stripped!r}) rather than a "
                    f"'RHP'/'LHP' hand line, so no hand could be read and the "
                    f"name is dropped rather than mistaken for the venue")
                pending_name = None
            continue
        clock = _CLOCK.match(stripped)
        if clock:
            current.clock_text = stripped
            seen_clock = True
            continue

        # A bare TBD in the probable's place: no name, but the slot is real.
        if _BARE_TBD.match(stripped) and seen_clock and not blocks:
            _flush_pending()
            pitchers.append(None)
            continue

        # Otherwise hold the line. The RHP/LHP line that may follow promotes it
        # to a probable pitcher; anything else displaces it into the venue.
        if seen_clock and not blocks and _looks_like_name(stripped):
            _flush_pending()
            pending_name = (stripped, ids[0] if ids else None)
            continue

    _close()
    for game in games:
        warnings.extend(f"{game.game_id or game.away_club + '@' + game.home_club}: {w}"
                        for w in game.warnings)
    if not games:
        warnings.append("no games parsed: the paste carried no 'Club@Club' line")
    return games, warnings


def _dk_team(code: str, club: str, warnings: List[str]) -> str:
    """A paste's team code as DK spells it, cross-checked against the club name.

    R33. The paste's ``<TEAM> Lineup`` header was previously used verbatim as the
    DK abbreviation. ``DK_ABBREV_REMAP`` exists precisely because the two
    vocabularies disagree on seven clubs -- AZ/ARI, WSN/WSH, TBR/TB, CHW/CWS,
    KCR/KC, SDP/SD, SFG/SF -- so a paste rendering any of those produced a
    ``game_id`` that matched nothing in the salary file, and the game was
    SKIPPED with a warning. On a Classic slate that silently drops a whole game
    from the pool and the build proceeds without it. The first real paste
    happened to contain none of the seven, which is exactly why the tests passed.

    The club name is the second, independent read of the same fact ('Astros' ->
    HOU), so a header typo or an unrecognised code is caught rather than trusted.
    They are cross-checked and the CLUB name wins, because it is the unambiguous
    one: it comes from the team's own page link, not from a three-letter code
    whose vocabulary is the thing in question.
    """
    from mlb_engine.intake.live_data_adapters import (
        team_name_to_dk_abbrev, to_dk_abbrev,
    )

    from_code = to_dk_abbrev(code)
    from_club = team_name_to_dk_abbrev(club) if club else None
    if from_club and from_code and from_club != from_code:
        warnings.append(
            f"header says {code!r} (reads as {from_code}) but the club link says "
            f"{club!r} (reads as {from_club}); using {from_club} from the club "
            f"link, which is the unambiguous one")
        return from_club
    if from_club and not from_code:
        return from_club
    return from_code


def _assign(game: PastedGame, headers: Sequence[str],
            blocks: Sequence[List[PastedPlayer]],
            pitchers: Sequence[Optional[PastedPitcher]]) -> None:
    """Attach headers, blocks and pitchers to a game, or refuse to guess.

    This is the paired-header trap. Both ``HOU Lineup`` and ``LAA Lineup`` appear
    before either block, so the Nth block belongs to the Nth header and nothing
    else. Any other shape leaves the lineups EMPTY with a warning, because a
    lineup attached to the wrong team is worse than no lineup: the build would
    stack the wrong side and every gate would pass.

    R32 round 2. Positional assignment is only sound when the count matches, and
    a count of ONE used to be handled by guessing rather than refusing: the lone
    block went to ``headers[0]`` and the lone pitcher went to the away slot. On a
    game where only the HOME side had posted, that is the home nine attached to
    the away team, silently, with every gate green. It failed safe on the
    2026-07-30 slate only because none of the nine pasted CIN names matched a PIT
    salary row; two same-division teams sharing a surname would have resolved.

    So the rule is now the same for both sequences and it is the rule the module
    docstring always claimed: the count is 0 or exactly 2, or nothing is
    attached. ``1. TBD`` and a bare ``TBD`` are what make 2 the normal count for
    a half-posted game, and DK's ``Starting`` column backfills a refused
    probable, so refusing costs a warning rather than a build.
    """
    if len(headers) >= 1:
        game.away_team = _dk_team(headers[0], game.away_club, game.warnings)
    if len(headers) >= 2:
        game.home_team = _dk_team(headers[1], game.home_club, game.warnings)
    if len(headers) != 2:
        game.warnings.append(
            f"expected 2 '<TEAM> Lineup' headers, found {len(headers)} "
            f"{list(headers)}; no lineup is attached to either side rather than "
            f"risk attaching one to the wrong team")
        return

    if len(blocks) == 2:
        game.away_lineup = list(blocks[0])
        game.home_lineup = list(blocks[1])
    elif len(blocks) != 0:
        game.warnings.append(
            f"found {len(blocks)} lineup block(s) for the 2 headers "
            f"{headers[0]}/{headers[1]}; no lineup is attached to either side "
            f"rather than risk attaching one to the wrong team. An unposted side "
            f"normally renders '1. TBD', which counts as its own empty block")

    if len(pitchers) == 2:
        game.away_pitcher = pitchers[0]
        game.home_pitcher = pitchers[1]
    elif len(pitchers) != 0:
        game.warnings.append(
            f"found {len(pitchers)} probable pitcher line(s) for the 2 headers "
            f"{headers[0]}/{headers[1]}; neither is attached rather than risk "
            f"attaching one to the wrong side. An unannounced side normally "
            f"renders a bare 'TBD', which holds its slot")


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


def _dedupe_by_dk_identity(hits: Sequence[Any]) -> List[Any]:
    """Collapse salary rows that are the SAME PERSON into one candidate.

    R45. A DK Showdown salary file carries two rows per player -- CPT and UTIL,
    identical ``Name`` and ``TeamAbbrev``, different ``ID`` and ``Salary`` -- and
    ``_resolve_one``'s ambiguity check counted them as two candidates. Every
    hitter on a fully-confirmed, zero-ambiguity Showdown paste came back
    "matches 2 salary rows" and the tool refused the paste. Three live burns in
    six days (SD@ARI 2026-08-03, STL@NYY 2026-08-05 with 16 blockers, HOU@SD
    2026-08-09 with 18), each ending in a hand-built feed at ~T-18 with no
    provenance line.

    Identity is the EXACT normalized full name, not the (initial, surname) match
    key the index is bucketed by. That distinction is the whole safety property:
    two CPT/UTIL rows share a full name and collapse, while Will Wilson and
    Weston Wilson -- the real ambiguity this module exists for, hit on the first
    live paste -- do not, and still raise the blocker that makes Ben state which.

    The UTIL row wins where both exist: it is the base salary and the identity
    the operator's own live workaround filtered to. Ties break on player_id so
    the choice is deterministic.
    """
    groups: Dict[str, List[Any]] = {}
    for player in hits:
        groups.setdefault(normalize_name(str(getattr(player, "name", "") or "")),
                          []).append(player)
    out: List[Any] = []
    for _, group in sorted(groups.items()):
        if len(group) == 1:
            out.append(group[0])
            continue
        out.append(sorted(group, key=_dk_identity_rank)[0])
    return out


def _dk_identity_rank(player: Any) -> Tuple[int, float, str]:
    raw = getattr(player, "raw", None) or {}
    slot = str(raw.get("Roster Position") or "").strip().upper()
    return (0 if slot == "UTIL" else 1,
            float(getattr(player, "salary", 0.0) or 0.0),
            str(getattr(player, "player_id", "")))


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
    # R45. Before the count, not after: the ambiguity test asks "how many PEOPLE
    # match", and two roster-variant rows for one person are one person.
    hits = _dedupe_by_dk_identity(hits)
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


DK_STARTING_TOKENS = frozenset({"SP", "P"})


def _dk_declared_starters(salary_players: Sequence[Any]) -> Dict[str, List[Any]]:
    """team -> the arms DK flagged as starting in the salary file's ``Starting``.

    R32 round 2 promotes this to a first-class probable source rather than a
    thing to patch in by hand afterwards. On 2026-07-30 DK declared Robbie Ray as
    the SF starter while mlb.com and the StatsAPI both still showed SF as TBD, so
    the CSV was AHEAD of both feeds, and CLAUDE.md already makes it authoritative.
    A build that has the column and still raises "no probable or declared
    starter" is refusing to read a fact it was handed.

    R323, N+1 of the entry's enumeration. This counted salary ROWS, and on a
    Showdown export one declared arm owns two of them, so ``_apply_dk_starting``
    read ``len(declared) > 1``, warned that "DK's Starting column flags 2 AAA
    arms" naming the SAME man twice, and took no probable at all -- a refusal
    caused entirely by the reader, over a file stating the fact plainly. The
    collapse is the one in ``slate_intake_manager``, it no-ops on a Classic file,
    and it is idempotent.
    """
    from mlb_engine.intake.slate_intake_manager import collapse_showdown_roles
    salary_players, _collapse_report = collapse_showdown_roles(
        list(salary_players))
    out: Dict[str, List[Any]] = {}
    for player in salary_players:
        if "P" not in set(getattr(player, "positions", ()) or ()):
            continue
        if str(getattr(player, "starting", "") or "").strip().upper() not in DK_STARTING_TOKENS:
            continue
        out.setdefault(str(getattr(player, "team", "")).upper(), []).append(player)
    return out


def _apply_dk_starting(probable: Optional[Dict[str, Any]], team: str, game_id: str,
                       dk_starters: Mapping[str, List[Any]],
                       dk_probables: List[Dict[str, str]],
                       warnings: List[str]) -> Optional[Dict[str, Any]]:
    """Fill a missing probable from DK, or report a disagreement with the paste.

    The paste WINS when both name someone, per R32: the paste is the primary
    source and the salary file's authority in CLAUDE.md covers identity, salary,
    team and eligibility, not who is on the mound. A disagreement is therefore
    reported and never repaired, the same way a team disagreement already is.

    The DK-derived probable carries no handedness, because the salary file has
    none. ``extract_opp_throws_from_lineups`` skips a hand outside ('R','L'), so
    the platoon view for the opposing side falls back to its default rather than
    keying off a hand nobody stated.
    """
    declared = list(dk_starters.get(team.upper(), []))
    if probable is not None:
        if declared and normalize_name(str(probable.get("name") or "")) not in {
                normalize_name(row.name) for row in declared}:
            warnings.append(
                f"{game_id}: the paste names {probable.get('name')!r} as {team}'s "
                f"probable and DK's Starting column names "
                f"{sorted(row.name for row in declared)}; the paste is the primary "
                f"source per R32, so it wins and this is reported, never corrected")
        return probable
    if not declared:
        return None
    if len(declared) > 1:
        warnings.append(
            f"{game_id}: DK's Starting column flags {len(declared)} {team} arms "
            f"{sorted(row.name for row in declared)}; no probable is taken from it "
            f"rather than pick one")
        return None
    row = declared[0]
    dk_probables.append({"team": team, "game_id": game_id, "name": row.name})
    return {"id": None, "name": row.name, "hand": "",
            "dk_player_id": row.player_id, "source": "dk_starting_column"}


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
    dk_starters = _dk_declared_starters(salary_players)

    blockers: List[str] = []
    unrostered: List[Dict[str, str]] = []
    feed_games: List[Dict[str, Any]] = []
    # R58(a): resolved up front, because whether a matchup's legs are separable
    # is a property of the whole paste and cannot be decided one game at a time.
    leg_start_by_game = _leg_starts(games, start_by_game, blockers, warnings)
    confirmed: List[str] = []
    partial: List[Dict[str, Any]] = []
    dk_probables: List[Dict[str, str]] = []
    resolved_count = 0
    hitters_pasted = 0

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
        if id(game) not in leg_start_by_game:
            # _leg_starts blocked this matchup as inseparable; it already said so.
            continue
        start = leg_start_by_game[id(game)]
        # The single-leg cross-check is a wrong-slate detector. On a doubleheader
        # the non-priced leg's clock differs LEGITIMATELY, and warning about it
        # attributed a wrong-slate signal to the wrong leg (R58a); _leg_starts
        # reports the multi-leg case instead.
        if sum(1 for g in games if g.game_id == game_id) == 1:
            # Against the SALARY start, not the derived one. Handing it the
            # derived value would compare the paste's clock with a number
            # computed from that same clock, which agrees by construction and
            # silences the wrong-slate detector entirely.
            _cross_check_clock(game, start_by_game[game_id], warnings)

        sides: Dict[str, Dict[str, Any]] = {}
        for side, team, lineup, pitcher in (
            ("away", game.away_team, game.away_lineup, game.away_pitcher),
            ("home", game.home_team, game.home_lineup, game.home_pitcher),
        ):
            rows: List[Dict[str, Any]] = []
            side_blocked = False
            side_absent = 0
            hitters_pasted += len(lineup)
            for player in sorted(lineup, key=lambda p: p.order):
                matched, blocker = _resolve_one(
                    player.display_name, team, hitter_index, overrides)
                if blocker:
                    blockers.append(f"{game_id} {team} slot {player.order}: {blocker}")
                    side_blocked = True
                    continue
                if matched is None:
                    side_absent += 1
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

            if lineup and side_absent > len(lineup) * SIDE_ABSENT_BLOCK_RATIO:
                blockers.append(
                    f"{game_id} {team}: {side_absent} of {len(lineup)} pasted "
                    f"starters have no row in the DK salary file. One is a "
                    f"call-up and is not fatal; past half a posted side it is one "
                    f"fact and not {side_absent} of them, and the fact is that "
                    f"this paste and this salary file are not the same game")

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
                                "dk_player_id": matched.player_id,
                                "source": "operator_paste"}
                    resolved_count += 1

            probable = _apply_dk_starting(
                probable, team, game_id, dk_starters, dk_probables, warnings)
            if probable is not None and probable.get("source") == "dk_starting_column":
                resolved_count += 1

            # Ben's call: a short block is PARTIAL, which the status builder reads
            # as projected and reports in partial_lineup_teams. Calling nine-minus-
            # one 'confirmed' would be the labels rule broken at the front door.
            status = ("confirmed" if len(rows) == POSTED_LINEUP_SLOTS
                      else ("partial" if rows else "tbd"))
            if status == "confirmed":
                confirmed.append(team)
            elif status == "partial":
                # A side short because a NAME would not resolve is a different
                # fact from a side mlb.com posted short, and the report must not
                # blur them: the first is this tool failing and is a blocker, the
                # second is the world and is a labelled projection.
                #
                # R133(1): there is a THIRD fact and it read as the second one.
                # mlb.com can post all nine while DK rosters eight of them, and
                # "mlb.com posted a partial lineup" is then simply false --
                # mlb.com posted a complete one and DK did not list a player.
                # The two have different remedies (wait and re-paste vs nothing
                # to do, he is unrosterable either way), so they are two lists
                # under ``posted_sides_incomplete`` and a ``cause`` on the row,
                # the ``opposing_probables_incomplete`` treatment. The counts
                # travel with it because the prose cannot be joined on.
                if side_blocked:
                    cause = "unresolved_name"
                    reason = "unresolved name(s); see blockers"
                elif len(lineup) >= POSTED_LINEUP_SLOTS and side_absent:
                    cause = "dk_unrostered"
                    reason = (f"mlb.com posted all {len(lineup)}; "
                              f"{side_absent} have no DK salary row, so DK did "
                              f"not list them and they are unrosterable")
                else:
                    # Unchanged wording on purpose: this is the one case the
                    # original sentence was TRUE about, and a reader who has
                    # seen it on three slates should still recognise it.
                    cause = "mlb_short"
                    reason = "mlb.com posted a partial lineup"
                partial.append({
                    "team": team, "game_id": game_id, "hitters_posted": len(rows),
                    "mlb_posted": len(lineup), "absent_from_dk": side_absent,
                    "cause": cause, "reason": reason,
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

    slate_absent = sum(1 for row in unrostered if row["order"] != "SP")
    slate_tripped = (hitters_pasted
                     and slate_absent >= SLATE_ABSENT_BLOCK_FLOOR
                     and slate_absent > hitters_pasted * SLATE_ABSENT_BLOCK_RATIO)
    if slate_tripped:
        blockers.append(
            f"{slate_absent} of {hitters_pasted} pasted starters across the whole "
            f"paste have no row in the DK salary file. That is a wrong-slate or "
            f"wrong-salary-file signal read once, not {slate_absent} independent "
            f"call-ups; check that the paste and "
            f"{Path(str(salary_csv)).name} describe the same slate")

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
        # R133(1). The machine-readable half of the reason strings above. Two
        # lists rather than one because the remedies differ: a short post is
        # fixed by waiting and re-pasting, and a DK-unrostered starter is not
        # fixable at all -- DK owns eligibility, so there is nothing to wait
        # for. ``unresolved_name`` is deliberately absent: that side is already
        # a blocker and a reader must not find it in a projection bucket.
        "posted_sides_incomplete": {
            "mlb_short": [r["team"] for r in partial if r["cause"] == "mlb_short"],
            "dk_unrostered": [r["team"] for r in partial
                              if r["cause"] == "dk_unrostered"],
        },
        "unrostered_starters": unrostered,
        "dk_declared_probables": dk_probables,
        "unrostered_policy": {
            "hitters_pasted": hitters_pasted,
            "hitters_absent_from_dk": slate_absent,
            "side_ratio": SIDE_ABSENT_BLOCK_RATIO,
            "slate_ratio": SLATE_ABSENT_BLOCK_RATIO,
            "slate_floor": SLATE_ABSENT_BLOCK_FLOOR,
            "slate_threshold_tripped": bool(slate_tripped),
            "rule": "absent from the DK pool is reported per name and never "
                    "fatal on its own; it blocks when it exceeds half of one "
                    "posted side, or the slate ratio and floor together",
        },
        "blockers": blockers,
        "warnings": warnings,
    }
    return {"feed": feed, "report": report}


def _utc():
    from datetime import timezone
    return timezone.utc


def _paste_clock_hm(game: PastedGame) -> Optional[Tuple[int, int]]:
    """The paste's bare clock as (hour, minute) in ET, or None when unreadable.

    mlb.com renders Eastern and the salary file's Game Info is Eastern, so the
    two are directly comparable without a zone conversion.
    """
    match = _CLOCK.match(game.clock_text or "")
    if not match:
        return None
    hour = int(match.group("h")) % 12
    if (match.group("ap") or "PM").upper() == "PM":
        hour += 12
    return hour, int(match.group("m"))


def _leg_starts(
    games: Sequence[PastedGame],
    start_by_game: Mapping[str, datetime],
    blockers: List[str],
    warnings: List[str],
) -> Dict[int, datetime]:
    """Per-LEG start per pasted game, keyed by ``id(game)`` (R58a).

    Every pasted leg of a matchup used to be stamped with the one start the
    salary file carries for that ``game_id``, because a DK draftgroup prices a
    single leg of a doubleheader and ``salary_game_times`` is keyed on
    ``AWAY@HOME``. Downstream, ``_select_slate_legs`` tie-breaks on
    ``game_date_utc`` against that same salary start, so with both legs carrying
    an identical stamp it kept whichever leg was pasted FIRST and dropped the
    other with the reason "matched salary start". Reproduced: a 9:38 PM night
    draftgroup confirmed the 1:05 PM leg's batting order, the night-only starters
    were absent from the pool, and the build exited 0.

    The date still comes from the salary file, which is authoritative for the
    slate and carries a full date; only the TIME OF DAY comes from the paste,
    which is the one thing the paste knows per leg and the salary file cannot.

    A matchup pasted more than once whose legs cannot be told apart by clock is a
    BLOCKER, not a guess: two indistinguishable legs mean the downstream selector
    has to pick arbitrarily, which is exactly the failure this closes.
    """
    legs_by_id: Dict[str, List[PastedGame]] = {}
    for game in games:
        if game.game_id in start_by_game:
            legs_by_id.setdefault(game.game_id, []).append(game)

    out: Dict[int, datetime] = {}
    for game_id, legs in legs_by_id.items():
        salary_start = start_by_game[game_id]
        clocks = [_paste_clock_hm(game) for game in legs]
        if len(legs) > 1:
            readable = [c for c in clocks if c is not None]
            if len(readable) != len(legs) or len(set(readable)) != len(legs):
                shown = ", ".join(
                    (game.clock_text or "<no clock>") for game in legs)
                blockers.append(
                    f"{game_id}: pasted {len(legs)} times and the legs cannot be "
                    f"told apart by clock ({shown}). A doubleheader needs one "
                    f"distinct start per leg or the wrong leg's batting order "
                    f"reaches the pool; re-paste with both game times shown"
                )
                continue
        for game, clock in zip(legs, clocks):
            # A single-leg matchup keeps the salary file's start verbatim. The CSV
            # is authoritative for the slate and the paste's bare clock stays a
            # pure CROSS-CHECK there, which is the existing contract. The ONLY
            # case where the salary file cannot answer the question is a matchup
            # pasted more than once, because it prices one leg and both legs
            # share the DK game_id.
            if clock is None or len(legs) == 1:
                out[id(game)] = salary_start
                continue
            out[id(game)] = salary_start.replace(
                hour=clock[0], minute=clock[1], second=0, microsecond=0)
        if len(legs) > 1:
            matched = [game for game, clock in zip(legs, clocks)
                       if clock == (salary_start.hour, salary_start.minute)]
            if not matched:
                warnings.append(
                    f"{game_id}: pasted {len(legs)} legs "
                    f"({', '.join(g.clock_text or '?' for g in legs)}) and NONE "
                    f"matches the salary file's "
                    f"{salary_start.strftime('%I:%M %p ET').lstrip('0')}; if this "
                    f"is the wrong slate nothing downstream will say so"
                )
            else:
                warnings.append(
                    f"{game_id}: doubleheader, {len(legs)} legs pasted; the "
                    f"{matched[0].clock_text} leg is the one the salary file "
                    f"prices and the others are carried with their own start so "
                    f"leg selection can tell them apart"
                )
    return out


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

