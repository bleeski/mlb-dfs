"""
MLB Classic Slate Intake Manager — v1.8
Framework patch: MLB Classic v2.16.0 Lean Decision System
Compiled: 2026-07-08 (v1.7 slate clock); 2026-07-19 (v1.8 name-fold fix)

v1.8 fix:
  - normalize_name() now NFKD-folds diacritics and strips generational suffixes
    (Jr/Sr/II/III/IV) before the alnum collapse. Previously an accented feed name
    (MLB Stats API, e.g. "Jose Fermin" with an acute accent on the o and i) failed
    to match the plain-ASCII DK salary name ("Jose Fermin") because the old regex
    deleted the accented character instead of folding it, splitting the surname
    into two dead tokens. The confirmed starter then had no salary match and its
    row was silently absent from the pool rather than flagged. Every caller shares
    the fix since they all import this one function: this module's own declared-
    pitcher and pasted-lineup reconciliation, plus every name-matching call site in
    live_data_adapters.py. Caught 2026-07-19 on the afternoon 4-game slate build:
    6 confirmed hitters affected before catch, worked around in-memory for that
    build, now fixed at the source.

v1.7 additions:
  - slate_clock(): first-lock detection and the T-minus-buffer delivery deadline.
    Parses game datetimes from the salary CSV Game Info column (or accepts the
    lineups feed's lock_time_by_game_id directly), names the first game to lock,
    and computes the delivery deadline at lock minus buffer_minutes (default 5).
    Deterministic bookkeeping surfaced on every run_slate checkpoint and result;
    it is never a guarantee the session meets the deadline.

Purpose
-------
This module validates and normalizes the operator intake surface before MLB
Classic research/projection work begins. It does not project players, scrape
websites, allocate contests, or replace optimizer_v3.py. It helps the executor:
  1. parse DraftKings salary CSV rows into stable Player_ID/team/position records;
  2. derive slate teams and game IDs from salary CSV Game Info;
  3. parse user-pasted confirmed lineup text into team/slot records when present;
  4. reconcile confirmed hitters against the salary CSV and flag missing slots;
  5. build a player-status table for downstream pool gates;
  6. run a neutral optimizer shell preflight to catch impossible CSV/pool shapes
     before time-consuming odds/weather/Statcast research;
  7. audit every rosterable salary-row pitcher against the declared/probable SP
     list so viable bulk/alternate SPs are not silently omitted;
  8. derive a Slate Context Packet checklist for batch odds/weather fetching;
  9. validate weather/odds freshness gates before optimizer/export work;
 10. skip optimizer/export certification when required weather/roof/odds packets are missing;
 11. surface the slate clock: first lock, delivery deadline, and minutes remaining.

Operating rules
---------------
Salary CSV is the source of truth for Player_ID, salary, team, and eligibility.
This module performs fail-fast validation only. Neutral shell output is not a
recommended lineup and must never be presented as a DFS build.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import csv
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "v1.10"
DK_ROSTER_SLOTS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
HITTER_SLOTS = {"C", "1B", "2B", "3B", "SS", "OF"}
PITCHER_ALIASES = {"P", "SP", "RP"}
REQUIRED_SALARY_FIELDS = ("Salary", "TeamAbbrev")
ID_FIELD_CANDIDATES = ("ID", "Player_ID", "Player ID")
NAME_ID_FIELD_CANDIDATES = ("Name + ID", "Name+ID")
POSITION_FIELD_CANDIDATES = ("Roster Position", "Position")
NAME_FIELD_CANDIDATES = ("Name", "Player")
GAME_FIELD_CANDIDATES = ("Game Info", "GameInfo", "Game")


@dataclass(frozen=True)
class SalaryPlayer:
    player_id: str
    name: str
    team: str
    positions: Tuple[str, ...]
    salary: float
    game_info: str = ""
    opponent: str = ""
    game_id: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    # DK ships availability in the salary file itself and the Classic path never
    # read it: an IL bat that survives the platoon or APPG fallback is a dead
    # roster slot, 10% of a Classic entry lost before first pitch. Both columns
    # are promoted to first-class fields so no consumer has to know they live in
    # ``raw``, and so the value carries onto the projection row.
    status: str = ""      # "", IL, O, OUT, NA, DTD ...
    starting: str = ""    # confirmed batting slot 1-9, or SP/PO for arms


@dataclass(frozen=True)
class ParsedLineupHitter:
    team: str
    slot: int
    name: str
    bats: str = ""
    position: str = ""


def normalize_player_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\((\d{5,})\)", text)
    if match:
        return match.group(1)
    nums = re.findall(r"\d{5,}", text)
    if nums:
        return nums[-1]
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def normalize_name(value: Any) -> str:
    # NFKD-fold first so an accented letter (feed data, e.g. MLB Stats API)
    # collapses to its plain-ASCII base instead of being deleted by the alnum
    # collapse below and matches DK's plain-ASCII salary spelling. See v1.8 note.
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    toks = [t for t in text.split() if t not in _NAME_SUFFIXES]
    return " ".join(toks)


def _first_existing(header: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    lower = {str(h).strip().lower(): str(h).strip() for h in header}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def parse_money(value: Any) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_positions(value: Any) -> Tuple[str, ...]:
    text = str(value or "").strip().upper().replace(" ", "")
    if not text:
        return tuple()
    out: List[str] = []
    for part in re.split(r"[/,;]", text):
        if not part:
            continue
        pos = "P" if part in PITCHER_ALIASES else part
        if pos in {"P", "C", "1B", "2B", "3B", "SS", "OF"} and pos not in out:
            out.append(pos)
    return tuple(out)


def infer_opponent_and_game_id(team: str, game_info: str) -> Tuple[str, str]:
    text = str(game_info or "").strip()
    team = str(team or "").strip().upper()
    if not text or "@" not in text:
        return "", ""
    first_token = text.split()[0]
    if "@" not in first_token:
        return "", ""
    away, home = [x.strip().upper() for x in first_token.split("@", 1)]
    opp = home if team == away else away if team == home else ""
    game_id = "@".join([away, home]) if away and home else ""
    return opp, game_id


def validate_salary_schema(path: str) -> Dict[str, Any]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    missing: List[str] = []
    for required in REQUIRED_SALARY_FIELDS:
        if _first_existing(header, (required,)) is None:
            missing.append(required)
    if _first_existing(header, ID_FIELD_CANDIDATES) is None and _first_existing(header, NAME_ID_FIELD_CANDIDATES) is None:
        missing.append("ID or Name + ID")
    if _first_existing(header, POSITION_FIELD_CANDIDATES) is None:
        missing.append("Roster Position or Position")
    if _first_existing(header, NAME_FIELD_CANDIDATES) is None and _first_existing(header, NAME_ID_FIELD_CANDIDATES) is None:
        missing.append("Name or Name + ID")
    return {
        "passed": not missing,
        "missing_columns": missing,
        "header": list(header),
        "summary": "Salary CSV schema passed" if not missing else "Salary CSV schema missing: " + ", ".join(missing),
    }


def parse_dk_salary_csv(path: str) -> List[SalaryPlayer]:
    schema = validate_salary_schema(path)
    if not schema["passed"]:
        raise ValueError(schema["summary"])
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    header = list(rows[0].keys())
    id_col = _first_existing(header, ID_FIELD_CANDIDATES)
    name_id_col = _first_existing(header, NAME_ID_FIELD_CANDIDATES)
    pos_col = _first_existing(header, POSITION_FIELD_CANDIDATES)
    name_col = _first_existing(header, NAME_FIELD_CANDIDATES) or name_id_col
    game_col = _first_existing(header, GAME_FIELD_CANDIDATES)
    players: List[SalaryPlayer] = []
    seen: set[str] = set()
    for row in rows:
        pid = normalize_player_id(row.get(id_col, "") if id_col else "")
        if not pid and name_id_col:
            pid = normalize_player_id(row.get(name_id_col, ""))
        if not pid:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        name = str(row.get(name_col, "") or "").strip() if name_col else ""
        if name_id_col and (not name or re.fullmatch(r"\d+", name)):
            name = re.sub(r"\s*\(\d{5,}\)\s*$", "", str(row.get(name_id_col, "")).strip())
        team = str(row.get("TeamAbbrev", "") or "").strip().upper()
        positions = parse_positions(row.get(pos_col, "") if pos_col else "")
        salary = parse_money(row.get("Salary", ""))
        game_info = str(row.get(game_col, "") or "").strip() if game_col else ""
        opp, game_id = infer_opponent_and_game_id(team, game_info)
        players.append(SalaryPlayer(
            pid, name, team, positions, salary, game_info, opp, game_id, dict(row),
            status=str(row.get("Status", "") or "").strip().upper(),
            starting=str(row.get("Starting", "") or "").strip().upper(),
        ))
    return players


# DK's availability vocabulary. OUT statuses are shelved and must never occupy a
# roster slot. DTD is playable-but-risky: it warns, and escalates to a blocker
# only inside a chosen primary stack, because hard-blocking every DTD bat would
# routinely strip legal players out of a legal pool.
SALARY_STATUS_OUT = frozenset({"IL", "O", "OUT", "NA", "IL10", "IL15", "IL60", "PUP", "SUSP"})
SALARY_STATUS_WATCH = frozenset({"DTD", "GTD", "Q"})


def salary_status_tier(status: Any) -> str:
    """'out' | 'watch' | 'clean' for a DK Status cell."""
    value = str(status or "").strip().upper()
    if value in SALARY_STATUS_OUT:
        return "out"
    if value in SALARY_STATUS_WATCH:
        return "watch"
    return "clean"


def _extract_game_date(game_info: str) -> str:
    """Extract an ISO game date from the DraftKings Game Info field when present."""
    match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", str(game_info or ""))
    if not match:
        return ""
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def derive_slate_games(players: Sequence[SalaryPlayer]) -> List[Dict[str, Any]]:
    games: Dict[str, Dict[str, Any]] = {}
    for p in players:
        if not p.game_id:
            continue
        record = games.setdefault(p.game_id, {"teams": set(), "game_date": ""})
        record["teams"].add(p.team)
        if p.opponent:
            record["teams"].add(p.opponent)
        if not record["game_date"]:
            record["game_date"] = _extract_game_date(p.game_info)
    output = []
    for gid, record in sorted(games.items()):
        away, home = (gid.split("@", 1) + [""])[:2] if "@" in gid else ("", "")
        output.append({
            "game_id": gid,
            "game_date": record["game_date"],
            "away_team": away,
            "home_team": home,
            "teams": sorted(record["teams"]),
        })
    return output


# ---------------------------------------------------------------------------
# v1.5 Material Weather + Minimal Odds Context
# ---------------------------------------------------------------------------

OUTDOOR_ROOF_TYPES = {"outdoor", "temporary", "open"}
WEATHER_REQUIRED_ROOF_TYPES = OUTDOOR_ROOF_TYPES  # backward-compatible name
ROOF_STATUS_REQUIRED_ROOF_TYPES = {"retractable"}
ROOF_STATUS_CLOSED_VALUES = {"closed", "closed_roof", "roof_closed", "dome", "fixed", "controlled"}
ROOF_STATUS_OPEN_VALUES = {"open", "open_roof", "roof_open"}
WEATHER_FRESHNESS_MINUTES = 120
ODDS_FRESHNESS_MINUTES = 180
WIND_STATUSES = {"out", "in", "cross", "variable", "not_material"}
DELAY_RISK_LEVELS = {"none", "low", "medium", "high"}
POSTPONEMENT_RISK_LEVELS = {"none", "low", "medium", "high"}
ODDS_REQUIRED_FIELDS = ("total", "source", "fetched_at")
DEFAULT_WIND_THRESHOLDS = {"high": 8.0, "moderate": 13.0, "medium": 13.0, "low": 999.0, "none": 999.0, "roof": 999.0}
PITCHER_DELAY_FACTORS = {"none": 1.0, "low": 1.0, "medium": 0.95, "high": 0.85}


def _to_float_or_none(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_minutes(fetched_at: Any, now: Optional[datetime] = None) -> Optional[float]:
    dt = _parse_timestamp(fetched_at)
    if dt is None:
        return None
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now_dt.astimezone(timezone.utc) - dt).total_seconds() / 60.0)


def _normalize_sensitivity(value: Any) -> str:
    text = str(value or "moderate").strip().lower()
    if text == "medium":
        text = "moderate"
    return text if text in {"high", "moderate", "low", "none", "roof"} else "moderate"


def _wind_threshold(row: Dict[str, Any], sensitivity: str) -> float:
    explicit = _to_float_or_none(row.get("Wind_Min_Speed_MPH") or row.get("wind_min_speed_mph"))
    return explicit if explicit is not None else DEFAULT_WIND_THRESHOLDS.get(sensitivity, 13.0)


def load_team_venue_map(path: str) -> Dict[str, Dict[str, Any]]:
    """Load the compact venue map used for material-weather decisions."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        team = str(row.get("Home_Team") or row.get("Team") or "").strip().upper()
        if not team:
            continue
        roof = str(row.get("Roof_Type") or "").strip().lower()
        weather_raw = str(row.get("Weather_Required") or "").strip().lower()
        if weather_raw in {"true", "1", "yes", "y"}:
            weather_required = True
        elif weather_raw in {"false", "0", "no", "n"}:
            weather_required = False
        else:
            weather_required = roof in OUTDOOR_ROOF_TYPES
        sensitivity = _normalize_sensitivity(row.get("Wind_Sensitivity"))
        out[team] = {
            "home_team": team,
            "venue": str(row.get("Venue") or "").strip(),
            "roof_type": roof,
            "cf_azimuth_degrees": _to_float_or_none(row.get("CF_Azimuth_Degrees")),
            "default_wind_direction": str(row.get("Default_Wind_Direction") or "cross").strip().lower(),
            "wind_sensitivity": sensitivity,
            "wind_min_speed_mph": _wind_threshold(row, sensitivity),
            "latitude": _to_float_or_none(row.get("Latitude")),
            "longitude": _to_float_or_none(row.get("Longitude")),
            "timezone": str(row.get("Timezone") or "").strip(),
            "weather_required": bool(weather_required),
            "roof_status_source": str(row.get("Roof_Status_Source") or "").strip(),
            "last_verified": str(row.get("Last_Verified") or "").strip(),
            "raw": dict(row),
        }
    return out


