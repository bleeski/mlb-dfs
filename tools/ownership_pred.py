#!/usr/bin/env python3
"""ownership_pred.py -- emit and grade the structural ownership prior (R135).

The predict-then-grade shadow loop, both halves in one file because both halves
read one schema and a schema split across two tools drifts. BUILD emits before
lock; ARCHIVE grades at mine time.

    emit   salary file (+ optional feed, odds, base map)
           -> outputs/<date>/ownership_pred_<slate>.json
    grade  that file + the archived DK standings export
           -> per-feature MAE / signed error / Spearman, beside two named
              baselines, plus a ledger block for ARCHIVE to file

Nothing here is calibrated. Every number this tool emits or grades is an
UNCALIBRATED STRUCTURAL PRIOR or a deterministic error measurement over one
contest; none of it is an ROI figure, a win rate, a cash rate, or a probability
claim. A single contest never moves a prior (ledger discipline), and the
prediction is never fed to the optimizer, to projections, or to Ownership_Tier.

Design constraints, all deliberate:
  - review-only: reads files, writes one JSON, touches no build artifact and
    no run directory, so it cannot change what gets uploaded
  - no network and no API quota. An absent odds file makes the implied-total
    tilt INERT and says so; it never fetches to fill the gap
  - one definition per fact. Batting order comes from the engine's own R143
    ranking (``merge_dk_starting_into_feed`` then
    ``build_status_map_from_lineups_feed``), the total split from
    ``projection_builder.implied_team_totals``, actual %Drafted from
    ``field_miner.own_by_player_norm``, the join key from
    ``field_miner.normalize_name``, and the CPT/UTIL role collapse from
    ``slate_intake_manager.collapse_showdown_roles``. This tool re-derives
    none of them
  - one row per PERSON. R235: a Showdown salary export prices everybody twice,
    so the collapse runs at intake, before anything counts a row. Every count,
    key and budget below is therefore a count of people
  - absent inputs are NAMED. R127's boundary applies in both directions: a
    missing FILE reports ``applied: false`` with a reason and no list, a
    missing or ambiguous PLAYER is named per player
  - deterministic: every emitted mapping is written in sorted key order, and
    every reported list is sorted or rank-ordered

Why the prediction file carries a name crosswalk. ``grade_against_actuals``
joins on DK Player_ID; a DK standings export names players and has no Player_ID
column at all. Without the salary file's own name -> Player_ID map recorded at
emit time the join is empty and the grade returns "no overlapping Player_IDs",
which is the acceptance criterion failing silently. Two players whose names
normalize identically on one slate are AMBIGUOUS (the R75 class) and are
excluded from the join and named, never resolved to one id by guessing.

Exit codes: 0 clean, 2 refused (a fact the caller must fix), 3 IO error.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERSION = "v1.0"
SCHEMA = "ownership_pred/v1"

# The baseline R10's bar names, and the harder null it hides. flat-12 is the
# optimizer's Mid tier default ({'Low': 5.0, 'Mid': 12.0, 'High': 25.0}), a
# constant 12% for every player: over a 180-player slate it spends 2160% of a
# 1000% budget, so beating it on MAE is nearly free and a report that showed
# only flat-12 would read as a win the prior has not earned. flat-budget is the
# structural null that spends the real budget -- 800% across the hitters and
# 200% across the arms, evenly -- and it is the number to argue with.
FLAT_12_PCT = 12.0

ORDER_BANDS = (("1-3", 1, 3), ("4-6", 4, 6), ("7-9", 7, 9))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slate_date_from_salary(salary_csv: str | Path) -> Optional[str]:
    """The slate date off the salary file's own Game Info, never the clock.

    A tool run at 00:30 UTC on a 19:10 ET slate is on the next calendar day,
    and a default that reads the clock writes the prediction into tomorrow's
    outputs directory.
    """
    try:
        with open(salary_csv, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                info = str(row.get("Game Info") or "")
                for token in info.replace(",", " ").split():
                    if token.count("/") == 2:
                        month, day, year = token.split("/")
                        if len(year) == 4:
                            return f"{year}-{int(month):02d}-{int(day):02d}"
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

def _order_and_probables(
    salary_csv: Path,
    salary_players: Sequence[Any],
    feed_path: Optional[Path],
) -> Tuple[Dict[str, int], List[str], Dict[str, Any]]:
    """(order by Player_ID, probable SP ids, report) under R143's ranking.

    Both facts come from the engine's own readers so the prior cannot disagree
    with the pool about who is posted: DK's complete 1-9 sides first, then
    whatever the feed supplies for the sides DK has not posted.
    """
    from mlb_engine.intake.live_data_adapters import (
        build_status_map_from_lineups_feed, dk_declared_probables,
        merge_dk_starting_into_feed,
    )
    salary_map = {p.player_id: p for p in salary_players}
    feed: Dict[str, Any] = {}
    feed_note: Dict[str, Any] = {"path": None, "read": False}
    if feed_path is not None:
        if not feed_path.exists():
            feed_note = {"path": str(feed_path), "read": False,
                         "reason": "file does not exist"}
        else:
            try:
                feed = json.loads(feed_path.read_text(encoding="utf-8"))
                feed_note = {"path": str(feed_path), "read": True,
                             "games": len(feed.get("games") or [])}
            except (OSError, ValueError) as exc:
                feed_note = {"path": str(feed_path), "read": False,
                             "reason": f"unreadable: {exc}"}

    merged, dk_report = merge_dk_starting_into_feed(feed, salary_map)
    status = build_status_map_from_lineups_feed(merged, salary_map)
    orders = {str(k): int(v) for k, v in
              (status.get("confirmed_order_by_player_id") or {}).items()}
    probables = sorted({str(x) for x in (status.get("probable_pitcher_ids") or [])}
                       | set(dk_declared_probables(salary_map).values()))

    # Every side count here is intersected with the SALARY file's teams. A feed
    # is a whole-day pull and a slate is a draftgroup: reporting the feed's 24
    # posted sides against a 3-game slate reads as coverage the build does not
    # have. The salary file decides what is on the slate, here as everywhere.
    slate_teams = {str(p.team).strip().upper() for p in salary_players if p.team}
    dk_sides = sorted(set(dk_report.get("dk_sides") or []) & slate_teams)
    teams_with_an_order = {str(p.team).strip().upper() for p in salary_players
                           if str(p.player_id) in orders}
    report = {
        "applied": bool(orders),
        "slots": len(orders),
        "source_ranking": "DK Starting column (complete 1-9) first, then the "
                          "feed; R143, per side",
        "slate_teams": len(slate_teams),
        "sides_from_dk": dk_sides,
        "sides_from_feed": sorted((set(status.get("confirmed_teams") or [])
                                   & slate_teams) - set(dk_sides)),
        "sides_dk_left_to_feed": sorted(set(dk_report.get("sides_left_to_feed")
                                            or []) & slate_teams),
        "sides_with_no_posted_order": sorted(slate_teams - teams_with_an_order),
        "dk_feed_disagreements": dk_report.get("disagreements") or [],
        "feed": feed_note,
    }
    if not orders:
        report["reason"] = (
            "no side is posted 1-9 in the salary file and no feed supplied one, "
            "so the batting-order attention prior is INERT for every hitter and "
            "the no-known-slot discount applies to all of them")
    return orders, probables, report


def _implied_totals(odds_path: Optional[Path],
                    salary_csv: Path,
                    slate_teams: Optional[Sequence[str]] = None,
                    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """(implied total by DK team, report). Absent odds are inert, never fetched.

    The returned map is restricted to the slate's teams. An odds pull covers the
    whole day, so an unrestricted count reports 30 teams priced on a 3-game
    slate and hides the one slate game the book had not posted.
    """
    if odds_path is None:
        return {}, {"applied": False, "teams": 0, "source": None,
                    "reason": "no --odds file supplied; this tool never fetches "
                              "(no quota, no network), so every team falls back "
                              "to the prior's LEAGUE_MEAN_IMPLIED and the "
                              "implied-total tilt is INERT"}
    if not odds_path.exists():
        return {}, {"applied": False, "teams": 0, "source": str(odds_path),
                    "reason": "odds file does not exist; the implied-total tilt "
                              "is INERT"}
    from mlb_engine.intake.live_data_adapters import (
        normalize_odds_payload, parse_the_odds_api_totals, salary_game_times,
    )
    from mlb_engine.projections.projection_builder import implied_team_totals
    try:
        payload = json.loads(odds_path.read_text(encoding="utf-8"))
        raw, shape = normalize_odds_payload(payload)
    except (OSError, ValueError) as exc:
        return {}, {"applied": False, "teams": 0, "source": str(odds_path),
                    "reason": f"odds file not usable: {exc}; the implied-total "
                              f"tilt is INERT"}
    try:
        slate_times = salary_game_times(str(salary_csv))
    except Exception:  # noqa: BLE001 - leg resolution never blocks a report
        slate_times = {}
    parsed = parse_the_odds_api_totals(raw, slate_game_times=slate_times)
    odds_by_game = parsed.get("odds_by_game_id") or {}
    on_slate = {str(t).strip().upper() for t in (slate_teams or [])}
    totals: Dict[str, float] = {}
    games_without_total: List[str] = []
    for game_id in sorted(odds_by_game):
        entry = odds_by_game[game_id] or {}
        if "@" not in game_id:
            continue
        away, home = (part.strip().upper() for part in game_id.split("@", 1))
        if on_slate and not ({away, home} & on_slate):
            continue
        moneyline = entry.get("moneyline") or {}
        split = implied_team_totals(entry.get("total"),
                                   moneyline.get(away), moneyline.get(home))
        if split is None:
            games_without_total.append(game_id)
            continue
        totals[away] = round(float(split[0]), 3)
        totals[home] = round(float(split[1]), 3)
    priced = sorted(set(totals) & on_slate) if on_slate else sorted(totals)
    report = {
        "applied": bool(totals),
        "teams": len(totals),
        "source": str(odds_path),
        "payload_shape": shape,
        "slate_teams_priced": (f"{len(priced)} of {len(on_slate)}" if on_slate
                               else str(len(priced))),
        "slate_teams_without_a_total": (sorted(on_slate - set(totals))
                                        if on_slate else []),
        "games_without_a_total": games_without_total,
        "split": "projection_builder.implied_team_totals (moneyline devig when "
                 "posted, even split when not)",
        "park_adjusted": False,
        "park_note": "field behaviour, not F1: the crowd reads the posted total, "
                     "so this prior deliberately does NOT de-park it the way "
                     "build_f1_factors does",
    }
    if not totals:
        report["reason"] = ("the odds payload mapped no game on this slate; the "
                           "implied-total tilt is INERT")
    elif report["slate_teams_without_a_total"]:
        report["partial_note"] = (
            "every team named above falls back to LEAGUE_MEAN_IMPLIED, so its "
            "hitters carry no implied-total tilt while the rest of the slate does")
    return totals, report


def _base_projections(path: Optional[Path]) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Optional {Player_ID: Base} for the value tilt, from a JSON map or a CSV."""
    if path is None:
        return {}, {"applied": False, "players": 0, "source": None,
                    "reason": "no --base file supplied; the value tilt "
                              "(points per $1k) is INERT"}
    if not path.exists():
        return {}, {"applied": False, "players": 0, "source": str(path),
                    "reason": "base file does not exist; the value tilt is INERT"}
    out: Dict[str, float] = {}
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                rows: Any = payload.get("base_by_player_id", payload)
                for pid, value in (rows or {}).items():
                    try:
                        out[str(pid)] = float(value)
                    except (TypeError, ValueError):
                        continue
        else:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    lower = {(k or "").strip().lower(): v for k, v in row.items()}
                    pid = lower.get("player_id") or lower.get("id")
                    value = lower.get("base") or lower.get("projection")
                    if pid is None or value in (None, ""):
                        continue
                    try:
                        out[str(pid).strip()] = float(value)
                    except (TypeError, ValueError):
                        continue
    except (OSError, ValueError) as exc:
        return {}, {"applied": False, "players": 0, "source": str(path),
                    "reason": f"base file not usable: {exc}; the value tilt is INERT"}
    report = {"applied": bool(out), "players": len(out), "source": str(path)}
    if not out:
        report["reason"] = ("the base file carried no usable Player_ID -> value "
                            "rows; the value tilt is INERT")
    return out, report


