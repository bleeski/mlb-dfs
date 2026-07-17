"""Tail candidate scanner v1.0.

Pre-build screening step that identifies games where market consensus may be
underpricing offensive output. Returns a ranked list of flagged games with
per-signal breakdowns, for deliberate use as contrarian lineup thesis inputs.

All outputs are deterministic review proxies. Not a probability estimate, ROI
claim, or win-rate tool.

Usage
-----
Call ``scan_tail_candidates`` with the slate game list and whatever live data
feeds are available. The scanner degrades gracefully when feeds are absent:

    Coverage tiers
    full          - Statcast ERA/xERA + park divergence + book spread + pitcher role
    statcast_park - ERA/xERA + park heuristic only (no odds feed)
    park_odds     - Park divergence + book spread only (no Statcast or lineups)
    park_only     - Hitter-friendly park flag only (no odds, Statcast, or lineups)

Signals
-------
era_xera_gap    Tier 1a  SP xERA - ERA >= threshold: pitcher outperforming on luck.
                         Uses Statcast expected_stats_pitching.csv joined by MLBAM
                         player ID from the lineups feed. Reports the max gap across
                         both starters in the game.
park_total_div  Tier 1b  Run_Factor_Applied vs consensus implied total divergence.
                         park_expected = LEAGUE_BASELINE * run_factor; divergence =
                         (park_expected - implied) / park_expected. Partial status
                         (hitter-friendly flag only) when implied total unavailable.
book_spread     Tier 2   |DK total - FD total| >= threshold: books disagree.
                         Requires odds_json from the mlb-game-odds skill.
pitcher_role    Tier 3b  SP Statcast PA count <= threshold: possible bulk or opener.
                         Partial signal; line movement (Tier 3a) is not available
                         with current tools and remains on the backlog.

Composite tail score
--------------------
Each triggered signal contributes 1 point. A park_total_div "partial" (hitter-
friendly park but implied total unavailable) contributes 0.5. Games with score
>= tail_score_min appear in ``flagged_games``; all games appear in ``all_games``.

Thresholds (all overrideable via the ``thresholds`` parameter)
--------------------------------------------------------------
era_xera_gap_min      0.30   xERA - ERA gap to flag a lucky SP
park_factor_min       1.040  Run_Factor_Applied to be considered hitter-friendly
park_total_div_min    0.06   Fractional divergence between park-expected and implied
book_spread_min       0.50   |DK - FD| total line gap
pitcher_role_pa_max   200    PA faced; below this for a "starter" = possible bulk
tail_score_min        2      Minimum composite score to appear in flagged_games

Integration
-----------
Call this before ``run_slate`` (``approve=False`` checkpoint phase). Review
the flagged games, decide if any clears your threshold, then set the F1
override for that game in the projection rows before the approved build.
The scanner informs the decision; the override is explicit in the checkpoint.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

VERSION = "v1.0"

# Approximate MLB league-average over/under used as the park divergence baseline.
_LEAGUE_BASELINE_TOTAL: float = 8.5

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "era_xera_gap_min": 0.30,
    "park_factor_min": 1.040,
    "park_total_div_min": 0.06,
    "book_spread_min": 0.50,
    "pitcher_role_pa_max": 200.0,
    "tail_score_min": 2.0,
}

# Full team name to DK-compatible abbreviation.  Stable across seasons; update
# only for expansion, contraction, or relocation.
_TEAM_NAME_TO_ABBREV: Dict[str, str] = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Athletics": "ATH",
    "Oakland Athletics": "ATH",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}

# MLB Stats API returns "AZ" and "ATH"; remap to DK abbreviations.
_API_ABBREV_REMAP: Dict[str, str] = {"AZ": "ARI", "ATH": "ATH"}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_park_factors(path: str | Path) -> Dict[str, float]:
    """Return {venue_name: Run_Factor_Applied} from f5_park_factors.csv."""
    factors: Dict[str, float] = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                factors[row["Venue"]] = float(row["Run_Factor_Applied"])
            except (KeyError, ValueError):
                pass
    return factors


def _load_team_venues(path: str | Path) -> Dict[str, str]:
    """Return {team_abbrev: venue_name} from team_to_venue.csv."""
    mapping: Dict[str, str] = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            mapping[row["Home_Team"]] = row["Venue"]
    return mapping


def _load_statcast_pitching(path: str | Path) -> Dict[int, Dict[str, Any]]:
    """Return {mlbam_player_id: row_dict} from expected_stats_pitching.csv.

    Keeps the highest-PA row on a player_id collision (same player, multiple
    years; the more-recent/larger sample is preferred for the ERA/xERA signal).
    """
    data: Dict[int, Dict[str, Any]] = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                pid = int(row["player_id"])
            except (KeyError, ValueError):
                continue
            try:
                pa = int(row.get("pa") or 0)
                era = float(row["era"]) if row.get("era") not in (None, "", "null") else None
                xera = float(row["xera"]) if row.get("xera") not in (None, "", "null") else None
            except ValueError:
                continue
            existing = data.get(pid)
            if existing is None or pa > existing.get("pa", 0):
                data[pid] = {
                    "first_name": (row.get("first_name") or "").strip(),
                    "last_name": (row.get("last_name") or "").strip(),
                    "pa": pa,
                    "era": era,
                    "xera": xera,
                }
    return data


# ---------------------------------------------------------------------------
# Feed parsers
# ---------------------------------------------------------------------------

def _odds_by_game(odds_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index odds feed by 'AWAY@HOME' abbreviation key.

    Uses _TEAM_NAME_TO_ABBREV to convert full team names from the odds feed.
    Falls back to the raw string when a name is not in the map (handles both
    full team names from the odds skill and abbreviations in test fixtures).
    When both DK and FD list a total, the implied total is their average.
    Falls back to whichever book is present.
    """
    indexed: Dict[str, Dict[str, Any]] = {}
    for game in odds_json.get("games", []):
        away_name = game.get("away_team", "")
        home_name = game.get("home_team", "")
        away = _TEAM_NAME_TO_ABBREV.get(away_name, away_name)
        home = _TEAM_NAME_TO_ABBREV.get(home_name, home_name)
        if not away or not home:
            continue
        books = game.get("books", {})
        dk_total = (books.get("draftkings") or {}).get("total", {}).get("line")
        fd_total = (books.get("fanduel") or {}).get("total", {}).get("line")
        if dk_total is not None and fd_total is not None:
            implied = (float(dk_total) + float(fd_total)) / 2.0
        elif dk_total is not None:
            implied = float(dk_total)
        elif fd_total is not None:
            implied = float(fd_total)
        else:
            implied = None
        key = f"{away}@{home}"
        indexed[key] = {
            "dk_total": float(dk_total) if dk_total is not None else None,
            "fd_total": float(fd_total) if fd_total is not None else None,
            "implied_total": implied,
        }
    return indexed


