#!/usr/bin/env python3
"""fetch_slate_bundle.py — local pre-fetch for the MLB Classic engine.

Runs on Ben's machine (any Python 3.9+, standard library only) and bundles the
three free live sources into ONE ``slate_bundle.json`` so per-slate intake
collapses from five hand-ferried artifacts to two (this bundle plus the
DKSalaries/DKEntries CSVs). It is an UNTRACKED companion script, not a
checksummed engine file: live fetching stays outside the audited engine on
purpose so projection construction stays deterministic.

Sources (all free tiers):
  1. MLB Stats API — schedule + probables + lineups, emitted in EXACTLY the
     mlb-lineups feed shape the engine already consumes
     (live_data_adapters.build_status_map_from_lineups_feed,
     extract_opposing_probables, extract_batter_hands,
     platoon_order_adapter.extract_opp_throws_from_lineups,
     tail_candidate_scanner lineups_json).
  2. the-odds-api.com v4 — DK+FD full-game totals, emitted as the RAW events
     payload so live_data_adapters.parse_the_odds_api_totals consumes it
     unchanged. Markets are totals AND h2h: the moneyline is what splits a
     game total into per-team implied totals, and without it F1 can price the
     game environment but cannot pick a side. Costs credits per market per
     region, so roughly double a totals-only pull, on the 500/month free
     plan. The API
     key is read from the THE_ODDS_API_KEY environment variable, is never
     printed, and is scrubbed from any error text. Skipped with a warning when
     the variable is unset.
  3. Open-Meteo — hourly forecast at each venue's coordinates around first
     pitch (temperature F, wind mph, wind direction, precipitation
     probability). Coordinates, roof type, and wind thresholds come from the
     engine's team_to_venue.csv. Fixed domes are skipped. NOTE: a forecast is
     never a roof status; the engine's fresh-retractable-roof rule still
     requires manual confirmation, and each retractable venue is flagged.

Each source fails independently: a failure is recorded in ``warnings`` and the
partial bundle is still written, because a bundle with lineups and no odds is
still worth uploading. Everything in the bundle is raw observed data or a
posted price, never a projection, edge, or probability claim.

Usage:
  python fetch_slate_bundle.py [--date YYYY-MM-DD] [--venues team_to_venue.csv]
                               [--out slate_bundle.json] [--skip-odds]
                               [--skip-weather] [--pretty]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
MLB_PEOPLE = "https://statsapi.mlb.com/api/v1/people"
ODDS_API = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
ODDS_KEY_ENV = "THE_ODDS_API_KEY"
TIMEOUT = 25.0
FIXED_ROOFS = {"dome"}  # no weather fetch; retractable/temporary/outdoor are fetched
DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file. Delegates to mlb_engine.repo_env.

    R29(5a): this loader used to be implemented here and nowhere else, so this
    script found the key and build_slate.py's odds auto-fetch did not. One rule
    with one implementation; the semantics are unchanged (an explicit export
    always wins over the file, and nothing here logs the file's contents).

    ``mlb_engine.repo_env`` is stdlib-only, so importing it keeps this script's
    no-dependency design intact: it still runs with neither pandas nor scipy
    installed, which is the state in which fetching a bundle matters most.
    """
    repo = str(Path(__file__).resolve().parents[1])
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from mlb_engine.repo_env import load_repo_dotenv

    load_repo_dotenv(path)


_load_dotenv(DOTENV_PATH)


def _scrub(text: str, secret: Optional[str]) -> str:
    return text.replace(secret, "***") if secret else text