def _crosswalk(salary_players: Sequence[Any]) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """(normalized name -> Player_ID, ambiguous names).

    The R75 class, named rather than resolved: two players whose names normalize
    identically on one slate cannot be told apart by a standings export, so both
    leave the join and both are reported.
    """
    from mlb_engine.field.field_miner import normalize_name
    by_norm: Dict[str, List[Any]] = {}
    for player in salary_players:
        by_norm.setdefault(normalize_name(player.name), []).append(player)
    out: Dict[str, str] = {}
    ambiguous: List[Dict[str, Any]] = []
    for norm in sorted(by_norm):
        players = by_norm[norm]
        if len(players) == 1:
            out[norm] = str(players[0].player_id)
            continue
        ambiguous.append({
            "name_norm": norm,
            "Player_IDs": sorted(str(p.player_id) for p in players),
            "names": sorted({str(p.name) for p in players}),
            "teams": sorted({str(p.team) for p in players}),
        })
    return out, ambiguous


def build_prediction(
    salary_csv: str | Path,
    feed_path: Optional[str | Path] = None,
    odds_path: Optional[str | Path] = None,
    base_path: Optional[str | Path] = None,
    archetypes: Optional[Sequence[str]] = None,
    slate_tag: str = "",
    slate_date: Optional[str] = None,
) -> Dict[str, Any]:
    """The whole prediction payload for one slate. No writes, no network."""
    from mlb_engine.field import ownership_prior
    from mlb_engine.field.field_miner import normalize_name
    from mlb_engine.intake.slate_intake_manager import (
        collapse_showdown_roles, parse_dk_salary_csv,
    )

    salary_csv = Path(salary_csv)
    players = list(parse_dk_salary_csv(str(salary_csv)))
    if not players:
        raise ValueError(f"{salary_csv} parsed to zero players")
    # R235. Before ANY count: on a Showdown file every person owns two salary
    # rows, and every reader below -- the crosswalk, the batting-order read, the
    # prior's 800/200 budget -- is a per-person reader handed per-role rows. A
    # Classic file passes through untouched.
    players, showdown_report = collapse_showdown_roles(players)
    players.sort(key=lambda p: str(p.player_id))

    slate_teams = sorted({str(p.team).strip().upper() for p in players if p.team})
    orders, probables, order_report = _order_and_probables(
        salary_csv, players, Path(feed_path) if feed_path else None)
    totals, totals_report = _implied_totals(
        Path(odds_path) if odds_path else None, salary_csv, slate_teams)
    bases, base_report = _base_projections(Path(base_path) if base_path else None)
    crosswalk, ambiguous = _crosswalk(players)

    wanted = list(archetypes or sorted(ownership_prior.ARCHETYPE_PARAMS))
    unknown = [a for a in wanted if a not in ownership_prior.ARCHETYPE_PARAMS]
    if unknown:
        raise ValueError(
            "unknown archetype(s) " + ", ".join(sorted(unknown)) + "; known: "
            + ", ".join(sorted(ownership_prior.ARCHETYPE_PARAMS)))

    probable_set = set(probables)
    rows: List[Dict[str, Any]] = []
    for player in players:
        pool = "pitcher" if "P" in {str(t).strip().upper()
                                   for t in player.positions} else "hitter"
        pid = str(player.player_id)
        rows.append({
            "Player_ID": pid,
            "Name": str(player.name),
            "name_norm": normalize_name(player.name),
            "team": str(player.team).strip().upper(),
            "salary": float(player.salary),
            "pool": pool,
            "features": {
                "batting_order": orders.get(pid),
                "implied_total": totals.get(str(player.team).strip().upper()),
                "probable_sp": pid in probable_set,
                "base_projection": bases.get(pid),
            },
        })

    # R306. A Showdown salary file gets TWO extra distributions beside the
    # Classic one, because the Classic geometry is not this contest's: a
    # Showdown roster is six people plus a captain, so the person market sums
    # to 600% and the captain slot to 100%, both measured at exactly those
    # values in 41 of 41 archived Showdown contests. ``predict_ownership``'s
    # 800/200 split sums to 1000% on the same file.
    #
    # THE DETECTOR IS BOTH HALVES, and the first cut of it was one half and
    # wrong. It read the roster tokens alone, on the stated reasoning that
    # ``showdown_report['applied']`` is False on a Showdown file whose every
    # key is an unpaired CPT/UTIL pair. That reasoning is FALSE: `applied` is
    # set for every file that reaches the collapse, pairing or not. What is
    # actually true is the case it misses in the other direction. A file whose
    # Roster Position column carries a CPT token AND something outside
    # CPT/UTIL takes ``collapse_showdown_roles``' early return -- `applied`
    # False, rows returned per ROLE rather than per PERSON -- while "CPT" is
    # still in `roles_seen`. A token-only detector emits a 600% PERSON market
    # over rows that are still one-per-role, which double-counts everybody:
    # R235's own bug, re-entered through a door R235 does not watch. So both
    # halves are required, and the geometry question and the "is this pool
    # per-person yet" question are asked separately because they are separate.
    is_showdown = (
        bool(showdown_report.get("applied"))
        and "CPT" in {str(r).strip().upper()
                      for r in (showdown_report.get("roles_seen") or [])})

    per_archetype: Dict[str, Any] = {}
    for archetype in sorted(wanted):
        prediction = ownership_prior.predict_ownership(
            players,
            archetype=archetype,
            implied_total_by_team=totals,
            batting_order_by_player_id=orders,
            probable_sp_ids=probables,
            base_projection_by_player_id=bases or None,
        )
        own = prediction["own_pct_by_player_id"]
        pools = {"hitter": 0.0, "pitcher": 0.0}
        for row in rows:
            pools[row["pool"]] += float(own.get(row["Player_ID"], 0.0))
        block: Dict[str, Any] = {
            "own_pct_by_player_id": {k: own[k] for k in sorted(own)},
            "tier_by_player_id": {k: prediction["tier_by_player_id"][k]
                                  for k in sorted(prediction["tier_by_player_id"])},
            "params": prediction["params"],
            "budget_check": {
                "hitter_pct_sum": round(pools["hitter"], 1),
                "hitter_budget_pct": ownership_prior.HITTER_BUDGET_PCT,
                "pitcher_pct_sum": round(pools["pitcher"], 1),
                "pitcher_budget_pct": ownership_prior.PITCHER_BUDGET_PCT,
                "note": "8 hitter slots and 2 P slots per Classic roster, so the "
                        "field's shares sum to 800 and 200; a sum off its budget "
                        "means a player left the pool between the softmax and here",
            },
        }
        if is_showdown:
            for key, predict, budget in (
                ("showdown_roster",
                 ownership_prior.predict_showdown_roster_ownership,
                 ownership_prior.SHOWDOWN_ROSTER_BUDGET_PCT),
                ("captain",
                 ownership_prior.predict_captain_ownership,
                 ownership_prior.CAPTAIN_BUDGET_PCT),
            ):
                sd = predict(
                    players,
                    archetype=archetype,
                    implied_total_by_team=totals,
                    batting_order_by_player_id=orders,
                    probable_sp_ids=probables,
                    base_projection_by_player_id=bases or None,
                )
                sd_own = sd["own_pct_by_player_id"]
                block[key] = {
                    "own_pct_by_player_id": {k: sd_own[k] for k in sorted(sd_own)},
                    "tier_by_player_id": {k: sd["tier_by_player_id"][k]
                                          for k in sorted(sd["tier_by_player_id"])},
                    "params": sd["params"],
                    "budget_check": {
                        "pct_sum": round(sum(sd_own.values()), 1),
                        "budget_pct": budget,
                        "note": "the softmax allocates exactly this budget, so a "
                                "sum off it by more than per-player rounding "
                                "means a player left the pool between the "
                                "softmax and here",
                    },
                    "note": sd["note"],
                }
        per_archetype[archetype] = block

    return {
        "schema": SCHEMA,
        "tool_version": VERSION,
        "prior_version": ownership_prior.VERSION,
        "generated_utc": _now_utc(),
        "slate_date": slate_date or slate_date_from_salary(salary_csv) or "",
        "slate_tag": str(slate_tag or ""),
        "salary_file": {"path": str(salary_csv), "sha256": _sha256(salary_csv),
                        "players": len(players),
                        "showdown_roles": showdown_report},
        "showdown_markets": {
            "applied": bool(is_showdown),
            "detector": "a CPT token in the salary file's Roster Position "
                        "column, read off collapse_showdown_roles' roles_seen",
            "captain_budget_pct": ownership_prior.CAPTAIN_BUDGET_PCT,
            "roster_budget_pct": ownership_prior.SHOWDOWN_ROSTER_BUDGET_PCT,
            "note": "R306. On a Showdown file each archetype block carries two "
                    "extra distributions over the SAME collapsed people: "
                    "`showdown_roster` at 600% and `captain` at 100%. The "
                    "Classic `own_pct_by_player_id` beside them is the 800/200 "
                    "split and sums to 1000% on this geometry; it is kept "
                    "because every existing reader reads it, and it is the "
                    "wrong accounting for a Showdown contest. Absent on a "
                    "Classic file, where the Classic split is correct."
                    if is_showdown else
                    "Classic salary file: the 800/200 split is this contest's "
                    "accounting and no Showdown distribution is emitted.",
        },
        "label": "UNCALIBRATED STRUCTURAL PRIOR. Predicted %Drafted per contest "
                 "archetype from features public before lock. Never a win rate, "
                 "an ROI figure, a cash rate, or a probability claim; never fed "
                 "to the optimizer, to projections, or to Ownership_Tier.",
        "inputs": {
            "batting_order": order_report,
            "implied_totals": totals_report,
            "probable_sp": {
                "applied": bool(probables),
                "count": len(probables),
                "ids": probables,
                "source": "DK Starting SP/P tokens plus the feed's probables",
                **({} if probables else {
                    "reason": "no probable arm is named by DK or the feed, so "
                              "every arm takes the non-probable discount"}),
            },
            "base_projection": base_report,
        },
        "crosswalk": {
            "name_norm_to_player_id": crosswalk,
            "normalizer": "field_miner.normalize_name, the same function that "
                          "produces player_norm in a mined standings export",
            "ambiguous_names": ambiguous,
            "note": "a DK standings export carries names and no Player_ID, so "
                    "the grade joins through this map; ambiguous names are "
                    "excluded from the join rather than resolved by guessing",
        },
        "players": rows,
        "archetypes": per_archetype,
        "prior_note": ownership_prior.predict_ownership(
            [], archetype=sorted(wanted)[0])["note"],
    }


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------