def resolve_game_venue_overrides_path(
    team_to_venue_csv_path: str,
    explicit_path: Optional[str] = None,
) -> Optional[str]:
    if explicit_path:
        if not os.path.exists(explicit_path):
            raise FileNotFoundError(f"game venue overrides file not found: {explicit_path}")
        return explicit_path
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(team_to_venue_csv_path)), "game_venue_overrides.csv"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_venue_overrides.csv"),
    ]
    return next((candidate for candidate in candidates if os.path.exists(candidate)), None)


def load_game_venue_overrides(path: str) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Load date-and-matchup venue overrides for neutral or alternate-site games."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        game_date = str(row.get("Game_Date") or "").strip()
        away = str(row.get("Away_Team") or "").strip().upper()
        home = str(row.get("Home_Team") or "").strip().upper()
        if not game_date or not away or not home:
            continue
        roof = str(row.get("Roof_Type") or "").strip().lower()
        weather_raw = str(row.get("Weather_Required") or "").strip().lower()
        if weather_raw in {"true", "1", "yes", "y"}:
            weather_required = True
        elif weather_raw in {"false", "0", "no", "n"}:
            weather_required = False
        else:
            weather_required = roof in OUTDOOR_ROOF_TYPES
        sensitivity = _normalize_sensitivity(row.get("Wind_Sensitivity"))
        gid = f"{away}@{home}"
        out[(game_date, gid)] = {
            "game_date": game_date,
            "game_id": gid,
            "away_team": away,
            "home_team": home,
            "venue": str(row.get("Venue") or "").strip(),
            "roof_type": roof,
            "cf_azimuth_degrees": _to_float_or_none(row.get("CF_Azimuth_Degrees")),
            "default_wind_direction": str(row.get("Default_Wind_Direction") or "cross").strip().lower(),
            "wind_sensitivity": sensitivity,
            "wind_min_speed_mph": _wind_threshold(row, sensitivity),
            "latitude": _to_float_or_none(row.get("Latitude")),
            "longitude": _to_float_or_none(row.get("Longitude")),
            "timezone": str(row.get("Timezone") or "").strip(),
            "weather_required": bool(weather_required),
            "roof_status_source": str(row.get("Roof_Status_Source") or "").strip(),
            "last_verified": str(row.get("Last_Verified") or "").strip(),
            "projection_f5_status": str(row.get("Projection_F5_Status") or "manual_required").strip().lower(),
            "run_factor_applied": _to_float_or_none(row.get("Run_Factor_Applied")),
            "hr_factor_applied": _to_float_or_none(row.get("HR_Factor_Applied")),
            "f5_approval_note": str(row.get("F5_Approval_Note") or "").strip(),
            "notes": str(row.get("Notes") or "").strip(),
            "source_url": str(row.get("Source_URL") or "").strip(),
            "raw": dict(row),
        }
    return out


