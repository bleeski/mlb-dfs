"""platoon_order_adapter.py

MLB Classic v2.22.0. VERSION = "v1.0".

Turns the FanGraphs RosterResource "Platoon Lineups" JSON into two upstream,
opt-in capabilities. Both run before execution_pipeline.run_slate and neither
touches the certified solve path. The FanGraphs file is a per-slate data input,
the same status as the Baseball Savant CSVs, not a checksummed engine file.

  (1) mispricing_screen(...) -- a deterministic review proxy. For each hitter it
      compares tonight's projected batting slot (the handedness-appropriate view)
      against the player's own RHP/LHP-frequency-weighted typical slot from the
      same file, and reports the F2-implied projection lift that the slot move
      represents. It routes attention to bats whose salary was likely set near a
      lower typical slot but who project higher tonight. It is NOT an ROI, edge,
      win-rate, or probability claim, and it does not change any projection by
      itself.

  (2) build_projected_order(...) -- a TBD-lineup fallback. It emits a
      {Player_ID: slot} map for the requested teams using the handedness view, to
      be applied as Batting_Order plus F2 = batting_order_factor(slot). It is
      consumed either by passing the map to run_slate(platoon_order_by_player_id=...)
      or by enriching projection_rows directly with apply_projected_order_to_rows.
      It intentionally does NOT emit confirmed_teams: a projected order must not
      trigger the confirmed-starter exclusion, so unconfirmed teams keep projected
      lineups (MLB_Classic.md section 4 / section 6). A real posted lineup later
      supersedes it through projection_builder.refresh_confirmed_lineups.

Opponent handedness comes from the mlb-lineups feed (probable_pitcher.hand), which
is usually populated even when batting orders are TBD, or from a caller-declared
map. The crosswalk reuses the engine's canonical name normalizer
(xwoba_base_correction._norm_name) so it never diverges from the xwOBA join, and
the authoritative salary file (slate_intake_manager.parse_dk_salary_csv) supplies
the DraftKings Player_IDs.

All outputs are deterministic review inputs. Nothing here is a profitability,
win-rate, or probability claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

# Canonical, shared helpers. Reused (not duplicated) so the name crosswalk cannot
# drift from the xwOBA join, and F2 stays identical to the engine's table.
from mlb_engine.projections.xwoba_base_correction import _norm_name
from mlb_engine.projections.projection_builder import batting_order_factor

VERSION = "v1.0"

# League-average share of games started by a RHP vs LHP. A labeled prior, not a
# calibrated value; override per slate with a better split if you have one.
DEFAULT_RHP_START_WEIGHT = 0.72

# Warn when a team's FanGraphs page is older than this many days at collection.
STALE_DAYS_WARN = 10


# The reference platoon file, refreshed manually from FanGraphs RosterResource.
# build_slate_pool loads this by default so TBD teams get a projected order
# instead of being dropped from the slate.
DEFAULT_PLATOON_REFERENCE = Path("data/reference/fangraphs_platoon_lineups.json")


# --------------------------------------------------------------------------- #
# Loading and opponent-hand resolution
# --------------------------------------------------------------------------- #
def _dk_abbrev(value: Any) -> str:
    """Normalize any source's team code to the DraftKings code.

    FanGraphs ships WSN/TBR/CHW/KCR/SDP/SFG and the MLB Stats API ships AZ. An
    un-normalized code matches no salary row and fills zero hitters without
    raising, so every team code entering this module goes through here.
    """
    from mlb_engine.intake.live_data_adapters import to_dk_abbrev

    return to_dk_abbrev(str(value or "").strip().upper())


def load_platoon_lineups(path: str | Path) -> Dict[str, Any]:
    """Read the FanGraphs platoon-lineups JSON from disk."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_opp_throws_from_lineups(lineups_json: Mapping[str, Any]) -> Dict[str, str]:
    """From an mlb-lineups feed, map each DK team abbrev to the OPPOSING starter's
    throw hand ('R'/'L'). A team's platoon view keys off the pitcher it faces, so
    the away team gets the home probable's hand and vice versa. The mlb-lineups
    feed usually populates probable_pitcher.hand even when lineup_status is 'tbd',
    which is exactly the TBD scenario the fallback targets.
    """
    out: Dict[str, str] = {}
    for g in lineups_json.get("games") or []:
        away, home = g.get("away") or {}, g.get("home") or {}
        a_team = _dk_abbrev(away.get("team_abbrev"))
        h_team = _dk_abbrev(home.get("team_abbrev"))
        a_hand = (away.get("probable_pitcher") or {}).get("hand")
        h_hand = (home.get("probable_pitcher") or {}).get("hand")
        if a_team and h_hand in ("R", "L"):
            out[a_team] = h_hand
        if h_team and a_hand in ("R", "L"):
            out[h_team] = a_hand
    return out


