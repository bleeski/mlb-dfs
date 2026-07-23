"""showdown.py -- DK Captain Mode (Showdown) build path, contract-driven.

Single-game DK Showdown: a roster of 1 CPT plus 5 UTIL, CPT scoring 1.5x and
using the CPT row's own salary and draftable id, no player in both roles, at
least one player from each team, salary cap 50000. Scoring is identical to
Classic, so projections transfer untouched; this module uses the salary file's
AvgPointsPerGame as a labeled deterministic Base proxy when no richer projection
is supplied.

SOLVER: scipy.optimize.milp only, mirroring optimizer_v3. TRUTHFUL LABELS: every
number here is a deterministic review proxy, never ROI, win rate, cash rate, or a
probability claim. Roster geometry, the salary rule, team representation, and the
export header come from mlb_engine.optimize.roster_contracts.SHOWDOWN.

Classic is untouched: this is a separate path and imports nothing from the Classic
solver, so test_golden_replay is unaffected.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from mlb_engine.optimize.roster_contracts import SHOWDOWN, RosterContract

VERSION = "0.2-review"

# A pure points-max solve always wants the single highest-Base player at CPT
# (1.5x multiplier beats any UTIL contribution), so an unbounded bank converges
# every lineup on the same captain. Observed 24/24 on the 2026-07-23 SD@ATL
# slate (Chris Sale, Base 22.35 against a next-best of ~15) before this cap
# existed. Default caps any single captain to just over a third of the bank.
DEFAULT_MAX_CPT_EXPOSURE_PCT = 0.35

_DIGITS = re.compile(r"\d+")


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _digits(cell: Any) -> str:
    m = _DIGITS.findall(str(cell or ""))
    return m[-1] if m else ""


# --------------------------------------------------------------------------- #
# Intake: melt the Showdown salary CSV to player grain with role-specific id/salary
# --------------------------------------------------------------------------- #
def melt_showdown_salary_csv(path: str | Path, exclude_out: bool = True,
                             starters_only: bool = True) -> pd.DataFrame:
    """Melt a DK Showdown salary export (two rows per player, CPT and UTIL) to one
    row per player carrying CPT_ID/CPT_Salary, UTIL_ID/UTIL_Salary, team, opponent,
    game, Base (AvgPointsPerGame, a labeled proxy), and the declared Starting value.

    Players missing either role row, or flagged out (Status IL/O/OUT) when
    ``exclude_out``, are dropped.

    ``starters_only`` restricts the pool to the players who can actually take the
    field, which is the same contract Classic enforces through
    ``live_data_adapters.build_slate_pool``. DraftKings publishes this in the salary
    file's ``Starting`` column: ``SP``/``P`` marks the declared starting pitcher and
    ``1``-``9`` marks a posted batting order slot. Without the filter the solver
    happily captains a reliever who will not pitch and rosters bench bats, because
    AvgPointsPerGame does not know who is playing. On the MIN@CHC fixture the
    unfiltered pool put a non-starting arm in every lineup while the file plainly
    declared someone else.

    The filter applies only when the file actually carries the information. Before
    lineups post, ``Starting`` is empty for everyone, so the pool falls back to all
    healthy players and stamps ``Pool_Basis='all_healthy'``. Read that column before
    treating a build as starter-restricted.
    """
    by_key: Dict[tuple, Dict[str, Any]] = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            name = str(r.get("Name") or "").strip()
            team = str(r.get("TeamAbbrev") or "").strip()
            role = str(r.get("Roster Position") or "").strip().upper()
            pid = _digits(r.get("ID") or r.get("Name + ID"))
            salary = _num(r.get("Salary"))
            if not name or not team or role not in ("CPT", "UTIL") or not pid or salary is None:
                continue
            status = str(r.get("Status") or "").strip().upper()
            if exclude_out and status in ("IL", "O", "OUT", "NA"):
                continue
            game_info = str(r.get("Game Info") or "")
            matchup = game_info.split(" ", 1)[0] if game_info else ""
            away, home = (matchup.split("@") + ["", ""])[:2] if "@" in matchup else ("", "")
            opponent = home if team == away else away
            base = _num(r.get("AvgPointsPerGame") or r.get("Avg Points Per Game")) or 0.0
            key = (name, team)
            starting = str(r.get("Starting") or "").strip().upper()
            rec = by_key.setdefault(key, {
                "Player_Key": f"{name}|{team}", "Name": name, "Team": team,
                "Opponent": opponent, "Position": str(r.get("Position") or "").strip(),
                "Game_ID": matchup, "Base": base, "Starting": starting,
                "CPT_ID": None, "CPT_Salary": None, "UTIL_ID": None, "UTIL_Salary": None,
            })
            if starting and not rec.get("Starting"):
                rec["Starting"] = starting
            if role == "CPT":
                rec["CPT_ID"], rec["CPT_Salary"] = pid, salary
            else:
                rec["UTIL_ID"], rec["UTIL_Salary"] = pid, salary
            if base and not rec.get("Base"):
                rec["Base"] = base
    rows = [r for r in by_key.values()
            if r["CPT_ID"] and r["UTIL_ID"] and r["CPT_Salary"] and r["UTIL_Salary"]]

    def _is_declared(rec: Mapping[str, Any]) -> bool:
        value = str(rec.get("Starting") or "").strip().upper()
        # PO (probable/projected opener) and PLR (piggyback/long reliever) are
        # DraftKings' own bullpen-game tags alongside SP/P; a bullpen-game slate
        # (opener + bulk arm) must keep both declared pitchers in the pool or the
        # entire team's pitching option silently vanishes from the build.
        return value in ("SP", "P", "PO", "PLR") or value.isdigit()

    declared = [r for r in rows if _is_declared(r)]
    basis = "all_healthy"
    if starters_only and declared:
        # Only restrict when the file has actually posted something. A slate where
        # nothing has posted yet leaves Starting blank for everyone, and filtering
        # to an empty pool would be worse than not filtering at all.
        rows = declared
        basis = "declared_starters"
    for rec in rows:
        rec["Pool_Basis"] = basis
        value = str(rec.get("Starting") or "").strip().upper()
        rec["Batting_Order"] = int(value) if value.isdigit() else None
        rec["Is_Declared_Starter"] = value in ("SP", "P", "PO", "PLR")

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Player_Key").reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# MILP: 1 CPT + 5 UTIL, role exclusivity, both teams, salary cap
# --------------------------------------------------------------------------- #
def build_showdown_lineup(
    df: pd.DataFrame,
    contract: RosterContract = SHOWDOWN,
    locks: Optional[Sequence[str]] = None,
    excludes: Optional[Sequence[str]] = None,
    cpt_lock: Optional[str] = None,
    cpt_excludes: Optional[Sequence[str]] = None,
    forbidden_sets: Optional[Sequence[Sequence[str]]] = None,
    time_limit: int = 20,
) -> Optional[Dict[str, Any]]:
    """Solve one legal Showdown lineup maximizing projected points (CPT at 1.5x).
    Returns None if infeasible. Deterministic scipy.milp; a review proxy."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    excl = {str(x) for x in (excludes or [])}
    work = df[~df["Player_Key"].isin(excl)].reset_index(drop=True) if excl else df.reset_index(drop=True)
    n = len(work)
    if n < contract.roster_size:
        return None
    n_util = contract.roster_size - 1  # UTIL count (5)
    cpt_mult = contract.multiplier_for(contract.captain_slot or "CPT")

    keys = work["Player_Key"].tolist()
    key_row = {k: work.iloc[i] for i, k in enumerate(keys)}
    # variables: [cpt_0..cpt_{n-1}, util_0..util_{n-1}]
    n_vars = 2 * n
    def cpt(i): return i
    def util(i): return n + i

    c = np.zeros(n_vars, dtype=float)
    for i in range(n):
        base = float(work.iloc[i]["Base"])
        c[cpt(i)] = -(cpt_mult * base)
        c[util(i)] = -(base)

    rows: List[Dict[int, float]] = []
    lbs: List[float] = []
    ubs: List[float] = []

    def add(coefs: Dict[int, float], lb: float, ub: float):
        rows.append(coefs); lbs.append(lb); ubs.append(ub)

    add({cpt(i): 1.0 for i in range(n)}, 1.0, 1.0)              # exactly one CPT
    add({util(i): 1.0 for i in range(n)}, float(n_util), float(n_util))  # exactly five UTIL
    for i in range(n):                                          # role exclusivity
        add({cpt(i): 1.0, util(i): 1.0}, -np.inf, 1.0)
    salary_coefs = {}
    for i in range(n):
        salary_coefs[cpt(i)] = float(work.iloc[i]["CPT_Salary"])
        salary_coefs[util(i)] = float(work.iloc[i]["UTIL_Salary"])
    add(salary_coefs, -np.inf, float(contract.salary_cap))     # salary cap

    if contract.min_players_per_team > 0:                      # both-teams rule
        for team in sorted(work["Team"].unique()):
            idxs = [i for i in range(n) if work.iloc[i]["Team"] == team]
            add({**{cpt(i): 1.0 for i in idxs}, **{util(i): 1.0 for i in idxs}},
                float(contract.min_players_per_team), np.inf)

    for lk in (locks or []):                                   # lock: selected in some role
        if lk in key_row:
            i = keys.index(lk)
            add({cpt(i): 1.0, util(i): 1.0}, 1.0, np.inf)
    if cpt_lock and cpt_lock in key_row:                       # lock captain
        add({cpt(keys.index(cpt_lock)): 1.0}, 1.0, 1.0)
    for ck in (cpt_excludes or []):                            # exposure cap: still
        if ck in key_row:                                      # eligible at UTIL,
            add({cpt(keys.index(ck)): 1.0}, 0.0, 0.0)           # just not as CPT
    for fs in (forbidden_sets or []):                          # forbid an exact 6-set
        idxs = [keys.index(k) for k in fs if k in key_row]
        if len(idxs) == contract.roster_size:
            add({**{cpt(i): 1.0 for i in idxs}, **{util(i): 1.0 for i in idxs}},
                -np.inf, float(contract.roster_size - 1))

    ri, ci, dv = [], [], []
    for rnum, coefs in enumerate(rows):
        for col, val in coefs.items():
            if val:
                ri.append(rnum); ci.append(col); dv.append(float(val))
    matrix = coo_matrix((dv, (ri, ci)), shape=(len(rows), n_vars)).tocsr()
    res = milp(
        c=c, integrality=np.ones(n_vars, dtype=int),
        bounds=Bounds(np.zeros(n_vars), np.ones(n_vars)),
        constraints=LinearConstraint(matrix, np.array(lbs), np.array(ubs)),
        options={"time_limit": time_limit, "disp": False},
    )
    if not res.success or res.x is None:
        return None
    cpt_i = [i for i in range(n) if res.x[cpt(i)] > 0.5]
    util_i = [i for i in range(n) if res.x[util(i)] > 0.5]
    if len(cpt_i) != 1 or len(util_i) != n_util:
        return None
    return _assemble_lineup(work, cpt_i[0], util_i, cpt_mult, contract)


