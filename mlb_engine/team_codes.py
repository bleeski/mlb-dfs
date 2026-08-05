"""team_codes.py -- the one place that maps a team code or name to DraftKings.

R59/R82. Three vocabularies reach this engine: the MLB Stats API (``AZ``),
FanGraphs RosterResource (``WSN``/``TBR``/``CHW``/``KCR``/``SDP``/``SFG``), and
DraftKings itself, which the salary CSV makes authoritative. Every ingest
boundary normalizes through here.

This module exists SEPARATELY from ``live_data_adapters``, where these maps used
to live, because normalizing a team code has nothing to do with fetching one.
``tools/lineups_from_paste.py`` needs the normalizer and carries a hard
zero-network contract (pinned by test); importing the adapters module to get
three lines of dict lookup pulled ``urllib.request`` into that tool's import
graph and quietly voided the contract. The maps are pure data and the two
functions are pure, so they belong on the network-free side of the line.

``live_data_adapters`` re-exports both names, so every existing caller and import
path is unchanged.

R82 still owns the other half: an UNKNOWN-code report. Today a code that fails to
normalize passes through unchanged and silently matches nothing downstream, which
is how WSH once filled 0 of 9 hitters and reported success. Adding the report is
that item; moving the boundary is this one.
"""
from __future__ import annotations

from typing import Optional

VERSION = "v1.0"


# A code that fails to normalize does not raise -- it passes through and
# silently matches nothing downstream (R82 owns making that loud).
# ATH passes through unchanged: DraftKings, the salary CSV, and data/reference all
# key the Athletics as ATH post-relocation (was OAK).
DK_ABBREV_REMAP = {
    # MLB Stats API
    "AZ": "ARI",
    # FanGraphs RosterResource
    "WSN": "WSH", "TBR": "TB", "CHW": "CWS", "KCR": "KC", "SDP": "SD", "SFG": "SF",
}

# the-odds-api returns full team names; DraftKings CSVs use abbreviations.
MLB_TEAM_NAME_TO_DK = {
    "arizona diamondbacks": "ARI", "atlanta braves": "ATL",
    "baltimore orioles": "BAL", "boston red sox": "BOS",
    "chicago cubs": "CHC", "chicago white sox": "CWS",
    "cincinnati reds": "CIN", "cleveland guardians": "CLE",
    "colorado rockies": "COL", "detroit tigers": "DET",
    "houston astros": "HOU", "kansas city royals": "KC",
    "los angeles angels": "LAA", "los angeles dodgers": "LAD",
    "miami marlins": "MIA", "milwaukee brewers": "MIL",
    "minnesota twins": "MIN", "new york mets": "NYM",
    "new york yankees": "NYY", "athletics": "ATH",
    "oakland athletics": "ATH", "philadelphia phillies": "PHI",
    "pittsburgh pirates": "PIT", "san diego padres": "SD",
    "san francisco giants": "SF", "seattle mariners": "SEA",
    "st louis cardinals": "STL", "st. louis cardinals": "STL",
    "tampa bay rays": "TB", "texas rangers": "TEX",
    "toronto blue jays": "TOR", "washington nationals": "WSH",
    # R33: the club NICKNAME alone, which is what mlb.com/starting-lineups
    # renders in its matchup links ("[Astros](...)@[Angels](...)"). Every MLB
    # nickname is unique, so these add no ambiguity, and they are what lets a
    # pasted '<TEAM> Lineup' header be cross-checked against a second,
    # independent read of the same fact instead of being trusted alone.
    "diamondbacks": "ARI", "d-backs": "ARI", "braves": "ATL",
    "orioles": "BAL", "red sox": "BOS", "cubs": "CHC", "white sox": "CWS",
    "reds": "CIN", "guardians": "CLE", "rockies": "COL", "tigers": "DET",
    "astros": "HOU", "royals": "KC", "angels": "LAA", "dodgers": "LAD",
    "marlins": "MIA", "brewers": "MIL", "twins": "MIN", "mets": "NYM",
    "yankees": "NYY", "phillies": "PHI", "pirates": "PIT", "padres": "SD",
    "giants": "SF", "mariners": "SEA", "cardinals": "STL", "rays": "TB",
    "rangers": "TEX", "blue jays": "TOR", "nationals": "WSH",
}


def to_dk_abbrev(api_abbrev: str) -> str:
    text = str(api_abbrev or "").strip().upper()
    return DK_ABBREV_REMAP.get(text, text)


def team_name_to_dk_abbrev(team_name: str) -> Optional[str]:
    key = " ".join(str(team_name or "").strip().lower().replace(".", ". ").split())
    return MLB_TEAM_NAME_TO_DK.get(key) or MLB_TEAM_NAME_TO_DK.get(key.replace(". ", " ").replace(".", ""))
