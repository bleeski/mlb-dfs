"""Live data adapters v1.2 for MLB Classic v2.26.0.

Converts external data into the pipeline's input contracts so production
inputs are derived, not hand-transcribed in chat:

- MLB Stats API lineups feed (the ``mlb-lineups`` skill output) ->
  ``status_by_player_id`` keyed by DraftKings Player_ID with lock times from
  game start, plus confirmed teams/hitters/orders for the projection refresh
  and per-team confirmed-hitter validation. v1.1 adds two matchup extractors
  for the deterministic F4: ``extract_opposing_probables`` (DK team -> the
  opposing probable SP with MLBAM id and hand) and ``extract_batter_hands``
  (DK Player_ID -> bat side for posted hitters).
- v1.2 adds ``build_slate_pool``, THE required intake step for every build:
  it restricts the slate to the players who can actually take the field.
  Hitters are the nine in each confirmed lineup plus the platoon-projected
  nine for each TBD team; pitchers are the feed's probables plus anything
  explicitly declared. Every other salary row is dropped before the engine
  sees it (absent, not Excluded), which ends both the full-CSV projection
  waste and the recurring non-starter pitcher-role confusion. The salary CSV
  stays authoritative for Player_ID, salary, team, positions, and game of
  the players kept. Output bundles run_slate-ready kwargs, the F4 building
  blocks, the slate clock, and a pool report with per-team status, warnings,
  and blockers.
- the-odds-api.com v4 (the ``mlb-game-odds`` skill's API) -> the odds packet
  entries the slate-context odds gate validates ({total, source, fetched_at}
  per game), and per-event player props -> implied probabilities.
- odds-api.io v3 (the ``mlb-hr-prop-arb`` skill's API) -> HR prop rows with
  decimal-odds implied probabilities.

Design rules:
- Every ``fetch_*`` has a ``parse_*`` counterpart that takes already-fetched
  JSON, so the adapters work without network egress when a skill or operator
  supplies the payload.
- Fetchers use only the standard library (urllib), never log or echo API keys,
  and scrub keys from error text.
- Free-tier facts, verified 2026-06-11: the-odds-api featured markets
  (h2h/spreads/totals) cost markets x regions per call covering all events
  (DK+FD totals = 1 credit); player props are non-featured and cost
  markets x regions PER EVENT via /events/{id}/odds. Free plan is 500
  credits/month; quota headers are surfaced. odds-api.io rate limits
  5,000 requests/hour on all plans. sportsdata.io's free trial scrambles
  scores, stats, and odds by their own documentation, so nothing here
  consumes it; do not wire decision paths to scrambled data.
- Implied probabilities are deterministic transforms of posted prices. They
  are review inputs for F3/F4/right-tail judgment, never win-rate or ROI
  claims (truthful-labels rule).
"""
from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.swap.late_swap_manager import (
    CONFIRMED_STARTER, PROJECTED_STARTER, UNKNOWN, PlayerLineupStatus,
)
from mlb_engine.intake.slate_intake_manager import normalize_name

VERSION = "v1.2"

THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_IO_BASE = "https://api.odds-api.io/v3"

# MLB Stats API abbreviations that differ from DraftKings CSV abbreviations.
DK_ABBREV_REMAP = {"AZ": "ARI"}  # ATH passes through unchanged: DraftKings, the salary CSV, and data/reference all key the Athletics as ATH post-relocation (was OAK)

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
}


def to_dk_abbrev(api_abbrev: str) -> str:
    text = str(api_abbrev or "").strip().upper()
    return DK_ABBREV_REMAP.get(text, text)


def team_name_to_dk_abbrev(team_name: str) -> Optional[str]:
    key = " ".join(str(team_name or "").strip().lower().replace(".", ". ").split())
    return MLB_TEAM_NAME_TO_DK.get(key) or MLB_TEAM_NAME_TO_DK.get(key.replace(". ", " ").replace(".", ""))


def _scrub(text: str, secret: Optional[str]) -> str:
    if secret:
        text = text.replace(secret, "***")
        text = text.replace(urllib.parse.quote(secret, safe=""), "***")
    return text