def _assemble_lineup(work, cpt_i, util_i, cpt_mult, contract) -> Dict[str, Any]:
    def rec(i, role):
        row = work.iloc[i]
        rid = str(row["CPT_ID"]) if role == "CPT" else str(row["UTIL_ID"])
        sal = float(row["CPT_Salary"]) if role == "CPT" else float(row["UTIL_Salary"])
        pts = (cpt_mult if role == "CPT" else 1.0) * float(row["Base"])
        return {"role": role, "player_key": row["Player_Key"], "name": row["Name"],
                "team": row["Team"], "draftable_id": rid, "salary": sal, "points": round(pts, 3)}
    captain = rec(cpt_i, "CPT")
    utils = sorted((rec(i, "UTIL") for i in util_i), key=lambda p: p["draftable_id"])
    players = [captain] + utils
    salary = sum(p["salary"] for p in players)
    return {
        "contract": contract.name,
        "captain": captain,
        "utils": utils,
        "players": players,
        "roster_ids": [captain["draftable_id"]] + [u["draftable_id"] for u in utils],
        "player_keys": [captain["player_key"]] + sorted(u["player_key"] for u in utils),
        "salary": round(salary, 1),
        "salary_cap": contract.salary_cap,
        "proj_points": round(sum(p["points"] for p in players), 3),
        "teams": sorted({p["team"] for p in players}),
        "label": "deterministic review proxy (Base = AvgPointsPerGame); never ROI, win rate, or probability",
    }


