#!/usr/bin/env python3
"""Thesis-driven DK Showdown portfolio builder.

Each entry is solved under its own game-state thesis: a labeled set of roster
constraints (captain lock, player locks, exclusions) plus a thesis-conditional
adjustment to the Base review proxy. Uniqueness is enforced across the portfolio
with forbidden_sets.

Every number here is a deterministic review proxy or a labeled prior. Nothing in
this file is ROI, win rate, cash rate, or a probability claim. Showdown output is
review_grade_build, not Classic-certified.

Solver: mlb_engine.optimize.showdown.build_showdown_lineup (scipy.optimize.milp).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

VERSION = "0.1"

# PA-share prior by batting-order slot. Deterministic, not fitted to this slate.
ORDER_FACTOR = {1: 1.08, 2: 1.06, 3: 1.05, 4: 1.03, 5: 1.00,
                6: 0.97, 7: 0.95, 8: 0.92, 9: 0.90}


def adjust_base(df: pd.DataFrame, lhp_teams: set[str], opener_teams: set[str],
                bat_side: dict[str, str]) -> pd.DataFrame:
    """Replace Base (raw AvgPointsPerGame) with a labeled prior:
    salary-regressed APPG x batting-order factor x platoon factor.

    The salary regression exists because AvgPointsPerGame on a short sample can
    sit far off the market's own read of a player. Left unregressed, one
    small-sample outlier captains most of the portfolio.
    """
    out = df.copy()
    hit = out["Batting_Order"].notna()
    h = out[hit]
    # OLS of APPG on UTIL salary across the posted hitters only.
    slope, intercept = np.polyfit(h["UTIL_Salary"].astype(float),
                                 h["Base"].astype(float), 1)
    out["Salary_Fit"] = out["UTIL_Salary"].astype(float) * slope + intercept
    out["APPG_Raw"] = out["Base"].astype(float)

    def prior(row):
        if pd.isna(row["Batting_Order"]):
            return float(row["APPG_Raw"])          # pitchers keep APPG
        blended = 0.60 * float(row["Salary_Fit"]) + 0.40 * float(row["APPG_Raw"])
        f_order = ORDER_FACTOR[int(row["Batting_Order"])]
        side = bat_side.get(row["Name"], "R")
        # Opposing starter handedness. Both starters are LHP on this slate.
        opp_lhp = row["Opponent"] in lhp_teams
        if side == "S" or not opp_lhp:
            f_plat = 1.00
        elif side == "L":
            f_plat = 0.94
        else:
            f_plat = 1.04
        # An opener will not face the order long, so the platoon read is halved
        # against a declared opener rather than a declared starting pitcher.
        if row["Opponent"] in opener_teams:
            f_plat = 1.0 + (f_plat - 1.0) * 0.5
        return blended * f_order * f_plat

    out["Base_Prior"] = out.apply(prior, axis=1)
    out["Base"] = out["Base_Prior"]
    return out


def solve(df: pd.DataFrame, thesis: dict, forbidden: list[list[str]], sd):
    work = df.copy()
    mult = thesis.get("mult", {})
    work["Base"] = [
        float(b) * float(mult.get(k, 1.0))
        for b, k in zip(work["Base"], work["Player_Key"])
    ]
    return sd.build_showdown_lineup(
        work,
        locks=thesis.get("locks"),
        excludes=thesis.get("excludes"),
        cpt_lock=thesis.get("cpt"),
        forbidden_sets=forbidden or None,
        time_limit=thesis.get("time_limit", 8),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salary", required=True)
    ap.add_argument("--entries", required=True)
    ap.add_argument("--theses", required=True, help="JSON file of thesis specs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--brief", required=True)
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo))
    from mlb_engine.optimize import showdown as sd

    spec = json.loads(Path(args.theses).read_text())
    df = sd.melt_showdown_salary_csv(args.salary)
    basis = str(df["Pool_Basis"].iloc[0])
    df = adjust_base(df, set(spec["lhp_teams"]), set(spec["opener_teams"]),
                     spec["bat_side"])

    reserved = sd.read_showdown_reserved_rows(args.entries)
    blank = [r for r in reserved["reserved"] if not r["is_complete"]]
    theses = spec["theses"]
    if len(theses) != len(blank):
        print(f"THESIS/ENTRY MISMATCH: {len(theses)} theses, {len(blank)} blank rows",
              file=sys.stderr)
        return 4

    forbidden: list[list[str]] = []
    assignments, report = [], []
    for row, thesis in zip(blank, theses):
        lu = solve(df, thesis, forbidden, sd)
        if lu is None:
            print(f"INFEASIBLE: {thesis['name']}", file=sys.stderr)
            return 3
        cert = sd.certify_showdown(lu, df)
        keys = list(lu["roster_keys"]) if "roster_keys" in lu else None
        if keys is None:
            idmap = dict(zip(df["UTIL_ID"], df["Player_Key"]))
            idmap.update(dict(zip(df["CPT_ID"], df["Player_Key"])))
            keys = [idmap[i] for i in lu["roster_ids"]]
        forbidden.append(keys)
        assignments.append({"entry_id": row["entry_id"],
                            "roster_ids": list(lu["roster_ids"])})
        names = {k: n for k, n in zip(df["Player_Key"], df["Name"])}
        teams = {k: t for k, t in zip(df["Player_Key"], df["Team"])}
        report.append({
            "entry_id": row["entry_id"],
            "thesis": thesis["name"],
            "rationale": thesis.get("why", ""),
            "captain": names[keys[0]],
            "captain_team": teams[keys[0]],
            "utils": [names[k] for k in keys[1:]],
            "team_split": {t: sum(1 for k in keys if teams[k] == t)
                           for t in sorted(set(teams[k] for k in keys))},
            "salary": lu.get("salary"),
            "proxy_points": round(float(
                lu.get("proj_points") or lu.get("projected") or lu.get("proj")
                or lu.get("Base_Total") or lu.get("projected_points") or 0.0), 2),
            "lineup_certified": bool(cert.get("passed", False)),
            "cert_errors": cert.get("errors", []),
        })

    sd.write_showdown_entries(args.entries, args.out, assignments)
    tmpl = sd.verify_template_preserved(args.entries, args.out)

    sets = [tuple(sorted(r_["utils"] + [r_["captain"]])) for r_ in report]
    brief = {
        "version": VERSION,
        "label": "review_grade_build",
        "pool_basis": basis,
        "pool_size": int(len(df)),
        "entries": len(report),
        "all_unique_player_sets": len(set(sets)) == len(sets),
        "all_unique_rosters": len({tuple(a["roster_ids"]) for a in assignments}) == len(assignments),
        "template_preserved": bool(tmpl.get("valid", tmpl.get("preserved", tmpl))),
        "all_lineups_certified": all(r_["lineup_certified"] for r_ in report),
        "prior_note": ("Base = 0.60*salary-regressed + 0.40*AvgPointsPerGame, "
                       "x batting-order PA factor x platoon factor. A labeled "
                       "deterministic prior, not a projection."),
        "lineups": report,
    }
    Path(args.brief).write_text(json.dumps(brief, indent=2))
    print(json.dumps({k: v for k, v in brief.items() if k != "lineups"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
