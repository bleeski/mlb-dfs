"""xwOBA Base-correction join for MLB Classic (build-time wiring, not an engine file).

The checksummed projection_builder.py already carries the xwOBA math
(load_savant_expected_stats, build_xwoba_corrections, apply_xwoba_correction).
The only missing piece is that build_xwoba_corrections returns a map keyed by the
Savant MLBAM player_id, while apply_xwoba_correction looks corrections up by the
slate's DraftKings Player_ID. Those two id systems never match directly.

This module bridges them: it name-matches each DraftKings player to a Savant row
(batter file for hitters, pitcher file for pitchers, role-correct ratio direction
already baked in by build_xwoba_corrections) and returns corrections re-keyed by
DraftKings Player_ID, ready to hand straight to apply_xwoba_correction.

DraftKings draftable ids change every slate, so this runs per slate against that
night's DKSalaries, exactly like loading the two Savant CSVs. The durable, reusable
piece is this matcher; the per-slate input is the salary file. Nothing here writes
to a checksummed engine file, claims profitability, or touches the MILP.

v1.1 adds build_dk_keyed_ceiling_multipliers, which re-keys the per-player
expected-ISO Ceiling multipliers (projection_builder.build_xiso_ceiling_multipliers)
onto DraftKings ids through the same name matcher, so the ceiling join can never
drift from the xwOBA join.

v1.2 adds build_dk_keyed_pitcher_ceiling_multipliers, which re-keys the
per-pitcher K-rate Ceiling multipliers
(projection_builder.build_k_rate_ceiling_multipliers, FanGraphs season pitching
CSV) onto DraftKings ids through the same name normalizer, pitchers only, with
the same collision discipline (higher batters-faced row wins and the collision
is reported). Deterministic labeled prior, never a probability claim.
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

# projection_builder is the source of truth for the xwOBA math.
from mlb_engine.projections import projection_builder as pb


VERSION = "v1.2"

PITCHER_POSITION_TOKENS = {"P", "SP", "RP"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm_name(value: str) -> str:
    """Normalize a name to 'first last' lowercase ascii, suffix-stripped."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace(".", " ").replace("'", "").replace("-", " ")
    tokens = [t for t in re.split(r"[\s,]+", text) if t and t not in SUFFIXES]
    return " ".join(tokens)


def _savant_name_key(last_comma_first: str) -> str:
    """'Wood, James' -> 'james wood'. Falls back to as-is normalization."""
    raw = str(last_comma_first or "")
    if "," in raw:
        last, first = raw.split(",", 1)
        return _norm_name(f"{first} {last}")
    return _norm_name(raw)


def _build_name_to_mlbam(table, corrections: Mapping[str, float]) -> Tuple[Dict[str, str], Dict[str, int]]:
    """Map only unambiguous names; a PA ranking cannot establish identity."""
    best_pa: Dict[str, float] = {}
    name_to_id: Dict[str, str] = {}
    collisions: Dict[str, int] = {}
    for _, row in table.iterrows():
        pid = str(row["player_id"]).strip()
        if pid not in corrections:
            continue
        key = _savant_name_key(row["last_name, first_name"]) if "last_name, first_name" in table.columns else ""
        if not key:
            continue
        pa = float(row.get("pa") or 0.0)
        if key in name_to_id and name_to_id[key] != pid:
            collisions[key] = collisions.get(key, 1) + 1
            if pa <= best_pa.get(key, -1.0):
                continue
        best_pa[key] = pa
        name_to_id[key] = pid
    return {key: pid for key, pid in name_to_id.items() if key not in collisions}, collisions