def _get_json(url: str, secret: Optional[str] = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "mlb-classic-slate-bundle/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RuntimeError(_scrub(f"HTTP {exc.code} for {url}: {body}", secret)) from None
    except Exception as exc:  # URLError, timeout, JSON decode
        raise RuntimeError(_scrub(f"{type(exc).__name__} for {url}: {exc}", secret)) from None


def _today_et() -> str:
    """Today's ET slate date, from the one ET authority (R65).

    This used to approximate ET as a hardcoded UTC-4 with the comment "EDT
    covers the MLB season". It does not: in EST months the offset is UTC-5, so
    any instant between 04:00 and 05:00 UTC returned tomorrow's date, and
    offseason archive work runs in exactly those months. repo_env is stdlib-only
    (ZoneInfo ships with Python), so importing it keeps this script's
    dependency-free property, the same reasoning the .env loader above uses.
    """
    from mlb_engine.repo_env import today_et
    return today_et()


# --------------------------------------------------------------------------- #
# 1. MLB Stats API -> mlb-lineups feed shape
# --------------------------------------------------------------------------- #
def fetch_lineups_feed(date: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
    params = urllib.parse.urlencode({
        "sportId": 1, "date": date,
        "hydrate": "lineups,probablePitcher(note),team",
    })
    schedule = _get_json(f"{MLB_SCHEDULE}?{params}")
    games_out: List[Dict[str, Any]] = []
    lineup_ids: List[int] = []
    raw_games: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    for date_block in schedule.get("dates") or []:
        for game in date_block.get("games") or []:
            entry: Dict[str, Any] = {
                "game_pk": game.get("gamePk"),
                "game_date_utc": game.get("gameDate"),
                "game_time_et": "",
                "status": ((game.get("status") or {}).get("detailedState")) or "",
                "venue": ((game.get("venue") or {}).get("name")) or "",
                "doubleheader": game.get("doubleHeader", "N"),
                "game_number": game.get("gameNumber", 1),
            }
            try:
                utc_dt = datetime.strptime(entry["game_date_utc"], "%Y-%m-%dT%H:%M:%SZ")
                entry["game_time_et"] = (utc_dt - timedelta(hours=4)).strftime("%-I:%M %p")
            except Exception:
                pass
            raw_games.append((game, entry))
            games_out.append(entry)

    lineups_by_game = _fetch_lineups_by_game(raw_games, warnings)
    probable_ids: List[int] = []
    for game, entry in raw_games:
        teams = game.get("teams") or {}
        for side_key in ("away", "home"):
            side = teams.get(side_key) or {}
            team = side.get("team") or {}
            record = side.get("leagueRecord") or {}
            probable = side.get("probablePitcher") or None
            probable_out = None
            if probable and probable.get("fullName"):
                hand = (((probable.get("pitchHand") or {}).get("code")) or None)
                probable_out = {"id": probable.get("id"), "name": probable.get("fullName"), "hand": hand}
                if isinstance(probable.get("id"), int):
                    probable_ids.append(probable["id"])
            lineup = lineups_by_game.get((entry["game_pk"], side_key), [])
            for hitter in lineup:
                if isinstance(hitter.get("id"), int):
                    lineup_ids.append(hitter["id"])
            status = "confirmed" if len(lineup) >= 9 else ("partial" if lineup else "tbd")
            entry[side_key] = {
                "team_id": team.get("id"),
                "team_abbrev": team.get("abbreviation") or "",
                "team_name": team.get("name") or "",
                "record": f"{record.get('wins', '')}-{record.get('losses', '')}",
                "probable_pitcher": probable_out,
                "lineup_status": status,
                "lineup": lineup,
            }

    _backfill_people(games_out, sorted(set(lineup_ids)),
                     sorted(set(probable_ids)), warnings)
    return {"date": date, "fetched_at": datetime.now(timezone.utc).isoformat(), "games": games_out}


def _fetch_lineups_by_game(raw_games, warnings) -> Dict[Tuple[Any, str], List[Dict[str, Any]]]:
    out: Dict[Tuple[Any, str], List[Dict[str, Any]]] = {}
    for game, entry in raw_games:
        lineups = game.get("lineups") or {}
        for side_key, list_key in (("away", "awayPlayers"), ("home", "homePlayers")):
            players = lineups.get(list_key) or []
            side_lineup = []
            for order, player in enumerate(players, start=1):
                side_lineup.append({
                    "order": order,
                    "id": player.get("id"),
                    "name": player.get("fullName") or "",
                    "position": ((player.get("primaryPosition") or {}).get("abbreviation")) or "",
                    "bat_side": None,  # backfilled from /people
                })
            if side_lineup:
                out[(entry["game_pk"], side_key)] = side_lineup
    return out


def _backfill_people(games_out, hitter_ids: List[int], probable_ids: List[int],
                     warnings: List[str]) -> None:
    """Fill `bat_side` on every lineup hitter AND `hand` on every probable.

    R190. Both halves of F4's platoon term come from `/people`, and until
    2026-08-23 this call fetched only one of them. The schedule hydrate
    (`probablePitcher(note)`) does not return `pitchHand`, so a probable's
    `hand` was whatever the hydrate happened to carry, which is nothing:
    measured 30 of 30 probables at `hand: None` on 2026-08-19, and 30 of 30
    again on 2026-08-18. F4's platoon component compares a hitter's `bat_side`
    against the OPPOSING probable's hand, so a null hand on every side makes
    that component inert for every hitter on the slate while `bat_side` sits
    populated on all 270 -- the brief reads `f4_platoon_applied: 0` beside
    `f4_hitters_scored: 162` and nothing else says why. Three BUILD sessions
    filed it (08-18, and twice on 08-19) and each worked around it with a
    second hand-rolled `/people` call; the reference implementation SKILL.md
    tells a sandbox session to copy is the one path that never did it, so a
    session copying the reference correctly still shipped the dead term.

    One request covers both id sets: `/people` returns `batSide` and
    `pitchHand` in the same person object, so the union costs no extra call.

    A named probable still holding a null hand AFTER the backfill is a fact
    worth a warning, not a silent field. It means the id was missing or
    `/people` declined it, and the platoon term is dead for the whole opposing
    side. The engine names the same fact in
    `pool_report.opposing_probables_incomplete.no_hand` (R117(b)); this warns
    at the source, where the fetch could still be retried.
    """
    ids = sorted(set(hitter_ids) | set(probable_ids))
    sides: Dict[int, Optional[str]] = {}
    positions: Dict[int, str] = {}
    hands: Dict[int, Optional[str]] = {}
    for start in range(0, len(ids), 100):
        chunk = ids[start:start + 100]
        try:
            payload = _get_json(f"{MLB_PEOPLE}?personIds={','.join(map(str, chunk))}")
        except RuntimeError as exc:
            warnings.append(f"people backfill failed for {len(chunk)} ids: {exc}")
            continue
        for person in payload.get("people") or []:
            sides[person.get("id")] = ((person.get("batSide") or {}).get("code")) or None
            positions[person.get("id")] = ((person.get("primaryPosition") or {}).get("abbreviation")) or ""
            hands[person.get("id")] = ((person.get("pitchHand") or {}).get("code")) or None
    unresolved: List[str] = []
    for game in games_out:
        for side_key in ("away", "home"):
            block = (game.get(side_key) or {})
            for hitter in block.get("lineup") or []:
                pid = hitter.get("id")
                if pid in sides:
                    hitter["bat_side"] = sides[pid]
                if not hitter.get("position") and pid in positions:
                    hitter["position"] = positions[pid]
            probable = block.get("probable_pitcher") or None
            if not probable or not probable.get("name"):
                continue
            if not probable.get("hand") and hands.get(probable.get("id")):
                probable["hand"] = hands[probable["id"]]
            if not probable.get("hand"):
                unresolved.append(
                    f"{block.get('team_abbrev') or '?'} {probable.get('name')}")
    if unresolved:
        warnings.append(
            "probable pitcher hand unresolved for "
            + ", ".join(sorted(unresolved))
            + "; F4's platoon component is inert for every hitter facing them")


# --------------------------------------------------------------------------- #
# 2. the-odds-api totals (DK + FD), raw payload
# --------------------------------------------------------------------------- #
def fetch_odds_raw(date: str, warnings: List[str]) -> Optional[List[Dict[str, Any]]]:
    api_key = os.environ.get(ODDS_KEY_ENV, "").strip()
    if not api_key:
        warnings.append(f"odds skipped: {ODDS_KEY_ENV} not set")
        return None
    start = f"{date}T04:00:00Z"  # ET day bounds expressed in UTC
    end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
    end = f"{end_dt.strftime('%Y-%m-%d')}T09:59:00Z"
    params = urllib.parse.urlencode({
        "apiKey": api_key, "regions": "us", "markets": "totals,h2h",
        "bookmakers": "draftkings,fanduel", "oddsFormat": "american",
        "commenceTimeFrom": start, "commenceTimeTo": end,
    })
    try:
        return _get_json(f"{ODDS_API}?{params}", secret=api_key)
    except RuntimeError as exc:
        warnings.append(f"odds fetch failed: {exc}")
        return None


# --------------------------------------------------------------------------- #
# 3. Open-Meteo per venue around first pitch
# --------------------------------------------------------------------------- #
def load_venues(path: Path, warnings: List[str]) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        warnings.append(f"weather skipped: venue file not found at {path}")
        return {}
    venues: Dict[str, Dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            venues[row["Venue"].strip()] = {
                "team": row.get("Home_Team", "").strip(),
                "roof_type": row.get("Roof_Type", "").strip().lower(),
                "lat": float(row["Latitude"]), "lon": float(row["Longitude"]),
                "wind_sensitivity": row.get("Wind_Sensitivity", "").strip(),
                "wind_min_speed_mph": row.get("Wind_Min_Speed_MPH", "").strip(),
            }
    return venues


def fetch_weather(feed: Optional[Dict[str, Any]], venues: Dict[str, Dict[str, Any]],
                  warnings: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not feed or not venues:
        return out
    for game in feed.get("games") or []:
        venue_name = game.get("venue") or ""
        meta = venues.get(venue_name)
        if meta is None:
            warnings.append(f"weather: venue '{venue_name}' not in team_to_venue.csv; skipped")
            continue
        if venue_name in out:
            out[venue_name]["game_pks"].append(game.get("game_pk"))
            continue
        record: Dict[str, Any] = {
            "game_pks": [game.get("game_pk")],
            "roof_type": meta["roof_type"],
            "wind_sensitivity": meta["wind_sensitivity"],
            "wind_min_speed_mph": meta["wind_min_speed_mph"],
            "retractable_note": ("roof open/closed status MUST still be confirmed manually; "
                                 "a forecast is never a roof status"
                                 if meta["roof_type"] == "retractable" else None),
        }
        if meta["roof_type"] in FIXED_ROOFS:
            record["skipped"] = "fixed roof; no weather fetch"
            out[venue_name] = record
            continue
        try:
            game_utc = datetime.strptime(game.get("game_date_utc"), "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            warnings.append(f"weather: unparseable game time for {venue_name}; skipped")
            continue
        params = urllib.parse.urlencode({
            "latitude": meta["lat"], "longitude": meta["lon"],
            "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation_probability",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
            "timezone": "UTC",
            "start_date": game_utc.strftime("%Y-%m-%d"),
            "end_date": (game_utc + timedelta(hours=5)).strftime("%Y-%m-%d"),
        })
        try:
            payload = _get_json(f"{OPEN_METEO}?{params}")
        except RuntimeError as exc:
            warnings.append(f"weather fetch failed for {venue_name}: {exc}")
            continue
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        window = []
        for index, stamp in enumerate(times):
            try:
                stamp_dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M")
            except Exception:
                continue
            if timedelta(hours=-1) <= (stamp_dt - game_utc.replace(tzinfo=None)) <= timedelta(hours=4):
                window.append({
                    "time_utc": stamp,
                    "temperature_f": (hourly.get("temperature_2m") or [None] * len(times))[index],
                    "wind_speed_mph": (hourly.get("wind_speed_10m") or [None] * len(times))[index],
                    "wind_gusts_mph": (hourly.get("wind_gusts_10m") or [None] * len(times))[index],
                    "wind_direction_deg": (hourly.get("wind_direction_10m") or [None] * len(times))[index],
                    "precip_probability_pct": (hourly.get("precipitation_probability") or [None] * len(times))[index],
                })
        record["hourly_window"] = window
        record["source"] = "open-meteo"
        out[venue_name] = record
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Bundle MLB lineups + odds + weather into slate_bundle.json")
    parser.add_argument("--date", default=_today_et(), help="ET slate date YYYY-MM-DD (default: today ET)")
    parser.add_argument("--venues", default="data/reference/team_to_venue.csv", help="path to the engine's team_to_venue.csv")
    parser.add_argument("--out", default="slate_bundle.json")
    parser.add_argument("--skip-odds", action="store_true")
    parser.add_argument("--skip-weather", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    warnings: List[str] = []
    bundle: Dict[str, Any] = {
        "bundle_version": "1.0",
        "slate_date_et": args.date,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "lineups": "MLB Stats API (statsapi.mlb.com)",
            "odds": "the-odds-api.com v4 totals, DK+FD" if not args.skip_odds else "skipped",
            "weather": "open-meteo.com hourly" if not args.skip_weather else "skipped",
        },
        "note": ("Raw observed data and posted prices only; nothing here is a projection, "
                 "edge, win-rate, or probability claim. Retractable-roof status still "
                 "requires manual confirmation per the engine's fresh-roof rule."),
    }

    try:
        bundle["lineups"] = fetch_lineups_feed(args.date, warnings)
    except RuntimeError as exc:
        warnings.append(f"lineups fetch failed: {exc}")
        bundle["lineups"] = None

    bundle["odds_raw_totals"] = None if args.skip_odds else fetch_odds_raw(args.date, warnings)

    if args.skip_weather:
        bundle["weather"] = {}
    else:
        venues = load_venues(Path(args.venues), warnings)
        bundle["weather"] = fetch_weather(bundle.get("lineups"), venues, warnings)

    bundle["warnings"] = warnings
    Path(args.out).write_text(
        json.dumps(bundle, indent=2 if args.pretty else None), encoding="utf-8")

    game_count = len((bundle.get("lineups") or {}).get("games") or [])
    odds_count = len(bundle.get("odds_raw_totals") or [])
    weather_count = len(bundle.get("weather") or {})
    print(f"wrote {args.out}: {game_count} games, {odds_count} odds events, "
          f"{weather_count} venues, {len(warnings)} warning(s)")
    for warning in warnings:
        print(f"  warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