def build_showdown_bank(df: pd.DataFrame, n: int, contract: RosterContract = SHOWDOWN,
                        max_cpt_exposure_pct: Optional[float] = DEFAULT_MAX_CPT_EXPOSURE_PCT,
                        diagnostics: Optional[Dict[str, Any]] = None,
                        **kwargs) -> List[Dict[str, Any]]:
    """Up to ``n`` distinct legal lineups, each differing from the prior ones by at
    least one player (exact-set forbidding), with no single captain filling more
    than ``max_cpt_exposure_pct`` of the bank. Pass ``max_cpt_exposure_pct=None``
    to disable the cap (e.g. a caller doing its own explicit cpt_lock rotation).

    Once a captain reaches its share of ``n`` it is excluded from the CPT role
    for the rest of the build -- it can still be rostered at UTIL, just not
    captained again. If that exclusion makes a slot infeasible (a thin pool with
    few legal captains), the cap relaxes for that one slot rather than shrinking
    the bank: an exposure cap is a diversity control, and a diversity control may
    never reduce the legal player set below what is needed to fill the entries
    already in front of it. ``diagnostics``, if passed a dict, is filled in place
    with ``cap_count``, ``captain_exposure`` (player_key -> count), and
    ``relaxed_slots`` so a caller can report or flag when the cap didn't hold.
    """
    bank: List[Dict[str, Any]] = []
    forbidden: List[List[str]] = []
    cpt_counts: Dict[str, int] = {}
    n_target = max(1, int(n))
    # floor, not ceil/round: this is an upper bound, so rounding must never let
    # the allowed count push the realized exposure pct above the requested cap.
    cap = max(1, math.floor(max_cpt_exposure_pct * n_target)) if max_cpt_exposure_pct else None
    relaxed_slots = 0
    for _ in range(n_target):
        cpt_excludes = [k for k, c in cpt_counts.items() if cap is not None and c >= cap] or None
        lu = build_showdown_lineup(df, contract=contract, forbidden_sets=forbidden,
                                   cpt_excludes=cpt_excludes, **kwargs)
        if lu is None and cpt_excludes:
            lu = build_showdown_lineup(df, contract=contract, forbidden_sets=forbidden, **kwargs)
            if lu is not None:
                relaxed_slots += 1
        if lu is None:
            break
        bank.append(lu)
        forbidden.append(lu["player_keys"])
        cpt_key = lu["captain"]["player_key"]
        cpt_counts[cpt_key] = cpt_counts.get(cpt_key, 0) + 1
    if diagnostics is not None:
        diagnostics["max_cpt_exposure_pct"] = max_cpt_exposure_pct
        diagnostics["cap_count"] = cap
        diagnostics["captain_exposure"] = dict(cpt_counts)
        diagnostics["relaxed_slots"] = relaxed_slots
    return bank