def _read_salary_pool(salary_csv: str | Path) -> List[Dict[str, str]]:
    with open(salary_csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append({
            "id": str(r.get("ID") or "").strip(),
            "name": str(r.get("Name") or "").strip(),
            "pos": str(r.get("Position") or "").strip().upper(),
            "team": str(r.get("TeamAbbrev") or "").strip().upper(),
        })
    return out


def build_dk_keyed_corrections(
    salary_csv: str | Path,
    batting_csv: Optional[str | Path] = None,
    pitching_csv: Optional[str | Path] = None,
    restrict_ids: Optional[set] = None,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Return ({DK_Player_ID: Base multiplier}, match_report).

    A player is matched in the batter file if their DK Position has no pitcher
    token, otherwise in the pitcher file. Either CSV may be None; players whose
    role has no file supplied fall back to a 1.0 neutral multiplier. restrict_ids
    optionally limits the report/return to a set of DK ids (e.g. the eligible
    pool) but the matcher runs over the whole salary pool regardless.
    """
    bat_corr: Dict[str, float] = {}
    bat_name: Dict[str, str] = {}
    bat_coll: Dict[str, int] = {}
    if batting_csv:
        _bat = pb.load_savant_expected_stats(batting_csv)
        bat_corr = pb.build_xwoba_corrections(_bat, "batter")     # MLBAM -> mult
        bat_name, bat_coll = _build_name_to_mlbam(_bat, bat_corr)

    pit_corr: Dict[str, float] = {}
    pit_name: Dict[str, str] = {}
    pit_coll: Dict[str, int] = {}
    if pitching_csv:
        _pit = pb.load_savant_expected_stats(pitching_csv)
        pit_corr = pb.build_xwoba_corrections(_pit, "pitcher")    # MLBAM -> mult
        pit_name, pit_coll = _build_name_to_mlbam(_pit, pit_corr)

    pool = _read_salary_pool(salary_csv)
    dk_corr: Dict[str, float] = {}
    matched, unmatched = [], []
    for p in pool:
        if restrict_ids is not None and p["id"] not in restrict_ids:
            continue
        is_pitcher = bool({t for t in re.split(r"[/]", p["pos"]) if t} & PITCHER_POSITION_TOKENS)
        key = _norm_name(p["name"])
        name_map = pit_name if is_pitcher else bat_name
        corr_map = pit_corr if is_pitcher else bat_corr
        mlbam = name_map.get(key)
        if mlbam is None:
            unmatched.append({"id": p["id"], "name": p["name"], "team": p["team"], "role": "P" if is_pitcher else "H"})
            continue
        mult = float(corr_map.get(mlbam, 1.0))
        dk_corr[p["id"]] = mult
        matched.append({"id": p["id"], "name": p["name"], "team": p["team"],
                        "role": "P" if is_pitcher else "H", "mlbam": mlbam, "mult": mult})

    considered = len(matched) + len(unmatched)
    report = {
        "considered": considered,
        "matched": len(matched),
        "unmatched": len(unmatched),
        "match_rate": (len(matched) / considered) if considered else 0.0,
        "neutral_1p0": sum(1 for m in matched if abs(m["mult"] - 1.0) < 1e-9),
        "name_collisions_batter": {k: v for k, v in bat_coll.items()},
        "name_collisions_pitcher": {k: v for k, v in pit_coll.items()},
        "matched_rows": matched,
        "unmatched_rows": unmatched,
    }
    return dk_corr, report


def build_dk_keyed_ceiling_multipliers(
    salary_csv: str | Path,
    batting_csv: str | Path,
    restrict_ids: Optional[set] = None,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Return ({DK_Player_ID: Ceiling multiplier}, match_report) for hitters.

    Reads the Savant batting expected-stats CSV, builds per-player Ceiling
    multipliers from the expected-ISO proxy
    (projection_builder.build_xiso_ceiling_multipliers), and re-keys them onto
    DraftKings ids through the same name matcher as the xwOBA join. Pitchers
    are skipped on purpose: they take the uniform neutral downstream (see the
    projection_builder v1.3 rationale). Unmatched or sub-floor hitters fall
    back to the neutral multiplier downstream because they are simply absent
    from the returned map. Deterministic prior, never a probability claim.
    """
    table = pb.load_savant_expected_stats(batting_csv)
    mults = pb.build_xiso_ceiling_multipliers(table)
    name_map, collisions = _build_name_to_mlbam(table, mults)

    pool = _read_salary_pool(salary_csv)
    dk_mults: Dict[str, float] = {}
    matched, unmatched = [], []
    for p in pool:
        if restrict_ids is not None and p["id"] not in restrict_ids:
            continue
        is_pitcher = bool({t for t in re.split(r"[/]", p["pos"]) if t} & PITCHER_POSITION_TOKENS)
        if is_pitcher:
            continue
        mlbam = name_map.get(_norm_name(p["name"]))
        if mlbam is None:
            unmatched.append({"id": p["id"], "name": p["name"], "team": p["team"]})
            continue
        mult = float(mults.get(mlbam, pb.XISO_CEILING_NEUTRAL))
        dk_mults[p["id"]] = mult
        matched.append({"id": p["id"], "name": p["name"], "team": p["team"], "mlbam": mlbam, "mult": mult})

    considered = len(matched) + len(unmatched)
    report = {
        "considered_hitters": considered,
        "matched": len(matched),
        "unmatched": len(unmatched),
        "match_rate": (len(matched) / considered) if considered else 0.0,
        "neutral": sum(1 for m in matched if abs(m["mult"] - pb.XISO_CEILING_NEUTRAL) < 1e-9),
        "name_collisions": {k: v for k, v in collisions.items()},
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "note": "Per-player Ceiling multipliers from expected ISO; deterministic prior, never a probability claim.",
    }
    return dk_mults, report


def build_dk_keyed_pitcher_ceiling_multipliers(
    salary_csv: str | Path,
    fangraphs_pitching_csv: str | Path,
    restrict_ids: Optional[set] = None,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Return ({DK_Player_ID: Ceiling multiplier}, match_report) for pitchers.

    Reads a FanGraphs season pitching CSV, builds per-pitcher Ceiling
    multipliers from the K-rate input
    (projection_builder.build_k_rate_ceiling_multipliers), and re-keys them
    onto DraftKings ids through the same name normalizer as the xwOBA and
    xISO joins. Hitters are skipped on purpose: their ceilings come from the
    xISO block. On a normalized-name collision inside the FanGraphs table the
    higher batters-faced row wins and the collision is reported, mirroring the
    Savant matcher. Unmatched, non-starter, or sub-floor pitchers fall back to
    the neutral multiplier downstream because they are simply absent from the
    returned map. Deterministic labeled prior, never a probability claim.
    """
    table = pb.load_fangraphs_pitching(fangraphs_pitching_csv)
    mults = pb.build_k_rate_ceiling_multipliers(table)
    rate_col = pb.k_rate_column(table)

    # Normalized-name index with collision handling: higher batters-faced wins.
    if "TBF" in table.columns:
        tbf = pd.to_numeric(table["TBF"], errors="coerce")
    else:
        ip = pd.to_numeric(table["IP"], errors="coerce") if "IP" in table.columns else None
        tbf = ip * pb.K_RATE_TBF_PER_IP if ip is not None else None
    weight_by_name: Dict[str, float] = {}
    if tbf is not None:
        for name, w in zip(table["Name"].astype(str).str.strip(), tbf):
            try:
                weight_by_name[name] = max(weight_by_name.get(name, 0.0), float(w))
            except (TypeError, ValueError):
                weight_by_name.setdefault(name, 0.0)
    name_map: Dict[str, str] = {}
    weights: Dict[str, float] = {}
    collisions: Dict[str, int] = {}
    for raw_name in mults:
        key = _norm_name(raw_name)
        if not key:
            continue
        w = weight_by_name.get(raw_name, 0.0)
        if key in name_map:
            collisions[key] = collisions.get(key, 1) + 1
            if w <= weights.get(key, 0.0):
                continue
        name_map[key] = raw_name
        weights[key] = w

    pool = _read_salary_pool(salary_csv)
    dk_mults: Dict[str, float] = {}
    matched, unmatched = [], []
    for p in pool:
        if restrict_ids is not None and p["id"] not in restrict_ids:
            continue
        is_pitcher = bool({t for t in re.split(r"[/]", p["pos"]) if t} & PITCHER_POSITION_TOKENS)
        if not is_pitcher:
            continue
        raw_name = name_map.get(_norm_name(p["name"]))
        if raw_name is None:
            unmatched.append({"id": p["id"], "name": p["name"], "team": p["team"]})
            continue
        mult = float(mults.get(raw_name, pb.XISO_CEILING_NEUTRAL))
        dk_mults[p["id"]] = mult
        matched.append({"id": p["id"], "name": p["name"], "team": p["team"],
                        "fg_name": raw_name, "mult": mult})

    considered = len(matched) + len(unmatched)
    report = {
        "considered_pitchers": considered,
        "matched": len(matched),
        "unmatched": len(unmatched),
        "match_rate": (len(matched) / considered) if considered else 0.0,
        "neutral": sum(1 for m in matched if abs(m["mult"] - pb.XISO_CEILING_NEUTRAL) < 1e-9),
        "rate_column": rate_col,
        "name_collisions": {k: v for k, v in collisions.items()},
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "note": "Per-pitcher Ceiling multipliers from a FanGraphs K-rate input; "
                "deterministic prior, never a probability claim.",
    }
    return dk_mults, report


if __name__ == "__main__":
    # quick CLI: python xwoba_base_correction.py DKSalaries.csv batting.csv pitching.csv
    sal, bcsv, pcsv = sys.argv[1], sys.argv[2], sys.argv[3]
    corr, rep = build_dk_keyed_corrections(sal, batting_csv=bcsv, pitching_csv=pcsv)
    print(f"considered={rep['considered']} matched={rep['matched']} "
          f"unmatched={rep['unmatched']} match_rate={rep['match_rate']:.1%} "
          f"neutral(=1.0)={rep['neutral_1p0']}")
