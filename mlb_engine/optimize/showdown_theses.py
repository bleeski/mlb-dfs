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
  0.2  undated     gap in this history -- the module version moved without a
                    line here; predates R156 and is not reconstructed
  0.3  2026-08-21  R156: duel()'s locks are now unconditional on both starters
                   via a new hard_locks field (build_thesis_ladder merges it
                   past the `!= cpt` filter), cpt_ladder restricted to the two
                   starters, the top-band hitter locks removed after being
                   measured infeasible against real prices, weight 0.30 -> 0.45
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from mlb_engine.optimize.showdown import (
    DEFAULT_MAX_CPT_EXPOSURE_PCT,
    DEFAULT_MAX_CPT_PER_CONTEST,
    DEFAULT_MAX_PLAYER_EXPOSURE_PCT,
    DEFAULT_MAX_SHARED_PLAYERS,
    build_showdown_lineup,
    certify_showdown,
    exposure_cap_count,
    per_contest_cap_count,
    player_cap_structural_floor,
)

VERSION = "0.3"

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
# Supplied Base (R249)
# --------------------------------------------------------------------------- #
def read_supplied_base(path) -> tuple[Dict[str, float], Dict[str, Any]]:
    """Read a ``Player_ID,Base`` map, the columns ``ownership_pred.py --base``
    already reads. Returns (by_dk_id, report).

    Column names are matched case-insensitively and ``id`` / ``projection`` are
    accepted as aliases, which is that tool's contract verbatim rather than a
    second one. The report carries the sha256 so the brief can name the exact
    bytes: an operator who edits the file between two builds gets two hashes,
    which is the whole point of recording it.

    A file that cannot be read is an ERROR here and not an empty map. R242's
    complaint is that a silent fallback looks identical to a build that was
    never asked for the input, and a projection file the operator named and the
    engine could not open is the case where that costs the most.
    """
    import csv
    import hashlib
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"projections file not found: {p}")
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    import math

    out: Dict[str, float] = {}
    skipped = 0
    rejected: list[str] = []
    duplicated: list[str] = []
    text = raw.decode("utf-8-sig", errors="replace").splitlines()
    for row in csv.DictReader(text):
        lower = {(k or "").strip().lower(): v for k, v in row.items()}
        pid = lower.get("player_id") or lower.get("id")
        value = lower.get("base") or lower.get("projection")
        if pid is None or value in (None, ""):
            skipped += 1
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            skipped += 1
            continue
        key = str(pid).strip()
        # R327, 2026-09-08. THIS is the `--projections` door the item names, and
        # it had no numeric boundary at all. Measured at `e3757ca` on a
        # four-row file: `nan`, `inf`, `-5` and `1e400` (which overflows to
        # +inf) were all ACCEPTED, `rows_usable: 4`, `rows_skipped: 0` --
        # `float("nan")` is a successful parse, so the try/except above is a
        # syntax check and never a value check. A supplied Base is the prior
        # the Showdown solver ranks on and it bypasses every derived check, so
        # a NaN here is a NaN objective on the one path the item calls the
        # live one.
        #
        # The rule is the scoring contract and not a generic nonnegativity: a
        # Base is the multiplicand of a factor product, and
        # `projection_builder.validate_projection_factors` has rejected a
        # negative Base on the Classic door since v1.0. A REFUSAL, never a
        # silent skip -- R242's complaint is that a silent fallback looks
        # identical to a build that was never asked for the input.
        if not math.isfinite(parsed):
            rejected.append(f"{key}={value!r} (not a finite number)")
            continue
        if parsed < 0:
            rejected.append(f"{key}={value!r} (negative)")
            continue
        if key in out:
            duplicated.append(key)
            continue
        out[key] = parsed
    if rejected or duplicated:
        detail = "; ".join(rejected[:10])
        if duplicated:
            detail += ((" ; " if detail else "")
                       + f"duplicate Player_ID: {sorted(set(duplicated))[:10]}")
        raise ValueError(
            f"projections file {p} carries {len(rejected) + len(duplicated)} "
            f"unusable row(s): {detail}. A supplied Base is used AS the prior "
            "and bypasses every derived check, so it is refused rather than "
            "carried into the solve (R327)")
    if not out:
        raise ValueError(
            f"projections file {p} carried no usable Player_ID,Base rows "
            f"({skipped} row(s) skipped); refusing rather than building "
            "without the input that was asked for")
    return out, {"source": str(p), "sha256": sha,
                 "rows_usable": len(out), "rows_skipped": skipped}