# --------------------------------------------------------------------------- #
# Certification: legality of a lineup under the contract (review proxy)
# --------------------------------------------------------------------------- #
def certify_showdown(lineup: Mapping[str, Any], df: pd.DataFrame,
                     contract: RosterContract = SHOWDOWN) -> Dict[str, Any]:
    errors: List[str] = []
    players = list(lineup.get("players") or [])
    caps = [p for p in players if p["role"] == "CPT"]
    utils = [p for p in players if p["role"] == "UTIL"]
    if len(caps) != 1:
        errors.append(f"expected exactly 1 CPT, got {len(caps)}")
    if len(utils) != contract.roster_size - 1:
        errors.append(f"expected {contract.roster_size - 1} UTIL, got {len(utils)}")
    keys = [p["player_key"] for p in players]
    if len(set(keys)) != len(keys):
        errors.append("a player fills more than one roster slot")
    if lineup.get("salary", 0) > contract.salary_cap:
        errors.append(f"salary {lineup.get('salary')} exceeds cap {contract.salary_cap}")
    slate_teams = set(df["Team"].unique()) if not df.empty else set()
    for team in slate_teams:
        if contract.min_players_per_team > 0 and sum(1 for p in players if p["team"] == team) < contract.min_players_per_team:
            errors.append(f"team {team} under-represented (need >= {contract.min_players_per_team})")
    # role-correct draftable ids
    by_key = {r["Player_Key"]: r for _, r in df.iterrows()} if not df.empty else {}
    for p in players:
        src = by_key.get(p["player_key"])
        if src is None:
            errors.append(f"{p['player_key']} not in the pool")
            continue
        want = str(src["CPT_ID"]) if p["role"] == "CPT" else str(src["UTIL_ID"])
        if str(p["draftable_id"]) != want:
            errors.append(f"{p['player_key']} {p['role']} uses id {p['draftable_id']}, expected {want}")
    return {"passed": not errors, "errors": errors,
            "checks": {"roster_size": len(players), "salary": lineup.get("salary"),
                       "teams": lineup.get("teams")}}