def _view_for_hand(team_entry: Mapping[str, Any], opp_hand: Optional[str],
                   default_hand: str) -> Tuple[List[dict], str]:
    """Return (lineup_rows, hand_used) for the handedness-appropriate view."""
    hand = (opp_hand or default_hand or "R").upper()
    key = "vs_LHP" if hand == "L" else "vs_RHP"
    return list(team_entry.get(key) or []), hand


def _page_stale_days(team_entry: Mapping[str, Any], collected_date: str) -> Optional[int]:
    from datetime import date
    pu = team_entry.get("page_updated")
    if not pu or not collected_date:
        return None
    try:
        y1, m1, d1 = (int(x) for x in str(pu).split("-"))
        y2, m2, d2 = (int(x) for x in str(collected_date).split("-"))
        return (date(y2, m2, d2) - date(y1, m1, d1)).days
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Name -> DK Player_ID crosswalk via the authoritative salary file
# --------------------------------------------------------------------------- #
def _salary_name_index(salary_csv: str | Path) -> Dict[Tuple[str, str], List[str]]:
    """(normalized_name, TEAM) -> [player_id]. Team-scoped to avoid name collisions."""
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    idx: Dict[Tuple[str, str], List[str]] = {}
    for p in parse_dk_salary_csv(str(salary_csv)):
        idx.setdefault((_norm_name(p.name), str(p.team).strip().upper()), []).append(p.player_id)
    return idx