def apply_supplied_base(df: pd.DataFrame,
                        supplied: Mapping[str, float],
                        read_report: Optional[Mapping[str, Any]] = None) -> pd.DataFrame:
    """Replace ``Base`` with an operator-supplied prior, keyed by DK player id.

    INSERTION POINT, decided 2026-09-01 and measured rather than argued. This
    runs AFTER ``apply_base_prior``, so a supplied number is the prior the solver
    ranks on and nothing further is layered on it. Two reasons, in order:

    1. ``apply_base_prior``'s own docstring scopes the 0.60 salary weight to
       AvgPointsPerGame's small-sample noise. A supplied projection is not APPG
       on a short sample; shrinking it toward the salary line is the exact
       mechanism R249 was filed against. Measured on 1920_1g_sd: supplying the
       number BEFORE the prior transmits a slope of 0.458 -- an operator asking
       for +10% gets +4.6% -- and it also refits the salary regression, so
       supplying ONE player moved all 17 other hitters' priors. Supplying a
       number for Hoerner is not a statement about Bregman.
    2. Recording is only truthful if the recorded number is the applied number.
       The brief states supplied-vs-APPG ratios; under any earlier insertion
       point those describe an input that a factor the brief does not state then
       transformed, which is R122's prior_note defect in a new place.

    The consequence, stated rather than discovered: for a covered player the
    batting-order PA factor and the platoon factor are NOT applied, because the
    operator supplied the finished prior. A partial file therefore ranks covered
    players on a supplied prior and everyone else on the derived one, and
    ``chain_bypassed_players`` counts exactly that.

    Both DK ids resolve to the same player. A Showdown salary file lists every
    player twice, CPT and UTIL, under different ids; an operator keying off
    either row means the same person, and refusing one of the two would be a
    trap with no upside. A row naming an id in neither column is reported in
    ``unmatched_ids`` and changes nothing.
    """
    out = df.copy()
    supplied = {str(k).strip(): float(v) for k, v in dict(supplied or {}).items()}
    by_row: Dict[int, float] = {}
    matched_ids: set[str] = set()
    for idx, row in out.iterrows():
        for col in ("UTIL_ID", "CPT_ID"):
            pid = row.get(col)
            key = str(pid).strip() if pid is not None else ""
            if key and key in supplied:
                by_row[idx] = supplied[key]
                matched_ids.add(key)
                break
    appg = (out["APPG_Raw"] if "APPG_Raw" in out.columns else out["Base"]).astype(float)
    ratios: List[float] = []
    differing = 0
    for idx, value in by_row.items():
        raw = float(appg.loc[idx])
        if raw > 0:
            ratios.append(value / raw)
            if abs(value - raw) > 1e-9:
                differing += 1
    hitters = out["Batting_Order"].notna() if "Batting_Order" in out.columns else None
    covered_hitters = sum(1 for i in by_row if hitters is None or bool(hitters.loc[i]))
    for idx, value in by_row.items():
        out.at[idx, "Base"] = value
    out["Base_Supplied"] = [idx in by_row for idx in out.index]
    ordered = sorted(ratios)
    report: Dict[str, Any] = dict(read_report or {})
    report.update({
        "applied": bool(by_row),
        "players_supplied": len(supplied),
        "players_matched": len(by_row),
        "unmatched_ids": sorted(set(supplied) - matched_ids),
        "players_differing_from_appg": differing,
        "ratio_min": round(ordered[0], 4) if ordered else None,
        "ratio_median": round(ordered[len(ordered) // 2], 4) if ordered else None,
        "ratio_max": round(ordered[-1], 4) if ordered else None,
        "hitters_covered": covered_hitters,
        "pitchers_covered": len(by_row) - covered_hitters,
        "chain_bypassed_players": len(by_row),
        "players_on_derived_prior": int(len(out) - len(by_row)),
        "label": ("Base for a covered player is the SUPPLIED number: the salary "
                  "regression, the batting-order PA factor and the platoon "
                  "factor were not applied to it. On the ladder path each "
                  "thesis still multiplies Base by its own game-state weight, "
                  "supplied and derived alike -- that is the template asking "
                  "'in THIS scenario, how much does this side matter', not part "
                  "of the prior chain this bypasses. A labeled operator input, "
                  "never a projection this engine produced or graded."),
    })
    out.attrs["supplied_base_report"] = report
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

        # R263 weight lever, MEASURED AND DECLINED, 2026-08-28. These five weights
        # are UNCHANGED and that is the finding, not an omission.
        #
        # Ben asked for a bump on the pitcher-captain theses (`win_big` and
        # `win_close`, the two whose `cpt_ladder` leads with that side's declared
        # arm) to move the portfolio's pitcher-CPT share off ~40% toward ~50%,
        # citing R156's 0.30 -> 0.45 on `pitchers_duel` as precedent. The bump was
        # built (0.26/0.22/0.24/0.16/0.12 -> 0.31/0.19/0.29/0.13/0.08, with
        # `pitchers_duel` 0.45 -> 0.55, `ace_loses` 0.22 -> 0.28, `both_explode`
        # 0.30 -> 0.14) and then measured over 96 apportion-and-solve checks on the
        # tracked MIN@CHC fixture: six moneyline scenarios x n = 9..24, which is
        # R156's own standard for this fixture.
        #
        #   mean realized pitcher-CPT share   43.66% -> 44.91%   (+1.25pp)
        #   mean STRUCTURAL CEILING            45.01% -> 45.01%   (unchanged)
        #   builds already at their ceiling    75/96  -> 94/96
        #   captain-cap relaxations            37     -> 56       (+19)
        #
        # The ceiling is why this was declined. Pitcher-CPT share on a slate with
        # two declared arms is bounded by 2 * floor(cpt_cap * n) / n, because the
        # captain cap is per PLAYER and only two players are eligible to fill that
        # slot. At the shipped 0.25 cap that bound averages 45.0% over n=9..24 and
        # never exceeds 50%; it is 42.1% at n=19. So the ~50% target is not
        # reachable by any weight, the pre-existing weights were already at 97% of
        # what IS reachable, and the bump spends 19 additional counted captain-cap
        # relaxations to collect the last 1.25pp. CLAUDE.md's own rule prices that
        # trade: a portfolio is not clean because the gates passed, it is clean
        # when the relaxation counts are zero. Buying 1.25pp on a metric whose
        # ceiling is 45% by manufacturing relaxations at n=16, 17 and 18 -- entry
        # counts that had none -- is the wrong side of that rule, and the pinned
        # test `test_ladder_spans_game_states_and_holds_the_captain_cap` is what
        # caught it.
        #
        # What DID ship is `construction_shadow`, which prints the ceiling beside
        # the share on every delivery, so the real population gets measured over
        # Ben's >= 12 conditioned slates instead of this one fixture. The lever
        # that can actually move this is the captain cap itself, or the order in
        # which the ladder spends captain slots across the two arms -- both out of
        # R263's scope, both waiting on the R238/R239 contest-awareness cluster.
        # Reversing this decision is a five-number edit; the search that produced
        # it is recorded in the CHANGELOG so it is not re-run from scratch.
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
            # Captain comes from the two starters ONLY, never a bottom-order bat.
            # "Pitchers duel" is about the two arms; a hitter captaining it is a
            # different story wearing this thesis's name. When both starters are
            # already at the captain cap the walk below forces one past it
            # (counted honestly in cap_relaxed) rather than reaching for a bat.
            "cpt_ladder": list(both_sp),
            # R156. No hitter lock here on purpose, and that is a change from the
            # original version, which locked one top-band bat from each side "so
            # a uniform suppression doesn't leave the solver free to fill all four
            # remaining slots from whichever team is cheaper." That reasoning
            # predates making both arms hard-required (below): an ace at CPT plus
            # the other arm at UTIL already runs 28,500-31,500 of the 50,000 cap,
            # and adding a top-band bat from EACH side on top of that was measured
            # infeasible on the 2026-08-21 ATL@MIL slate -- Sale CPT + Misiorowski
            # UTIL + one top-band hitter each ran to 47,500-48,100, leaving under
            # $2,500 for two more roster spots against a $3,000 pool floor,
            # regardless of which arm captained. The two-teams rule
            # (`min_players_per_team=1`) is already satisfied by the two arms
            # alone, since they come from different teams, so nothing here needs
            # to force it a second time; which four hitters actually join them is
            # a salary/points question for the solver, not a locked assumption,
            # and the suppression multiplier below still prices every hitter down
            # uniformly so none of the four is a full-price bat.
            "locks": [],
            # R156, Ben 2026-08-21: "pitchers duel categorically means both
            # pitchers play well and thus should be rostered." Both arms are
            # HARD-required regardless of who ends up captaining -- unlike an
            # ordinary "locks" entry, this is never filtered by `cpt` in
            # build_thesis_ladder, so it survives every rung of solve_ladder's
            # relaxation ladder. Without it, the starter who is NOT the
            # initially-assigned captain had no protection at all (the generic
            # ladder code filters him out of "locks" only because he WAS picked
            # as cpt), so once the overlap bound forced a captain substitution he
            # was free to be dropped from the roster entirely rather than merely
            # losing the armband -- caught from a live ATL@MIL delivery where
            # this thesis shipped with only one of the two starters.
            "hard_locks": list(both_sp),
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

    # R156, 2026-08-21: 0.30 -> 0.45. A single slot cannot hedge which arm ends
    # up captaining, and six directional templates already get a second
    # variant (favorite/underdog x win_big/win_big_no_sp/win_close) for exactly
    # that hedge. This is a bias in the largest-remainder apportionment, not a
    # guarantee: whether this template clears a second slot at a given n still
    # depends on how its share lands against the other ten under that n's
    # moneyline split.
    # R263, 2026-08-28: the neutral half of the same declined bump. `pitchers_duel`
    # 0.45 -> 0.55, `ace_loses` 0.22 -> 0.28 and `both_explode` 0.30 -> 0.14 were
    # built and measured with the directional five above, and are unchanged for the
    # same reason -- the full measurement is in the comment on that block. R156's
    # 0.45 on `pitchers_duel` stands exactly as R156 set it.
    add("pitchers_duel", None, 0.45, duel)
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


def contest_partition(contest_of_entry: Optional[Sequence[str]],
                      n_entries: int) -> Dict[str, Any]:
    """Turn a per-entry contest vector into the partition the ladder can use.

    R239 seam. ``contest_of_entry[i]`` is the contest the i-th ladder slot will
    be entered into, in the SAME order the caller will later zip theses against
    reserved rows. The alignment is the whole contract: `run_showdown` assigns
    with ``zip(rows, bank)``, ``bank[j]`` solves ``theses[j]``, and ``theses`` is
    built in ``_round_robin`` order, so slot j lands in ``rows[j]``'s contest.

    Returns ``sizes`` (entries per contest), ``size_of_entry`` (each slot's own
    contest size), and the vector itself, truncated or reported short against
    ``n_entries`` rather than silently zipped. ``None`` in gives an UNAVAILABLE
    partition, which every consumer must treat as "no per-contest information",
    never as "one contest".

    The distinction matters because those two readings differ: a build with no
    partition and a build whose entries genuinely all sit in one contest want
    different reports, and collapsing them is how a portfolio-level number gets
    presented as a per-contest one.
    """
    if contest_of_entry is None:
        return {"available": False, "reason": "no contest vector supplied",
                "contest_of_entry": None, "sizes": {}, "size_of_entry": None}
    vec = [str(c) for c in contest_of_entry]
    short = len(vec) < int(n_entries)
    vec = vec[:int(n_entries)]
    sizes: Dict[str, int] = {}
    for cid in vec:
        sizes[cid] = sizes.get(cid, 0) + 1
    return {
        "available": not short,
        "reason": (f"contest vector covers {len(vec)} of {int(n_entries)} entries"
                   if short else ""),
        "contest_of_entry": vec,
        "sizes": dict(sorted(sizes.items())),
        "size_of_entry": [sizes[c] for c in vec],
        "n_contests": len(sizes),
    }


def per_contest_report(df: pd.DataFrame,
                       lineups: Sequence[Optional[Mapping[str, Any]]],
                       contest_of_entry: Optional[Sequence[str]],
                       max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST,
                       ) -> Dict[str, Any]:
    """R239(c). What was entered, sliced by the contest that pays it.

    The portfolio counters answer "what share of the ENTERED SET does this
    captain own". In a one-ticket satellite that is the wrong denominator: the
    prize resolves per contest, so two entries sharing a captain inside one
    2-entry contest is one outcome bought twice, and the portfolio reading of the
    same file can sit at 23.8% under a 0.25 cap and call it clean. That is
    verbatim the 2026-08-28 `2215_1g_sd` delivery.

    Per contest: ``n``, ``distinct_captains``, ``captain_counts``, top player
    exposure, ``max_pairwise_overlap``, and the team-shape spread (how many
    distinct team splits the contest's entries span, which is the crude read on
    whether one contest's entries are all the same construction).

    ``clean`` here means every contest held the per-contest captain bar. It is
    deliberately NOT the same question as the portfolio's `counted_relaxations`,
    and the caller ANDs the two rather than replacing one with the other.
    """
    if contest_of_entry is None:
        return {"available": False,
                "reason": "no contest partition; per-contest slices unavailable",
                "by_contest": {}, "over_cap": [], "clean": None}

    names = dict(zip(df["Player_Key"], df["Name"]))
    teams = dict(zip(df["Player_Key"], df["Team"]))
    buckets: Dict[str, List[Mapping[str, Any]]] = {}
    for cid, lu in zip(contest_of_entry, lineups):
        if lu is not None:
            buckets.setdefault(str(cid), []).append(lu)

    by_contest: Dict[str, Any] = {}
    over_cap: List[Dict[str, Any]] = []
    for cid in sorted(buckets):
        lus = buckets[cid]
        n = len(lus)
        sets = [set(lu["player_keys"]) for lu in lus]
        cpts: Dict[str, int] = {}
        for lu in lus:
            key = lu["captain"]["player_key"]
            label = names.get(key, key)
            cpts[label] = cpts.get(label, 0) + 1
        players: Dict[str, int] = {}
        for s in sets:
            for k in s:
                label = names.get(k, k)
                players[label] = players.get(label, 0) + 1
        splits = {"-".join(str(v) for _, v in sorted(
            {t: sum(1 for k in s if teams.get(k) == t)
             for t in sorted({teams.get(k, "") for k in s})}.items()))
            for s in sets}
        cap = per_contest_cap_count(n, max_cpt_per_contest)
        breaches = [{"contest_id": cid, "player": p, "n": c, "cap": cap,
                     "pct": round(100.0 * c / n, 1)}
                    for p, c in sorted(cpts.items(), key=lambda kv: (-kv[1], kv[0]))
                    if c > cap]
        over_cap.extend(breaches)
        by_contest[cid] = {
            "n": n,
            "cap": cap,
            "distinct_captains": len(cpts),
            "captain_counts": dict(sorted(cpts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "max_captain_pct": round(100.0 * max(cpts.values()) / n, 1) if cpts else 0.0,
            "top_player_exposure": dict(sorted(players.items(),
                                               key=lambda kv: (-kv[1], kv[0]))[:5]),
            "max_player_pct": round(100.0 * max(players.values()) / n, 1) if players else 0.0,
            "max_pairwise_overlap": max((len(a & b) for i, a in enumerate(sets)
                                         for b in sets[i + 1:]), default=0),
            "team_shape_spread": len(splits),
            "team_shapes": sorted(splits),
            "over_cap": breaches,
        }
    return {"available": True, "reason": "",
            "by_contest": by_contest,
            "over_cap": over_cap,
            "max_cpt_per_contest": int(max_cpt_per_contest),
            "contests": len(by_contest),
            "multi_entry_contests": sum(1 for b in by_contest.values() if b["n"] > 1),
            "clean": not over_cap}


def captain_assignment_feasible(captain_counts: Mapping[str, int],
                                contest_sizes: Sequence[int],
                                max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST,
                                ) -> Dict[str, Any]:
    """Can this captain multiset be dealt so no contest exceeds the per-contest cap?

    R239(b)(ii), the precondition R239 did not originally have. Gale-Ryser on
    captain counts against contest sizes: an assignment exists if and only if,
    for every k, the sum of the k largest captain counts is at most
    ``sum over contests of min(n_j, k * m)``, where m is the per-contest cap.

    The bound is what one contest can absorb from the k most-used captains: at
    most ``m`` entries each, and never more than the contest's own size.

    At ``m = 1`` this is R239's stated form. The 2026-08-28 bank fails it there
    at k=3 -- counts (5,5,4,4,1,1,1) against sizes (7,7,2,2,1,1,1) give
    ``14 > 13`` -- which is the finding worth keeping: **that bank admitted no
    valid assignment at all, so no permutation of the delivered file could have
    produced a clean one.** Dealing cannot create diversity the bank does not
    contain, which is why R239(a) waits on (b).

    Run this on the apportionment BEFORE solving. A failure is not a refusal: a
    blank reserved row blocks certification, so the remedy is to widen the
    captain pool, never to refuse and never to relax in silence.
    """
    counts = sorted((int(c) for c in captain_counts.values()), reverse=True)
    sizes = [int(s) for s in contest_sizes]
    m = max(1, int(max_cpt_per_contest))
    # The per-contest bar depends on the contest's own size (`n - 1` keeps a
    # 2-entry contest from being filled by one captain), so capacity is summed
    # against each contest's OWN bar, not against a flat m.
    bars = [per_contest_cap_count(s, m) for s in sizes]
    total = sum(counts)
    capacity = sum(min(s, len(counts) * b) for s, b in zip(sizes, bars))
    failures: List[Dict[str, int]] = []
    for k in range(1, len(counts) + 1):
        lhs = sum(counts[:k])
        rhs = sum(min(s, k * b) for s, b in zip(sizes, bars))
        if lhs > rhs:
            failures.append({"k": k, "needed": lhs, "capacity": rhs,
                             "short_by": lhs - rhs})
    return {
        "feasible": not failures and total <= capacity,
        "max_cpt_per_contest": m,
        "captain_counts_desc": counts,
        "contest_sizes": sorted(sizes, reverse=True),
        "entries": total,
        "failures": failures,
        # The binding k is the FIRST one to break: it names how many captains are
        # over-concentrated, which is how many more the pool has to produce.
        # `short_by` is that same k's shortfall and not the worst one, because a
        # pair of adjacent fields describing two different failures is a report
        # that reads as one fact and is two.
        "binding_k": failures[0]["k"] if failures else None,
        "short_by": failures[0]["short_by"] if failures else 0,
        "worst_short_by": max((f["short_by"] for f in failures), default=0),
    }


def build_thesis_ladder(df: pd.DataFrame, n_entries: int,
                        moneyline: Optional[Mapping[str, float]] = None,
                        implied_totals: Optional[Mapping[str, float]] = None,
                        max_cpt_exposure_pct: Optional[float] = DEFAULT_MAX_CPT_EXPOSURE_PCT,
                        contest_of_entry: Optional[Sequence[str]] = None,
                        max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST,
                        ) -> Dict[str, Any]:
    """Generate ``n_entries`` thesis specs, allocated across game states and with
    captains rotated so no captain exceeds the cap.

    Returns ``{"theses": [...], "shape": {...}, "allocation": {...}}``.

    R239 seam, 2026-08-29. ``contest_of_entry`` is accepted, validated and
    echoed back as ``contest_partition``; NOTHING reads it for a decision yet, so
    every output of this function is byte-identical with and without it. It is
    threaded first and alone deliberately: R239's own note says do that, and the
    partition has to exist here before the per-contest captain cap can bind at
    the moment a captain slot is filled rather than be evaluated after the fact.
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

    cap = exposure_cap_count(max_cpt_exposure_pct, int(n_entries))
    cpt_counts: Dict[str, int] = {}
    cap_relaxed = 0
    theses: List[Dict[str, Any]] = []
    allocation: Dict[str, int] = {}

    # R239(b)(i). The per-contest cap, applied at the moment the captain slot is
    # apportioned rather than evaluated after the fact -- R153's finding with
    # population substituted for enforcement point. `partition["size_of_entry"]`
    # is aligned to the ladder order, so slot j knows its own contest.
    partition = contest_partition(contest_of_entry, int(n_entries))
    per_contest_cap = max(1, int(max_cpt_per_contest))
    # The bar is per CONTEST, because it depends on that contest's own size:
    # `n - 1` is what stops a 2-entry contest being allowed both its entries on
    # one captain. See showdown.per_contest_cap_count.
    cap_for_contest = {cid: per_contest_cap_count(size, per_contest_cap)
                       for cid, size in (partition.get("sizes") or {}).items()}
    contest_cpt_counts: Dict[str, Dict[str, int]] = {}
    # Widening the captain pool is NOT a relaxation and is counted apart from
    # one: the cap held, the ladder simply reached past a template's own
    # shortlist to hold it. R239 is explicit that a per-contest bind is answered
    # by building more distinct captains, never by refusing (a blank reserved row
    # blocks certification) and never by relaxing in silence.
    pool_widened: List[Dict[str, str]] = []
    contest_cap_relaxed = 0
    # Slate-wide fallback captains, best Base first, for when a template's own
    # ladder is exhausted. Deterministic: Base descending, then key, so a tie
    # never depends on frame order.
    base_by_key = shape["_base"]
    wide_ladder = [k for k, _ in sorted(base_by_key.items(),
                                        key=lambda kv: (-float(kv[1]), str(kv[0])))]

    def _under_caps(cand: str, cid: Optional[str]) -> bool:
        if cap is not None and cpt_counts.get(cand, 0) >= cap:
            return False
        if cid is not None:
            here = contest_cpt_counts.get(cid, {})
            # The effective bound on one captain inside one contest is
            # min(portfolio cap, per-contest cap); both are checked, so the min
            # holds without being computed.
            if here.get(cand, 0) >= cap_for_contest.get(cid, per_contest_cap):
                return False
        return True

    # Round-robin the templates so a truncated build still spans game states
    # rather than filling every entry from the first template in the list.
    order = _round_robin(counts)
    for slot, idx in enumerate(order):
        spec = specs[idx]
        built = spec["build"]()
        allocation[spec["id"]] = allocation.get(spec["id"], 0) + 1
        cid = None
        if partition["available"] and partition["contest_of_entry"] is not None:
            if slot < len(partition["contest_of_entry"]):
                cid = partition["contest_of_entry"][slot]
        cpt = None
        own_ladder = list(built.get("cpt_ladder") or [])
        for cand in own_ladder:
            if _under_caps(cand, cid):
                cpt = cand
                break
        if cpt is None and cid is not None:
            # The template's own shortlist is exhausted under the caps. Widen
            # before giving anything up: a captain outside this template's
            # ladder is still a legal captain, and the thesis label moving is a
            # far smaller cost than two entries in one contest sharing a slot.
            for cand in wide_ladder:
                if cand not in own_ladder and _under_caps(cand, cid):
                    cpt = cand
                    pool_widened.append({
                        "template": str(spec["id"]),
                        "contest_id": str(cid),
                        "captain": str(cand),
                        "reason": "template ladder exhausted under the per-contest cap",
                    })
                    break
        if cpt is None:                       # every eligible captain at cap
            ladder = own_ladder
            cpt = ladder[0] if ladder else None
            # Which cap actually bound decides which counter moves. A
            # per-contest bind that survived the widening above is a different
            # event from the portfolio cap running out of captains, and folding
            # them into one number is how a reader loses the ability to tell a
            # thin pool from a thin contest.
            if cid is not None and cpt is not None and not _under_caps(cpt, None):
                cap_relaxed += 1
            elif cid is not None:
                contest_cap_relaxed += 1
            else:
                cap_relaxed += 1
        if cpt is not None:
            cpt_counts[cpt] = cpt_counts.get(cpt, 0) + 1
            if cid is not None:
                bucket = contest_cpt_counts.setdefault(cid, {})
                bucket[cpt] = bucket.get(cpt, 0) + 1
        # More entries than live templates means templates repeat. The rosters
        # still differ (the overlap bound guarantees it), but two rows sharing a
        # thesis name reads as a duplicate in the brief when it is not one, so
        # the repeat is named by what actually distinguishes it: its captain.
        name = built["name"]
        if allocation[spec["id"]] > 1:
            cpt_name = str(df.loc[df["Player_Key"] == cpt, "Name"].iloc[0]) \
                if cpt is not None and (df["Player_Key"] == cpt).any() else "no captain"
            name = f"{name} (variant {allocation[spec['id']]}, {cpt_name} captain)"
        # R156. `locks` strips the captain because a captain does not need
        # separate protection -- true as long as HE stays captain. `hard_locks`
        # is the escape hatch for a player who must be rostered no matter what
        # happens to the captain assignment later (solve_ladder's relaxation
        # ladder can drop or substitute cpt on its own). It is never filtered by
        # `cpt`, so it survives every rung. Only `duel()` sets it today.
        raw_locks = [k for k in (built.get("locks") or []) if k and k != cpt]
        hard_locks = [k for k in (built.get("hard_locks") or []) if k]
        locks = raw_locks + [k for k in hard_locks if k not in raw_locks]
        thesis = {
            "template": spec["id"],
            "name": name,
            "why": built["why"],
            "cpt": cpt,
            "locks": locks,
            "excludes": [k for k in (built.get("excludes") or []) if k and k != cpt],
            "mult": {k: v for k, v in (built.get("mult") or {}).items()},
        }
        theses.append(thesis)

    return {"theses": theses, "shape": {k: v for k, v in shape.items()
                                        if not k.startswith("_")},
            "allocation": allocation,
            "captain_cap_count": cap,
            "captain_cap_relaxed": cap_relaxed,
            "contest_partition": partition,
            # R239(b). The per-contest cap and what it cost to hold.
            "max_cpt_per_contest": per_contest_cap,
            # NOT a relaxation: the cap held and the ladder reached past a
            # template's own shortlist to hold it, so the thesis built with a
            # captain its label does not imply. Same treatment R153 gave
            # `cap_reassignments`, and named for the same reason.
            "captain_pool_widened": pool_widened,
            # A per-contest bind that survived the widening. Distinct from
            # `captain_cap_relaxed` (the PORTFOLIO cap running out) so a reader
            # can tell a thin pool from a thin contest.
            "captain_contest_cap_relaxed": contest_cap_relaxed,
            # R239(b)(ii). The precondition, on the apportionment this function
            # just produced. Reported rather than raised: the caller decides,
            # and a blank reserved row is worse than a named infeasibility.
            "captain_assignment_feasibility": captain_assignment_feasible(
                cpt_counts, list((partition.get("sizes") or {}).values()),
                max_cpt_per_contest=per_contest_cap)
            if partition["available"] else {
                "feasible": None,
                "reason": "no contest partition; the precondition needs contest sizes"},
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
                 max_player_exposure_pct: Optional[float] = DEFAULT_MAX_PLAYER_EXPOSURE_PCT,
                 max_cpt_exposure_pct: Optional[float] = DEFAULT_MAX_CPT_EXPOSURE_PCT,
                 time_limit: int = 8,
                 diagnostics: Optional[Dict[str, Any]] = None,
                 contest_of_entry: Optional[Sequence[str]] = None,
                 max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST,
                 ) -> List[Optional[Dict[str, Any]]]:
    """Solve each thesis under its own constraints, enforcing the overlap bound
    and the player-exposure cap against every lineup already built.

    Relaxation order when a thesis will not solve: drop the overlap bound, then
    drop the player-exposure cap, then drop the captain lock, then report the
    thesis infeasible. The captain lock goes before the thesis itself because a
    thesis with a different captain is still that game state; a missing lineup is
    a blank reserved row, and a blank row blocks certification.

    R153, on where the player cap sits. Overlap gives way first because two
    lineups differing by one bat are one lineup and that is the cheapest thing to
    lose. The player cap gives way second: relaxing it puts one more entry on a
    player already at half the set, a washout cost spread thin, where relaxing the
    captain lock concentrates the single highest-leverage slot. Captain stays
    last, unchanged.

    R153, second pass. **Both caps are HARD and bind against the REALIZED set, not
    against the apportionment.** The first pass got this wrong in two ways that the
    2026-08-19 ARI@BOS build made visible, and both are worth keeping written down
    because they are the same mistake in two places: a cap that is enforced
    somewhere other than where the roster spots are actually spent is not a cap.

    1. The player cap protected a thesis's own ``cpt`` and ``locks`` on the
       reasoning that a lock is the more specific instruction. That reasoning is
       fine and the consequence was not: the ladder assigns captains by name, a
       captain IS a roster spot, and so the carve-out let Wilyer Abreu reach 11 of
       19 (57.9%) under a 50% cap with ``player_relaxed: 0`` -- the cap reporting
       itself clean while not holding. A capped player is now removed from the
       thesis's cpt and locks BEFORE the solve, and the removal is named in
       ``player_cap_cpt_reassigned`` / ``player_cap_locks_dropped``. The thesis
       still gets built; it gets built with a different captain, which the ladder
       already treats as the same game state.
    2. ``solve_ladder`` enforced no captain cap whatsoever. It relied on
       ``build_thesis_ladder``'s apportionment, which caps the captains it ASSIGNS
       -- but the lock-relaxation rung then picks a substitute captain with no cap
       awareness, so a substitution lands on top of an already-full captain. Payton
       Tolle reached 5 of 19 (26.3%) against a cap count of 4. The cap is now
       enforced here too, against the running realized count, on every rung.
    """
    prior: List[List[str]] = []
    out: List[Optional[Dict[str, Any]]] = []
    overlap_relaxed = cpt_relaxed = infeasible = both_relaxed = 0
    player_relaxed = contest_cap_relaxed = 0
    # R223. The FOURTH counter, and the one R153's landing claim assumed existed.
    # `cpt_relaxed` counts captain LOCK substitutions; nothing counted the captain
    # CAP giving way, because until now nothing made it give way on the record --
    # the floor rung simply dropped it.
    cpt_cap_relaxed = 0
    cap_reassignments_withdrawn = 0
    # R158. A compute limit is not a strategy fact, and these counters are kept
    # apart from every relaxation counter for that reason. CLAUDE.md: "A timeout
    # is recorded in solver_report, never climbs the overlap ladder."
    solver_timeouts = 0
    time_limited_accepted = 0
    timeout_detail: List[Dict[str, str]] = []
    player_counts: Dict[str, int] = {}
    cpt_counts: Dict[str, int] = {}
    player_cap = exposure_cap_count(max_player_exposure_pct, len(theses))
    cpt_cap = exposure_cap_count(max_cpt_exposure_pct, len(theses))
    player_cap_cpt_reassigned: List[Dict[str, str]] = []
    player_cap_locks_dropped: List[Dict[str, str]] = []
    cpt_cap_reassigned: List[Dict[str, str]] = []
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
    # R250. Captain budget, reserved before UTIL can spend it.
    #
    # The measured case: a player named captain by three theses, cheap enough that
    # every earlier rung took him as UTIL salary relief first, finished at the
    # player cap (9 of 23) with ZERO captain slots. The cap overruled the ladder's
    # own captain judgment on ARRIVAL ORDER rather than on merits, and the
    # portfolio spent his entire exposure budget at 1.0x and none of it at 1.5x.
    # The captain slot is the largest single differentiator on a six-man roster,
    # so inverting it silently trades away the apex half of the dual objective.
    #
    # The mechanism is a hold, not a reorder. Walk the ladder once, count how many
    # theses NAME each player as captain, and hold one unit of that player's
    # player-cap budget per naming rung, up to the captain cap (he cannot captain
    # more often than that, so reserving more would strand budget). While a hold
    # is outstanding, the player is blocked from the UTIL slot ONLY -- never from
    # the pool, and never from the captain slot -- so the reserved budget is still
    # there when his own rungs solve.
    #
    # Why a hold and NOT R250's cheaper "reorder the rungs" variant: R239 made
    # ladder slot j an assignment to `rows[j]`'s CONTEST (`run_showdown` zips
    # `rows` with the bank, `bank[j]` solves `theses[j]`). Reordering rungs would
    # therefore redeal entries between prize pools as an invisible side effect of
    # a captain-leverage fix, and would do it underneath the per-contest captain
    # cap that binds on that same mapping. A hold moves no slot, so the contest
    # partition is untouched.
    captain_demand: Dict[str, int] = {}
    for t in theses:
        want = t.get("cpt")
        if want:
            captain_demand[str(want)] = captain_demand.get(str(want), 0) + 1
    reserve_ceiling = cpt_cap if cpt_cap is not None else len(theses)
    reserved_remaining: Dict[str, int] = {
        k: min(v, reserve_ceiling) for k, v in captain_demand.items()}
    captain_budget_reserved = {k: v for k, v in reserved_remaining.items() if v}
    util_block_slots = 0
    util_block_detail: List[Dict[str, str]] = []
    # R239(b)(i). The per-contest cap enforced HERE, where the roster spot is
    # actually spent. R153's second pass is the whole reason: `solve_ladder`
    # trusted `build_thesis_ladder`'s apportionment and then substituted captains
    # on its own relaxation rungs with no cap awareness, which is how a captain
    # reached 26.3% under a 25% cap with every counter clean. A per-contest cap
    # that lived only in the apportionment would repeat that exactly.
    solve_partition = contest_partition(contest_of_entry, len(theses))
    per_contest_cap = max(1, int(max_cpt_per_contest))
    cap_for_contest = {cid: per_contest_cap_count(size, per_contest_cap)
                       for cid, size in (solve_partition.get("sizes") or {}).items()}
    contest_cpt_counts: Dict[str, Dict[str, int]] = {}
    contest_cpt_excluded: List[Dict[str, str]] = []

    def _rung(latch: Dict[str, Any], **call_kw: Any) -> Optional[Dict[str, Any]]:
        """Run one ladder rung, latching what the SOLVER said as distinct from
        what the constraints said.

        R158. ``build_showdown_lineup`` returning ``None`` used to be the ladder's
        only signal, and it conflated the two facts that demand opposite
        responses. An infeasible rung means this combination of controls has no
        lineup, and the ladder should relax one and try again. A timed-out rung
        means the clock ran out, and relaxing anything cannot make the clock
        longer -- it just re-pays the full time limit on a rung whose result will
        then be recorded as a control giving way. Latching the timeout is what
        lets the caller BREAK instead of descending.
        """
        st_out: Dict[str, Any] = {}
        got = build_showdown_lineup(status_out=st_out, **call_kw)
        if got is None:
            if st_out.get("timed_out"):
                latch["timed_out"] = True
                latch["message"] = str(st_out.get("message") or "")
                latch["incumbent_rejected"] = bool(st_out.get("incumbent_rejected"))
        elif st_out.get("optimality") == "time_limited":
            # A verified incumbent accepted under the clock. Not a relaxation and
            # not a refusal: the lineup is legal, it is simply not proven optimal.
            latch["time_limited"] = True
        return got

    def _record_lock_relaxation(thesis: Mapping[str, Any], solved: Mapping[str, Any]) -> int:
        """Record a captain substitution and return 1, or 0 if none happened.

        R153. A rung that drops the lock and then happens to pick the SAME captain
        substituted nothing, and counting it puts a row in the caution naming a
        player who replaced himself. The floor rung made this reachable, because it
        solves with no ``cpt_excludes`` at all. The counter and the detail list are
        incremented together so ``len(detail) == captain_lock_relaxed`` always.
        """
        requested = thesis.get("cpt")
        actual = (solved.get("captain") or {}).get("player_key")
        if requested and actual and requested == actual:
            return 0
        lock_relaxation_detail.append({
            "thesis": str(thesis.get("name") or thesis.get("template") or "?"),
            "requested": name_by_key.get(requested, requested) if requested else "none",
            "actual": name_by_key.get(actual, actual) if actual else "?",
        })
        return 1

    for slot, thesis in enumerate(theses):
        work = df.copy()
        mult = thesis.get("mult") or {}
        if mult:
            work["Base"] = [float(b) * float(mult.get(k, 1.0))
                            for b, k in zip(work["Base"], work["Player_Key"])]
        tname = str(thesis.get("name") or thesis.get("template") or "?")
        thesis_excludes = [str(k) for k in (thesis.get("excludes") or [])]
        # R153. Both caps bind against the REALIZED counts, and a capped player is
        # removed from this thesis's own cpt and locks first. A lock plus an
        # exclude on one key is an instant infeasibility that misreports as "the
        # thesis could not solve", so the contradiction is resolved here, in favour
        # of the cap, and every removal is named.
        over = sorted(k for k, c in player_counts.items()
                      if player_cap is not None and c >= player_cap)
        over_set = set(over)
        cpt_full = {k for k, c in cpt_counts.items()
                    if cpt_cap is not None and c >= cpt_cap}
        # R239(b)(i). This slot's own contest, and who is already at the
        # per-contest cap inside it. The effective bound on one captain in one
        # contest is min(portfolio cap count, per-contest cap count); both sets
        # feed the same exclusion list, so the min holds without being computed
        # and without either cap being able to override the other.
        slot_cid = None
        if solve_partition["available"] and solve_partition["contest_of_entry"]:
            if slot < len(solve_partition["contest_of_entry"]):
                slot_cid = solve_partition["contest_of_entry"][slot]
        contest_full: set = set()
        if slot_cid is not None:
            here = contest_cpt_counts.get(slot_cid, {})
            bar = cap_for_contest.get(slot_cid, per_contest_cap)
            contest_full = {k for k, c in here.items() if c >= bar}
        # A player at the PLAYER cap cannot take a captain slot either, since the
        # captain is a roster spot. Union, not just the captain counts.
        cpt_excludes = sorted(cpt_full | over_set | contest_full) or None

        want_cpt = str(thesis["cpt"]) if thesis.get("cpt") else None
        cpt_lock = want_cpt
        # R223. Which list took this slot's reassignment record, and which record,
        # so a lower rung that re-seats the very captain the record calls removed
        # can WITHDRAW it. Two records in one brief contradicting each other is
        # worse than either of them.
        #
        # R233, the class: there are THREE reassignment lists and all three are
        # contradictable the same way, because every one of them is written before
        # the solve and every relaxation rung below can re-seat the captain. R223
        # named only `cpt_cap_reassigned`; fixing that one alone would have left
        # the identical defect in the two beside it.
        reassigned_into: Optional[List[Dict[str, str]]] = None
        reassigned_record: Optional[Dict[str, str]] = None
        if want_cpt and want_cpt in over_set:
            cpt_lock = None
            reassigned_record = {
                "thesis": tname, "player": name_by_key.get(want_cpt, want_cpt),
                "count_at_cap": str(player_counts.get(want_cpt, 0))}
            reassigned_into = player_cap_cpt_reassigned
        elif want_cpt and want_cpt in cpt_full:
            cpt_lock = None
            reassigned_record = {
                "thesis": tname, "player": name_by_key.get(want_cpt, want_cpt),
                "count_at_cap": str(cpt_counts.get(want_cpt, 0))}
            reassigned_into = cpt_cap_reassigned
        elif want_cpt and want_cpt in contest_full:
            # R239(b). Same treatment, third cap. NOT a relaxation: the cap held
            # and the thesis label moved, which is R153's own distinction.
            cpt_lock = None
            reassigned_record = {
                "thesis": tname, "player": name_by_key.get(want_cpt, want_cpt),
                "contest_id": str(slot_cid),
                "count_at_cap": str(contest_cpt_counts.get(slot_cid, {})
                                    .get(want_cpt, 0))}
            reassigned_into = contest_cpt_excluded
        if reassigned_into is not None and reassigned_record is not None:
            reassigned_into.append(reassigned_record)

        want_locks = [str(k) for k in (thesis.get("locks") or []) if k]
        locks = [k for k in want_locks if k not in over_set]
        for k in [k for k in want_locks if k in over_set]:
            player_cap_locks_dropped.append({
                "thesis": tname, "player": name_by_key.get(k, k),
                "count_at_cap": str(player_counts.get(k, 0))})

        with_cap = (thesis_excludes + [k for k in over if k not in thesis_excludes]) or None
        without_cap = thesis_excludes or None
        # R250. Who is holding reserved captain budget right now. A player is
        # blocked from the UTIL seat only while (a) he still has captain rungs
        # ahead of him and (b) taking one more non-captain seat would eat into the
        # units those rungs need. Below that line he is spent freely: the hold is
        # the LAST few units of his budget, not his whole exposure.
        util_blocked: List[str] = []
        if player_cap is not None:
            for k, held in reserved_remaining.items():
                if held <= 0:
                    continue
                if player_counts.get(k, 0) >= player_cap - held:
                    util_blocked.append(k)
        util_blocked = sorted(util_blocked)
        if util_blocked:
            util_block_slots += 1
            # One row per (slot, player) rather than a joined string, so the
            # HELD figure is readable rather than parsed. It shrinks as the hold
            # is spent, and a hold that never shrinks is a player blocked out of
            # UTIL seats forever after his captain rungs are done -- stranded
            # budget, which is the opposite of what the reservation is for.
            for k in util_blocked:
                util_block_detail.append({
                    "thesis": tname,
                    "player": name_by_key.get(k, k),
                    "held": str(reserved_remaining[k]),
                })
        util_kw = {"util_excludes": util_blocked or None}
        kw = dict(locks=locks or None, time_limit=time_limit)
        # R158. One latch per slot. Every rung below is additionally guarded on
        # `not latch["timed_out"]`, so the ladder stops descending the moment the
        # solver reports a clock expiry rather than an infeasibility. Without that
        # guard a single slow solve walks the whole ladder, re-paying the time
        # limit at each rung, and every control it passed on the way down is
        # recorded as having been relaxed.
        latch: Dict[str, Any] = {"timed_out": False, "time_limited": False}
        # R250. The hold rides WITH the player cap: it is applied on every rung
        # that still carries `with_cap`, and dropped the moment the player cap
        # itself is relaxed. Reserving budget is only meaningful while there is a
        # budget; once the ladder is relaxing the cap it is already short of
        # lineups, and a blank reserved row blocks certification.
        lu = _rung(latch, df=work, cpt_lock=cpt_lock, cpt_excludes=cpt_excludes,
                   forbidden_sets=prior or None, excludes=with_cap,
                   max_shared_players=max_shared_players, **util_kw, **kw)
        if lu is None and not latch["timed_out"] and max_shared_players is not None:
            lu = _rung(latch, df=work, cpt_lock=cpt_lock, cpt_excludes=cpt_excludes,
                       forbidden_sets=prior or None,
                       excludes=with_cap, **util_kw, **kw)
            if lu is not None:
                overlap_relaxed += 1
        # R153. Player cap second, before the captain lock.
        if lu is None and not latch["timed_out"] and over:
            lu = _rung(latch, df=work, cpt_lock=cpt_lock, cpt_excludes=cpt_excludes,
                       forbidden_sets=prior or None,
                       excludes=without_cap,
                       max_shared_players=max_shared_players, **kw)
            if lu is not None:
                player_relaxed += 1
        if (lu is None and not latch["timed_out"] and over
                and max_shared_players is not None):
            lu = _rung(latch, df=work, cpt_lock=cpt_lock, cpt_excludes=cpt_excludes,
                       forbidden_sets=prior or None,
                       excludes=without_cap, **kw)
            if lu is not None:
                player_relaxed += 1
                overlap_relaxed += 1
        if lu is None and not latch["timed_out"]:
            lu = _rung(latch, df=work, cpt_excludes=cpt_excludes,
                       forbidden_sets=prior or None,
                       excludes=with_cap,
                       max_shared_players=max_shared_players, **util_kw, **kw)
            if lu is not None:
                cpt_relaxed += _record_lock_relaxation(thesis, lu)
        # R54(b). The fourth rung, which the BANK ladder had and this one did
        # not: a thesis solvable only under both relaxations returned None and
        # left a blank reserved row -- write-blocked at T-5 -- on a pool the bank
        # path fills. Counted in every place it is true, matching
        # build_showdown_bank: these answer "how many lineups were built without
        # this control", so a clean ladder is all three at zero.
        if (lu is None and not latch["timed_out"] and cpt_lock
                and max_shared_players is not None):
            lu = _rung(latch, df=work, cpt_excludes=cpt_excludes,
                       forbidden_sets=prior or None,
                       excludes=with_cap, **util_kw, **kw)
            if lu is not None:
                substituted = _record_lock_relaxation(thesis, lu)
                both_relaxed += substituted
                overlap_relaxed += 1
                cpt_relaxed += substituted
        # R153. The floor rung: every portfolio control off, the thesis's own
        # excludes still honoured. Counted in every place it is true, matching
        # build_showdown_bank, because these counters answer "how many lineups were
        # built WITHOUT this control" and the brief's clean verdict rests on that.
        # The captain cap comes off here too: at this rung nothing else has worked
        # and the alternative is a blank reserved row, which blocks certification.
        if lu is None and not latch["timed_out"] and (
                over or cpt_lock or cpt_excludes
                or max_shared_players is not None):
            # R223. This rung drops the OVERLAP bound and the player-exposure
            # EXCLUDES, and it now keeps every captain exclusion -- portfolio and
            # per-contest alike. It used to pass `sorted(contest_full)`, which
            # silently dropped `cpt_full` and `over_set`: the captain cap coming
            # off with nothing counting it, which is verbatim R153's founding
            # defect ("the overlap bound was clean, the captain cap was clean")
            # and the reason a delivered brief could read `0 relaxations` over a
            # breached 25% cap.
            #
            # The documented order is overlap, then player exposure, then captain
            # lock, then thesis. The captain CAP therefore may not come off in the
            # same breath as the overlap bound; it gets its own rung below, after
            # player exposure has already given way here.
            lu = _rung(latch, df=work,
                       cpt_excludes=cpt_excludes,
                       forbidden_sets=prior or None,
                       excludes=without_cap, **kw)
            if lu is not None:
                if over:
                    player_relaxed += 1
                if max_shared_players is not None:
                    overlap_relaxed += 1
                substituted = _record_lock_relaxation(thesis, lu) if cpt_lock else 0
                cpt_relaxed += substituted
                if max_shared_players is not None:
                    both_relaxed += substituted
        # R223. The PORTFOLIO captain cap gives way here, and is COUNTED when it
        # does. `cpt_full` is the portfolio captain cap; `over_set` is the player
        # cap reaching the captain slot, since a captain is a roster spot. Both
        # come off together because both are portfolio-level bounds and the rung
        # below this one is the per-contest cap, which is more specific and
        # cheaper to keep. A blank reserved row blocks certification, so the cap
        # gives way rather than never -- but it gives way on the record.
        portfolio_cpt_excluded = sorted(cpt_full | over_set)
        if lu is None and not latch["timed_out"] and portfolio_cpt_excluded:
            lu = _rung(latch, df=work,
                       cpt_excludes=sorted(contest_full) or None,
                       forbidden_sets=prior or None,
                       excludes=without_cap, **kw)
            if lu is not None:
                cpt_cap_relaxed += 1
                if over:
                    player_relaxed += 1
                if max_shared_players is not None:
                    overlap_relaxed += 1
                substituted = _record_lock_relaxation(thesis, lu) if cpt_lock else 0
                cpt_relaxed += substituted
                if max_shared_players is not None:
                    both_relaxed += substituted
        # R239(b). The TRUE floor, reachable only when a per-contest cap is
        # actually binding. A blank reserved row blocks certification, so the
        # per-contest cap gives way last rather than never -- and it is counted,
        # because a portfolio is clean when the relaxation counts are zero, not
        # when the gates passed.
        if lu is None and not latch["timed_out"] and contest_full:
            lu = _rung(latch, df=work, forbidden_sets=prior or None,
                       excludes=without_cap, **kw)
            if lu is not None:
                contest_cap_relaxed += 1
                # R223. This rung passes NO captain exclusions at all, so the
                # portfolio cap gave way here too and is counted here too. These
                # counters answer "how many lineups were built WITHOUT this
                # control", so a rung that drops two controls increments two.
                if portfolio_cpt_excluded:
                    cpt_cap_relaxed += 1
                if over:
                    player_relaxed += 1
                if max_shared_players is not None:
                    overlap_relaxed += 1
                cpt_relaxed += _record_lock_relaxation(thesis, lu) if cpt_lock else 0
        if latch["time_limited"]:
            time_limited_accepted += 1
        if lu is None:
            # R158. "The allocator says 'time limit at gap X' or 'proven
            # infeasible: <constraint>', never both" (CLAUDE.md). A slot the clock
            # ended is not evidence the pool has no lineup, so it does not enter
            # `infeasible` -- that counter is a claim about the CONSTRAINTS, and
            # attributing a compute limit to it is the same inversion R158 was
            # filed for, one level up from the solver.
            if latch["timed_out"]:
                solver_timeouts += 1
                timeout_detail.append({
                    "thesis": tname, "slot": str(slot),
                    "message": str(latch.get("message") or ""),
                    "incumbent_rejected": str(bool(latch.get("incumbent_rejected"))),
                })
            else:
                infeasible += 1
        else:
            prior.append(list(lu["player_keys"]))
            for key in lu["player_keys"]:
                player_counts[key] = player_counts.get(key, 0) + 1
            got_cpt = (lu.get("captain") or {}).get("player_key")
            # R223. A lower rung re-seated the very captain a cap record says was
            # removed, so the record is withdrawn rather than shipped beside the
            # exposure table that contradicts it. Counted, because a withdrawal is
            # a fact about the ladder and not a silent edit: it says the cap did
            # not hold where the reassignment claimed it did.
            if (reassigned_record is not None and reassigned_into is not None
                    and got_cpt and want_cpt and got_cpt == want_cpt):
                reassigned_into.remove(reassigned_record)
                cap_reassignments_withdrawn += 1
            if got_cpt:
                cpt_counts[got_cpt] = cpt_counts.get(got_cpt, 0) + 1
                # R250. The hold is spent when the seat it was held for is
                # filled. Never below zero: a player can be captained by a rung
                # that never named him, and that costs him nothing he was owed.
                if reserved_remaining.get(got_cpt, 0) > 0:
                    reserved_remaining[got_cpt] -= 1
                # R239(b). Against the REALIZED captain, not the requested one.
                # R153's finding was that the ladder's apportionment is not what
                # the solver spends, so the per-contest counter reads what came
                # back from the solve, the same as `cpt_counts` above.
                if slot_cid is not None:
                    bucket = contest_cpt_counts.setdefault(slot_cid, {})
                    bucket[got_cpt] = bucket.get(got_cpt, 0) + 1
            # R54(c). A thesis lock the melt never carried used to no-op in
            # silence, and cpt_counts then accounted against captains that were
            # never enforced.
            for key in (lu.get("ignored_locks") or []):
                if key not in ignored_locks:
                    ignored_locks.append(key)
        out.append(lu)

    # R250. The apex caution, stated as its own condition rather than left for a
    # reader to derive by crossing three tables. "At the player cap, named captain
    # by at least one rung, captained zero times" is the exact sentence that would
    # have caught the measured case, where the portfolio spent a named captain's
    # entire budget at 1.0x and none of it at 1.5x.
    captain_budget_inversions = [
        {
            "player": name_by_key.get(k, k),
            "named_by_rungs": str(captain_demand.get(k, 0)),
            "player_count": str(player_counts.get(k, 0)),
            "player_cap_count": str(player_cap),
            "captain_slots": "0",
        }
        for k in sorted(captain_demand)
        if captain_demand.get(k, 0) >= 1
        and cpt_counts.get(k, 0) == 0
        and player_cap is not None
        and player_counts.get(k, 0) >= player_cap
    ]
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
            # R158. Compute facts, reported beside the relaxation counters and
            # never summed into them. `solver_timeouts` counts slots that ended on
            # the clock with no lineup; `time_limited_accepted` counts slots that
            # DID produce a lineup from a verified incumbent under the clock --
            # legal, delivered, and simply not proven optimal. A brief that shows
            # relaxations at zero and `solver_timeouts` nonzero is reporting an
            # infrastructure limit, which is a time-limit change, not a strategy
            # change.
            "solver_timeouts": solver_timeouts,
            "time_limited_accepted": time_limited_accepted,
            "solver_timeout_detail": list(timeout_detail),
            # R153. The player-exposure cap, reported on the same footing as the
            # other two controls so "clean" means all three held. The three
            # reassignment lists are NOT relaxations: nothing gave way, a capped
            # player was taken off a thesis's own cpt or locks so the cap could
            # hold. They are named because a thesis that built with a different
            # captain than its label implies is a fact the reader wants.
            "max_player_exposure_pct": max_player_exposure_pct,
            "player_cap_count": player_cap,
            "player_relaxed": player_relaxed,
            "player_cap_cpt_reassigned": list(player_cap_cpt_reassigned),
            "player_cap_locks_dropped": list(player_cap_locks_dropped),
            "player_cap_structural_floor": player_cap_structural_floor(
                len(df), len(theses)),
            "max_cpt_exposure_pct": max_cpt_exposure_pct,
            "cpt_cap_count": cpt_cap,
            "cpt_cap_reassigned": list(cpt_cap_reassigned),
            # R223. The fourth counter. `captain_lock_relaxed` above counts LOCK
            # substitutions; this counts the portfolio captain CAP giving way,
            # which nothing measured before -- the floor rung dropped it in
            # silence and the brief read `0 relaxations` over a breached cap.
            #
            # NAMED `cpt_cap_relaxed`, not `captain_cap_relaxed`, and the reason
            # is R113. `build_thesis_ladder` ALREADY returns a
            # `captain_cap_relaxed`, and it is a different mechanism: the
            # APPORTIONMENT step reaching past a template's shortlist. R113 was
            # filed because those two were once summed into one number the brief
            # called "captain cap relaxed" no matter which fired. Reusing the name
            # here would have rebuilt that collision one function over. This one
            # follows `contest_cap_relaxed`'s convention: the solver-side counters
            # carry their internal names.
            "cpt_cap_relaxed": cpt_cap_relaxed,
            # R250. The captain budget held back from the UTIL seat, and what it
            # cost. NOT a relaxation and NOT a cap breach: nothing gave way, a
            # player who several rungs name as captain was stopped from spending
            # the last of his own exposure budget at 1.0x before those rungs
            # solved. `captain_budget_reserved` is the hold as planned;
            # `captain_budget_util_blocks` is the number of slots where it
            # actually bound.
            "captain_budget_reserved": dict(captain_budget_reserved),
            "captain_budget_util_blocks": util_block_slots,
            "captain_budget_block_detail": list(util_block_detail),
            # The apex caution itself. Non-empty means the portfolio spent a named
            # captain's entire budget at 1.0x and none at 1.5x, which is the
            # condition R250 was filed for. Empty on a clean ladder.
            "captain_budget_inversions": captain_budget_inversions,
            # Reassignment records withdrawn because a lower rung re-seated the
            # captain they name. Zero on a clean ladder.
            "cap_reassignments_withdrawn": cap_reassignments_withdrawn,
            "captain_exposure_realized": dict(cpt_counts),
            "contest_partition": solve_partition,
            # R239(b). The fourth control, on the same footing as the other
            # three so "clean" can mean all four held.
            "max_cpt_per_contest": per_contest_cap,
            # NOT a relaxation: a captain at the per-contest cap taken off this
            # thesis's own captain slot so the cap could hold.
            "contest_cpt_reassigned": list(contest_cpt_excluded),
            # A relaxation, and the last one available: the true floor gave the
            # per-contest cap up rather than leave a blank reserved row.
            "contest_cap_relaxed": contest_cap_relaxed,
            "captain_exposure_by_contest": {
                cid: dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
                for cid, counts in sorted(contest_cpt_counts.items())
            },
        })
    return out


# ---------------------------------------------------------------------------
# R263 shadow report, Ben's dated decision of 2026-08-28. SHADOW ONLY.
# ---------------------------------------------------------------------------
#
# These three bands come from ledger 3.21 and the root greenfield doc. They are
# PRINTED beside the caps and they steer NOTHING: no thesis, no posture, no
# constraint reads them. The hard-band half of R263 waits on the R238/R239
# contest-awareness cluster, and R153's lesson is exactly why it waits -- a cap
# enforced anywhere other than where the roster spots are actually spent is not a
# cap, and the place SD roster spots are spent is `solve_ladder`, not a report.
#
# What 3.21 measured, all observed cohort shares over 249 Showdown contests:
#   - Pitcher CPT: 46.0% of field rows, 56.8% of top-decile, 65.5% of winners,
#     with disc/val winner shares .692/.631 -- REPLICATED direction, the
#     strongest construction signal in either format. We deliver 40%.
#   - Team split of the 6 rostered: 5-1 is 50.2% of the top-1% cohort against a
#     field at 35.3%, and 3-3 is -10.3pp. Direction stable, magnitude unstable
#     across halves: STABLE DIRECTIONAL. We deliver 73.4% 5-1, which is the one
#     axis where we are OVER-concentrated -- above even the top cohort.
#
# None of this is a win rate, a cash rate, or a probability claim.
R263_SHADOW_BANDS: Dict[str, Any] = {
    "pitcher_cpt_share_pct": {
        "low": 48.0, "high": 52.0,
        "condition": "both starters declared",
        "evidence": "3.21: field 46.0, top-decile 56.8, winners 65.5 (REPLICATED direction)",
    },
    "team_split_5_1_pct": {
        "low": 45.0, "high": 55.0,
        "condition": None,
        "evidence": "3.21: top-1% 50.2 vs field 35.3 (STABLE DIRECTIONAL); ours 73.4",
    },
    "team_split_4_2_pct": {
        "low": 30.0, "high": None,
        "condition": None,
        "evidence": "3.21: restore 4-2 to >= 30% as the counterweight to 5-1 over-concentration",
    },
}


def _split_pattern(team_split: Mapping[str, int]) -> str:
    """A team split dict -> the canonical pattern string, e.g. ``{'BOS':5,'ARI':1}``
    -> ``'5-1'``. Counts sorted DESCENDING and joined by '-', which is the same
    canonicalization `field_miner`'s `stack_pattern` uses, so a delivered split
    and a mined field share are directly comparable strings rather than two
    vocabularies for one fact."""
    counts = sorted((int(v) for v in team_split.values()), reverse=True)
    return "-".join(str(c) for c in counts) if counts else ""


def construction_shadow(
    df: pd.DataFrame,
    report: Mapping[str, Any],
    max_cpt_exposure_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """R263's shadow report: pitcher-CPT share, team-split mix, and the band check.

    Steers nothing. Every number is counted off the SOLVED lineups, so it
    describes the file that is about to be delivered rather than the ladder's
    apportionment -- the distinction R153 paid for, where a captain apportionment
    read clean while the realized set breached the cap.

    ``pitcher_cpt_ceiling_pct`` is the part of this block worth reading FIRST,
    and it is why the band check prints a ceiling column at all. A Showdown slate
    with two declared arms cannot put a pitcher in the captain slot of more than
    ``2 * floor(cap_pct * n)`` entries, because the captain cap is per PLAYER and
    there are only two players eligible to be that captain. At the shipped 0.25
    cap that ceiling is at most 50% and is usually less: at n=19 it is
    2*floor(4.75)/19 = 42.1%. So a 48-52% band is UNREACHABLE on a two-arm slate
    at 19 entries no matter what any thesis weight does, and a delivered 40%
    there is 95% of the structural maximum rather than 8 points short of a
    target. A bullpen game raises the ceiling by adding eligible arms; nothing
    else does except the cap itself, which is out of R263's scope.
    """
    rows = [r for r in (report.get("lineups") or []) if r.get("solved")]
    n = len(rows)
    out: Dict[str, Any] = {
        "label": "R263 CONSTRUCTION SHADOW — observed cohort comparison; steers "
                 "nothing, gates nothing, and is never a win rate, cash rate, or "
                 "probability claim",
        "decision": "Ben, dated 2026-08-28; bands graded as finish cohorts over "
                    ">= 12 conditioned slates before any tightening",
        "entries_solved": n,
        "pitcher_cpt_entries": None,
        "pitcher_cpt_share_pct": None,
        "pitcher_cpt_ceiling_pct": None,
        "pitcher_cpt_share_of_ceiling_pct": None,
        "declared_arms": None,
        "team_split_mix": {},
        "team_split_mix_pct": {},
        "band_check": {},
        "steers": False,
    }
    if not n:
        return out
    # A Showdown pitcher is a row with no batting order, which is the same
    # definition `describe_slate` uses to find the starters. Read from the melt
    # rather than from a position string: DK prices every player twice in this
    # format and `Roster_Position` carries CPT/UTIL, not P.
    try:
        pitcher_names = {
            str(nm) for nm, bo in zip(df["Name"], df["Batting_Order"])
            if pd.isna(bo)}
    except Exception:
        pitcher_names = set()
    out["declared_arms"] = len(pitcher_names)
    cpt_is_p = [1 if str(r.get("captain")) in pitcher_names else 0 for r in rows]
    out["pitcher_cpt_entries"] = sum(cpt_is_p)
    out["pitcher_cpt_share_pct"] = round(100.0 * sum(cpt_is_p) / n, 1)
    if pitcher_names and max_cpt_exposure_pct:
        per_player = exposure_cap_count(max_cpt_exposure_pct, n)
        if per_player is not None:
            ceiling = min(n, len(pitcher_names) * int(per_player))
            out["pitcher_cpt_ceiling_pct"] = round(100.0 * ceiling / n, 1)
            if ceiling:
                out["pitcher_cpt_share_of_ceiling_pct"] = round(
                    100.0 * sum(cpt_is_p) / ceiling, 1)
    patterns = [_split_pattern(r.get("team_split") or {}) for r in rows]
    mix = Counter(p for p in patterns if p)
    out["team_split_mix"] = dict(sorted(mix.items(), key=lambda kv: -kv[1]))
    out["team_split_mix_pct"] = {
        k: round(100.0 * v / n, 1) for k, v in out["team_split_mix"].items()}

    def _check(key: str, observed: Optional[float], ceiling: Optional[float] = None):
        band = R263_SHADOW_BANDS[key]
        lo, hi = band["low"], band["high"]
        if observed is None:
            verdict = "unmeasurable"
        elif lo is not None and observed < lo:
            verdict = "below_band"
        elif hi is not None and observed > hi:
            verdict = "above_band"
        else:
            verdict = "in_band"
        entry: Dict[str, Any] = {
            "observed_pct": observed, "band_low": lo, "band_high": hi,
            "verdict": verdict, "evidence": band["evidence"],
            "condition": band.get("condition"),
        }
        if ceiling is not None:
            entry["structural_ceiling_pct"] = ceiling
            # A band the caps forbid is not a miss and must not read as one.
            if lo is not None and ceiling < lo:
                entry["band_reachable"] = False
                entry["note"] = (
                    f"the band's floor of {lo}% is ABOVE this portfolio's "
                    f"structural ceiling of {ceiling}%, which the per-player "
                    f"captain cap fixes at 2 x floor(cap x n) on a two-arm "
                    f"slate. Thesis weights cannot reach it; only the cap or "
                    f"another declared arm can. Read the share against the "
                    f"ceiling, not against the band")
            else:
                entry["band_reachable"] = True
        out["band_check"][key] = entry

    _check("pitcher_cpt_share_pct", out["pitcher_cpt_share_pct"],
           ceiling=out["pitcher_cpt_ceiling_pct"])
    _check("team_split_5_1_pct", out["team_split_mix_pct"].get("5-1", 0.0))
    _check("team_split_4_2_pct", out["team_split_mix_pct"].get("4-2", 0.0))
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
        # R153. The realized ceiling of the player-exposure cap, next to the
        # captain one it mirrors. Realized off the SOLVED lineups, so it is what
        # the delivered file actually carries, not what was requested.
        "max_player_exposure_pct": round(max(exposure.values()) / n * 100, 1) if n and exposure else 0.0,
        "prior_note": ("Base = 0.60*salary-regressed + 0.40*AvgPointsPerGame, "
                       "x batting-order PA factor x platoon factor. A labeled "
                       "deterministic prior, not a projection."),
        "label": "review_grade_build",
    }