# --------------------------------------------------------------------------- #
# DKEntries Showdown template read/write (6-slot geometry, Classic untouched)
# --------------------------------------------------------------------------- #
def read_showdown_reserved_rows(path: str | Path, contract: RosterContract = SHOWDOWN) -> Dict[str, Any]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise ValueError("empty DKEntries file")
    header = rows[0]
    if [c.strip() for c in header[:4]] != ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]:
        raise ValueError("DKEntries header must start with Entry ID, Contest Name, Contest ID, Entry Fee")
    start, end = contract.entry_roster_start_col, contract.roster_end_col_exclusive
    if [c.strip().upper() for c in header[start:end]] != [s.upper() for s in contract.slots]:
        raise ValueError(f"not a {contract.name} template; header slots are {header[start:end]}")
    reserved = []
    for i, row in enumerate(rows[1:], start=2):
        eid, cid = (row[0].strip() if len(row) > 0 else ""), (row[2].strip() if len(row) > 2 else "")
        if not re.fullmatch(r"\d+", eid) or not re.fullmatch(r"\d+", cid):
            continue
        cells = [(_digits(row[c]) if c < len(row) else "") for c in range(start, end)]
        reserved.append({
            "row_index": i, "entry_id": eid, "contest_id": cid,
            "contest_name": row[1].strip() if len(row) > 1 else "",
            "cells": cells, "is_blank": not any(cells), "is_complete": all(cells),
        })
    return {"header": header, "rows": rows, "reserved": reserved}


def write_showdown_entries(template_path: str | Path, candidate_path: str | Path,
                           assignments: Sequence[Mapping[str, Any]],
                           contract: RosterContract = SHOWDOWN) -> Dict[str, Any]:
    """Fill blank reserved rows with roster_ids ([CPT_ID, 5x UTIL_ID]); preserve every
    other cell. Never overwrites the template."""
    source, target = Path(template_path).resolve(), Path(candidate_path).resolve()
    if source == target:
        raise ValueError("candidate_path must differ from template_path")
    parsed = read_showdown_reserved_rows(source, contract)
    rows = parsed["rows"]
    by_entry = {r["entry_id"]: r for r in parsed["reserved"]}
    start, end = contract.entry_roster_start_col, contract.roster_end_col_exclusive
    errors: List[str] = []
    logs: List[Dict[str, Any]] = []
    used = set()
    for a in assignments:
        eid = str(a.get("entry_id") or "").strip()
        ids = [str(x) for x in (a.get("roster_ids") or [])]
        if eid not in by_entry:
            errors.append(f"entry id not found: {eid}"); continue
        if eid in used:
            errors.append(f"duplicate assignment for {eid}"); continue
        if len(ids) != contract.roster_size or not all(ids):
            errors.append(f"{eid}: need {contract.roster_size} roster ids"); continue
        r = by_entry[eid]
        if r["is_complete"]:
            errors.append(f"{eid} already complete and immutable"); continue
        raw = rows[r["row_index"] - 1]
        while len(raw) < end:
            raw.append("")
        raw[start:end] = ids
        used.add(eid)
        logs.append({"entry_id": eid, "contest_id": r["contest_id"], "roster_ids": ids})
    if errors:
        return {"passed": False, "errors": errors, "candidate_path": None, "assignment_log": logs}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return {"passed": True, "errors": [], "candidate_path": str(target), "assignment_log": logs}


def verify_template_preserved(source_path: str | Path, candidate_path: str | Path,
                              contract: RosterContract = SHOWDOWN) -> Dict[str, Any]:
    with Path(source_path).open(newline="", encoding="utf-8-sig") as fh:
        src = list(csv.reader(fh))
    with Path(candidate_path).open(newline="", encoding="utf-8-sig") as fh:
        cand = list(csv.reader(fh))
    errors: List[str] = []
    if len(src) != len(cand):
        return {"passed": False, "errors": ["row count changed"]}
    start, end = contract.entry_roster_start_col, contract.roster_end_col_exclusive
    for i, (s, c) in enumerate(zip(src, cand), start=1):
        w = max(len(s), len(c))
        s = s + [""] * (w - len(s)); c = c + [""] * (w - len(c))
        for col in list(range(0, start)) + list(range(end, w)):
            if s[col] != c[col]:
                errors.append(f"non-roster cell changed at row {i}, col {col + 1}")
    return {"passed": not errors, "errors": errors}