def _resolve_game_venue(
    game: Dict[str, Any],
    venue_map: Dict[str, Dict[str, Any]],
    game_venue_overrides: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    gid = str(game.get("game_id") or "").strip().upper()
    game_date = str(game.get("game_date") or "").strip()
    overrides = game_venue_overrides or {}
    override = overrides.get((game_date, gid))
    if override:
        return override, "game_override"
    if not game_date and any(override_gid == gid for (_date, override_gid) in overrides):
        return None, "override_date_missing"
    home = str(game.get("home_team") or "").strip().upper()
    return venue_map.get(home), "home_team_default"


def derive_slate_context_requirements(
    games: Sequence[Dict[str, Any]],
    venue_map: Dict[str, Dict[str, Any]],
    game_venue_overrides: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return one compact checklist for roof, material weather, and game totals."""
    rows: List[Dict[str, Any]] = []
    missing_venue_teams: List[str] = []
    weather_required: List[Dict[str, Any]] = []
    roof_status_required: List[Dict[str, Any]] = []
    odds_required: List[str] = []
    unverified_park_factor_games: List[str] = []
    unverified_park_factor_reasons: Dict[str, List[str]] = {}
    missing_game_dates: List[str] = []
    for game in games:
        gid = str(game.get("game_id") or "").strip()
        home = str(game.get("home_team") or "").strip().upper()
        away = str(game.get("away_team") or "").strip().upper()
        venue, venue_source = _resolve_game_venue(game, venue_map, game_venue_overrides)
        if not venue:
            missing_venue_teams.append(home or gid)
            if venue_source == "override_date_missing":
                missing_game_dates.append(gid)
            row = {
                "game_id": gid, "game_date": str(game.get("game_date") or ""), "away_team": away,
                "home_team": home, "venue": "", "venue_source": venue_source, "roof_type": "unknown",
                "weather_required": True, "roof_status_required": True, "wind_sensitivity": "moderate",
                "wind_min_speed_mph": 13.0, "latitude": None, "longitude": None, "timezone": "",
            }
        else:
            row = {
                "game_id": gid,
                "game_date": str(game.get("game_date") or ""),
                "away_team": away,
                "home_team": home,
                "venue": venue["venue"],
                "venue_source": venue_source,
                "roof_type": venue["roof_type"],
                "weather_required": bool(venue["weather_required"]),
                "roof_status_required": venue.get("roof_type") in ROOF_STATUS_REQUIRED_ROOF_TYPES,
                "wind_sensitivity": _normalize_sensitivity(venue.get("wind_sensitivity")),
                "wind_min_speed_mph": float(venue.get("wind_min_speed_mph") or 13.0),
                "latitude": venue.get("latitude"),
                "longitude": venue.get("longitude"),
                "timezone": venue.get("timezone"),
                "cf_azimuth_degrees": venue.get("cf_azimuth_degrees"),
                "default_wind_direction": venue.get("default_wind_direction"),
                "projection_f5_status": venue.get("projection_f5_status", "verified" if venue_source == "home_team_default" else "manual_required"),
                "run_factor_applied": venue.get("run_factor_applied"),
                "hr_factor_applied": venue.get("hr_factor_applied"),
                "f5_approval_note": venue.get("f5_approval_note", ""),
                "venue_notes": venue.get("notes", ""),
                "venue_source_url": venue.get("source_url", ""),
            }
            if venue_source == "game_override":
                reasons: List[str] = []
                if row["projection_f5_status"] not in {"verified", "approved"}:
                    reasons.append("projection_f5_status_not_approved")
                factors = (row.get("run_factor_applied"), row.get("hr_factor_applied"))
                if not all(value is not None and 0.75 <= float(value) <= 1.25 for value in factors):
                    reasons.append("approved_run_hr_factors_missing_or_out_of_bounds")
                if not str(row.get("f5_approval_note") or "").strip():
                    reasons.append("f5_approval_note_missing")
                if row.get("latitude") is None or row.get("longitude") is None or not row.get("timezone"):
                    reasons.append("weather_location_metadata_incomplete")
                if not str(row.get("venue_source_url") or "").strip():
                    reasons.append("source_url_missing")
                if reasons:
                    unverified_park_factor_games.append(gid)
                    unverified_park_factor_reasons[gid] = reasons
        rows.append(row)
        odds_required.append(gid)
        if row["weather_required"]:
            weather_required.append(row)
        if row.get("roof_status_required"):
            roof_status_required.append(row)
    passed = not missing_venue_teams and not unverified_park_factor_games
    return {
        "games": rows,
        "weather_required_games": weather_required,
        "roof_status_required_games": roof_status_required,
        "odds_required_games": odds_required,
        "missing_venue_teams": missing_venue_teams,
        "missing_game_dates": missing_game_dates,
        "unverified_park_factor_games": unverified_park_factor_games,
        "unverified_park_factor_reasons": unverified_park_factor_reasons,
        "passed": passed,
        "summary": "Material-weather and minimal-odds requirements derived" if passed else "Context requirements blocked by missing venue metadata or unapproved special venue",
    }


def _packet_games(packet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    games = packet.get("games") or []
    if isinstance(games, dict):
        return {str(k): dict(v or {}) for k, v in games.items()}
    return {str(row.get("game_id") or ""): dict(row) for row in games if row.get("game_id")}


def _field_missing(mapping: Dict[str, Any], field: str) -> bool:
    return mapping.get(field) in (None, "")


def _normalize_roof_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ROOF_STATUS_CLOSED_VALUES:
        return "closed"
    if text in ROOF_STATUS_OPEN_VALUES:
        return "open"
    return text


def _extract_roof_status(pkt_game: Dict[str, Any], weather: Dict[str, Any]) -> Dict[str, Any]:
    status = pkt_game.get("roof_status") or weather.get("roof_status")
    source = pkt_game.get("roof_status_source") or weather.get("roof_status_source") or weather.get("source")
    fetched_at = pkt_game.get("roof_status_fetched_at") or weather.get("roof_status_fetched_at") or weather.get("fetched_at")
    return {"roof_status": _normalize_roof_status(status), "source": source, "fetched_at": fetched_at}


PRECIP_DELAY_BANDS = ((60.0, "high", "medium"), (35.0, "medium", "low"), (15.0, "low", "low"))


def risk_from_precip_probability(precip_pct: Any) -> Tuple[str, str]:
    """Return (delay_risk, postponement_risk) for a precipitation probability.

    F18. This is the only mapping from rain to the delay and postponement
    levels ``f5_weather_adjustments.csv`` is keyed on, and until now nothing
    production reached it: ``build_f5_map`` hardcoded both to "none", so the
    delay pitcher downgrade and the postponement exposure cap were unreachable
    branches in ``compute_f5_factor``.

    Below 15% both read "none" rather than "low". The two are identical in
    effect (delay low is a 1.000 pitcher factor and there is no postponement
    low row), so this changes no number; it stops a 0%-rain forecast from
    printing "low delay risk" in the brief, which is a false label.
    """
    precip = _to_float_or_none(precip_pct)
    if precip is None:
        return "", ""
    for threshold, delay, postpone in PRECIP_DELAY_BANDS:
        if precip >= threshold:
            return delay, postpone
    return "none", "none"


def _legacy_risk_from_precip(weather: Dict[str, Any]) -> Tuple[str, str]:
    """Risk levels from whichever precipitation key the payload carries.

    F18. This read ``precip_probability`` only. Nothing in the repo emits that
    key: ``fetch_slate_bundle`` writes ``precip_probability_pct`` per forecast
    hour, so the fallback returned ("", "") on every real bundle and the levels
    were always whatever the caller had already set.
    """
    for key in ("precip_probability", "precip_probability_pct", "precip_pct"):
        if weather.get(key) not in (None, ""):
            return risk_from_precip_probability(weather.get(key))
    return "", ""


def _normalized_weather(weather: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(weather or {})
    out["wind_status"] = str(out.get("wind_status") or out.get("wind_direction_tag") or "").strip().lower()
    if out.get("wind_speed_mph") in (None, ""):
        out["wind_speed_mph"] = out.get("wind_speed")
    legacy_delay, legacy_post = _legacy_risk_from_precip(out)
    out["delay_risk"] = str(out.get("delay_risk") or legacy_delay or "").strip().lower()
    out["postponement_risk"] = str(out.get("postponement_risk") or legacy_post or "").strip().lower()
    return out


def material_weather_adjustments(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Translate classified weather into direct DFS controls without false precision."""
    pitcher_factors: Dict[str, float] = {}
    game_exposure_caps: Dict[str, float] = {}
    excluded_games: List[str] = []
    for gid, pkt_game in _packet_games(packet or {}).items():
        weather = _normalized_weather(dict(pkt_game.get("weather") or {}))
        delay = weather.get("delay_risk") or "none"
        postpone = weather.get("postponement_risk") or "none"
        pitcher_factors[gid] = PITCHER_DELAY_FACTORS.get(delay, 1.0)
        if postpone == "medium":
            game_exposure_caps[gid] = 0.25
        elif postpone == "high":
            excluded_games.append(gid)
    return {
        "pitcher_delay_factors": pitcher_factors,
        "game_exposure_caps": game_exposure_caps,
        "excluded_games": excluded_games,
    }


def validate_slate_context_packet(
    packet: Dict[str, Any],
    games: Sequence[Dict[str, Any]],
    venue_map: Optional[Dict[str, Dict[str, Any]]] = None,
    game_venue_overrides: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    max_weather_age_minutes: int = WEATHER_FRESHNESS_MINUTES,
    max_odds_age_minutes: int = ODDS_FRESHNESS_MINUTES,
    require_odds: bool = True,
) -> Dict[str, Any]:
    """Validate only decision-relevant weather and one current game total per game."""
    venue_map = venue_map or {}
    pkt_games = _packet_games(packet or {})
    weather_errors: List[str] = []
    weather_warnings: List[str] = []
    weather_required_games: List[str] = []
    weather_covered_games: List[str] = []
    roof_errors: List[str] = []
    roof_warnings: List[str] = []
    roof_required_games: List[str] = []
    roof_covered_games: List[str] = []
    odds_errors: List[str] = []
    odds_warnings: List[str] = []
    odds_covered_games: List[str] = []

    for game in games:
        gid = str(game.get("game_id") or "").strip()
        home = str(game.get("home_team") or "").strip().upper()
        venue, _source = _resolve_game_venue(game, venue_map, game_venue_overrides)
        venue = venue or {}
        venue_name = str(venue.get("venue") or home or gid)
        roof_type = str(venue.get("roof_type") or "unknown").strip().lower()
        sensitivity = _normalize_sensitivity(venue.get("wind_sensitivity"))
        threshold = float(venue.get("wind_min_speed_mph") or DEFAULT_WIND_THRESHOLDS.get(sensitivity, 13.0))
        weather_required = bool(venue.get("weather_required", True if not venue else False))
        pkt_game = pkt_games.get(gid, {})
        weather = _normalized_weather(dict(pkt_game.get("weather") or {}))

        if roof_type in ROOF_STATUS_REQUIRED_ROOF_TYPES:
            roof_required_games.append(gid)
            roof = _extract_roof_status(pkt_game, weather)
            missing = [field for field in ("roof_status", "source", "fetched_at") if _field_missing(roof, field)]
            if missing:
                roof_errors.append(f"{gid} {venue_name}: missing roof fields {missing}")
            else:
                age = _age_minutes(roof.get("fetched_at"), now=now)
                if age is None or age > int(max_weather_age_minutes):
                    roof_errors.append(f"{gid} {venue_name}: roof status stale or unparseable")
                elif roof["roof_status"] == "open":
                    roof_covered_games.append(gid)
                    weather_required = True
                elif roof["roof_status"] == "closed":
                    roof_covered_games.append(gid)
                    weather_required = False
                else:
                    roof_errors.append(f"{gid} {venue_name}: unsupported roof_status '{roof['roof_status']}'")

        if weather_required:
            weather_required_games.append(gid)
            base_fields = ("wind_status", "delay_risk", "postponement_risk", "source", "fetched_at")
            missing = [field for field in base_fields if _field_missing(weather, field)]
            if missing:
                weather_errors.append(f"{gid} {venue_name}: missing material-weather fields {missing}")
            else:
                age = _age_minutes(weather.get("fetched_at"), now=now)
                if age is None or age > int(max_weather_age_minutes):
                    weather_errors.append(f"{gid} {venue_name}: weather stale or unparseable")
                if weather["wind_status"] not in WIND_STATUSES:
                    weather_errors.append(f"{gid} {venue_name}: invalid wind_status '{weather['wind_status']}'")
                if weather["delay_risk"] not in DELAY_RISK_LEVELS:
                    weather_errors.append(f"{gid} {venue_name}: invalid delay_risk '{weather['delay_risk']}'")
                if weather["postponement_risk"] not in POSTPONEMENT_RISK_LEVELS:
                    weather_errors.append(f"{gid} {venue_name}: invalid postponement_risk '{weather['postponement_risk']}'")
                if weather["postponement_risk"] == "high":
                    weather_errors.append(f"{gid} {venue_name}: high postponement risk; exclude game or wait")
                elif weather["postponement_risk"] == "medium":
                    weather_warnings.append(f"{gid}: medium postponement risk; cap game exposure")
                if weather["delay_risk"] in {"medium", "high"}:
                    weather_warnings.append(f"{gid}: {weather['delay_risk']} delay risk; apply pitcher-only downgrade")
                if sensitivity in {"high", "moderate"} and weather["wind_status"] != "not_material":
                    speed = _to_float_or_none(weather.get("wind_speed_mph"))
                    if speed is None:
                        weather_errors.append(f"{gid} {venue_name}: wind speed required for {sensitivity}-sensitivity park")
                    elif speed < threshold:
                        weather_warnings.append(f"{gid}: wind below {threshold:g} mph threshold; treat as not_material")
                weather_covered_games.append(gid)

        if require_odds:
            odds = dict(pkt_game.get("odds") or {})
            missing = [field for field in ODDS_REQUIRED_FIELDS if _field_missing(odds, field)]
            if missing:
                odds_errors.append(f"{gid}: missing minimal odds fields {missing}")
            else:
                total = _to_float_or_none(odds.get("total"))
                if total is None or not 4.0 <= total <= 20.0:
                    odds_errors.append(f"{gid}: invalid game total")
                age = _age_minutes(odds.get("fetched_at"), now=now)
                if age is None or age > int(max_odds_age_minutes):
                    odds_errors.append(f"{gid}: odds stale or unparseable")
                else:
                    odds_covered_games.append(gid)
                if odds.get("away_implied_total") in (None, "") or odds.get("home_implied_total") in (None, ""):
                    odds_warnings.append(f"{gid}: team implied totals unavailable; use game total only")

    weather_gate = {
        "required_games": weather_required_games,
        "covered_games": sorted(set(weather_covered_games)),
        "errors": weather_errors,
        "warnings": weather_warnings,
        "passed": not weather_errors,
    }
    roof_gate = {
        "required_games": roof_required_games,
        "covered_games": sorted(set(roof_covered_games)),
        "errors": roof_errors,
        "warnings": roof_warnings,
        "passed": not roof_errors,
    }
    odds_gate = {
        "required_games": [str(g.get("game_id") or "") for g in games],
        "covered_games": sorted(set(odds_covered_games)),
        "errors": odds_errors,
        "warnings": odds_warnings,
        "passed": not require_odds or not odds_errors,
    }
    passed = weather_gate["passed"] and roof_gate["passed"] and odds_gate["passed"]
    return {
        "passed": bool(passed),
        "weather_gate": weather_gate,
        "roof_gate": roof_gate,
        "odds_gate": odds_gate,
        "material_weather_adjustments": material_weather_adjustments(packet),
        "summary": "Material weather and minimal odds gates passed" if passed else "Context gates failed; keep output DO_NOT_UPLOAD",
    }


def resolve_slate_context_preflight(
    games: Sequence[Dict[str, Any]],
    venue_map: Dict[str, Dict[str, Any]],
    slate_context_packet: Optional[Dict[str, Any]] = None,
    game_venue_overrides: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    require_odds: bool = True,
) -> Dict[str, Any]:
    requirements = derive_slate_context_requirements(games, venue_map, game_venue_overrides)
    blockers: List[str] = []
    validation: Optional[Dict[str, Any]] = None
    if requirements.get("missing_venue_teams"):
        blockers.append("missing_venue_metadata")
    if requirements.get("missing_game_dates"):
        blockers.append("special_venue_game_date_missing")
    if requirements.get("unverified_park_factor_games"):
        blockers.append("unverified_special_venue_park_factor")
    if slate_context_packet is None:
        blockers.append("slate_context_packet_missing")
    else:
        validation = validate_slate_context_packet(
            slate_context_packet, games, venue_map, game_venue_overrides=game_venue_overrides,
            now=now, require_odds=require_odds,
        )
        if not validation.get("passed"):
            blockers.append("slate_context_packet_failed")
    passed = bool(requirements.get("passed") and slate_context_packet is not None and (validation or {}).get("passed"))
    return {
        "passed": passed,
        "optimizer_certification_allowed": passed,
        "requirements": requirements,
        "validation": validation,
        "blockers": blockers,
        "summary": "Context preflight passed" if passed else "Context preflight failed; stop upload-ready promotion",
    }


def emit_slate_context_packet_template(
    salary_csv_path: str,
    team_to_venue_csv_path: str,
    output_path: Optional[str] = None,
    game_venue_overrides_csv_path: Optional[str] = None,
) -> Dict[str, Any]:
    players = parse_dk_salary_csv(salary_csv_path)
    games = derive_slate_games(players)
    venue_map = load_team_venue_map(team_to_venue_csv_path)
    resolved_overrides_path = resolve_game_venue_overrides_path(team_to_venue_csv_path, game_venue_overrides_csv_path)
    overrides = load_game_venue_overrides(resolved_overrides_path) if resolved_overrides_path else {}
    requirements = derive_slate_context_requirements(games, venue_map, overrides)
    packet = {
        "schema_version": "slate_context_v2_material",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": [],
        "requirements": requirements,
        "game_venue_overrides_source": resolved_overrides_path,
        "notes": "For outdoor/open-roof games classify wind_status, delay_risk and postponement_risk. Temperature and humidity are optional. Odds require one current game total; team totals are optional.",
    }
    for row in requirements["games"]:
        weather = {
            "wind_status": "",
            "wind_speed_mph": "",
            "delay_risk": "",
            "postponement_risk": "",
            "source": "",
            "fetched_at": "",
        } if row["weather_required"] else {"not_required_reason": row["roof_type"] or "closed_or_dome"}
        packet["games"].append({
            "game_id": row["game_id"],
            "game_date": row.get("game_date", ""),
            "away_team": row["away_team"],
            "home_team": row["home_team"],
            "venue": row["venue"],
            "venue_source": row.get("venue_source", "home_team_default"),
            "projection_f5_status": row.get("projection_f5_status", "verified"),
            "run_factor_applied": row.get("run_factor_applied"),
            "hr_factor_applied": row.get("hr_factor_applied"),
            "f5_approval_note": row.get("f5_approval_note", ""),
            "venue_notes": row.get("venue_notes", ""),
            "venue_source_url": row.get("venue_source_url", ""),
            "roof_type": row["roof_type"],
            "weather_required": row["weather_required"],
            "wind_sensitivity": row.get("wind_sensitivity"),
            "wind_min_speed_mph": row.get("wind_min_speed_mph"),
            "roof_status_required": row.get("roof_status_required", False),
            "roof_status": "" if row.get("roof_status_required") else "not_required",
            "roof_status_source": "" if row.get("roof_status_required") else row["roof_type"] or "not_required",
            "roof_status_fetched_at": "",
            "weather": weather,
            "odds": {"total": "", "away_implied_total": "", "home_implied_total": "", "source": "", "fetched_at": ""},
        })
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2, sort_keys=True)
    return packet



def load_cached_json_artifact(path: str, max_age_minutes: Optional[int] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Load a cached slate artifact and optionally enforce generated/fetched age."""
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if max_age_minutes is None:
        return {"passed": True, "payload": payload, "age_minutes": None, "summary": "Cached artifact loaded"}
    timestamp = payload.get("generated_at") or payload.get("fetched_at") or payload.get("created_at")
    age = _age_minutes(timestamp, now=now)
    passed = age is not None and age <= int(max_age_minutes)
    return {
        "passed": passed,
        "payload": payload,
        "age_minutes": age,
        "summary": "Cached artifact fresh" if passed else "Cached artifact stale or missing timestamp",
    }


def pre_prune_player_pool(
    status_rows: Sequence[Dict[str, Any]],
    allow_tbd_late_swap: bool = False,
    explicit_exclude_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return active/excluded Player_ID sets before MILP construction.

    This is an efficiency gate only. It removes confirmed-out hitters and, unless
    late-swap pivot support is explicitly active, unknown/TBD hitters from teams
    with confirmed lineups. It never weakens DK hard constraints.
    """
    exclude_ids = {normalize_player_id(x) for x in (explicit_exclude_ids or []) if normalize_player_id(x)}
    active: List[str] = []
    excluded: List[Dict[str, Any]] = []
    for row in status_rows:
        pid = normalize_player_id(row.get("player_id") or row.get("Player_ID") or "")
        status = str(row.get("status") or "").strip()
        is_hitter = "P" not in str(row.get("positions") or "")
        reason = ""
        if pid in exclude_ids:
            reason = "explicit_exclude"
        elif status == "Confirmed_Out":
            reason = "confirmed_out"
        elif is_hitter and status in {"Unknown", "Bench_Risk"} and not allow_tbd_late_swap:
            reason = "tbd_without_late_swap_pivot"
        if reason:
            excluded.append({"player_id": pid, "name": row.get("name"), "team": row.get("team"), "reason": reason})
        elif pid:
            active.append(pid)
    return {
        "active_player_ids": active,
        "excluded_players": excluded,
        "active_count": len(active),
        "excluded_count": len(excluded),
        "passed": True,
        "summary": f"Pre-pruned active pool: {len(active)} active, {len(excluded)} excluded",
    }


def validate_position_coverage(players: Sequence[SalaryPlayer]) -> Dict[str, Any]:
    counts = Counter()
    for p in players:
        for pos in p.positions:
            counts[pos] += 1
    missing = []
    for pos in ["P", "C", "1B", "2B", "3B", "SS", "OF"]:
        required = 2 if pos == "P" else 3 if pos == "OF" else 1
        if counts.get(pos, 0) < required:
            missing.append({"position": pos, "available": counts.get(pos, 0), "required": required})
    return {
        "passed": not missing,
        "position_counts": dict(counts),
        "missing_position_coverage": missing,
        "summary": "Position coverage passed" if not missing else f"Position coverage failed for {len(missing)} slot type(s)",
    }


PITCHER_HAND_LINES = {"RHP", "LHP", "R/R", "L/L", "R/L", "L/R"}
_PITCHER_CONTEXT_SKIP = {
    "GAMEDAY", "TICKETS", "LINEUP", "LINEUPS", "BATTING", "ORDER", "SUMMARY",
    "ROCKIES", "DODGERS", "MARINERS", "ATHLETICS", "PADRES", "PHILLIES",
}


def parse_declared_pitchers_text(text: str) -> List[str]:
    """Extract probable/declared pitcher names from common MLB lineup pastes.

    The parser is intentionally conservative: it treats a non-section line as a
    pitcher only when the following line is a pitcher-handedness marker such as
    RHP or LHP. It does not validate role; downstream audit reconciles names to
    salary rows and surfaces unresolved/high-signal anomalies.
    """
    lines = [str(x).strip() for x in str(text or "").splitlines() if str(x).strip()]
    names: List[str] = []
    for i, line in enumerate(lines[:-1]):
        nxt = lines[i + 1].strip().upper()
        if nxt not in PITCHER_HAND_LINES:
            continue
        upper = line.upper()
        if any(token in upper for token in ["@", "LINEUP", "GAMEDAY", "TICKET"]):
            continue
        if upper in _PITCHER_CONTEXT_SKIP:
            continue
        if len(line.split()) < 2:
            continue
        if line not in names:
            names.append(line)
    return names


def _safe_float(value: Any) -> float:
    try:
        return float(str(value or "").replace(",", "").strip() or 0.0)
    except (TypeError, ValueError):
        return 0.0


def audit_pitcher_pool(
    salary_players: Sequence[SalaryPlayer],
    declared_pitcher_names: Optional[Sequence[str]] = None,
    declared_pitcher_ids: Optional[Sequence[str]] = None,
    high_signal_salary_rank: int = 6,
    high_signal_avg_points_rank: int = 6,
) -> Dict[str, Any]:
    """Audit every rosterable salary-row pitcher before projections.

    Purpose: prevent a viable DK pitcher from being omitted because the pasted
    probable-starter block listed a different pitcher, an opener/bulk role, or a
    late SP change. This is a review gate, not a projection or roster decision.
    """
    pitchers = [p for p in salary_players if "P" in set(p.positions)]
    declared_names = {normalize_name(n) for n in (declared_pitcher_names or []) if normalize_name(n)}
    declared_ids = {normalize_player_id(x) for x in (declared_pitcher_ids or []) if normalize_player_id(x)}
    has_declared_context = bool(declared_names or declared_ids)

    salaries_sorted = sorted({float(p.salary) for p in pitchers}, reverse=True)
    salary_rank_by_value = {sal: idx + 1 for idx, sal in enumerate(salaries_sorted)}
    avg_by_pid = {p.player_id: _safe_float(p.raw.get("AvgPointsPerGame") or p.raw.get("Avg Points Per Game")) for p in pitchers}
    avg_sorted = sorted({v for v in avg_by_pid.values() if v > 0}, reverse=True)
    avg_rank_by_value = {val: idx + 1 for idx, val in enumerate(avg_sorted)}

    rows: List[Dict[str, Any]] = []
    high_signal_unverified: List[Dict[str, Any]] = []
    review_required: List[Dict[str, Any]] = []
    max_salary = max([p.salary for p in pitchers], default=0.0)

    for p in sorted(pitchers, key=lambda x: (-x.salary, normalize_name(x.name), x.player_id)):
        name_key = normalize_name(p.name)
        declared = (p.player_id in declared_ids) or (name_key in declared_names)
        salary_rank = salary_rank_by_value.get(float(p.salary))
        avg_points = avg_by_pid.get(p.player_id, 0.0)
        avg_rank = avg_rank_by_value.get(avg_points) if avg_points > 0 else None
        high_signal = bool(
            has_declared_context and not declared and (
                (salary_rank is not None and salary_rank <= int(high_signal_salary_rank))
                or (avg_rank is not None and avg_rank <= int(high_signal_avg_points_rank))
                or (max_salary > 0 and p.salary >= 0.72 * max_salary)
            )
        )
        row = {
            "player_id": p.player_id,
            "name": p.name,
            "team": p.team,
            "opponent": p.opponent,
            "salary": p.salary,
            "avg_points_per_game": avg_points,
            "salary_rank_among_pitchers": salary_rank,
            "avg_points_rank_among_pitchers": avg_rank,
            "declared_pitcher_match": declared,
            "review_required": bool(has_declared_context and not declared),
            "high_signal_unverified": high_signal,
            "recommended_gate": "verify_role_or_explicitly_exclude" if high_signal else "tag_role" if has_declared_context and not declared else "declared_probable_sp" if declared else "no_declared_sp_context",
        }
        rows.append(row)
        if row["review_required"]:
            review_required.append(row)
        if high_signal:
            high_signal_unverified.append(row)

    return {
        "passed": not high_signal_unverified,
        "declared_pitcher_names": list(declared_pitcher_names or []),
        "declared_pitcher_ids": list(declared_pitcher_ids or []),
        "pitcher_count": len(pitchers),
        "review_required_count": len(review_required),
        "high_signal_unverified_count": len(high_signal_unverified),
        "rows": rows,
        "high_signal_unverified_pitchers": high_signal_unverified,
        "summary": (
            "Pitcher pool audit passed" if not high_signal_unverified
            else f"Pitcher pool audit requires role review for {len(high_signal_unverified)} high-signal pitcher(s)"
        ),
    }


def parse_confirmed_lineups_text(text: str) -> List[ParsedLineupHitter]:
    """Parse simple pasted lineup blocks headed by '<TEAM> Lineup'.

    This intentionally handles the common DK/operator paste format only. If the
    parse is incomplete, downstream reconciliation surfaces missing slots rather
    than guessing.
    """
    hitters: List[ParsedLineupHitter] = []
    current_team = ""
    slot = 0
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m_header = re.match(r"^([A-Za-z]{2,4})\s+Lineup\b", line, re.I)
        if m_header:
            current_team = m_header.group(1).upper()
            slot = 0
            continue
        if not current_team:
            continue
        # Example: T Turner (R) SS / Kyle Schwarber (L) OF
        m = re.match(r"^(.+?)\s*(?:\(([RLS])\))?\s+([A-Z0-9/]+)$", line)
        if not m:
            continue
        name, bats, pos = m.group(1).strip(), m.group(2) or "", m.group(3).upper()
        # avoid parsing section labels that happen to fit
        if "lineup" in name.lower() or len(name) < 2:
            continue
        slot += 1
        hitters.append(ParsedLineupHitter(current_team, slot, name, bats, pos))
    return hitters


def reconcile_lineups_to_salary(
    lineup_hitters: Sequence[ParsedLineupHitter],
    salary_players: Sequence[SalaryPlayer],
    expected_teams: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    by_team_slots: Dict[str, Dict[int, ParsedLineupHitter]] = defaultdict(dict)
    for h in lineup_hitters:
        by_team_slots[h.team][h.slot] = h
    salary_names_by_team: Dict[str, Dict[str, SalaryPlayer]] = defaultdict(dict)
    for p in salary_players:
        if set(p.positions) & HITTER_SLOTS:
            salary_names_by_team[p.team][normalize_name(p.name)] = p
    teams = sorted(set(expected_teams or []) | set(by_team_slots.keys()))
    rows = []
    missing_slots = []
    unresolved = []
    matched_ids = []
    for team in teams:
        slots = by_team_slots.get(team, {})
        team_missing = [i for i in range(1, 10) if i not in slots]
        if team_missing:
            missing_slots.append({"team": team, "missing_slots": team_missing})
        for slot_num, hitter in sorted(slots.items()):
            key = normalize_name(hitter.name)
            match = salary_names_by_team.get(team, {}).get(key)
            status = "matched" if match else "unresolved"
            if match:
                matched_ids.append(match.player_id)
            else:
                unresolved.append({"team": team, "slot": slot_num, "name": hitter.name})
            rows.append({
                "team": team,
                "slot": slot_num,
                "name": hitter.name,
                "position": hitter.position,
                "status": status,
                "player_id": match.player_id if match else "",
            })
    return {
        "passed": not missing_slots and not unresolved,
        "lineup_rows": rows,
        "matched_player_ids": matched_ids,
        "missing_slots": missing_slots,
        "unresolved_players": unresolved,
        "summary": "Confirmed lineup reconciliation passed" if not missing_slots and not unresolved else f"Lineup reconciliation found {len(missing_slots)} team-slot issue(s) and {len(unresolved)} unresolved player(s)",
    }


def build_player_status_table(
    salary_players: Sequence[SalaryPlayer],
    lineup_reconciliation: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    confirmed = set((lineup_reconciliation or {}).get("matched_player_ids") or [])
    confirmed_teams = {r["team"] for r in (lineup_reconciliation or {}).get("lineup_rows", [])}
    rows = []
    for p in salary_players:
        pos_set = set(p.positions)
        if p.player_id in confirmed:
            status = "Confirmed_Starter"
        elif p.team in confirmed_teams and (pos_set & HITTER_SLOTS):
            status = "Confirmed_Out"
        elif "P" in pos_set:
            status = "Projected_Starter"
        else:
            status = "Unknown"
        rows.append({
            "player_id": p.player_id,
            "name": p.name,
            "team": p.team,
            "positions": "/".join(p.positions),
            "salary": p.salary,
            "game_id": p.game_id,
            "opponent": p.opponent,
            "status": status,
        })
    return rows


def optimizer_shell_preflight(players: Sequence[SalaryPlayer]) -> Dict[str, Any]:
    """Run a neutral MILP shell to catch impossible salary/position/game shapes.

    The neutral projections are not a DFS opinion. This function is a feasibility
    test only and should run before expensive research when scipy is available.
    """
    try:
        import pandas as pd
        from mlb_engine.optimize import optimizer_v3

    except Exception as exc:  # pragma: no cover - dependency/environment path
        return {"passed": False, "skipped": True, "errors": [str(exc)], "summary": "Optimizer shell preflight skipped"}

    rows = []
    for p in players:
        if not p.player_id or not p.positions or p.salary <= 0:
            continue
        rows.append({
            "Player_ID": p.player_id,
            "Name": p.name,
            "Team": p.team,
            "Opponent": p.opponent,
            "Position": "/".join(p.positions),
            "Salary": p.salary,
            "Base_Projection": 10.0 if "P" not in p.positions else 15.0,
            "Floor": 7.0 if "P" not in p.positions else 10.0,
            "Ceiling": 10.0 if "P" not in p.positions else 15.0,
            "Ownership_Tier": "Mid",
            "Confidence_Tier": "NeutralShell",
            "Locked": False,
            "Excluded": False,
            "Stack_Group": p.team,
            "Notes": "",
            "Salary_Suppression": 0,
            "Base_Projection_MetaLineup": 10.0,
            "Game_ID": p.game_id or f"{p.team}_{p.opponent}",
        })
    if not rows:
        return {"passed": False, "skipped": False, "errors": ["No usable salary rows"], "summary": "Optimizer shell preflight failed"}
    df = pd.DataFrame(rows)
    try:
        preflight = optimizer_v3.runtime_preflight()
        if not preflight.get("optimizer_certifiable"):
            return {"passed": False, "skipped": True, "preflight": preflight, "errors": ["scipy MILP unavailable"], "summary": "Optimizer shell preflight skipped"}
        lineup, _obj = optimizer_v3.build_single_lineup(df, target="ceiling")
        if lineup is None:
            return {"passed": False, "skipped": False, "preflight": preflight, "errors": ["Neutral shell infeasible"], "summary": "Optimizer shell preflight failed"}
        return {"passed": True, "skipped": False, "preflight": preflight, "lineup_size": int(len(lineup)), "salary_used": float(lineup["Salary"].sum()), "summary": "Optimizer shell preflight passed"}
    except Exception as exc:
        return {"passed": False, "skipped": False, "errors": [str(exc)], "summary": "Optimizer shell preflight failed"}


def emit_slate_preflight_report(
    salary_csv_path: str,
    confirmed_lineups_text: str = "",
    run_optimizer_shell: bool = True,
    team_to_venue_csv_path: Optional[str] = None,
    slate_context_packet: Optional[Dict[str, Any]] = None,
    require_slate_context_before_optimizer: Optional[bool] = None,
    game_venue_overrides_csv_path: Optional[str] = None,
) -> Dict[str, Any]:
    schema = validate_salary_schema(salary_csv_path)
    if not schema["passed"]:
        return {"passed": False, "salary_schema": schema, "summary": schema["summary"]}
    players = parse_dk_salary_csv(salary_csv_path)
    games = derive_slate_games(players)
    teams = sorted({p.team for p in players if p.team})
    position_coverage = validate_position_coverage(players)
    lineup_parse = parse_confirmed_lineups_text(confirmed_lineups_text)
    declared_pitchers = parse_declared_pitchers_text(confirmed_lineups_text)
    lineup_recon = reconcile_lineups_to_salary(lineup_parse, players, expected_teams=None) if lineup_parse else None
    pitcher_audit = audit_pitcher_pool(players, declared_pitcher_names=declared_pitchers)
    statuses = build_player_status_table(players, lineup_recon)
    slate_context_requirements = None
    slate_context_validation = None
    slate_context_preflight = None
    context_gate_required = bool(team_to_venue_csv_path) if require_slate_context_before_optimizer is None else bool(require_slate_context_before_optimizer)
    context_allows_optimizer = True
    if team_to_venue_csv_path:
        venue_map = load_team_venue_map(team_to_venue_csv_path)
        resolved_overrides_path = resolve_game_venue_overrides_path(team_to_venue_csv_path, game_venue_overrides_csv_path)
        game_venue_overrides = load_game_venue_overrides(resolved_overrides_path) if resolved_overrides_path else {}
        slate_context_preflight = resolve_slate_context_preflight(
            games,
            venue_map,
            slate_context_packet,
            game_venue_overrides=game_venue_overrides,
        )
        slate_context_requirements = slate_context_preflight["requirements"]
        slate_context_validation = slate_context_preflight.get("validation")
        context_allows_optimizer = bool(slate_context_preflight.get("optimizer_certification_allowed")) or not context_gate_required
    if run_optimizer_shell and context_allows_optimizer:
        shell = optimizer_shell_preflight(players)
    elif run_optimizer_shell and not context_allows_optimizer:
        shell = {"passed": False, "skipped": True, "blocked_by": "slate_context_preflight", "summary": "Optimizer shell preflight skipped until slate context preflight passes"}
    else:
        shell = {"skipped": True, "summary": "Optimizer shell preflight not requested"}
    context_passed = True if not context_gate_required else bool(slate_context_preflight and slate_context_preflight.get("passed"))
    passed = bool(schema["passed"] and position_coverage["passed"] and pitcher_audit["passed"] and (lineup_recon is None or lineup_recon["passed"]) and context_passed and (shell.get("passed") or (shell.get("skipped") and not shell.get("blocked_by"))))
    return {
        "passed": passed,
        "salary_schema": schema,
        "player_count": len(players),
        "team_count": len(teams),
        "teams": teams,
        "games": games,
        "position_coverage": position_coverage,
        "confirmed_lineup_parse_count": len(lineup_parse),
        "declared_pitcher_parse_count": len(declared_pitchers),
        "lineup_reconciliation": lineup_recon,
        "pitcher_pool_audit": pitcher_audit,
        "player_status_counts": dict(Counter(r["status"] for r in statuses)),
        "slate_context_requirements": slate_context_requirements,
        "slate_context_validation": slate_context_validation,
        "slate_context_preflight": slate_context_preflight,
        "game_venue_overrides_source": resolved_overrides_path if team_to_venue_csv_path else None,
        "optimizer_shell_preflight": shell,
        "summary": "Slate intake preflight passed" if passed else "Slate intake preflight failed; resolve before research/projections/optimizer",
    }


# ---------------------------------------------------------------------------
# v1.6 Deterministic F5 computation from the project's own data files
# ---------------------------------------------------------------------------
# f5_park_factors.csv and f5_weather_adjustments.csv previously existed only as
# reference tables the operator eyeballed while setting F5 by hand, which made
# the one environment factor unreproducible. compute_f5_factor() makes F5 a
# deterministic, auditable function of those files plus the classified weather.

WIND_SPEED_BANDS = (("8-12", 8.0, 12.999), ("13-17", 13.0, 17.999), ("18+", 18.0, float("inf")))


def load_f5_park_factors(path: str) -> Dict[str, Dict[str, Any]]:
    """Load applied park factors keyed by exact Venue string."""
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            venue = str(row.get("Venue") or "").strip()
            if not venue:
                continue
            out[venue] = {
                "venue": venue,
                "run_factor_applied": _to_float_or_none(row.get("Run_Factor_Applied")),
                "hr_factor_applied": _to_float_or_none(row.get("HR_Factor_Applied")),
                "run_factor_raw": _to_float_or_none(row.get("Run_Factor_Raw")),
                "hr_factor_raw": _to_float_or_none(row.get("HR_Factor_Raw")),
                "wind_sensitivity": _normalize_sensitivity(row.get("Wind_Sensitivity")),
                "last_updated": str(row.get("Last_Updated") or "").strip(),
            }
    return out


def load_f5_weather_adjustments(path: str) -> List[Dict[str, Any]]:
    """Load the weather adjustment table rows verbatim with typed factors."""
    rows: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append({
                "adjustment_type": str(row.get("Adjustment_Type") or "").strip().lower(),
                "level": str(row.get("Level") or "").strip().lower(),
                "direction": str(row.get("Direction") or "").strip().lower(),
                "hitter_factor": _to_float_or_none(row.get("Hitter_Factor")) or 1.0,
                "pitcher_factor": _to_float_or_none(row.get("Pitcher_Factor")) or 1.0,
                "game_exposure_cap": _to_float_or_none(row.get("Game_Exposure_Cap")),
                "exclude_game": str(row.get("Exclude_Game") or "").strip().lower() in {"true", "1", "yes"},
                "notes": str(row.get("Notes") or "").strip(),
            })
    return rows


def _wind_band_for_speed(speed_mph: float) -> str:
    for label, low, high in WIND_SPEED_BANDS:
        if low <= speed_mph <= high:
            return label
    return ""


def _adjustment_lookup(rows: Sequence[Dict[str, Any]], adjustment_type: str, level: str, direction: str = "") -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["adjustment_type"] != adjustment_type:
            continue
        if row["level"] != level:
            continue
        if direction and row["direction"] != direction:
            continue
        if not direction and row["direction"]:
            continue
        return row
    return None


def compute_f5_factor(
    venue_name: str,
    weather: Dict[str, Any],
    park_factors: Dict[str, Dict[str, Any]],
    adjustments: Sequence[Dict[str, Any]],
    wind_threshold_mph: Optional[float] = None,
    roof_closed: bool = False,
) -> Dict[str, Any]:
    """Compute deterministic F5 components for one game.

    Returns hitter/pitcher F5 factors plus the postponement-derived game
    exposure cap and exclusion flag from f5_weather_adjustments.csv.

    Composition rules, stated so they are auditable rather than implied:
    - hitter_f5 = park Run_Factor_Applied x wind hitter factor.
    - pitcher_f5 = wind pitcher factor x delay pitcher factor. The park
      component for pitchers is intentionally 1.0: the run environment already
      moves through opposing hitters, and inventing an inverse-park pitcher
      factor would double count. Operators may layer pitcher park judgment in
      F4 explicitly.
    - Wind applies only when direction is out/in, speed meets the venue
      threshold, and the roof is not closed. Cross/variable/not_material wind
      and dome/closed-roof games take no wind adjustment.
    - hr_environment is surfaced for right-tail tagging; it is NOT multiplied
      into F5.
    All outputs are deterministic review inputs to Base x F1..F5; nothing here
    is a simulation or an ROI claim.
    """
    park = park_factors.get(str(venue_name or "").strip(), {})
    park_run = float(park.get("run_factor_applied") or 1.0)
    components: Dict[str, Any] = {
        "venue": str(venue_name or "").strip(),
        "park_run_factor": park_run,
        "wind_row": None,
        "delay_row": None,
        "postponement_row": None,
    }
    hitter = park_run
    pitcher = 1.0

    wind_status = str(weather.get("wind_status") or "").strip().lower()
    wind_speed = _to_float_or_none(weather.get("wind_speed_mph"))
    threshold = float(wind_threshold_mph) if wind_threshold_mph is not None else None
    wind_applies = (
        not roof_closed
        and wind_status in {"out", "in"}
        and wind_speed is not None
        and (threshold is None or wind_speed >= threshold)
    )
    if wind_applies:
        band = _wind_band_for_speed(float(wind_speed))
        row = _adjustment_lookup(adjustments, "wind", band, wind_status) if band else None
        if row:
            hitter *= row["hitter_factor"]
            pitcher *= row["pitcher_factor"]
            components["wind_row"] = {"level": band, "direction": wind_status, **{k: row[k] for k in ("hitter_factor", "pitcher_factor")}}

    delay = str(weather.get("delay_risk") or "none").strip().lower()
    delay_row = _adjustment_lookup(adjustments, "delay", delay)
    if delay_row:
        pitcher *= delay_row["pitcher_factor"]
        components["delay_row"] = {"level": delay, "pitcher_factor": delay_row["pitcher_factor"]}

    postponement = str(weather.get("postponement_risk") or "none").strip().lower()
    post_row = _adjustment_lookup(adjustments, "postponement", postponement)
    game_exposure_cap = None
    exclude_game = False
    if post_row:
        game_exposure_cap = post_row["game_exposure_cap"]
        exclude_game = bool(post_row["exclude_game"])
        components["postponement_row"] = {
            "level": postponement,
            "game_exposure_cap": game_exposure_cap,
            "exclude_game": exclude_game,
        }

    return {
        "hitter_f5": round(hitter, 6),
        "pitcher_f5": round(pitcher, 6),
        "hr_environment": float(park.get("hr_factor_applied") or 1.0),
        "game_exposure_cap": game_exposure_cap,
        "exclude_game": exclude_game,
        "components": components,
        "formula": "hitter_f5 = park_run x wind_hitter; pitcher_f5 = wind_pitcher x delay_pitcher",
    }


# ---------------------------------------------------------------------------
# v1.7 slate clock: first lock and the T-minus-buffer delivery deadline
# ---------------------------------------------------------------------------

_GAME_INFO_DT_RE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET",
    re.IGNORECASE,
)


def _eastern_tz(year: int, month: int, day: int):
    """America/New_York via zoneinfo, with a documented DST approximation fallback."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        # Approximation: EDT mid-March through very early November, else EST.
        edt = (3 < month < 11) or (month == 3 and day >= 15) or (month == 11 and day <= 1)
        return timezone(timedelta(hours=-4 if edt else -5))


def parse_game_info_datetime(game_info: Any) -> Optional[datetime]:
    """Parse the DK Game Info datetime ('AAA@BBB 07/08/2026 07:05PM ET') to an
    aware datetime, or None when the cell carries no parseable ET timestamp
    (for example 'Final' or 'Postponed')."""
    m = _GAME_INFO_DT_RE.search(str(game_info or ""))
    if not m:
        return None
    mm, dd, yyyy, hh, mi, ap = m.groups()
    month, day, year = int(mm), int(dd), int(yyyy)
    hour = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
    return datetime(year, month, day, hour, int(mi), tzinfo=_eastern_tz(year, month, day))


def slate_clock(
    salary_csv: Optional[str] = None,
    *,
    players: Optional[Sequence[SalaryPlayer]] = None,
    lock_time_by_game_id: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    buffer_minutes: int = 5,
) -> Dict[str, Any]:
    """First-lock clock and the T-minus-``buffer_minutes`` delivery deadline.

    Sources, in priority order: an explicit ``lock_time_by_game_id`` map (UTC ISO
    strings or datetimes, as emitted by the lineups-feed adapter), an already
    parsed ``players`` sequence, or a ``salary_csv`` path whose Game Info column
    carries the ET game datetimes. The first game to start is the first contest
    lock on a DK Classic slate; the delivery deadline is that lock minus
    ``buffer_minutes`` (default 5 per the standing delivery rule: the certified
    file is presented no later than T-5).

    Deterministic bookkeeping for the checkpoint and the build report. It makes
    the clock visible; it is never a guarantee the session meets it, and it is
    never a win-rate, ROI, or probability claim.
    """
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    locks: Dict[str, datetime] = {}
    source = None
    if lock_time_by_game_id:
        source = "lock_time_map"
        for gid, value in lock_time_by_game_id.items():
            if isinstance(value, datetime):
                dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            else:
                try:
                    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            locks[str(gid)] = dt
    else:
        plist = list(players) if players is not None else (
            parse_dk_salary_csv(str(salary_csv)) if salary_csv else []
        )
        source = "salary_game_info"
        for sp in plist:
            dt = parse_game_info_datetime(sp.game_info)
            if dt is None:
                continue
            gid = sp.game_id or sp.game_info
            if gid not in locks or dt < locks[gid]:
                locks[str(gid)] = dt

    if not locks:
        return {
            "available": False,
            "source": source,
            "note": "no parseable game datetimes; clock unavailable",
            "buffer_minutes": int(buffer_minutes),
        }

    first_gid, first_dt = min(locks.items(), key=lambda kv: kv[1])

    # Cross-check the feed-derived clock against the salary file. The salary CSV is
    # authoritative for which games are on the slate, so when a feed map disagrees
    # about the first lock the salary file wins and the disagreement is surfaced.
    # A feed keyed by matchup alone reports a doubleheader's night game for a
    # matinee draftgroup, which moves the deadline the wrong way by hours.
    cross_check: Optional[Dict[str, Any]] = None
    if source == "lock_time_map":
        plist = list(players) if players is not None else (
            parse_dk_salary_csv(str(salary_csv)) if salary_csv else []
        )
        salary_locks: Dict[str, datetime] = {}
        for sp in plist:
            dt = parse_game_info_datetime(sp.game_info)
            if dt is None:
                continue
            gid = str(sp.game_id or sp.game_info)
            if gid not in salary_locks or dt < salary_locks[gid]:
                salary_locks[gid] = dt
        if salary_locks:
            sal_gid, sal_dt = min(salary_locks.items(), key=lambda kv: kv[1])
            if sal_dt.tzinfo is None:
                sal_dt = sal_dt.replace(tzinfo=timezone.utc)
            drift = (first_dt - sal_dt).total_seconds() / 60.0
            agrees = abs(drift) <= 5.0 and sal_gid == first_gid
            cross_check = {
                "checked": True,
                "agrees": bool(agrees),
                "salary_first_lock_game_id": sal_gid,
                "salary_first_lock_utc": sal_dt.astimezone(timezone.utc).isoformat(),
                "feed_first_lock_game_id": first_gid,
                "drift_minutes": round(drift, 1),
            }
            if not agrees:
                cross_check["note"] = (
                    "feed lock map disagrees with the authoritative salary file; "
                    "salary file used. Check for a doubleheader leg collision."
                )
                first_gid, first_dt = sal_gid, sal_dt
                locks = dict(salary_locks)
                source = "salary_game_info_after_cross_check"

    deadline = first_dt - timedelta(minutes=int(buffer_minutes))
    minutes_to_lock = (first_dt - now_dt).total_seconds() / 60.0
    minutes_to_deadline = (deadline - now_dt).total_seconds() / 60.0
    return {
        "available": True,
        "source": source,
        "first_lock_game_id": first_gid,
        "first_lock_utc": first_dt.astimezone(timezone.utc).isoformat(),
        "deadline_utc": deadline.astimezone(timezone.utc).isoformat(),
        "now_utc": now_dt.astimezone(timezone.utc).isoformat(),
        "buffer_minutes": int(buffer_minutes),
        "minutes_to_lock": round(minutes_to_lock, 1),
        "minutes_to_deadline": round(minutes_to_deadline, 1),
        "past_deadline": minutes_to_deadline < 0,
        "salary_cross_check": cross_check,
        "lock_time_by_game_id": {
            gid: dt.astimezone(timezone.utc).isoformat() for gid, dt in sorted(locks.items())
        },
    }