def _pitchers_by_game(lineups_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return {AWAY@HOME: {away_pitcher_id, home_pitcher_id, ...}} from lineups feed.

    Remaps MLB Stats API abbreviations (AZ, ATH) to DK abbreviations.
    """
    result: Dict[str, Dict[str, Any]] = {}
    for game in lineups_json.get("games", []):
        away_abbrev = _API_ABBREV_REMAP.get(
            game.get("away", {}).get("team_abbrev", ""),
            game.get("away", {}).get("team_abbrev", ""),
        )
        home_abbrev = _API_ABBREV_REMAP.get(
            game.get("home", {}).get("team_abbrev", ""),
            game.get("home", {}).get("team_abbrev", ""),
        )
        if not away_abbrev or not home_abbrev:
            continue
        key = f"{away_abbrev}@{home_abbrev}"
        away_sp = game.get("away", {}).get("probable_pitcher") or {}
        home_sp = game.get("home", {}).get("probable_pitcher") or {}
        result[key] = {
            "away_pitcher_id": away_sp.get("id"),
            "away_pitcher_name": away_sp.get("name"),
            "home_pitcher_id": home_sp.get("id"),
            "home_pitcher_name": home_sp.get("name"),
        }
    return result


# ---------------------------------------------------------------------------
# Signal computers
# ---------------------------------------------------------------------------

def _era_xera_signal(
    away_pid: Optional[int],
    home_pid: Optional[int],
    statcast: Dict[int, Dict[str, Any]],
    threshold: float,
) -> Dict[str, Any]:
    """ERA/xERA luck divergence signal.

    Computes xERA - ERA for each SP with a Statcast match, then uses the
    maximum gap across both starters.  A positive gap means xERA exceeds ERA:
    the pitcher has outperformed on balls in play (gotten lucky) and the market
    may be anchoring the implied total to an ERA that understates true run risk.
    """
    candidates: List[Dict[str, Any]] = []
    for pid in (away_pid, home_pid):
        if pid is None:
            continue
        row = statcast.get(int(pid))
        if row is None:
            continue
        era = row.get("era")
        xera = row.get("xera")
        if era is None or xera is None:
            continue
        gap = xera - era
        candidates.append({
            "player_id": pid,
            "name": f"{row['first_name']} {row['last_name']}".strip() or str(pid),
            "era": round(era, 3),
            "xera": round(xera, 3),
            "gap": round(gap, 3),
        })
    if not candidates:
        return {
            "status": "unavailable",
            "reason": "no_statcast_match",
            "threshold": threshold,
        }
    best = max(candidates, key=lambda c: c["gap"])
    triggered = best["gap"] >= threshold
    return {
        "status": "triggered" if triggered else "not_triggered",
        "value": best["gap"],
        "threshold": threshold,
        "pitcher": best["name"],
        "era": best["era"],
        "xera": best["xera"],
        "all_pitchers": candidates,
    }


def _park_total_signal(
    run_factor: Optional[float],
    implied_total: Optional[float],
    park_factor_min: float,
    div_min: float,
) -> Dict[str, Any]:
    """Park factor vs. implied total divergence signal.

    When the implied total is unavailable, reports a partial flag for
    hitter-friendly parks so downstream can see the park context even without
    odds.  The partial flag contributes 0.5 to the composite tail score.
    """
    if run_factor is None:
        return {
            "status": "unavailable",
            "reason": "no_park_factor",
            "park_factor_min": park_factor_min,
            "div_threshold": div_min,
        }
    if implied_total is None:
        if run_factor >= park_factor_min:
            return {
                "status": "partial",
                "reason": "hitter_friendly_park_no_implied_total",
                "run_factor": round(run_factor, 4),
                "park_factor_min": park_factor_min,
                "note": "hitter-friendly park; divergence not computable without implied total",
            }
        return {
            "status": "not_triggered",
            "run_factor": round(run_factor, 4),
            "park_factor_min": park_factor_min,
            "div_threshold": div_min,
        }
    park_expected = _LEAGUE_BASELINE_TOTAL * run_factor
    divergence = (park_expected - implied_total) / park_expected
    triggered = run_factor >= park_factor_min and divergence >= div_min
    return {
        "status": "triggered" if triggered else "not_triggered",
        "value": round(divergence, 4),
        "threshold": div_min,
        "run_factor": round(run_factor, 4),
        "park_expected_total": round(park_expected, 2),
        "implied_total": implied_total,
    }


def _book_spread_signal(
    dk_total: Optional[float],
    fd_total: Optional[float],
    threshold: float,
) -> Dict[str, Any]:
    """DK vs FanDuel total line disagreement signal.

    Two major books disagreeing on a total by >= threshold quantifies market
    uncertainty about the game script, making tail outcomes more plausible.
    """
    if dk_total is None and fd_total is None:
        return {"status": "unavailable", "reason": "no_book_data", "threshold": threshold}
    if dk_total is None:
        return {"status": "unavailable", "reason": "dk_total_missing", "threshold": threshold, "fd_total": fd_total}
    if fd_total is None:
        return {"status": "unavailable", "reason": "fd_total_missing", "threshold": threshold, "dk_total": dk_total}
    spread = round(abs(dk_total - fd_total), 2)
    triggered = spread >= threshold
    return {
        "status": "triggered" if triggered else "not_triggered",
        "value": spread,
        "threshold": threshold,
        "dk_total": dk_total,
        "fd_total": fd_total,
    }


def _pitcher_role_signal(
    away_pid: Optional[int],
    home_pid: Optional[int],
    away_name: Optional[str],
    home_name: Optional[str],
    statcast: Dict[int, Dict[str, Any]],
    pa_max: float,
) -> Dict[str, Any]:
    """Pitcher role inference signal (Tier 3b).

    A declared starter with Statcast PA count at or below pa_max has a profile
    more consistent with a bulk reliever or opener than a true starter.  The
    implied total suppression from SP quality modeling may overstate how good
    the pitching truly is.

    Caveat: this is an indirect proxy.  PA count from Statcast reflects full
    season accumulation; a starter with few PA may simply be new or injured.
    Always verify manually before building a lineup on this signal alone.
    """
    if away_pid is None and home_pid is None:
        return {"status": "unavailable", "reason": "no_pitcher_ids", "pa_max": int(pa_max)}
    flagged: List[Dict[str, Any]] = []
    for pid, display_name in [(away_pid, away_name), (home_pid, home_name)]:
        if pid is None:
            continue
        row = statcast.get(int(pid))
        if row is None:
            continue
        pa = row.get("pa", 0)
        if pa <= pa_max:
            name = display_name or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip() or str(pid)
            flagged.append({"player_id": pid, "name": name, "pa": pa})
    if not flagged:
        return {"status": "not_triggered", "pa_max": int(pa_max)}
    return {
        "status": "triggered",
        "pa_max": int(pa_max),
        "flagged_pitchers": flagged,
        "caveat": "low PA may reflect new/injured starter; verify role manually",
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _tail_score(signals: Dict[str, Any]) -> float:
    """Sum triggered signals; partial park_total_div counts 0.5."""
    score = 0.0
    for name, sig in signals.items():
        status = sig.get("status", "")
        if status == "triggered":
            score += 1.0
        elif name == "park_total_div" and status == "partial":
            score += 0.5
    return score


def _thesis_summary(
    signals: Dict[str, Any],
    game_id: str,
    venue: str,
) -> str:
    """One-line human-readable summary of what triggered."""
    parts: List[str] = []
    era = signals.get("era_xera_gap", {})
    if era.get("status") == "triggered":
        parts.append(
            f"{era.get('pitcher', 'SP')} xERA-ERA gap {era.get('value', 0):+.2f}"
        )
    park = signals.get("park_total_div", {})
    if park.get("status") in ("triggered", "partial"):
        rf = park.get("run_factor", "")
        implied = park.get("implied_total")
        if implied is not None:
            parts.append(f"park {rf} vs implied {implied}")
        else:
            parts.append(f"hitter-friendly park ({rf}); no total available")
    spread = signals.get("book_spread", {})
    if spread.get("status") == "triggered":
        parts.append(
            f"DK/FD spread {spread.get('value', 0):.1f} "
            f"(DK {spread.get('dk_total')}, FD {spread.get('fd_total')})"
        )
    role = signals.get("pitcher_role", {})
    if role.get("status") == "triggered":
        names = [p.get("name", "") for p in role.get("flagged_pitchers", [])]
        parts.append(f"possible bulk/opener: {', '.join(names)}")
    if not parts:
        return f"{game_id}: no signals triggered"
    location = f" at {venue}" if venue else ""
    return f"{game_id}{location}: " + "; ".join(parts)


def _coverage_tier(
    statcast_available: bool,
    lineups_available: bool,
    odds_available: bool,
) -> str:
    """Determine coverage tier label from available feed combination."""
    if statcast_available and lineups_available and odds_available:
        return "full"
    if statcast_available and lineups_available:
        return "statcast_park"
    if odds_available:
        return "park_odds"
    return "park_only"


def _active_signals(all_games: List[Dict[str, Any]]) -> List[str]:
    """Return signal names that are not universally unavailable across all games."""
    names = ("era_xera_gap", "park_total_div", "book_spread", "pitcher_role")
    return [
        n for n in names
        if any(
            g["signals"].get(n, {}).get("status") != "unavailable"
            for g in all_games
        )
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_tail_candidates(
    *,
    game_slate: Sequence[Dict[str, Any]],
    park_factors_path: str | Path,
    team_to_venue_path: str | Path,
    savant_pitching_path: Optional[str | Path] = None,
    odds_json: Optional[Dict[str, Any]] = None,
    lineups_json: Optional[Dict[str, Any]] = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Screen the slate for contrarian game thesis candidates.

    Parameters
    ----------
    game_slate
        Sequence of game dicts.  Required keys: ``away_team``, ``home_team``
        (DK-compatible abbreviations).  Optional: ``game_id``; derived as
        ``{away}@{home}`` when absent.
    park_factors_path
        Path to ``f5_park_factors.csv``.
    team_to_venue_path
        Path to ``team_to_venue.csv``.
    savant_pitching_path
        Path to ``expected_stats_pitching.csv``.  When None, era_xera_gap and
        pitcher_role signals are unavailable.
    odds_json
        Parsed output dict from the ``mlb-game-odds`` skill.  When None,
        book_spread is unavailable and park_total_div runs in partial mode.
    lineups_json
        Parsed output dict from the ``mlb-lineups`` skill.  When None,
        era_xera_gap and pitcher_role are unavailable.
    thresholds
        Dict of threshold overrides.  Keys must match ``DEFAULT_THRESHOLDS``.
        Unrecognized keys are silently ignored.

    Returns
    -------
    dict
        ``coverage_tier``, ``signals_active``, ``signals_unavailable``,
        ``flagged_games`` (score >= tail_score_min), ``all_games`` (every
        game with signal breakdown), ``thresholds_applied``.
        All outputs are labeled as deterministic review proxies.
    """
    t: Dict[str, float] = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    # --- load static tables ---
    park_factors = _load_park_factors(park_factors_path)
    team_venues = _load_team_venues(team_to_venue_path)

    # --- load optional feeds ---
    statcast: Dict[int, Dict[str, Any]] = {}
    statcast_available = False
    if savant_pitching_path is not None:
        try:
            statcast = _load_statcast_pitching(savant_pitching_path)
            statcast_available = bool(statcast)
        except Exception:
            statcast_available = False

    odds_index: Dict[str, Dict[str, Any]] = {}
    odds_available = False
    if odds_json is not None:
        try:
            odds_index = _odds_by_game(odds_json)
            odds_available = bool(odds_index)
        except Exception:
            odds_available = False

    pit_index: Dict[str, Dict[str, Any]] = {}
    lineups_available = False
    if lineups_json is not None:
        try:
            pit_index = _pitchers_by_game(lineups_json)
            lineups_available = bool(pit_index)
        except Exception:
            lineups_available = False

    all_games: List[Dict[str, Any]] = []
    for entry in game_slate:
        away = str(entry.get("away_team", "")).strip()
        home = str(entry.get("home_team", "")).strip()
        game_id = str(entry.get("game_id") or f"{away}@{home}").strip()
        venue = team_venues.get(home, "")
        run_factor = park_factors.get(venue)

        # Normalize lookup key so away@home always resolves even when game_id
        # was supplied with an alternate format.
        lookup_key = f"{away}@{home}"
        game_odds = odds_index.get(game_id) or odds_index.get(lookup_key) or {}
        game_pits = pit_index.get(game_id) or pit_index.get(lookup_key) or {}

        implied_total: Optional[float] = game_odds.get("implied_total")
        dk_total: Optional[float] = game_odds.get("dk_total")
        fd_total: Optional[float] = game_odds.get("fd_total")
        away_pid: Optional[int] = game_pits.get("away_pitcher_id")
        home_pid: Optional[int] = game_pits.get("home_pitcher_id")
        away_pname: Optional[str] = game_pits.get("away_pitcher_name")
        home_pname: Optional[str] = game_pits.get("home_pitcher_name")

        if statcast_available and lineups_available:
            era_sig = _era_xera_signal(away_pid, home_pid, statcast, t["era_xera_gap_min"])
            role_sig = _pitcher_role_signal(
                away_pid, home_pid, away_pname, home_pname, statcast, t["pitcher_role_pa_max"]
            )
        else:
            era_sig = {"status": "unavailable", "reason": "statcast_or_lineups_unavailable"}
            role_sig = {"status": "unavailable", "reason": "statcast_or_lineups_unavailable"}

        park_sig = _park_total_signal(run_factor, implied_total, t["park_factor_min"], t["park_total_div_min"])

        if odds_available:
            spread_sig = _book_spread_signal(dk_total, fd_total, t["book_spread_min"])
        else:
            spread_sig = {"status": "unavailable", "reason": "no_odds_feed"}

        signals = {
            "era_xera_gap": era_sig,
            "park_total_div": park_sig,
            "book_spread": spread_sig,
            "pitcher_role": role_sig,
        }

        score = _tail_score(signals)
        thesis = _thesis_summary(signals, game_id, venue)

        all_games.append({
            "game_id": game_id,
            "away_team": away,
            "home_team": home,
            "venue": venue,
            "run_factor": round(run_factor, 4) if run_factor is not None else None,
            "implied_total": implied_total,
            "tail_score": score,
            "signals": signals,
            "thesis": thesis,
        })

    all_games.sort(key=lambda g: g["tail_score"], reverse=True)
    flagged = [g for g in all_games if g["tail_score"] >= t["tail_score_min"]]

    active = _active_signals(all_games)
    all_signal_names = ["era_xera_gap", "park_total_div", "book_spread", "pitcher_role"]
    unavailable = [n for n in all_signal_names if n not in active]
    tier = _coverage_tier(statcast_available, lineups_available, odds_available)

    return {
        "scanner_version": VERSION,
        "coverage_tier": tier,
        "signals_active": active,
        "signals_unavailable": unavailable,
        "flagged_games": flagged,
        "all_games": all_games,
        "thresholds_applied": {k: v for k, v in t.items()},
        "note": (
            "deterministic review proxy only — not a probability estimate, "
            "ROI claim, or win-rate tool"
        ),
    }
