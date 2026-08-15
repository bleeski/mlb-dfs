"""Game-state thesis ladder for DK Showdown.

A points-max Showdown solve answers one question: which six players score the
most under a single set of projections. A Showdown slate is one game, so that
question has one answer, and a portfolio built from it is the same lineup with
punt bats rotated. The ladder answers a different question for each entry: given
that the game unfolds THIS way, which six players score the most.

Every template here is a roster SHAPE conditioned on a game state, not a captain
preference. Two theses that produce the same shape are one thesis.

Truthful labels: the weights below are labeled deterministic priors over game
states. They are not probabilities, ROI, win rates, or forecasts. The moneyline
split is the market's price with the vig removed, reported as such and used only
to allocate entries across templates.

VERSION history
  0.1  2026-07-25  initial ladder, 12 templates, captain cap + overlap enforced
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from mlb_engine.optimize.showdown import (
    DEFAULT_MAX_CPT_EXPOSURE_PCT,
    DEFAULT_MAX_SHARED_PLAYERS,
    build_showdown_lineup,
    certify_showdown,
)

VERSION = "0.1"

# PA-share prior by batting-order slot. Deterministic, not fitted to any slate.
ORDER_FACTOR = {1: 1.08, 2: 1.06, 3: 1.05, 4: 1.03, 5: 1.00,
                6: 0.97, 7: 0.95, 8: 0.92, 9: 0.90}

# Suppression applied to the team the thesis says loses or goes quiet. A team
# that is shut out still fills the contract's minimum one roster spot, so the
# multiplier decides whether that spot is a punt or a real bat.
SUPPRESS_BLOWOUT = 0.40
SUPPRESS_CLOSE = 0.60
# 0.75 rather than 0.85: at 0.85 the losing side's cheap bats still won the
# salary-per-point comparison and the "X wins a shootout" rosters came out 3-3,
# which is the both-explode template wearing a different label.
SUPPRESS_SHOOTOUT = 0.75
SUPPRESS_DUEL = 0.78

TOP, MIDDLE, BOTTOM = (1, 2, 3), (4, 5, 6), (7, 8, 9)


# --------------------------------------------------------------------------- #
# Base prior
# --------------------------------------------------------------------------- #
def apply_base_prior(df: pd.DataFrame,
                     bat_side: Optional[Mapping[str, str]] = None,
                     pitcher_hand: Optional[Mapping[str, str]] = None) -> pd.DataFrame:
    """Replace Base (raw AvgPointsPerGame) with a labeled prior:
    salary-regressed APPG x batting-order PA factor x platoon factor.

    The salary regression exists because AvgPointsPerGame on a short sample can
    sit far off the market's own read of a player. Left unregressed, one
    small-sample outlier captains most of the portfolio.

    Platoon handles BOTH starter hands. An earlier version only modeled LHP
    starters, so a slate with two RHP starters silently got a flat 1.00 for
    every hitter and the platoon component contributed nothing while still
    appearing in the prior_note. ``pitcher_hand`` maps a TEAM to its declared
    starter's hand; a team missing from it gets a flat factor and is reported.
    """
    out = df.copy()
    bat_side = dict(bat_side or {})
    pitcher_hand = {k: str(v).upper()[:1] for k, v in (pitcher_hand or {}).items()}

    hit = out["Batting_Order"].notna()
    h = out[hit]
    if len(h) >= 2 and h["UTIL_Salary"].nunique() > 1:
        slope, intercept = np.polyfit(h["UTIL_Salary"].astype(float),
                                      h["Base"].astype(float), 1)
    else:                                    # degenerate pool: skip the regression
        slope, intercept = 0.0, float(h["Base"].mean()) if len(h) else 0.0
    out["Salary_Fit"] = out["UTIL_Salary"].astype(float) * slope + intercept
    out["APPG_Raw"] = out["Base"].astype(float)

    unresolved: set[str] = set()

    def prior(row):
        if pd.isna(row["Batting_Order"]):
            return float(row["APPG_Raw"])                    # pitchers keep APPG
        blended = 0.60 * float(row["Salary_Fit"]) + 0.40 * float(row["APPG_Raw"])
        f_order = ORDER_FACTOR[int(row["Batting_Order"])]
        side = str(bat_side.get(row["Name"], "")).upper()[:1]
        opp_hand = pitcher_hand.get(row["Opponent"], "")
        if not side or not opp_hand or side == "S":
            if not opp_hand:
                unresolved.add(str(row["Opponent"]))
            f_plat = 1.00
        elif side == opp_hand:                               # same-handed: penalty
            f_plat = 0.94
        else:                                                # opposite hands: edge
            f_plat = 1.04
        return blended * f_order * f_plat

    out["Base_Prior"] = out.apply(prior, axis=1)
    out["Base"] = out["Base_Prior"]
    out.attrs["platoon_unresolved_teams"] = sorted(unresolved)
    return out


# --------------------------------------------------------------------------- #
# Slate shape
# --------------------------------------------------------------------------- #
def _no_vig(moneyline: Mapping[str, float]) -> Dict[str, float]:
    """American odds -> vig-free implied share. The market's price, not a forecast."""
    raw = {}
    for team, ml in moneyline.items():
        ml = float(ml)
        raw[team] = (-ml) / ((-ml) + 100.0) if ml < 0 else 100.0 / (ml + 100.0)
    total = sum(raw.values()) or 1.0
    return {t: v / total for t, v in raw.items()}