def _http_get_json(url: str, timeout: float = 20.0, secret: Optional[str] = None) -> Tuple[Any, Dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "mlb-classic-adapters/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            return json.loads(response.read().decode("utf-8")), headers
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(_scrub(f"HTTP {exc.code} from {url}: {detail}", secret)) from None
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise RuntimeError(_scrub(f"network error fetching {url}: {exc.reason}", secret)) from None


def _record_get(record: Any, key: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _load_salary_players(salary_players: Any) -> Dict[str, Any]:
    """Accept a pid->record mapping or a DK salary CSV path."""
    if isinstance(salary_players, (str, Path)):
        from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
        return {p.player_id: p for p in parse_dk_salary_csv(str(salary_players))}
    return dict(salary_players)


def _parse_utc(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# MLB Stats API lineups feed -> late-swap and confirmation contracts
# ---------------------------------------------------------------------------

def build_status_map_from_lineups_feed(
    feed: Mapping[str, Any],
    salary_players: Any,
    unlisted_status: str = UNKNOWN,
) -> Dict[str, Any]:
    """Derive the late-swap status map from the lineups feed plus the salary CSV.

    Every salary player whose game appears in the feed receives a
    ``PlayerLineupStatus`` keyed by DraftKings Player_ID, with ``lock_time``
    taken from the game's ``game_date_utc``. Players in a posted lineup are
    ``Confirmed_Starter`` (with batting order); probable pitchers are
    ``Projected_Starter``; everyone else gets ``unlisted_status`` (default
    ``Unknown``, which counts as TBD). Salary players whose game is absent
    from the feed are returned in ``uncovered_salary_player_ids`` and are NOT
    given a status, so the default fail-closed late-swap policy blocks rather
    than guessing their lock state.

    Returns a dict with: status_by_player_id, confirmed_teams,
    confirmed_hitter_ids, confirmed_order_by_player_id, starter_player_ids,
    probable_pitcher_ids, excluded_game_ids (postponed/cancelled),
    lock_time_by_game_id, unmatched_feed_players, uncovered_salary_player_ids.
    """
    players = _load_salary_players(salary_players)
    salary_by_name_team: Dict[Tuple[str, str], List[str]] = {}
    for pid, record in players.items():
        key = (normalize_name(_record_get(record, "name")), str(_record_get(record, "team")).strip().upper())
        salary_by_name_team.setdefault(key, []).append(str(pid))

    games: List[Mapping[str, Any]] = list(feed.get("games") or [])
    lock_time_by_game_id: Dict[str, datetime] = {}
    game_meta: Dict[str, Dict[str, Any]] = {}
    excluded_game_ids: List[str] = []
    status_by_player_id: Dict[str, PlayerLineupStatus] = {}
    confirmed_teams: List[str] = []
    confirmed_hitter_ids: List[str] = []
    confirmed_order: Dict[str, int] = {}
    probable_pitcher_ids: List[str] = []
    unmatched: List[Dict[str, str]] = []

    def match_dk_id(name: str, dk_team: str) -> Optional[str]:
        hits = salary_by_name_team.get((normalize_name(name), dk_team), [])
        if len(hits) == 1:
            return hits[0]
        unmatched.append({"name": str(name), "team": dk_team,
                          "reason": "no salary match" if not hits else "ambiguous salary match"})
        return None

    for game_entry in games:
        away = game_entry.get("away") or {}
        home = game_entry.get("home") or {}
        away_team = to_dk_abbrev(away.get("team_abbrev"))
        home_team = to_dk_abbrev(home.get("team_abbrev"))
        if not away_team or not home_team:
            continue
        game_id = f"{away_team}@{home_team}"
        lock_time = _parse_utc(game_entry.get("game_date_utc"))
        lock_time_by_game_id[game_id] = lock_time
        game_meta[game_id] = {
            "game_pk": game_entry.get("game_pk"),
            "venue": game_entry.get("venue"),
            "status": game_entry.get("status"),
            "lock_time_utc": lock_time.isoformat(),
        }
        state = str(game_entry.get("status") or "").strip().lower()
        if "postpon" in state or "cancel" in state or "suspend" in state:
            excluded_game_ids.append(game_id)

        for side, dk_team in ((away, away_team), (home, home_team)):
            if str(side.get("lineup_status") or "").strip().lower() == "confirmed":
                confirmed_teams.append(dk_team)
            for hitter in side.get("lineup") or []:
                dk_id = match_dk_id(hitter.get("name"), dk_team)
                if dk_id is None:
                    continue
                order = hitter.get("order")
                status_by_player_id[dk_id] = PlayerLineupStatus(
                    player_id=dk_id, name=str(hitter.get("name") or ""), team=dk_team,
                    game_id=game_id, lock_time=lock_time, status=CONFIRMED_STARTER,
                    batting_order=int(order) if order is not None else None,
                )
                if str(side.get("lineup_status") or "").strip().lower() == "confirmed":
                    confirmed_hitter_ids.append(dk_id)
                    if order is not None:
                        confirmed_order[dk_id] = int(order)
            probable = side.get("probable_pitcher") or None
            if probable and probable.get("name"):
                dk_id = match_dk_id(probable.get("name"), dk_team)
                if dk_id is not None:
                    status_by_player_id[dk_id] = PlayerLineupStatus(
                        player_id=dk_id, name=str(probable.get("name") or ""), team=dk_team,
                        game_id=game_id, lock_time=lock_time, status=PROJECTED_STARTER,
                    )
                    probable_pitcher_ids.append(dk_id)

    uncovered: List[str] = []
    for pid, record in players.items():
        pid_text = str(pid)
        if pid_text in status_by_player_id:
            continue
        team = to_dk_abbrev(_record_get(record, "team"))
        game_id = str(_record_get(record, "game_id") or "")
        lock_time = lock_time_by_game_id.get(game_id)
        if lock_time is None:
            for candidate_gid, candidate_lock in lock_time_by_game_id.items():
                if team and team in candidate_gid.split("@"):
                    game_id, lock_time = candidate_gid, candidate_lock
                    break
        if lock_time is None:
            uncovered.append(pid_text)
            continue
        status_by_player_id[pid_text] = PlayerLineupStatus(
            player_id=pid_text, name=str(_record_get(record, "name") or ""), team=team,
            game_id=game_id, lock_time=lock_time, status=unlisted_status,
        )

    return {
        "status_by_player_id": status_by_player_id,
        "confirmed_teams": sorted(set(confirmed_teams)),
        "confirmed_hitter_ids": sorted(set(confirmed_hitter_ids)),
        "confirmed_order_by_player_id": confirmed_order,
        "starter_player_ids": sorted(set(confirmed_hitter_ids)),
        "probable_pitcher_ids": sorted(set(probable_pitcher_ids)),
        "excluded_game_ids": sorted(set(excluded_game_ids)),
        "lock_time_by_game_id": {k: v.isoformat() for k, v in lock_time_by_game_id.items()},
        "game_meta": game_meta,
        "unmatched_feed_players": unmatched,
        "uncovered_salary_player_ids": sorted(uncovered),
        "feed_date": feed.get("date"),
        "feed_fetched_at": feed.get("fetched_at"),
    }


def extract_opposing_probables(feed: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """From an mlb-lineups feed, map each DK team abbrev to the OPPOSING probable SP.

    Returns ``{team: {"id": mlbam_id_str, "name": ..., "hand": "R"/"L"}}``. The
    away team gets the home probable and vice versa. The MLBAM ``id`` joins
    directly to the Savant pitching expected-stats table, so the F4 quality
    component needs no name matching. Teams whose opponent has no posted
    probable are simply absent; projection_builder.compute_f4_factors treats
    them as neutral and reports them. Feed probables are usually populated even
    when batting orders are still TBD.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for game_entry in feed.get("games") or []:
        away = game_entry.get("away") or {}
        home = game_entry.get("home") or {}
        away_team = to_dk_abbrev(away.get("team_abbrev"))
        home_team = to_dk_abbrev(home.get("team_abbrev"))
        away_probable = away.get("probable_pitcher") or {}
        home_probable = home.get("probable_pitcher") or {}
        if away_team and home_probable.get("name"):
            out[away_team] = {
                "id": str(home_probable.get("id") or "").strip(),
                "name": str(home_probable.get("name") or ""),
                "hand": home_probable.get("hand"),
            }
        if home_team and away_probable.get("name"):
            out[home_team] = {
                "id": str(away_probable.get("id") or "").strip(),
                "name": str(away_probable.get("name") or ""),
                "hand": away_probable.get("hand"),
            }
    return out


def extract_batter_hands(feed: Mapping[str, Any], salary_players: Any) -> Dict[str, str]:
    """From an mlb-lineups feed, map DK Player_ID -> bat side ("L"/"R"/"S").

    Uses the same name+team salary match as the status map, so the crosswalk
    cannot drift from it. Only hitters present in a posted lineup carry a
    ``bat_side``, so TBD teams are absent; the F4 platoon component simply
    stays neutral for them while the team-level SP-quality component still
    applies. Ambiguous or unmatched feed hitters are skipped, never guessed.
    """
    players = _load_salary_players(salary_players)
    salary_by_name_team: Dict[Tuple[str, str], List[str]] = {}
    for pid, record in players.items():
        key = (normalize_name(_record_get(record, "name")), str(_record_get(record, "team")).strip().upper())
        salary_by_name_team.setdefault(key, []).append(str(pid))
    out: Dict[str, str] = {}
    for game_entry in feed.get("games") or []:
        for side in (game_entry.get("away") or {}, game_entry.get("home") or {}):
            dk_team = to_dk_abbrev(side.get("team_abbrev"))
            if not dk_team:
                continue
            for hitter in side.get("lineup") or []:
                bat_side = str(hitter.get("bat_side") or "").strip().upper()
                if bat_side not in ("L", "R", "S"):
                    continue
                hits = salary_by_name_team.get((normalize_name(hitter.get("name")), dk_team), [])
                if len(hits) == 1:
                    out[hits[0]] = bat_side
    return out



# ---------------------------------------------------------------------------
# v1.2 pool contract: only players who can actually take the field
# ---------------------------------------------------------------------------

def _pool_row(sp: Any, batting_order: Optional[int] = None) -> Dict[str, Any]:
    """One run_slate-ready projection row from a SalaryPlayer, salary-authoritative."""
    appg: Optional[float] = None
    raw = getattr(sp, "raw", {}) or {}
    for key in ("AvgPointsPerGame", "AvgPointsPerContest"):
        value = raw.get(key)
        if value not in (None, ""):
            try:
                appg = float(value)
            except (TypeError, ValueError):
                appg = None
            break
    row: Dict[str, Any] = {
        "Player_ID": str(sp.player_id),
        "Name": sp.name,
        "Team": sp.team,
        "Opponent": sp.opponent,
        "Position": "/".join(sp.positions),
        "Salary": float(sp.salary),
        "Game_ID": sp.game_id or sp.game_info,
        "AvgPointsPerGame": appg,
        "Excluded": False,
    }
    if batting_order is not None:
        row["Batting_Order"] = int(batting_order)
    return row


def build_slate_pool(
    salary_csv: str | Path,
    lineups_feed: Mapping[str, Any],
    platoon_json: Optional[Mapping[str, Any]] = None,
    declared_pitchers: Optional[Mapping[str, str]] = None,
    tbd_fallback: str = "top9_appg",
    now: Optional[datetime] = None,
    lock_buffer_minutes: int = 5,
) -> Dict[str, Any]:
    """Restrict the slate to the players who can actually take the field.

    THE pool contract (v2.26.0): hitters are the nine in each confirmed lineup
    plus the platoon-projected nine for each TBD team; pitchers are the feed's
    probables plus anything explicitly declared via ``declared_pitchers``
    ({DK Player_ID: role}). Every other salary row is dropped before the engine
    sees it, absent rather than Excluded, so no downstream step pays for bench
    bats or non-starting arms and the only P rows in the frame are the starters.
    The salary CSV stays authoritative for Player_ID, salary, team, positions,
    and game of the players kept.

    Mechanics: confirmed teams and orders come from the lineups feed through
    ``build_status_map_from_lineups_feed`` (the canonical name+team salary
    crosswalk). Confirmed hitters carry Batting_Order and a stamped
    F2 = batting_order_factor(slot), so confirmed and projected orders get
    symmetric F2 treatment. TBD teams take the platoon projected order when
    ``platoon_json`` is supplied (slots flow through
    ``platoon_order_by_player_id``, never Batting_Order, so a posted lineup
    still supersedes); a TBD team the platoon data cannot fill falls back to
    its top-9 salary hitters by AvgPointsPerGame with a loud warning, or is
    excluded when ``tbd_fallback='exclude'``. Postponed or cancelled games are
    excluded with a warning. A team left with no probable and no declared arm
    is surfaced as a blocker because declaring that starter is a real decision.

    Returns projection rows, ``run_slate_kwargs`` ready to splat into
    ``run_slate``, the F4 building blocks (``team_by_player_id``,
    ``opposing_probables``, ``batter_hands`` for
    ``projection_builder.compute_f4_factors``), the slate clock, and a
    ``pool_report`` with per-team status, warnings, and blockers. Deterministic
    intake bookkeeping; it moves no projection and is never a win-rate, ROI, or
    probability claim.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv, slate_clock
    from mlb_engine.projections.projection_builder import batting_order_factor

    players = parse_dk_salary_csv(str(salary_csv))
    by_id = {p.player_id: p for p in players}
    salary_map = {p.player_id: p for p in players}
    status = build_status_map_from_lineups_feed(lineups_feed, salary_map)

    confirmed_teams = set(status["confirmed_teams"])
    confirmed_hitter_ids = list(status["confirmed_hitter_ids"])
    confirmed_order = dict(status["confirmed_order_by_player_id"])
    probable_ids = list(status["probable_pitcher_ids"])
    excluded_game_ids = set(status["excluded_game_ids"])

    def is_pitcher(sp: Any) -> bool:
        return "P" in tuple(sp.positions)

    def appg_of(sp: Any) -> float:
        try:
            return float((sp.raw or {}).get("AvgPointsPerGame") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    slate_teams = sorted({p.team for p in players if p.team})
    team_game = {p.team: (p.game_id or p.game_info) for p in players if p.team}
    excluded_teams = {t for t, g in team_game.items() if g in excluded_game_ids}

    warnings: List[str] = []
    blockers: List[str] = []
    teams_report: Dict[str, Dict[str, Any]] = {}

    tbd_teams = [t for t in slate_teams if t not in confirmed_teams and t not in excluded_teams]
    platoon_order: Dict[str, int] = {}
    platoon_report: Optional[Dict[str, Any]] = None
    if tbd_teams and platoon_json is not None:
        try:
            from mlb_engine.intake.platoon_order_adapter import (
                build_projected_order, extract_opp_throws_from_lineups,
            )
            opp_throws = extract_opp_throws_from_lineups(lineups_feed)
            platoon_order, platoon_report = build_projected_order(
                platoon_json, salary_csv, opp_throws, only_teams=list(tbd_teams),
            )
            platoon_order = {str(k): int(v) for k, v in platoon_order.items()}
        except Exception as exc:  # defensive: pool must degrade, not die
            warnings.append(f"platoon projected order unavailable: {exc}")
            platoon_order = {}

    keep: Dict[str, Dict[str, Any]] = {}

    # Confirmed hitters: Batting_Order + stamped F2 from the posted slot.
    for pid in confirmed_hitter_ids:
        sp = by_id.get(str(pid))
        if sp is None or is_pitcher(sp) or sp.team in excluded_teams:
            continue
        slot = confirmed_order.get(str(pid))
        row = _pool_row(sp, batting_order=slot)
        if slot is not None:
            row["F2"] = batting_order_factor(int(slot))
            row["Notes"] = "confirmed_order: F2 from posted batting order"
        keep[str(pid)] = row
    for team in sorted(confirmed_teams - excluded_teams):
        n = sum(1 for r in keep.values() if r["Team"] == team)
        teams_report[team] = {"status": "confirmed", "hitters": n}
        if n != 9:
            warnings.append(f"{team}: confirmed lineup matched {n}/9 salary hitters")

    # TBD teams: platoon projected nine, APPG fallback when platoon cannot fill.
    platoon_by_team: Dict[str, List[str]] = {}
    for pid in platoon_order:
        sp = by_id.get(pid)
        if sp is not None and not is_pitcher(sp) and sp.team not in excluded_teams:
            platoon_by_team.setdefault(sp.team, []).append(pid)
    for team in tbd_teams:
        got = platoon_by_team.get(team, [])
        for pid in got:
            keep[pid] = _pool_row(by_id[pid], batting_order=None)
        n = len(got)
        if n >= 9:
            teams_report[team] = {"status": "platoon", "hitters": n}
            continue
        if tbd_fallback == "exclude":
            teams_report[team] = {"status": "excluded_no_order_data", "hitters": n}
            blockers.append(
                f"{team}: TBD lineup and platoon data filled only {n}/9; "
                f"team excluded (tbd_fallback='exclude')"
            )
            continue
        candidates = sorted(
            (p for p in players
             if p.team == team and not is_pitcher(p) and p.player_id not in keep),
            key=appg_of, reverse=True,
        )
        for sp in candidates[: 9 - n]:
            keep[sp.player_id] = _pool_row(sp, batting_order=None)
        filled = min(9, n + len(candidates[: 9 - n]))
        teams_report[team] = {
            "status": "platoon_plus_appg_fallback" if n > 0 else "fallback_top9_appg",
            "hitters": filled,
        }
        warnings.append(
            f"{team}: TBD lineup; {'platoon filled ' + str(n) + '/9, ' if n > 0 else ''}"
            f"top-AvgPointsPerGame fallback supplied {filled - n} hitters"
        )
    for team in sorted(excluded_teams):
        teams_report[team] = {"status": "excluded_postponed", "hitters": 0}
        warnings.append(f"{team}: game {team_game.get(team)} postponed/cancelled/suspended; team excluded")

    # Pitchers: probables plus explicit declarations. Nothing else exists.
    pitcher_roles: Dict[str, str] = {}
    for pid in probable_ids:
        sp = by_id.get(str(pid))
        if sp is None or sp.team in excluded_teams:
            continue
        pitcher_roles[str(pid)] = "declared_probable_sp"
        keep[str(pid)] = _pool_row(sp, batting_order=None)
    for pid, role in (declared_pitchers or {}).items():
        sp = by_id.get(str(pid))
        if sp is None:
            warnings.append(f"declared pitcher id {pid} not on the salary file; skipped")
            continue
        pitcher_roles[str(pid)] = str(role or "declared_probable_sp")
        keep.setdefault(str(pid), _pool_row(sp, batting_order=None))
    teams_with_arm = {by_id[pid].team for pid in pitcher_roles if pid in by_id}
    for team in slate_teams:
        if team in excluded_teams or team in teams_with_arm:
            continue
        blockers.append(
            f"{team}: no probable or declared starter; declare one via "
            f"declared_pitchers or that side has no rosterable arm"
        )

    rows = sorted(keep.values(), key=lambda r: (r["Team"], r["Player_ID"]))
    missing_appg = [r["Player_ID"] for r in rows if r.get("AvgPointsPerGame") in (None, "")]
    if missing_appg:
        warnings.append(
            f"{len(missing_appg)} kept rows missing AvgPointsPerGame; supply Base "
            f"before run_slate or those rows will fail assembly"
        )

    clock = slate_clock(
        players=players,
        lock_time_by_game_id=status.get("lock_time_by_game_id") or None,
        now=now,
        buffer_minutes=lock_buffer_minutes,
    )

    team_by_player_id = {
        r["Player_ID"]: r["Team"] for r in rows if r["Player_ID"] not in pitcher_roles
    }
    kept_confirmed_hitters = sorted(
        pid for pid in confirmed_hitter_ids if str(pid) in keep
    )

    return {
        "projection_rows": rows,
        "run_slate_kwargs": {
            "projection_rows": rows,
            "confirmed_hitter_ids": kept_confirmed_hitters,
            "confirmed_teams": sorted(confirmed_teams - excluded_teams),
            "pitcher_roles": pitcher_roles,
            "platoon_order_by_player_id": platoon_order or None,
        },
        "pitcher_roles": pitcher_roles,
        "platoon_order_by_player_id": platoon_order,
        "platoon_report": platoon_report,
        "team_by_player_id": team_by_player_id,
        "opposing_probables": extract_opposing_probables(lineups_feed),
        "batter_hands": extract_batter_hands(lineups_feed, salary_map),
        "clock": clock,
        "lock_time_by_game_id": status.get("lock_time_by_game_id"),
        "pool_report": {
            "salary_rows_total": len(players),
            "kept": len(rows),
            "dropped": len(players) - len(rows),
            "hitters_kept": len(team_by_player_id),
            "pitchers_kept": len(pitcher_roles),
            "teams": teams_report,
            "pitchers": [
                {"player_id": pid, "name": by_id[pid].name, "team": by_id[pid].team,
                 "role": role}
                for pid, role in sorted(pitcher_roles.items()) if pid in by_id
            ],
            "unmatched_feed_players": status.get("unmatched_feed_players"),
            "warnings": warnings,
            "blockers": blockers,
        },
    }



# ---------------------------------------------------------------------------
# the-odds-api.com v4: game totals -> odds packet entries
# ---------------------------------------------------------------------------

def _et_day_utc_bounds(date_et: Optional[str]) -> Tuple[str, str]:
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    if date_et:
        day = datetime.strptime(date_et, "%Y-%m-%d").replace(tzinfo=eastern)
    else:
        day = datetime.now(eastern).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def fetch_the_odds_api_totals(
    api_key: str,
    date_et: Optional[str] = None,
    bookmakers: str = "draftkings,fanduel",
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Fetch full-game MLB totals. Cost: 1 credit per ~10 bookmakers (DK+FD = 1).

    Returns {"raw": <api response>, "quota": {"remaining", "used"}}.
    """
    start, end = _et_day_utc_bounds(date_et)
    params = {
        "apiKey": api_key, "markets": "totals", "oddsFormat": "american",
        "dateFormat": "iso", "bookmakers": bookmakers,
        "commenceTimeFrom": start, "commenceTimeTo": end,
    }
    url = f"{THE_ODDS_API_BASE}/sports/baseball_mlb/odds?{urllib.parse.urlencode(params)}"
    raw, headers = _http_get_json(url, timeout=timeout, secret=api_key)
    return {"raw": raw, "quota": {
        "remaining": headers.get("x-requests-remaining"),
        "used": headers.get("x-requests-used"),
    }}


def parse_the_odds_api_totals(raw: Sequence[Mapping[str, Any]], fetched_at: Optional[str] = None) -> Dict[str, Any]:
    """Parse a v4 odds response (markets=totals) into odds-gate packet entries.

    Output ``odds_by_game_id`` maps ``AWAY@HOME`` (DK abbreviations) to
    ``{"total", "source", "fetched_at", "books", "commence_time_utc"}``. The
    consensus total is the median across books. Merge each entry under the
    matching game's ``odds`` key in the slate context packet.
    """
    odds_by_game_id: Dict[str, Dict[str, Any]] = {}
    unmapped: List[str] = []
    for event in raw or []:
        home = team_name_to_dk_abbrev(event.get("home_team"))
        away = team_name_to_dk_abbrev(event.get("away_team"))
        if not home or not away:
            unmapped.append(f"{event.get('away_team')} @ {event.get('home_team')}")
            continue
        game_id = f"{away}@{home}"
        books: Dict[str, float] = {}
        latest_update: Optional[str] = None
        for bookmaker in event.get("bookmakers") or []:
            key = str(bookmaker.get("key") or "").lower()
            for market in bookmaker.get("markets") or []:
                if str(market.get("key")) != "totals":
                    continue
                update = market.get("last_update") or bookmaker.get("last_update")
                if update and (latest_update is None or str(update) > latest_update):
                    latest_update = str(update)
                for outcome in market.get("outcomes") or []:
                    point = outcome.get("point")
                    if point is not None:
                        books[key] = float(point)
                        break
        if not books:
            continue
        stamp = fetched_at or latest_update or datetime.now(timezone.utc).isoformat()
        odds_by_game_id[game_id] = {
            "total": float(statistics.median(sorted(books.values()))),
            "source": "the-odds-api:" + ",".join(sorted(books)),
            "fetched_at": stamp,
            "books": books,
            "commence_time_utc": event.get("commence_time"),
            "event_id": event.get("id"),
        }
    return {"odds_by_game_id": odds_by_game_id, "unmapped_teams": unmapped}


# ---------------------------------------------------------------------------
# the-odds-api.com v4: per-event player props -> implied probabilities
# ---------------------------------------------------------------------------

def fetch_the_odds_api_events(api_key: str, date_et: Optional[str] = None, timeout: float = 20.0) -> Dict[str, Any]:
    """List MLB event ids for the ET day (needed for per-event props calls)."""
    start, end = _et_day_utc_bounds(date_et)
    params = {"apiKey": api_key, "dateFormat": "iso", "commenceTimeFrom": start, "commenceTimeTo": end}
    url = f"{THE_ODDS_API_BASE}/sports/baseball_mlb/events?{urllib.parse.urlencode(params)}"
    raw, headers = _http_get_json(url, timeout=timeout, secret=api_key)
    return {"raw": raw, "quota": {
        "remaining": headers.get("x-requests-remaining"),
        "used": headers.get("x-requests-used"),
    }}


def fetch_the_odds_api_event_props(
    api_key: str,
    event_id: str,
    markets: str = "batter_home_runs",
    regions: str = "us",
    bookmakers: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Fetch player props for one event. Cost: markets x regions PER EVENT.

    A 12-game slate with one market and one region costs ~12 credits, so on
    the free 500/month plan treat props as an occasional research pull, not a
    daily default. Use estimate_the_odds_api_props_cost() before fetching.
    """
    params: Dict[str, str] = {
        "apiKey": api_key, "markets": markets, "oddsFormat": "american", "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = bookmakers
    else:
        params["regions"] = regions
    url = f"{THE_ODDS_API_BASE}/sports/baseball_mlb/events/{urllib.parse.quote(str(event_id))}/odds?{urllib.parse.urlencode(params)}"
    raw, headers = _http_get_json(url, timeout=timeout, secret=api_key)
    return {"raw": raw, "quota": {
        "remaining": headers.get("x-requests-remaining"),
        "used": headers.get("x-requests-used"),
    }}


def estimate_the_odds_api_props_cost(n_events: int, n_markets: int = 1, n_regions: int = 1) -> int:
    return max(0, int(n_events)) * max(1, int(n_markets)) * max(1, int(n_regions))


def american_to_implied_prob(price: float) -> float:
    value = float(price)
    if value > 0:
        return 100.0 / (value + 100.0)
    if value < 0:
        return -value / (-value + 100.0)
    raise ValueError("american odds of 0 are undefined")


def vig_free_probabilities(prob_a: float, prob_b: float) -> Tuple[float, float]:
    total = float(prob_a) + float(prob_b)
    if total <= 0:
        raise ValueError("probabilities must be positive")
    return float(prob_a) / total, float(prob_b) / total


def parse_the_odds_api_event_props(raw_event: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Flatten one event-odds response into prop rows with implied probabilities."""
    rows: List[Dict[str, Any]] = []
    home = team_name_to_dk_abbrev(raw_event.get("home_team"))
    away = team_name_to_dk_abbrev(raw_event.get("away_team"))
    game_id = f"{away}@{home}" if home and away else ""
    for bookmaker in raw_event.get("bookmakers") or []:
        book = str(bookmaker.get("key") or "").lower()
        for market in bookmaker.get("markets") or []:
            market_key = str(market.get("key") or "")
            for outcome in market.get("outcomes") or []:
                price = outcome.get("price")
                if price is None:
                    continue
                rows.append({
                    "event_id": raw_event.get("id"),
                    "game_id": game_id,
                    "market": market_key,
                    "player": str(outcome.get("description") or outcome.get("name") or ""),
                    "book": book,
                    "side": str(outcome.get("name") or ""),
                    "point": outcome.get("point"),
                    "price_american": float(price),
                    "implied_prob": round(american_to_implied_prob(float(price)), 6),
                })
    return rows


def build_props_implied_table(
    rows: Sequence[Mapping[str, Any]],
    salary_players: Any = None,
) -> List[Dict[str, Any]]:
    """Per (player, market): best Over/Yes implied probability, vig-free when paired.

    The vig-free probability normalizes the SAME book's Over/Under pair at the
    same point. Output is a deterministic research table for F3/F4/right-tail
    tags; it is not an ownership model and not a win-rate claim.
    """
    players = _load_salary_players(salary_players) if salary_players is not None else {}
    salary_by_name: Dict[str, List[str]] = {}
    for pid, record in players.items():
        salary_by_name.setdefault(normalize_name(_record_get(record, "name")), []).append(str(pid))

    over_sides = {"over", "yes"}
    under_sides = {"under", "no"}
    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for row in rows:
        key = (normalize_name(row.get("player")), str(row.get("market") or ""))
        grouped.setdefault(key, []).append(row)

    table: List[Dict[str, Any]] = []
    for (player_norm, market), group in sorted(grouped.items()):
        best: Optional[Mapping[str, Any]] = None
        for row in group:
            if str(row.get("side") or "").lower() in over_sides:
                if best is None or float(row["implied_prob"]) < float(best["implied_prob"]):
                    best = row  # lowest implied = best price on the Over
        if best is None:
            continue
        vig_free = None
        for row in group:
            same_book = row.get("book") == best.get("book")
            same_point = row.get("point") == best.get("point")
            if same_book and same_point and str(row.get("side") or "").lower() in under_sides:
                vig_free = round(vig_free_probabilities(float(best["implied_prob"]), float(row["implied_prob"]))[0], 6)
                break
        matches = salary_by_name.get(player_norm, [])
        table.append({
            "player": best.get("player"), "market": market, "game_id": best.get("game_id"),
            "best_over_book": best.get("book"), "point": best.get("point"),
            "best_over_price_american": best.get("price_american"),
            "implied_prob": best.get("implied_prob"),
            "vig_free_prob": vig_free,
            "dk_player_id": matches[0] if len(matches) == 1 else None,
        })
    return table


# ---------------------------------------------------------------------------
# odds-api.io v3: HR props (decimal odds), tolerant parser
# ---------------------------------------------------------------------------

def decimal_to_implied_prob(price_decimal: float) -> float:
    value = float(price_decimal)
    if value <= 1.0:
        raise ValueError("decimal odds must exceed 1.0")
    return 1.0 / value


def parse_odds_api_io_hr_props(payload: Any) -> List[Dict[str, Any]]:
    """Flatten odds-api.io event odds into HR prop rows.

    odds-api.io's docs do not publish baseball prop response examples, so this
    parser is deliberately tolerant about where the player name and prices
    live (mirrors the discovery-first approach in the mlb-hr-prop-arb skill).
    Run that skill's ``--discover`` mode once per account to confirm shapes;
    if a field moves, the row simply carries what was found.
    Bookmaker names on odds-api.io are case-sensitive (Bet365, DraftKings,
    Fanatics). Rate limit: 5,000 requests/hour on all plans.
    """
    events = payload.get("events") if isinstance(payload, Mapping) else payload
    if isinstance(events, Mapping):
        events = list(events.values())
    rows: List[Dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        event_id = event.get("id") or event.get("eventId") or event.get("event_id")
        bookmakers = event.get("bookmakers") or event.get("books") or []
        if isinstance(bookmakers, Mapping):
            bookmakers = [{"name": name, **(value if isinstance(value, Mapping) else {"markets": value})}
                          for name, value in bookmakers.items()]
        for bookmaker in bookmakers:
            book = str(bookmaker.get("name") or bookmaker.get("bookmaker") or bookmaker.get("key") or "")
            markets = bookmaker.get("markets") or bookmaker.get("odds") or []
            for market in markets if isinstance(markets, list) else []:
                if not isinstance(market, Mapping):
                    continue
                market_name = str(market.get("name") or market.get("market") or market.get("key") or "")
                if "home run" not in market_name.lower():
                    continue
                market_player = str(market.get("label") or market.get("player") or "").strip()
                outcomes = market.get("odds") or market.get("outcomes") or market.get("selections") or []
                for outcome in outcomes if isinstance(outcomes, list) else []:
                    if not isinstance(outcome, Mapping):
                        continue
                    price = outcome.get("price") or outcome.get("odds") or outcome.get("decimal")
                    if price is None:
                        continue
                    side = str(outcome.get("label") or outcome.get("name") or outcome.get("selection") or "")
                    player = market_player or str(outcome.get("player") or outcome.get("participant") or "").strip()
                    point = outcome.get("point", outcome.get("line", outcome.get("handicap", 0.5)))
                    try:
                        implied = round(decimal_to_implied_prob(float(price)), 6)
                    except (TypeError, ValueError):
                        continue
                    rows.append({
                        "event_id": event_id, "market": market_name, "player": player,
                        "book": book, "side": side, "point": point,
                        "price_decimal": float(price), "implied_prob": implied,
                    })
    return rows