def _bucket_metrics(pairs: Sequence[Tuple[float, float]]) -> Dict[str, Any]:
    """MAE, mean signed error and Spearman over (predicted, actual) pairs."""
    if not pairs:
        return {"n": 0}
    errors = [p - a for p, a in pairs]
    out: Dict[str, Any] = {
        "n": len(pairs),
        "mae_pct_points": round(sum(abs(e) for e in errors) / len(errors), 2),
        "mean_signed_error_pct_points": round(sum(errors) / len(errors), 2),
        "mean_actual_pct": round(sum(a for _, a in pairs) / len(pairs), 2),
    }
    if len(pairs) >= 3:
        spearman = _spearman([p for p, _ in pairs], [a for _, a in pairs])
        out["spearman_rank_corr"] = (round(spearman, 3) if spearman is not None
                                     else None)
    return out


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    def ranks(values: Sequence[float]) -> List[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


def _feature_buckets(row: Mapping[str, Any]) -> List[str]:
    """Which per-feature buckets one player belongs to.

    A player sits in several at once (pool, order band, salary band, SP flag),
    which is the point: the question R135 exists to answer is WHICH structural
    signal misses, and a single partition cannot say.
    """
    features = row.get("features") or {}
    labels = [f"pool={row.get('pool')}"]
    order = features.get("batting_order")
    if order is None:
        labels.append("order=unposted")
    else:
        for name, low, high in ORDER_BANDS:
            if low <= int(order) <= high:
                labels.append(f"order={name}")
                break
        else:
            labels.append("order=unposted")
    if row.get("pool") == "pitcher":
        labels.append("probable_sp=" + ("yes" if features.get("probable_sp")
                                        else "no"))
    total = features.get("implied_total")
    if total is None:
        labels.append("implied_total=absent")
    else:
        labels.append("implied_total=" + ("high" if float(total) >= 5.0
                                          else ("low" if float(total) < 4.0
                                                else "mid")))
    return labels


def _salary_band_labels(rows: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    """Player_ID -> salary quartile label, computed WITHIN each pool.

    Across pools it would only ever rediscover that arms cost more than bats.
    """
    out: Dict[str, str] = {}
    for pool in ("hitter", "pitcher"):
        members = sorted((r for r in rows if r.get("pool") == pool),
                         key=lambda r: (float(r["salary"]), str(r["Player_ID"])))
        n = len(members)
        for index, row in enumerate(members):
            quartile = min(4, int(4 * index / n) + 1) if n else 1
            out[str(row["Player_ID"])] = f"salary_q{quartile}"
    return out


def grade_prediction(
    prediction: Mapping[str, Any],
    actual_by_norm: Mapping[str, float],
    archetype: str,
    contest_id: str = "",
    field_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Grade one archetype's prediction against one contest's actual %Drafted."""
    from mlb_engine.field.ownership_prior import grade_against_actuals

    archetypes = prediction.get("archetypes") or {}
    if archetype not in archetypes:
        raise ValueError(
            f"the prediction file carries no archetype {archetype!r}; it has "
            + (", ".join(sorted(archetypes)) or "none"))
    predicted = archetypes[archetype]["own_pct_by_player_id"]
    rows = list(prediction.get("players") or [])
    by_id = {str(r["Player_ID"]): r for r in rows}
    crosswalk = ((prediction.get("crosswalk") or {})
                 .get("name_norm_to_player_id") or {})
    ambiguous = {a["name_norm"] for a in
                 ((prediction.get("crosswalk") or {}).get("ambiguous_names") or [])}

    actual_by_id: Dict[str, float] = {}
    unmatched_names: List[str] = []
    ambiguous_hits: List[str] = []
    for norm in sorted(actual_by_norm):
        if norm in ambiguous:
            ambiguous_hits.append(norm)
            continue
        pid = crosswalk.get(norm)
        if pid is None:
            unmatched_names.append(norm)
            continue
        actual_by_id[pid] = float(actual_by_norm[norm])

    overall = grade_against_actuals(predicted, actual_by_id)
    joined_ids = sorted(set(predicted) & set(actual_by_id))

    pairs = [(float(predicted[pid]), float(actual_by_id[pid])) for pid in joined_ids]
    salary_bands = _salary_band_labels(rows)
    buckets: Dict[str, List[Tuple[float, float]]] = {}
    for pid in joined_ids:
        row = by_id.get(pid)
        if row is None:
            continue
        pair = (float(predicted[pid]), float(actual_by_id[pid]))
        for label in _feature_buckets(row) + [salary_bands.get(pid, "salary_q?")]:
            buckets.setdefault(label, []).append(pair)

    baselines = {
        "flat_12": _bucket_metrics([(FLAT_12_PCT, a) for _, a in pairs]),
        "flat_budget": _bucket_metrics(
            _flat_budget_pairs(joined_ids, by_id, actual_by_id)),
    }
    prior_mae = _bucket_metrics(pairs).get("mae_pct_points")
    verdict = {
        "prior_mae_pct_points": prior_mae,
        "beats_flat_12": (None if prior_mae is None
                          else prior_mae < baselines["flat_12"]["mae_pct_points"]),
        "beats_flat_budget": (None if prior_mae is None
                              else prior_mae < baselines["flat_budget"]["mae_pct_points"]),
        "note": "flat-12 is the baseline R10's bar names (the optimizer's Mid "
                "tier default, a constant 12% that spends double the roster "
                "budget), so clearing it is nearly free; flat-budget spends the "
                "real 800/200 evenly and is the null worth arguing with. ONE "
                "contest never moves a prior.",
    }

    return {
        "schema": "ownership_grade/v1",
        "tool_version": VERSION,
        "prior_version": prediction.get("prior_version"),
        "graded_utc": _now_utc(),
        "slate_date": prediction.get("slate_date"),
        "slate_tag": prediction.get("slate_tag"),
        "archetype": archetype,
        "contest_id": str(contest_id or ""),
        "field_size": field_size,
        "overall": overall,
        "per_feature": {label: _bucket_metrics(buckets[label])
                        for label in sorted(buckets)},
        "baselines": baselines,
        "verdict": verdict,
        "join": {
            "actual_names": len(actual_by_norm),
            "joined_players": len(joined_ids),
            "unmatched_actual_names": unmatched_names,
            "ambiguous_actual_names": ambiguous_hits,
            "predicted_not_in_contest": len(set(predicted) - set(actual_by_id)),
            "note": "an actual name that reaches no Player_ID is named here, not "
                    "dropped into a count: a standings export whose slate is not "
                    "this salary file's produces a near-total unmatched list, "
                    "which is a different fact from a prior that missed",
        },
        "label": "DETERMINISTIC ERROR MEASUREMENT of an uncalibrated structural "
                 "prior over ONE contest. Not a win rate, an ROI figure, a cash "
                 "rate, or a probability claim. Condition on contest archetype "
                 "and field size; never pool across them.",
    }


def _flat_budget_pairs(joined_ids: Sequence[str],
                       by_id: Mapping[str, Any],
                       actual_by_id: Mapping[str, float]) -> List[Tuple[float, float]]:
    from mlb_engine.field.ownership_prior import (
        HITTER_BUDGET_PCT, PITCHER_BUDGET_PCT,
    )
    counts = {"hitter": 0, "pitcher": 0}
    for pid, row in by_id.items():
        counts[str(row.get("pool"))] = counts.get(str(row.get("pool")), 0) + 1
    flat = {
        "hitter": HITTER_BUDGET_PCT / counts["hitter"] if counts["hitter"] else 0.0,
        "pitcher": PITCHER_BUDGET_PCT / counts["pitcher"] if counts["pitcher"] else 0.0,
    }
    pairs: List[Tuple[float, float]] = []
    for pid in joined_ids:
        row = by_id.get(pid)
        if row is None:
            continue
        pairs.append((flat.get(str(row.get("pool")), 0.0), float(actual_by_id[pid])))
    return pairs


def actuals_from_standings(standings_csv: str | Path) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """{normalized name: actual %Drafted} from a DK standings export.

    R235(b). ``contest_type`` is READ off the miner's own parse, never
    re-derived here. This function used to call ``detect_contest_type`` a
    second time over ``entry['lineup']`` -- which ``parse_standings_export``
    returns as ``[(slot, name), ...]`` tuples, not as the raw cell text the
    detector counts slot tokens in. Every token missed, so the detector took
    its documented empty-input fallback and EVERY Showdown contest graded here
    was labelled ``classic`` in the grade's own evidence block. The miner
    already decided the contract before parsing a row and returns the answer;
    this is the tool's stated "one definition per fact" rule applied to the one
    fact where it had quietly grown a second implementation.
    """
    from mlb_engine.field.field_miner import (
        own_by_player_norm, parse_standings_export,
    )
    standings = parse_standings_export(str(standings_csv))
    own = own_by_player_norm(standings["player_table"])
    meta = {
        "path": str(standings_csv),
        "contest_type": str(standings.get("contest_type") or "unknown"),
        "contest_type_source": "field_miner.parse_standings_export",
        "entries": len(standings.get("entries") or []),
        "players_with_a_share": len(own),
    }
    return own, meta


def captain_actuals_from_entries(
    entries: Sequence[Mapping[str, Any]],
    crosswalk: Mapping[str, str],
    pool_player_ids: Sequence[str],
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """{Player_ID: realized captain %} over the WHOLE Showdown pool. R306 step 3.

    Counts ``captain_norm`` across complete entries, which
    ``parse_standings_export`` has stored on every mined file since R39, so
    this needs no re-mine and no new parsing. Two decisions worth stating:

    NOT ``field_miner``'s ``captain_table``. R39's producer computes one, but
    the key is absent -- not present-and-empty -- in 379 of 379 mined files on
    disk, so a code read suggests the aggregate is already stored and it is
    not. It is also truncated to ``most_common(8)`` and the median contest has
    12 distinct captains, so it would cap the distribution even once
    backfilled.

    NOT DK's ``%Drafted`` column either, though the reason on disk is not the
    one the filing gave. The filing says DK's ``player_table`` is person-level
    because ``roster_position`` reads ``UTIL`` on sampled rows. A census over
    all 41 usable archived Showdown exports finds 346 CPT rows beside 934 UTIL
    rows: 22 of the 41 ARE role-grained, and where they are, DK's CPT
    ``%Drafted`` agrees with the share counted here to a mean of 0.4 points.
    The real reason to count entries is that DK's right-hand table is
    TRUNCATED -- 19 of 41 exports carry no CPT row at all, and three that do
    carry exactly one against 8 to 10 distinct captains in their entries.
    ``entries[]`` is complete; the player table is not.

    THE ZERO TAIL IS INCLUDED, and that is why the pool is a parameter. On a
    Showdown slate the salary file IS the contest's player pool, so a player
    nobody captained has an observed captain share of 0.0. Dropping those
    truncates the sample at the end the prior is most likely to get wrong.
    """
    complete = [e for e in entries
                if e.get("lineup_complete") and e.get("captain_norm")]
    counts: Dict[str, int] = {}
    for entry in complete:
        norm = str(entry["captain_norm"])
        counts[norm] = counts.get(norm, 0) + 1
    n = len(complete)
    actual = {str(pid): 0.0 for pid in sorted({str(p) for p in pool_player_ids})}
    unmatched: List[str] = []
    for norm in sorted(counts):
        pid = crosswalk.get(norm)
        if pid is None or str(pid) not in actual:
            unmatched.append(norm)
            continue
        actual[str(pid)] = round(100.0 * counts[norm] / n, 4) if n else 0.0
    meta = {
        "complete_entries": n,
        "distinct_captains": len(counts),
        "pool_players": len(actual),
        "zero_captain_players": sum(1 for v in actual.values() if v == 0.0),
        "captain_names_reaching_no_pool_id": unmatched,
        "share_sum_pct": round(sum(actual.values()), 1),
        "source": "mined entries[].captain_norm, complete lineups only",
    }
    return actual, meta


def grade_captain_prediction(
    prediction: Mapping[str, Any],
    actual_by_id: Mapping[str, float],
    archetype: str,
    contest_id: str = "",
    field_size: Optional[int] = None,
    market: str = "captain",
) -> Dict[str, Any]:
    """Grade one Showdown market against its realized shares. R306 step 3.

    ``market`` selects the distribution: ``captain`` (100% budget) or
    ``showdown_roster`` (600%). The baseline is a FLAT allocation of that
    market's own budget over the pool, which is the honest null here: the
    flat-12 constant ``grade_prediction`` uses is a Classic artifact and means
    nothing against a 100% budget spread over twenty-odd people.
    """
    from mlb_engine.field.ownership_prior import grade_against_actuals

    archetypes = prediction.get("archetypes") or {}
    if archetype not in archetypes:
        raise ValueError(
            f"the prediction file carries no archetype {archetype!r}; it has "
            + (", ".join(sorted(archetypes)) or "none"))
    block = archetypes[archetype].get(market)
    if not block:
        raise ValueError(
            f"the prediction file carries no {market!r} distribution for "
            f"{archetype!r}; emit it from a Showdown salary file (see "
            "`showdown_markets` in the prediction)")
    predicted = block["own_pct_by_player_id"]
    budget = float((block.get("budget_check") or {}).get("budget_pct") or 0.0)

    overall = grade_against_actuals(predicted, actual_by_id)
    joined = sorted(set(map(str, predicted)) & set(map(str, actual_by_id)))
    pairs = [(float(predicted[pid]), float(actual_by_id[pid])) for pid in joined]
    flat = budget / len(joined) if joined else 0.0
    baseline = _bucket_metrics([(flat, a) for _, a in pairs])
    prior_mae = _bucket_metrics(pairs).get("mae_pct_points")

    return {
        "schema": "ownership_captain_grade/v1",
        "tool_version": VERSION,
        "prior_version": prediction.get("prior_version"),
        "graded_utc": _now_utc(),
        "market": str(market),
        "budget_pct": budget,
        "slate_date": prediction.get("slate_date"),
        "slate_tag": prediction.get("slate_tag"),
        "archetype": archetype,
        "contest_id": str(contest_id or ""),
        "field_size": field_size,
        "params": block.get("params"),
        "overall": overall,
        "join": {
            "joined_players": len(joined),
            "predicted_players": len(predicted),
            "actual_players": len(actual_by_id),
            "actual_nonzero": sum(1 for v in actual_by_id.values() if float(v) > 0),
        },
        "baseline_flat_budget": baseline,
        "verdict": {
            "prior_mae_pct_points": prior_mae,
            "beats_flat_budget": (
                None if prior_mae is None or baseline.get("mae_pct_points") is None
                else prior_mae < baseline["mae_pct_points"]),
        },
        "label": "DETERMINISTIC ERROR MEASUREMENT of an uncalibrated structural "
                 "prior over ONE contest's Showdown "
                 + str(market) + " market. The Spearman is a rank correlation "
                 "between two measured shares, not a prediction of anything. "
                 "Not a win rate, an ROI figure, a cash rate, or a probability "
                 "claim. Condition on contest archetype and field size; never "
                 "pool across them.",
    }


def ledger_block(grade: Mapping[str, Any]) -> str:
    """The block ARCHIVE files. One contest, labeled, conditioned, never pooled."""
    overall = grade.get("overall") or {}
    verdict = grade.get("verdict") or {}
    baselines = grade.get("baselines") or {}
    join = grade.get("join") or {}
    lines = [
        f"**Ownership prior grade | {grade.get('slate_date')} "
        f"{grade.get('slate_tag') or ''} | archetype {grade.get('archetype')} "
        f"| contest {grade.get('contest_id') or 'unnamed'} "
        f"| field {grade.get('field_size') if grade.get('field_size') else 'unstated'}**",
        "",
        f"- Prior `{grade.get('prior_version')}`: MAE "
        f"{overall.get('mae_pct_points')} pts, mean signed "
        f"{overall.get('mean_signed_error_pct_points')} pts, Spearman "
        f"{overall.get('spearman_rank_corr')}, joined {join.get('joined_players')} "
        f"of {join.get('actual_names')} named players.",
        f"- Baselines: flat-12 MAE "
        f"{(baselines.get('flat_12') or {}).get('mae_pct_points')} pts "
        f"(beaten: {verdict.get('beats_flat_12')}); flat-budget MAE "
        f"{(baselines.get('flat_budget') or {}).get('mae_pct_points')} pts "
        f"(beaten: {verdict.get('beats_flat_budget')}).",
    ]
    per_feature = grade.get("per_feature") or {}
    ranked = sorted(
        ((label, metrics) for label, metrics in per_feature.items()
         if metrics.get("mae_pct_points") is not None),
        key=lambda kv: -float(kv[1]["mae_pct_points"]))
    if ranked:
        lines.append("- Worst per-feature buckets: " + "; ".join(
            f"{label} MAE {metrics['mae_pct_points']} (n={metrics['n']})"
            for label, metrics in ranked[:5]) + ".")
    unmatched = join.get("unmatched_actual_names") or []
    if unmatched:
        lines.append(f"- {len(unmatched)} actual name(s) reached no Player_ID: "
                     + ", ".join(unmatched[:8])
                     + ("..." if len(unmatched) > 8 else "") + ".")
    ambiguous = join.get("ambiguous_actual_names") or []
    if ambiguous:
        lines.append(f"- {len(ambiguous)} name(s) ambiguous on this slate and "
                     f"excluded from the join: " + ", ".join(ambiguous) + ".")
    lines += ["", "- " + str(grade.get("label"))]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _emit_cli(args: argparse.Namespace) -> int:
    salary = Path(args.salary)
    if not salary.exists():
        print(f"REFUSED: salary file not found: {salary}", file=sys.stderr)
        return 3
    archetypes = ([a.strip() for a in args.archetype.split(",") if a.strip()]
                  if args.archetype else None)
    try:
        prediction = build_prediction(
            salary, feed_path=args.feed, odds_path=args.odds,
            base_path=args.base, archetypes=archetypes,
            slate_tag=args.slate or "", slate_date=args.date)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    slate_date = prediction["slate_date"]
    if args.out:
        out = Path(args.out)
    else:
        if not slate_date:
            print("REFUSED: no slate date in the salary file's Game Info; pass "
                  "--date or --out", file=sys.stderr)
            return 2
        tag = prediction["slate_tag"] or "slate"
        out = REPO_ROOT / "outputs" / slate_date / f"ownership_pred_{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(prediction, indent=2, sort_keys=False) + "\n",
                   encoding="utf-8")

    inputs = prediction["inputs"]
    print(f"ownership prior {prediction['prior_version']} | "
          f"{prediction['slate_date']} {prediction['slate_tag']} | "
          f"{len(prediction['players'])} salary players | "
          f"{len(prediction['archetypes'])} archetypes")
    for name in ("batting_order", "implied_totals", "probable_sp",
                 "base_projection"):
        block = inputs[name]
        state = "applied" if block.get("applied") else "INERT"
        detail = block.get("reason") or ""
        print(f"  {name:<16} {state}"
              + (f": {detail}" if detail else "")
              + ("" if detail else
                 f" ({block.get('slots') or block.get('teams') or block.get('count') or block.get('players')})"))
    roles = prediction["salary_file"].get("showdown_roles") or {}
    if roles.get("applied"):
        line = (f"  showdown_roles   COLLAPSED {roles['rows_in']} CPT/UTIL rows "
                f"to {roles['rows_out']} people; the UTIL row is kept")
        unpaired = roles.get("unpaired") or []
        if unpaired:
            line += (f"; {len(unpaired)} key(s) not a clean CPT+UTIL pair and "
                     f"left whole: "
                     + ", ".join(u["person_key"] for u in unpaired))
        print(line)
    markets = prediction.get("showdown_markets") or {}
    if markets.get("applied"):
        first = sorted(prediction["archetypes"])[0]
        block = prediction["archetypes"][first]
        cap = (block.get("captain") or {}).get("budget_check") or {}
        ros = (block.get("showdown_roster") or {}).get("budget_check") or {}
        print(f"  showdown_markets APPLIED: captain {cap.get('pct_sum')}% of "
              f"{cap.get('budget_pct')}%, roster {ros.get('pct_sum')}% of "
              f"{ros.get('budget_pct')}% (archetype {first})")
        print("                   the Classic 800/200 column beside them sums "
              "to 1000% on this geometry and is NOT this contest's accounting")
    ambiguous = prediction["crosswalk"]["ambiguous_names"]
    if ambiguous:
        print(f"  crosswalk        {len(ambiguous)} ambiguous name(s), excluded "
              f"from any grade join: "
              + ", ".join(a["name_norm"] for a in ambiguous))
    print(f"  written          {out}")
    print("  UNCALIBRATED STRUCTURAL PRIOR. Review only; nothing here reaches "
          "the optimizer.")
    return 0


def _grade_cli(args: argparse.Namespace) -> int:
    pred_path, standings = Path(args.pred), Path(args.standings)
    for path in (pred_path, standings):
        if not path.exists():
            print(f"REFUSED: file not found: {path}", file=sys.stderr)
            return 3
    try:
        prediction = json.loads(pred_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"REFUSED: {pred_path} is not readable JSON: {exc}", file=sys.stderr)
        return 3
    if str(prediction.get("schema")) != SCHEMA:
        print(f"REFUSED: {pred_path} carries schema "
              f"{prediction.get('schema')!r}, not {SCHEMA!r}", file=sys.stderr)
        return 2
    actual, meta = actuals_from_standings(standings)
    if not actual:
        print(f"REFUSED: {standings} yielded no %Drafted rows", file=sys.stderr)
        return 2
    try:
        grade = grade_prediction(prediction, actual, args.archetype,
                                contest_id=args.contest_id or "",
                                field_size=args.field_size)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    grade["standings"] = meta
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(grade, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    print(ledger_block(grade))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit and grade the structural ownership prior (R135). "
                    "Review-only; every number is an uncalibrated prior or a "
                    "deterministic error measurement.")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit", help="write the pre-lock prediction file")
    emit.add_argument("--salary", required=True, help="DKSalaries CSV")
    emit.add_argument("--feed", help="lineups_feed.json; DK's own posted 1-9 "
                                     "sides outrank it per side (R143)")
    emit.add_argument("--odds", help="odds packet / slate_bundle / raw "
                                     "the-odds-api events. Omitted means the "
                                     "implied-total tilt is inert; this tool "
                                     "never fetches.")
    emit.add_argument("--base", help="optional Player_ID -> Base map for the "
                                     "value tilt: a JSON dict, or any CSV with "
                                     "Player_ID and Base columns, which is what "
                                     "runs/<run_id>/final/projections.csv is. "
                                     "Omitted means the value tilt is inert.")
    emit.add_argument("--archetype", help="comma-separated subset; default all")
    emit.add_argument("--slate", help="slate tag for the filename, e.g. 1910_10g")
    emit.add_argument("--date", help="slate date; read off Game Info if omitted")
    emit.add_argument("--out", help="output path; default "
                                    "outputs/<date>/ownership_pred_<slate>.json")
    emit.set_defaults(func=_emit_cli)

    grade = sub.add_parser("grade", help="grade a prediction against a "
                                         "completed contest's standings")
    grade.add_argument("--pred", required=True, help="the prediction JSON")
    grade.add_argument("--standings", required=True,
                       help="DK standings export CSV (Ben downloads it by hand)")
    grade.add_argument("--archetype", required=True,
                       help="the archetype this contest actually was")
    grade.add_argument("--contest-id", dest="contest_id", default="")
    grade.add_argument("--field-size", dest="field_size", type=int, default=None)
    grade.add_argument("--out", help="write the grade JSON here")
    grade.set_defaults(func=_grade_cli)

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except OSError as exc:
        print(f"IO error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