def describe_slate(df: pd.DataFrame,
                   moneyline: Optional[Mapping[str, float]] = None,
                   implied_totals: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    """Favorite, underdog, declared starters, and batting-order bands."""
    teams = sorted(df["Team"].unique())
    if len(teams) != 2:
        raise ValueError(f"Showdown expects exactly 2 teams, found {teams}")

    share: Dict[str, float]
    basis: str
    if moneyline and all(t in moneyline for t in teams):
        share, basis = _no_vig(moneyline), "moneyline_no_vig"
    elif implied_totals and all(t in implied_totals for t in teams):
        tot = sum(float(implied_totals[t]) for t in teams) or 1.0
        share = {t: float(implied_totals[t]) / tot for t in teams}
        basis = "implied_team_totals"
    else:
        # No market input. Split even rather than inventing a favorite from
        # salary: the DK price is a projection input, and reusing it as a
        # game-state prior would double-count it.
        share, basis = {t: 0.5 for t in teams}, "even_split_no_market_input"

    fav = max(teams, key=lambda t: share[t])
    dog = [t for t in teams if t != fav][0]

    starters, bands = {}, {}
    for team in teams:
        sub = df[df["Team"] == team]
        sp = sub[sub["Batting_Order"].isna()].sort_values("Base", ascending=False)
        starters[team] = str(sp.iloc[0]["Player_Key"]) if len(sp) else None
        hitters = sub[sub["Batting_Order"].notna()]
        bands[team] = {
            "top": _keys_in_band(hitters, TOP),
            "middle": _keys_in_band(hitters, MIDDLE),
            "bottom": _keys_in_band(hitters, BOTTOM),
            "all": list(hitters.sort_values("Base", ascending=False)["Player_Key"]),
        }
    return {"teams": teams, "favorite": fav, "underdog": dog,
            "win_share": share, "win_share_basis": basis,
            "starters": starters, "bands": bands,
            # A team with no declared starter is a bullpen game or an
            # unannounced arm. Either way the SP-captain templates are void for
            # that team and the bullpen template becomes live.
            "bullpen_teams": [t for t in teams if starters[t] is None]}


def _keys_in_band(hitters: pd.DataFrame, band: Sequence[int]) -> List[str]:
    sub = hitters[hitters["Batting_Order"].isin(band)]
    return list(sub.sort_values("Base", ascending=False)["Player_Key"])


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def _suppress(keys: Sequence[str], factor: float) -> Dict[str, float]:
    return {k: factor for k in keys}


def _hitters(shape: Mapping[str, Any], team: str) -> List[str]:
    return list(shape["bands"][team]["all"])


def _template_specs(shape: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The ladder. Each entry is (id, weight_key, builder). Weight keys route to
    the favorite's share, the underdog's share, or a fixed neutral slice."""
    fav, dog = shape["favorite"], shape["underdog"]
    sp = shape["starters"]
    specs: List[Dict[str, Any]] = []

    def add(tid, side, weight, build):
        specs.append({"id": tid, "side": side, "weight": weight, "build": build})

    for side, other in ((fav, dog), (dog, fav)):
        tag = "favorite" if side == fav else "underdog"
        sp_side, sp_other = sp[side], sp[other]

        def win_big(s=side, o=other, sps=sp_side, spo=sp_other):
            return {
                "name": f"{s} win big - starter carries it",
                "why": (f"{s} breaks it open behind a long start. {o}'s starter is "
                        f"off the card; the one required {o} bat is salary filler, "
                        f"not a read."),
                "cpt_ladder": ([sps] if sps else []) + _hitters(shape, s),
                "excludes": [spo] if spo else [],
                "mult": _suppress(_hitters(shape, o), SUPPRESS_BLOWOUT),
            }

        def win_big_no_sp(s=side, o=other, sps=sp_side, spo=sp_other):
            return {
                "name": f"{s} win big - offense-led, no starting pitcher",
                "why": (f"{s} wins by a wide margin on a night neither starter "
                        f"finishes six. Both arms off, the full {s} order on."),
                "cpt_ladder": _hitters(shape, s),
                "excludes": [k for k in (sps, spo) if k],
                "mult": _suppress(_hitters(shape, o), SUPPRESS_BLOWOUT),
            }

        def win_close(s=side, o=other, sps=sp_side, spo=sp_other):
            return {
                "name": f"{s} win close - low-scoring win",
                "why": (f"{s} wins by a run or two. {o} still scores, so two "
                        f"cheaper {o} bats stay live rather than one punt."),
                "cpt_ladder": ([sps] if sps else []) + _hitters(shape, s),
                "excludes": [spo] if spo else [],
                "mult": _suppress(_hitters(shape, o), SUPPRESS_CLOSE),
            }

        def shootout(s=side, o=other, sps=sp_side, spo=sp_other):
            return {
                "name": f"{s} wins a shootout",
                "why": (f"Both bullpens leak and both starters come off the card. "
                        f"{s}-tilted split with {o} bats still producing."),
                "cpt_ladder": _hitters(shape, s),
                # Suppression alone does not hold the split here. A shootout
                # keeps the losing side's bats live, so their salary-per-point
                # stays competitive and the solver drifts back to even. Locking
                # the winning side's best bats is what makes the label true.
                # Four rather than three because the ladder strips any lock that
                # is also the captain, and the captain is drawn from this same
                # list: at three, "NYM wins a shootout" kept coming out 3-3.
                "locks": _hitters(shape, s)[:4],
                "excludes": [k for k in (sps, spo) if k],
                "mult": _suppress(_hitters(shape, o), SUPPRESS_SHOOTOUT),
            }

        def bottom_order(s=side, o=other, sps=sp_side, spo=sp_other):
            band = shape["bands"][s]
            return {
                "name": f"{s} win close - bottom of the order does it",
                "why": (f"The 7-8-9 spots produce in a tight {s} win. That is where "
                        f"the leverage sits, because nobody captains slot seven."),
                "cpt_ladder": band["bottom"] + band["middle"],
                "locks": band["bottom"][:1],
                "excludes": ([spo] if spo else []) + band["top"][:1],
                "mult": _suppress(_hitters(shape, o), SUPPRESS_CLOSE),
            }

        add(f"{tag}_win_big", side, 0.26, win_big)
        add(f"{tag}_win_big_no_sp", side, 0.22, win_big_no_sp)
        add(f"{tag}_win_close", side, 0.24, win_close)
        add(f"{tag}_shootout", side, 0.16, shootout)
        add(f"{tag}_bottom_order", side, 0.12, bottom_order)

    # --- neutral templates: no winner assumed ---------------------------------
    both_sp = [sp[t] for t in shape["teams"] if sp[t]]

    def duel():
        return {
            "name": "Pitchers duel - both starters rostered",
            "why": ("Neither offense gets going. Both arms on the card carry the "
                    "score, and the four bats are cheap because runs are scarce."),
            "cpt_ladder": (both_sp
                           + shape["bands"][fav]["bottom"]
                           + shape["bands"][dog]["bottom"]),
            # Both arms, plus one bat locked from each side. Without the bat
            # locks a uniform suppression leaves the solver free to fill all
            # four remaining slots from whichever team is cheaper, and a 1-5
            # split is not what "neither offense gets going" describes.
            "locks": both_sp + shape["bands"][fav]["top"][:1]
                             + shape["bands"][dog]["top"][:1],
            "mult": {k: SUPPRESS_DUEL
                     for t in shape["teams"] for k in _hitters(shape, t)},
        }

    def both_explode():
        fb, db = shape["bands"][fav], shape["bands"][dog]
        return {
            "name": "Both offenses explode - no starters",
            "why": ("Highest-scoring branch on the board with no winner assumed. "
                    "Both arms off and the split locked even, so neither side is "
                    "favored by the roster."),
            "cpt_ladder": db["all"] + fb["all"],
            "locks": fb["all"][:2] + db["all"][:1],
            "excludes": both_sp,
            "mult": {},
        }

    def ace_loses():
        # The one shape no other template produces: the better arm plus the bats
        # he is facing. A dominant start and a loss are not mutually exclusive,
        # and no points-max solve will ever build this on its own.
        ace = max(both_sp, key=lambda k: _base_of(shape, k)) if both_sp else None
        if ace is None:
            return None
        ace_team = _team_of(shape, ace)
        opp = [t for t in shape["teams"] if t != ace_team][0]
        return {
            "name": f"{ace_team} ace dominates and still takes the loss",
            "why": (f"The {ace_team} starter racks up strikeouts while his own "
                    f"offense goes quiet and {opp} scratches out the win. "
                    f"Contrarian by construction: a points-max solve never "
                    f"pairs an ace with the bats hitting against him."),
            "cpt_ladder": [ace] + shape["bands"][opp]["all"],
            "locks": [ace],
            "excludes": [k for k in both_sp if k != ace],
            "mult": _suppress(_hitters(shape, ace_team), SUPPRESS_CLOSE),
        }

    def bullpen_game():
        # Only live when a team has no declared starter. Roster shape differs
        # from every other template: no arm from that side is rosterable at all,
        # and its bats face a parade of relievers rather than one starter.
        pens = shape["bullpen_teams"]
        if not pens:
            return None
        pen = pens[0]
        opp = [t for t in shape["teams"] if t != pen][0]
        return {
            "name": f"{pen} bullpen game - {opp} bats face a parade",
            "why": (f"{pen} has no declared starter, so its arms are unrosterable "
                    f"and {opp} sees a different pitcher every two innings. Bats "
                    f"carry full weight; the third time through the order never "
                    f"happens."),
            "cpt_ladder": shape["bands"][opp]["all"] + shape["bands"][pen]["all"],
            "excludes": [sp[pen]] if sp[pen] else [],
            "mult": {},
        }

    add("pitchers_duel", None, 0.30, duel)
    add("both_explode", None, 0.30, both_explode)
    add("ace_loses", None, 0.22, ace_loses)
    # Weighted well above the other neutral templates because it is only ever
    # live when a whole team's pitching is unrosterable, which is the single
    # largest structural fact a Showdown slate can carry. At 0.18 it normalized
    # to roughly half a slot in an 18-entry portfolio and got dropped by the
    # apportionment, which is how a slate-defining condition goes unrepresented.
    add("bullpen_game", None, 0.60, bullpen_game)
    return specs


def _base_of(shape, key) -> float:
    return float(shape["_base"].get(key, 0.0))


def _team_of(shape, key) -> str:
    return str(shape["_team"].get(key, ""))


# --------------------------------------------------------------------------- #
# Ladder
# --------------------------------------------------------------------------- #
NEUTRAL_SHARE = 0.18   # slice of the portfolio reserved for no-winner theses


def build_thesis_ladder(df: pd.DataFrame, n_entries: int,
                        moneyline: Optional[Mapping[str, float]] = None,
                        implied_totals: Optional[Mapping[str, float]] = None,
                        max_cpt_exposure_pct: Optional[float] = DEFAULT_MAX_CPT_EXPOSURE_PCT,
                        ) -> Dict[str, Any]:
    """Generate ``n_entries`` thesis specs, allocated across game states and with
    captains rotated so no captain exceeds the cap.

    Returns ``{"theses": [...], "shape": {...}, "allocation": {...}}``.
    """
    shape = dict(describe_slate(df, moneyline, implied_totals))
    shape["_base"] = dict(zip(df["Player_Key"], df["Base"]))
    shape["_team"] = dict(zip(df["Player_Key"], df["Team"]))

    specs = [s for s in _template_specs(shape) if s["build"]() is not None]
    fav, dog = shape["favorite"], shape["underdog"]
    fav_share = float(shape["win_share"][fav])

    # Directional templates split (1 - NEUTRAL_SHARE) by the market; neutral
    # templates split NEUTRAL_SHARE evenly among themselves.
    directional = 1.0 - NEUTRAL_SHARE
    weights: Dict[int, float] = {}
    neutral_idx = [i for i, s in enumerate(specs) if s["side"] is None]
    for i, s in enumerate(specs):
        if s["side"] is None:
            weights[i] = NEUTRAL_SHARE * s["weight"]
        else:
            side_share = fav_share if s["side"] == fav else (1.0 - fav_share)
            weights[i] = directional * side_share * s["weight"]
    total = sum(weights.values()) or 1.0
    weights = {i: w / total for i, w in weights.items()}

    counts = _largest_remainder(weights, int(n_entries))

    cap = (max(1, math.floor(max_cpt_exposure_pct * max(1, int(n_entries))))
           if max_cpt_exposure_pct else None)
    cpt_counts: Dict[str, int] = {}
    cap_relaxed = 0
    theses: List[Dict[str, Any]] = []
    allocation: Dict[str, int] = {}

    # Round-robin the templates so a truncated build still spans game states
    # rather than filling every entry from the first template in the list.
    order = _round_robin(counts)
    for idx in order:
        spec = specs[idx]
        built = spec["build"]()
        allocation[spec["id"]] = allocation.get(spec["id"], 0) + 1
        cpt = None
        for cand in built.get("cpt_ladder") or []:
            if cap is None or cpt_counts.get(cand, 0) < cap:
                cpt = cand
                break
        if cpt is None:                       # every eligible captain at cap
            ladder = built.get("cpt_ladder") or []
            cpt = ladder[0] if ladder else None
            cap_relaxed += 1
        if cpt is not None:
            cpt_counts[cpt] = cpt_counts.get(cpt, 0) + 1
        # More entries than live templates means templates repeat. The rosters
        # still differ (the overlap bound guarantees it), but two rows sharing a
        # thesis name reads as a duplicate in the brief when it is not one, so
        # the repeat is named by what actually distinguishes it: its captain.
        name = built["name"]
        if allocation[spec["id"]] > 1:
            cpt_name = str(df.loc[df["Player_Key"] == cpt, "Name"].iloc[0]) \
                if cpt is not None and (df["Player_Key"] == cpt).any() else "no captain"
            name = f"{name} (variant {allocation[spec['id']]}, {cpt_name} captain)"
        thesis = {
            "template": spec["id"],
            "name": name,
            "why": built["why"],
            "cpt": cpt,
            "locks": [k for k in (built.get("locks") or []) if k and k != cpt],
            "excludes": [k for k in (built.get("excludes") or []) if k and k != cpt],
            "mult": {k: v for k, v in (built.get("mult") or {}).items()},
        }
        theses.append(thesis)

    return {"theses": theses, "shape": {k: v for k, v in shape.items()
                                        if not k.startswith("_")},
            "allocation": allocation,
            "captain_cap_count": cap,
            "captain_cap_relaxed": cap_relaxed,
            "win_share_basis": shape["win_share_basis"]}


def _largest_remainder(weights: Mapping[int, float], n: int) -> Dict[int, int]:
    """Apportion n slots across weights without drift. Deterministic ties."""
    if n <= 0:
        return {}
    exact = {i: w * n for i, w in weights.items()}
    base = {i: int(math.floor(v)) for i, v in exact.items()}
    left = n - sum(base.values())
    ranked = sorted(exact, key=lambda i: (-(exact[i] - base[i]), i))
    for i in ranked[:left]:
        base[i] += 1
    return {i: c for i, c in base.items() if c > 0}


def _round_robin(counts: Mapping[int, int]) -> List[int]:
    remaining = dict(counts)
    order: List[int] = []
    while remaining:
        for i in sorted(remaining):
            order.append(i)
            remaining[i] -= 1
        remaining = {i: c for i, c in remaining.items() if c > 0}
    return order


# --------------------------------------------------------------------------- #
# Solve
# --------------------------------------------------------------------------- #
def solve_ladder(df: pd.DataFrame, theses: Sequence[Mapping[str, Any]],
                 max_shared_players: Optional[int] = DEFAULT_MAX_SHARED_PLAYERS,
                 time_limit: int = 8,
                 diagnostics: Optional[Dict[str, Any]] = None,
                 ) -> List[Optional[Dict[str, Any]]]:
    """Solve each thesis under its own constraints, enforcing the overlap bound
    against every lineup already built.

    Relaxation order when a thesis will not solve: drop the overlap bound, then
    drop the captain lock, then report the thesis infeasible. The captain lock
    goes before the thesis itself because a thesis with a different captain is
    still that game state; a missing lineup is a blank reserved row, and a blank
    row blocks certification.
    """
    prior: List[List[str]] = []
    out: List[Optional[Dict[str, Any]]] = []
    overlap_relaxed = cpt_relaxed = infeasible = both_relaxed = 0
    ignored_locks: List[str] = []
    # R113. `captain_lock_relaxed` (this counter) and `captain_cap_relaxed`
    # (from the thesis-apportionment step, a different mechanism entirely) used
    # to be summed into one number the brief called "captain cap relaxed" no
    # matter which one fired. Naming WHICH thesis lost its assigned captain, and
    # to whom, is what a caution pointing at this event actually needs -- the
    # count alone reads the same as a cap event, and `captain_exposure.by_player`
    # cannot show a lock substitution because it is not an exposure event.
    name_by_key = dict(zip(df["Player_Key"], df["Name"]))
    lock_relaxation_detail: List[Dict[str, str]] = []

    def _record_lock_relaxation(thesis: Mapping[str, Any], solved: Mapping[str, Any]) -> None:
        requested = thesis.get("cpt")
        actual = (solved.get("captain") or {}).get("player_key")
        lock_relaxation_detail.append({
            "thesis": str(thesis.get("name") or thesis.get("template") or "?"),
            "requested": name_by_key.get(requested, requested) if requested else "none",
            "actual": name_by_key.get(actual, actual) if actual else "?",
        })

    for thesis in theses:
        work = df.copy()
        mult = thesis.get("mult") or {}
        if mult:
            work["Base"] = [float(b) * float(mult.get(k, 1.0))
                            for b, k in zip(work["Base"], work["Player_Key"])]
        kw = dict(locks=thesis.get("locks") or None,
                  excludes=thesis.get("excludes") or None,
                  time_limit=time_limit)
        lu = build_showdown_lineup(work, cpt_lock=thesis.get("cpt"),
                                   forbidden_sets=prior or None,
                                   max_shared_players=max_shared_players, **kw)
        if lu is None and max_shared_players is not None:
            lu = build_showdown_lineup(work, cpt_lock=thesis.get("cpt"),
                                       forbidden_sets=prior or None, **kw)
            if lu is not None:
                overlap_relaxed += 1
        if lu is None:
            lu = build_showdown_lineup(work, forbidden_sets=prior or None,
                                       max_shared_players=max_shared_players, **kw)
            if lu is not None:
                cpt_relaxed += 1
                _record_lock_relaxation(thesis, lu)
        # R54(b). The fourth rung, which the BANK ladder had and this one did
        # not: a thesis solvable only under both relaxations returned None and
        # left a blank reserved row -- write-blocked at T-5 -- on a pool the bank
        # path fills. Counted in every place it is true, matching
        # build_showdown_bank: these answer "how many lineups were built without
        # this control", so a clean ladder is all three at zero.
        if lu is None and thesis.get("cpt") and max_shared_players is not None:
            lu = build_showdown_lineup(work, forbidden_sets=prior or None, **kw)
            if lu is not None:
                both_relaxed += 1
                overlap_relaxed += 1
                cpt_relaxed += 1
                _record_lock_relaxation(thesis, lu)
        if lu is None:
            infeasible += 1
        else:
            prior.append(list(lu["player_keys"]))
            # R54(c). A thesis lock the melt never carried used to no-op in
            # silence, and cpt_counts then accounted against captains that were
            # never enforced.
            for key in (lu.get("ignored_locks") or []):
                if key not in ignored_locks:
                    ignored_locks.append(key)
        out.append(lu)

    if diagnostics is not None:
        diagnostics.update({
            "max_shared_players": max_shared_players,
            "overlap_relaxed": overlap_relaxed,
            "captain_lock_relaxed": cpt_relaxed,
            # R113. One entry per lock relaxation, naming the thesis and the
            # requested-vs-actual captain, so a caution citing this counter can
            # say WHO was substituted instead of pointing at an exposure table
            # that cannot show a lock event.
            "lock_relaxation_detail": list(lock_relaxation_detail),
            "both_relaxed": both_relaxed,
            "ignored_locks": list(ignored_locks),
            "infeasible": infeasible,
        })
    return out


def portfolio_report(df: pd.DataFrame, theses: Sequence[Mapping[str, Any]],
                     lineups: Sequence[Optional[Mapping[str, Any]]]) -> Dict[str, Any]:
    """Exposure, overlap, and per-lineup certification for a solved ladder."""
    names = dict(zip(df["Player_Key"], df["Name"]))
    teams = dict(zip(df["Player_Key"], df["Team"]))
    rows, exposure, captains = [], {}, {}
    sets: List[set] = []
    for thesis, lu in zip(theses, lineups):
        if lu is None:
            rows.append({"thesis": thesis["name"], "template": thesis.get("template"),
                         "solved": False})
            continue
        keys = list(lu["player_keys"])
        cpt_key = lu["captain"]["player_key"]
        sets.append(set(keys))
        captains[names.get(cpt_key, cpt_key)] = captains.get(names.get(cpt_key, cpt_key), 0) + 1
        for k in keys:
            exposure[names.get(k, k)] = exposure.get(names.get(k, k), 0) + 1
        rows.append({
            "thesis": thesis["name"], "template": thesis.get("template"),
            "rationale": thesis.get("why", ""), "solved": True,
            "captain": names.get(cpt_key, cpt_key),
            "captain_team": teams.get(cpt_key, ""),
            "utils": [names.get(k, k) for k in keys if k != cpt_key],
            "team_split": {t: sum(1 for k in keys if teams.get(k) == t)
                           for t in sorted({teams.get(k, "") for k in keys})},
            "salary": lu.get("salary"),
            "proxy_points": round(float(lu.get("proj_points") or 0.0), 2),
            "lineup_certified": bool(certify_showdown(lu, df).get("passed", False)),
        })
    n = len(sets)
    max_overlap = max((len(a & b) for i, a in enumerate(sets)
                       for b in sets[i + 1:]), default=0)
    return {
        "lineups": rows,
        "solved": n,
        "all_unique_rosters": len({frozenset(s) for s in sets}) == n,
        "max_pairwise_overlap": max_overlap,
        "captain_exposure": dict(sorted(captains.items(), key=lambda kv: -kv[1])),
        "max_captain_exposure_pct": round(max(captains.values()) / n * 100, 1) if n else 0.0,
        "player_exposure": dict(sorted(exposure.items(), key=lambda kv: -kv[1])),
        "prior_note": ("Base = 0.60*salary-regressed + 0.40*AvgPointsPerGame, "
                       "x batting-order PA factor x platoon factor. A labeled "
                       "deterministic prior, not a projection."),
        "label": "review_grade_build",
    }