# --------------------------------------------------------------------------- #
# Feature (2): TBD-lineup fallback -> {Player_ID: projected_slot}
# --------------------------------------------------------------------------- #
def build_projected_order(
    platoon: Mapping[str, Any],
    salary_csv: str | Path,
    opp_throws_by_team: Mapping[str, str],
    *,
    only_teams: Optional[List[str]] = None,
    default_hand: str = "R",
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Emit {Player_ID: slot} for the requested teams using the handedness view.

    Pass only_teams with the set of TBD teams so confirmed teams are left to the
    real lineup feed. opp_throws_by_team maps TEAM -> 'R'/'L' (see
    extract_opp_throws_from_lineups). When a team's opponent hand is unknown it
    falls back to default_hand and is recorded under hand_assumed_teams. Returns
    (order_map, report). The report's note states that these teams must NOT be
    passed as confirmed_teams.
    """
    name_idx = _salary_name_index(salary_csv)
    collected = str(platoon.get("collected_date") or "")
    order: Dict[str, int] = {}
    matched: List[dict] = []
    unmatched: List[dict] = []
    stale: List[dict] = []
    hand_assumed: List[str] = []
    want = {_dk_abbrev(t) for t in only_teams} if only_teams else None
    opp_throws_by_team = {_dk_abbrev(k): v for k, v in (opp_throws_by_team or {}).items()}

    for team_entry in platoon.get("teams") or []:
        team = _dk_abbrev(team_entry.get("abbrev"))
        if want is not None and team not in want:
            continue
        opp_hand = opp_throws_by_team.get(team)
        if opp_hand not in ("R", "L"):
            hand_assumed.append(team)
        rows, hand_used = _view_for_hand(team_entry, opp_hand, default_hand)
        sd = _page_stale_days(team_entry, collected)
        if sd is not None and sd > STALE_DAYS_WARN:
            stale.append({"team": team, "page_updated": team_entry.get("page_updated"), "days_old": sd})
        for row in rows:
            pid_list = name_idx.get((_norm_name(row.get("player", "")), team), [])
            if len(pid_list) == 1:
                order[pid_list[0]] = int(row["slot"])
                matched.append({"player": row.get("player"), "player_id": pid_list[0],
                                "team": team, "slot": int(row["slot"]), "hand_used": hand_used})
            else:
                unmatched.append({"player": row.get("player"), "team": team,
                                  "reason": "no salary match" if not pid_list else "ambiguous salary match"})

    # A requested team the file covers but that filled nothing is a crosswalk
    # failure (team code or name normalization), not thin data. It used to read as
    # success because the caller only saw a per-team hitter count.
    covered = {_dk_abbrev(t.get("abbrev")) for t in platoon.get("teams") or []}
    filled: Dict[str, int] = {}
    for m in matched:
        filled[m["team"]] = filled.get(m["team"], 0) + 1
    zero_fill = sorted(t for t in (want or covered) if t in covered and not filled.get(t))
    missing_from_file = sorted(t for t in (want or set()) if t not in covered)

    report = {
        "version": VERSION,
        "collected_date": collected,
        "n_matched": len(matched),
        "n_unmatched": len(unmatched),
        "matched": matched,
        "unmatched": unmatched,
        "filled_by_team": dict(sorted(filled.items())),
        "zero_fill_teams": zero_fill,
        "teams_missing_from_file": missing_from_file,
        "stale_teams": stale,
        "hand_assumed_teams": hand_assumed,
        "note": "Projected order, not confirmed. Do NOT pass these teams as "
                "confirmed_teams; a real posted lineup supersedes this via "
                "refresh_confirmed_lineups. Stale teams may predate roster moves.",
    }
    return order, report


def apply_projected_order_to_rows(
    rows: List[Mapping[str, Any]],
    order_by_player_id: Mapping[str, int],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Enrich projection_rows in place-equivalent fashion: for each row whose
    Player_ID is in order_by_player_id AND that lacks a Batting_Order, set
    Batting_Order = slot and F2 = batting_order_factor(slot), and tag Notes. Rows
    that already carry a Batting_Order are left untouched so a confirmed or
    explicit order always wins. Returns (new_rows, applied_player_ids).

    This is the row-level twin of run_slate(platoon_order_by_player_id=...); use it
    when you want to inspect or override the enriched rows before building.
    """
    bo = {str(k): int(v) for k, v in (order_by_player_id or {}).items()}
    out: List[Dict[str, Any]] = []
    applied: List[str] = []
    for raw in rows:
        r = dict(raw)
        pid = str(r.get("Player_ID") or r.get("player_id") or "").strip()
        slot = bo.get(pid)
        existing = r.get("Batting_Order")
        has_order = existing not in (None, "") and str(existing).strip() != ""
        if slot is not None and not has_order:
            r["Batting_Order"] = slot
            r["F2"] = batting_order_factor(slot)
            r["Notes"] = (str(r.get("Notes") or "") + "; F2 from projected batting order (platoon fallback)").lstrip("; ")
            applied.append(pid)
        out.append(r)
    return out, applied


# --------------------------------------------------------------------------- #
# Feature (1): mispricing screen (review proxy)
# --------------------------------------------------------------------------- #
def _f2_interp(slot: float) -> float:
    """Linear interpolation of the engine's F2 table for fractional (blended)
    slots. Integer slots return exactly batting_order_factor(slot)."""
    lo = max(1, int(slot))
    hi = min(9, lo + 1)
    f_lo, f_hi = batting_order_factor(lo), batting_order_factor(hi)
    return f_lo + (f_hi - f_lo) * (slot - lo)


def _typical_slot_blend(team_entry: Mapping[str, Any], rhp_w: float) -> Dict[str, Dict[str, Any]]:
    """Per player (keyed by normalized name): blended typical slot, per-view slots,
    and a platoon_only flag for players who appear in only one view."""
    lhp_w = 1.0 - rhp_w
    r = {_norm_name(p["player"]): p for p in team_entry.get("vs_RHP") or []}
    l = {_norm_name(p["player"]): p for p in team_entry.get("vs_LHP") or []}
    out: Dict[str, Dict[str, Any]] = {}
    for key in set(r) | set(l):
        sr = r[key]["slot"] if key in r else None
        sl = l[key]["slot"] if key in l else None
        name = (r.get(key) or l.get(key))["player"]
        if sr is not None and sl is not None:
            typ, platoon_only = rhp_w * sr + lhp_w * sl, None
        elif sr is not None:
            typ, platoon_only = float(sr), "vs_R only"
        else:
            typ, platoon_only = float(sl), "vs_L only"
        out[key] = {"name": name, "slot_vsRHP": sr, "slot_vsLHP": sl,
                    "typical_slot": typ, "platoon_only": platoon_only}
    return out


def mispricing_screen(
    platoon: Mapping[str, Any],
    opp_throws_by_team: Mapping[str, str],
    *,
    salary_csv: Optional[str | Path] = None,
    rhp_weight: float = DEFAULT_RHP_START_WEIGHT,
    default_hand: str = "R",
    only_teams: Optional[List[str]] = None,
    typical_order_map: Optional[Mapping[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Return rows sorted by F2-implied projection lift (descending). Review proxy.

    lift_pct = F2(tonight_slot) / F2(typical_slot) - 1, where typical_slot is the
    player's RHP/LHP-frequency-weighted slot in this same file. Positive means the
    player projects higher in the order tonight than their own platoon-blended
    norm, so a salary anchored to that norm understates expected plate appearances
    and leverage.

    typical_order_map, when supplied, overrides the within-file blend with an
    external typical-slot baseline (for example the output of
    build_typical_order_from_statcast.py, which reflects actual recent usage and is
    a sharper baseline). Keys are normalized "first last" names, optionally
    qualified as "TEAM|first last"; a name absent from the map falls back to the
    blend. If salary_csv is given, the DK Player_ID is attached.

    This is a deterministic review input. It does not change any projection by
    itself and is never an ROI, edge, win-rate, or probability claim.
    """
    name_idx = _salary_name_index(salary_csv) if salary_csv else None
    want = {_dk_abbrev(t) for t in only_teams} if only_teams else None
    opp_throws_by_team = {_dk_abbrev(k): v for k, v in (opp_throws_by_team or {}).items()}
    ext = {str(k): float(v) for k, v in (typical_order_map or {}).items()}
    out: List[Dict[str, Any]] = []
    for team_entry in platoon.get("teams") or []:
        team = _dk_abbrev(team_entry.get("abbrev"))
        if want is not None and team not in want:
            continue
        opp_hand = opp_throws_by_team.get(team) or default_hand
        view_key = "vs_LHP" if str(opp_hand).upper() == "L" else "vs_RHP"
        tonight = {_norm_name(p["player"]): p for p in team_entry.get(view_key) or []}
        blend = _typical_slot_blend(team_entry, rhp_weight)
        for key, prow in tonight.items():
            b = blend.get(key, {})
            tonight_slot = int(prow["slot"])
            typical = ext.get(f"{team}|{key}", ext.get(key, b.get("typical_slot", float(tonight_slot))))
            typical_source = "external" if (f"{team}|{key}" in ext or key in ext) else "within_file_blend"
            f_tonight = batting_order_factor(tonight_slot)
            f_typ = _f2_interp(typical)
            lift = (f_tonight / f_typ - 1.0) if f_typ else 0.0
            rec: Dict[str, Any] = {
                "team": team,
                "player": prow.get("player"),
                "bats": prow.get("bats"),
                "opp_hand": str(opp_hand).upper(),
                "tonight_slot": tonight_slot,
                "typical_slot": round(typical, 2),
                "typical_source": typical_source,
                "slot_delta": round(typical - tonight_slot, 2),  # + = moved up
                "f2_tonight": round(f_tonight, 4),
                "f2_typical": round(f_typ, 4),
                "lift_pct": round(100.0 * lift, 2),
                "platoon_only": b.get("platoon_only"),
            }
            if name_idx is not None:
                hits = name_idx.get((key, team), [])
                rec["Player_ID"] = hits[0] if len(hits) == 1 else None
            out.append(rec)
    out.sort(key=lambda r: r["lift_pct"], reverse=True)
    return out
