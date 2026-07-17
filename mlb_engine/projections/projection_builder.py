"""Shared MLB Classic projection builder v1.4.

MLB Classic v2.24.0.

All projections use exactly ``Base × F1 × F2 × F3 × F4 × F5``. The builder
supports provider projections and a clearly labelled emergency proxy. The proxy
Base may be optionally corrected for park and contact luck with Statcast
expected stats (xwOBA) before the factors are applied; see the xwOBA section
below. Confirmed
lineup refreshes use the same F2 logic and emit an auditable delta report.

v1.3 adds two deterministic, opt-in capabilities, both labeled priors or review
inputs and never ROI, win-rate, or probability claims:

- Per-player Ceiling multipliers from an expected-ISO proxy
  (``build_xiso_ceiling_multipliers``), consumed by ``build_projections``
  through an optional per-row ``Ceiling_Multiplier`` column. Uniform 1.42 stays
  the neutral default; the column only differentiates hitters matched to a
  Savant expected-stats row at or above the PA floor.
- A deterministic F4 (matchup quality) for hitters
  (``compute_f4_factors``): opposing-SP contact quality from Savant
  xwOBA-against times a platoon-hand prior. Pitcher F4 stays 1.0 in this
  version; the opposing-lineup aggregation is deliberately out of scope until
  a team-level opposing-lineup input (K% and wOBA vs hand) exists.

v1.4 closes the pitcher half of the ceiling gap: per-pitcher Ceiling
multipliers from a K-rate input (``build_k_rate_ceiling_multipliers``), read
from a FanGraphs season pitching CSV (``load_fangraphs_pitching``). Same
percentile/shrink/clip discipline as the hitter xISO block, same neutral, same
per-row ``Ceiling_Multiplier`` consumption path. K rate is the pitcher
right-tail shape signal (DK pitcher scoring is strikeout-heavy) and is
deliberately distinct from the xwOBA-against contact signal the Base
correction already carries, which is exactly why re-ranking pitcher ceilings
by xwOBA-against was rejected as rank-redundant in v1.3. Deterministic labeled
prior, never a win-rate, ROI, or probability claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import pandas as pd

VERSION = "v1.4"
MODES = {"provider_projection", "emergency_proxy"}
FACTOR_COLUMNS = ("F1", "F2", "F3", "F4", "F5")
CORE_COLUMNS = (
    "Player_ID", "Name", "Team", "Opponent", "Position", "Salary", "Game_ID",
    "Floor", "Ceiling", "Excluded", "Locked",
)


def batting_order_factor(slot: Optional[int]) -> float:
    if slot is None:
        return 1.0
    mapping = {1: 1.10, 2: 1.08, 3: 1.07, 4: 1.06, 5: 1.03, 6: 1.00, 7: 0.97, 8: 0.94, 9: 0.91}
    return mapping.get(int(slot), 1.0)


def _as_dataframe(rows: Any) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows.copy()
    return pd.DataFrame(list(rows))


def validate_projection_factors(frame: pd.DataFrame) -> Dict[str, Any]:
    required = {"Player_ID", "Name", "Team", "Opponent", "Position", "Salary", "Game_ID", "Base", *FACTOR_COLUMNS}
    missing = sorted(required - set(frame.columns))
    errors = []
    if not missing:
        for column in ("Base", *FACTOR_COLUMNS):
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.isna().any():
                errors.append(f"{column} contains nonnumeric values")
            if (values < 0).any():
                errors.append(f"{column} contains negative values")
    return {"passed": not missing and not errors, "missing_fields": missing, "errors": errors}


def build_projections(
    rows: Any,
    mode: str,
    floor_multiplier: float = 0.58,
    ceiling_multiplier: float = 1.42,
    source_metadata: Optional[Mapping[str, Any]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build projections and a factor-level audit table."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    frame = _as_dataframe(rows)
    validation = validate_projection_factors(frame)
    if not validation["passed"]:
        raise ValueError(f"projection factors invalid: {validation}")
    for column in ("Base", *FACTOR_COLUMNS):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    resolved = frame["Base"]
    for column in FACTOR_COLUMNS:
        resolved = resolved * frame[column]
    frame["Base_Projection"] = resolved
    if "Floor" not in frame.columns:
        frame["Floor"] = resolved * float(floor_multiplier)
    if "Ceiling" not in frame.columns:
        if "Ceiling_Multiplier" in frame.columns:
            # Per-player ceiling protocol (v1.3): a row-level multiplier, built by
            # build_xiso_ceiling_multipliers and joined upstream, differentiates
            # right-tail outcomes. Rows without a value fall back to the uniform
            # default so the column is strictly additive. The Ceiling >= Floor
            # hard error below still governs; nothing is silently repaired.
            per_row = pd.to_numeric(frame["Ceiling_Multiplier"], errors="coerce")
            per_row = per_row.fillna(float(ceiling_multiplier)).astype(float)
            frame["Ceiling_Multiplier"] = per_row
            frame["Ceiling"] = resolved * per_row
        else:
            frame["Ceiling"] = resolved * float(ceiling_multiplier)
    frame["Floor"] = pd.to_numeric(frame["Floor"], errors="raise").clip(lower=0)
    frame["Ceiling"] = pd.to_numeric(frame["Ceiling"], errors="raise")
    bad = frame["Ceiling"] < frame["Floor"] - 1e-9
    if bool(bad.any()):
        offenders = frame.loc[bad, "Player_ID"].astype(str).tolist()[:10]
        raise ValueError(
            f"Ceiling below Floor for Player_ID(s) {offenders}; "
            "the projection contract requires Ceiling >= Floor and bad rows are not silently repaired"
        )
    if "Excluded" not in frame.columns:
        frame["Excluded"] = False
    if "Locked" not in frame.columns:
        frame["Locked"] = False
    frame["Projection_Mode"] = mode
    frame["Projection_Quality"] = "provider" if mode == "provider_projection" else "emergency_proxy"
    metadata = dict(source_metadata or {})
    frame["Projection_Source"] = str(metadata.get("source") or mode)
    frame["Projection_Source_Timestamp"] = str(metadata.get("timestamp") or "")
    frame["Projection_Formula"] = "Base*F1*F2*F3*F4*F5"
    if "Notes" not in frame.columns:
        frame["Notes"] = ""

    projection_columns = list(CORE_COLUMNS) + [
        "Base_Projection", "Base", *FACTOR_COLUMNS, "Projection_Mode",
        "Projection_Quality", "Projection_Source", "Projection_Source_Timestamp",
        "Projection_Formula", "Notes",
    ]
    optional = [column for column in frame.columns if column not in projection_columns]
    projections = frame[projection_columns + optional].copy()
    audit = frame[[
        "Player_ID", "Name", "Team", "Base", *FACTOR_COLUMNS,
        "Base_Projection", "Floor", "Ceiling", "Projection_Mode",
        "Projection_Source", "Projection_Source_Timestamp",
    ]].copy()
    return projections, audit


def refresh_confirmed_lineups(
    projections: pd.DataFrame,
    confirmed_order_by_player_id: Mapping[str, int],
    starter_player_ids: Optional[Iterable[str]] = None,
    confirmed_teams: Optional[Iterable[str]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Refresh F2 and exclusion status using the shared projection formula.

    ``confirmed_teams`` restricts the starter exclusion to teams whose lineup is
    actually confirmed. Hitters on teams not listed keep their current exclusion
    state, so TBD teams may continue using projected lineups (spec section 4).
    When ``confirmed_teams`` is None the legacy global behavior is preserved.
    """
    frame = projections.copy()
    required = {"Player_ID", "Base", *FACTOR_COLUMNS, "Floor", "Ceiling"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"projection frame missing shared-factor fields: {sorted(missing)}")
    starter_set = {str(x) for x in starter_player_ids} if starter_player_ids is not None else None
    confirmed_team_set = {str(t).strip().upper() for t in confirmed_teams} if confirmed_teams is not None else None
    rows = []
    for index, row in frame.iterrows():
        pid = str(row["Player_ID"])
        old_f2 = float(row["F2"])
        old_floor = float(row["Floor"])
        old_ceiling = float(row["Ceiling"])
        old_order = row.get("Batting_Order")
        new_order = confirmed_order_by_player_id.get(pid)
        changed = False
        if new_order is not None:
            new_f2 = batting_order_factor(new_order)
            frame.at[index, "F2"] = new_f2
            frame.at[index, "Batting_Order"] = int(new_order)
            changed = abs(new_f2 - old_f2) > 1e-12 or old_order != new_order
        team_is_confirmed = confirmed_team_set is None or str(row.get("Team", "")).strip().upper() in confirmed_team_set
        if starter_set is not None and team_is_confirmed and "P" not in str(row.get("Position", "")).split("/"):
            excluded = pid not in starter_set
            if bool(frame.at[index, "Excluded"]) != excluded:
                changed = True
            frame.at[index, "Excluded"] = excluded
        resolved = float(frame.at[index, "Base"])
        for factor in FACTOR_COLUMNS:
            resolved *= float(frame.at[index, factor])
        old_base_projection = float(row.get("Base_Projection", resolved))
        floor_ratio = old_floor / old_base_projection if old_base_projection else 0.58
        ceiling_ratio = old_ceiling / old_base_projection if old_base_projection else 1.42
        frame.at[index, "Base_Projection"] = resolved
        frame.at[index, "Floor"] = max(0.0, resolved * floor_ratio)
        frame.at[index, "Ceiling"] = max(frame.at[index, "Floor"], resolved * ceiling_ratio)
        if changed:
            rows.append({
                "Player_ID": pid,
                "Name": row.get("Name", ""),
                "old_batting_order": old_order,
                "new_batting_order": new_order,
                "old_F2": old_f2,
                "new_F2": float(frame.at[index, "F2"]),
                "old_ceiling": old_ceiling,
                "new_ceiling": float(frame.at[index, "Ceiling"]),
                "ceiling_delta_pct": 100.0 * (float(frame.at[index, "Ceiling"]) - old_ceiling) / old_ceiling if old_ceiling else None,
                "excluded": bool(frame.at[index, "Excluded"]),
            })
    return frame, pd.DataFrame(rows)


# --- xwOBA baseline correction (v1.2) --------------------------------------
# Optional, context-neutral correction applied to the proxy Base (typically
# DraftKings AvgPointsPerGame) BEFORE F1..F5. It strips park and contact luck
# using Baseball Savant expected stats so the Base reflects skill at contact,
# not the park a player's points happened to be earned in. Batter ratio is
# est_woba / woba; pitcher ratio is woba / est_woba, inverted because a low
# wOBA-against is good for a pitcher. It is a deterministic review input, never
# a profitability or win-rate claim, and because it is applied before F1/F5 it
# does not double count the implied total (F1) or tonight's park (F5).

XWOBA_REQUIRED_COLUMNS = ("player_id", "pa", "woba", "est_woba")
XWOBA_PA_FULL = 100          # PA at or above which the full correction applies
XWOBA_PA_MIN = 50            # below this, no correction (raw Base is used)
XWOBA_BATTER_CLIP = (0.85, 1.15)
XWOBA_PITCHER_CLIP = (0.90, 1.10)
XWOBA_ROLES = {"batter", "pitcher"}


def load_savant_expected_stats(path: str | Path) -> pd.DataFrame:
    """Load a Baseball Savant Expected Statistics CSV (batter or pitcher).

    Handles the UTF-8 BOM Savant ships and coerces the four consumed columns.
    Extra Savant columns (est_ba, est_slg, era, xera, diffs, name) ride along
    unused. player_id is normalized to string to match salary-row ids.
    """
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame.columns = [str(c).strip().strip('"') for c in frame.columns]
    missing = [c for c in XWOBA_REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(
            f"expected-stats CSV missing columns {missing}; got {list(frame.columns)}"
        )
    frame["player_id"] = frame["player_id"].astype(str).str.strip()
    for column in ("pa", "woba", "est_woba"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _shrink_and_clip(ratio: float, pa: float, clip: Tuple[float, float], pa_full: int, pa_min: int) -> float:
    if pa < pa_min:
        return 1.0
    weight = 1.0 if pa >= pa_full else (pa - pa_min) / float(pa_full - pa_min)
    adjusted = 1.0 + (ratio - 1.0) * weight
    low, high = clip
    return float(min(high, max(low, adjusted)))


def build_xwoba_corrections(
    table: pd.DataFrame,
    role: str,
    pa_full: int = XWOBA_PA_FULL,
    pa_min: int = XWOBA_PA_MIN,
    clip: Optional[Tuple[float, float]] = None,
) -> Dict[str, float]:
    """Map player_id -> context-neutral Base multiplier from expected stats.

    Sub-floor PA, zero, or missing wOBA yields 1.0 so the raw Base is used
    unchanged. Between pa_min and pa_full the correction is shrunk linearly
    toward 1.0 by sample weight, then clipped to the role band.
    """
    if role not in XWOBA_ROLES:
        raise ValueError(f"role must be one of {sorted(XWOBA_ROLES)}")
    if clip is None:
        clip = XWOBA_BATTER_CLIP if role == "batter" else XWOBA_PITCHER_CLIP
    corrections: Dict[str, float] = {}
    for _, row in table.iterrows():
        pid = str(row["player_id"]).strip()
        woba = row.get("woba")
        est = row.get("est_woba")
        pa = row.get("pa")
        if pd.isna(woba) or pd.isna(est) or pd.isna(pa) or float(woba) <= 0 or float(est) <= 0:
            corrections[pid] = 1.0
            continue
        ratio = (float(est) / float(woba)) if role == "batter" else (float(woba) / float(est))
        corrections[pid] = _shrink_and_clip(ratio, float(pa), clip, pa_full, pa_min)
    return corrections


def apply_xwoba_correction(
    rows: Any,
    corrections: Mapping[str, float],
    base_in: str = "AvgPointsPerGame",
    base_out: str = "Base",
    default: float = 1.0,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Set ``base_out = base_in * correction`` and return (rows, audit).

    Players absent from ``corrections`` take ``default`` (1.0), i.e. the raw
    Base is used. That is the fallback when no expected-stats row exists, such
    as early-season call-ups or sub-floor PA. Merge the batter and pitcher
    correction maps (``{**batter, **pitcher}``) before calling; the role-correct
    ratio direction is already baked into each map.
    """
    frame = _as_dataframe(rows)
    if base_in not in frame.columns:
        raise ValueError(f"rows missing baseline column '{base_in}'")
    ids = frame["Player_ID"].astype(str).str.strip() if "Player_ID" in frame.columns else pd.Series([""] * len(frame))
    raw = pd.to_numeric(frame[base_in], errors="raise").astype(float)
    factor = ids.map(lambda p: float(corrections.get(p, default)))
    frame[base_out] = (raw.to_numpy() * factor.to_numpy()).clip(min=0)
    audit = pd.DataFrame({
        "Player_ID": frame["Player_ID"] if "Player_ID" in frame.columns else ids,
        "Name": frame["Name"] if "Name" in frame.columns else "",
        "raw_base": raw.to_numpy(),
        "xwoba_correction": factor.to_numpy(),
        "corrected_base": frame[base_out].to_numpy(),
        "matched": ids.isin(set(corrections.keys())).to_numpy(),
    })
    return frame, audit


# --- Per-player ceiling multipliers from expected ISO (v1.3) ----------------
# Uniform Floor/Ceiling multipliers make ceiling-maximization rank-identical to
# mean-maximization, so the GPP "ceiling" objective carried no player-specific
# variance information. This block differentiates hitter ceilings using an
# expected-ISO proxy (est_slg - est_ba) from the same Savant expected-stats CSV
# the xwOBA correction reads. It is a deterministic prior on right-tail shape,
# never an ROI, win-rate, or probability claim. Pitchers stay at the uniform
# neutral: the pitching CSV carries no K-rate input, and re-ranking pitcher
# ceilings by the same xwOBA-against signal the Base correction already uses
# would be rank-redundant, which is the exact flaw this block removes for
# hitters. Floors stay uniform on purpose; the GPP objective consumes Ceiling.

XISO_CEILING_NEUTRAL = 1.42          # matches the build_projections default
XISO_CEILING_SPAN = 0.30             # total multiplier span across the xISO percentile range
XISO_CEILING_CLIP = (1.25, 1.60)     # hard band; always above the 0.58 floor multiplier
XISO_REQUIRED_COLUMNS = ("player_id", "pa", "est_ba", "est_slg")


def build_xiso_ceiling_multipliers(
    batting_table: pd.DataFrame,
    neutral: float = XISO_CEILING_NEUTRAL,
    span: float = XISO_CEILING_SPAN,
    clip: Tuple[float, float] = XISO_CEILING_CLIP,
    pa_full: int = XWOBA_PA_FULL,
    pa_min: int = XWOBA_PA_MIN,
) -> Dict[str, float]:
    """Map MLBAM player_id -> per-player Ceiling multiplier from expected ISO.

    xISO = est_slg - est_ba, the luck-stripped power proxy. Multiplier is
    ``neutral + (percentile - 0.5) * span`` where the percentile ranks the
    player's xISO within the qualified rows of the supplied table (pa >= pa_min
    with valid est_slg/est_ba), so the league context, not the slate, defines
    power. Below pa_min the multiplier is neutral; between pa_min and pa_full it
    shrinks linearly toward neutral, mirroring the xwOBA sample discipline. The
    result is clipped to ``clip``. Missing est columns raise so a truncated CSV
    cannot silently neutralize the feature.
    """
    missing = [c for c in XISO_REQUIRED_COLUMNS if c not in batting_table.columns]
    if missing:
        raise ValueError(f"batting table missing columns {missing} required for xISO ceilings")
    table = batting_table.copy()
    table["player_id"] = table["player_id"].astype(str).str.strip()
    for column in ("pa", "est_ba", "est_slg"):
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["_xiso"] = table["est_slg"] - table["est_ba"]
    qualified = table[(table["pa"] >= pa_min) & table["_xiso"].notna()].copy()
    multipliers: Dict[str, float] = {pid: float(neutral) for pid in table["player_id"]}
    if qualified.empty:
        return multipliers
    qualified["_pct"] = qualified["_xiso"].rank(pct=True, method="average")
    low, high = clip
    for _, row in qualified.iterrows():
        raw = float(neutral) + (float(row["_pct"]) - 0.5) * float(span)
        pa = float(row["pa"])
        weight = 1.0 if pa >= pa_full else (pa - pa_min) / float(pa_full - pa_min)
        adjusted = float(neutral) + (raw - float(neutral)) * weight
        multipliers[str(row["player_id"])] = float(min(high, max(low, adjusted)))
    return multipliers


# --- Per-pitcher ceiling multipliers from a K-rate input (v1.4) -------------
# The v1.3 block above deliberately left pitchers at the uniform neutral: the
# Savant expected-stats CSV carries no K-rate input, and re-ranking pitcher
# ceilings by the same xwOBA-against signal the Base correction already uses
# would be rank-redundant. This block closes that gap from a FanGraphs season
# pitching CSV (a per-slate data input on the same footing as the Savant CSVs,
# never checksummed). K rate is the pitcher right-tail shape signal: DK pitcher
# scoring is strikeout-heavy, so a high-whiff arm's best games clear a
# low-whiff arm's best games even at identical contact quality. K% is preferred
# when the export carries it; K/9 is the accepted fallback (slightly flattered
# for pitchers who allow more baserunners, which the percentile rank and the
# clip absorb). The percentile universe is starter rows only (GS >= 1 when a GS
# column exists) because reliever K rates run structurally higher and would
# depress every starter's percentile; a GS == 0 arm simply takes the neutral.
# Sample weight is batters faced: a real TBF column when present, else
# IP x K_RATE_TBF_PER_IP, shrunk under the shared 50/100 discipline. Floors
# stay uniform on purpose; the GPP objective consumes Ceiling. Deterministic
# labeled prior, never a win-rate, ROI, or probability claim.

K_RATE_TBF_PER_IP = 4.25             # league batters-faced-per-inning proxy
FG_PITCHING_RATE_COLUMNS = ("K%", "K/9")   # preference order


def load_fangraphs_pitching(path: str | Path) -> pd.DataFrame:
    """Read a FanGraphs season pitching CSV export (utf-8-sig, 'First Last' names).

    Requires a ``Name`` column and at least one K-rate column (``K%`` or
    ``K/9``). Raises when neither rate column exists so a truncated export
    cannot silently neutralize the feature, mirroring the xISO column guard.
    """
    table = pd.read_csv(path, encoding="utf-8-sig")
    if "Name" not in table.columns:
        raise ValueError("FanGraphs pitching CSV missing required column 'Name'")
    if not any(c in table.columns for c in FG_PITCHING_RATE_COLUMNS):
        raise ValueError(
            f"FanGraphs pitching CSV carries none of {FG_PITCHING_RATE_COLUMNS}; "
            "a K-rate column is required for pitcher ceiling multipliers"
        )
    return table


def k_rate_column(table: pd.DataFrame) -> str:
    """Return the K-rate column this table will rank on (K% preferred over K/9)."""
    for column in FG_PITCHING_RATE_COLUMNS:
        if column in table.columns:
            return column
    raise ValueError(f"table carries none of {FG_PITCHING_RATE_COLUMNS}")


def build_k_rate_ceiling_multipliers(
    pitching_table: pd.DataFrame,
    neutral: float = XISO_CEILING_NEUTRAL,
    span: float = XISO_CEILING_SPAN,
    clip: Tuple[float, float] = XISO_CEILING_CLIP,
    pa_full: int = XWOBA_PA_FULL,
    pa_min: int = XWOBA_PA_MIN,
    tbf_per_ip: float = K_RATE_TBF_PER_IP,
) -> Dict[str, float]:
    """Map FanGraphs Name -> per-pitcher Ceiling multiplier from K rate.

    Multiplier is ``neutral + (percentile - 0.5) * span`` where the percentile
    ranks the pitcher's K rate within the qualified starter rows of the
    supplied table (GS >= 1 when a GS column exists, batters faced >= pa_min,
    valid rate), so the league starter population, not the slate, defines
    whiff. Batters faced is a real ``TBF`` column when present, else
    ``IP * tbf_per_ip``. Below pa_min the multiplier is neutral; between
    pa_min and pa_full it shrinks linearly toward neutral, mirroring the xwOBA
    and xISO sample discipline. The result is clipped to ``clip``. Every row in
    the table gets an entry (non-starters and sub-floor arms at the neutral) so
    an absent value can never invent signal downstream. Keys are the raw Name
    strings; DK re-keying lives in
    ``xwoba_base_correction.build_dk_keyed_pitcher_ceiling_multipliers``.
    """
    rate_col = k_rate_column(pitching_table)
    table = pitching_table.copy()
    table["Name"] = table["Name"].astype(str).str.strip()
    rate = table[rate_col].astype(str).str.replace("%", "", regex=False)
    table["_rate"] = pd.to_numeric(rate, errors="coerce")
    if "TBF" in table.columns:
        table["_tbf"] = pd.to_numeric(table["TBF"], errors="coerce")
    else:
        ip = pd.to_numeric(table["IP"], errors="coerce") if "IP" in table.columns else pd.Series(dtype=float)
        table["_tbf"] = ip * float(tbf_per_ip)
    if "GS" in table.columns:
        starter = pd.to_numeric(table["GS"], errors="coerce").fillna(0) >= 1
    else:
        starter = pd.Series(True, index=table.index)
    multipliers: Dict[str, float] = {name: float(neutral) for name in table["Name"]}
    qualified = table[starter & (table["_tbf"] >= pa_min) & table["_rate"].notna()].copy()
    if qualified.empty:
        return multipliers
    qualified["_pct"] = qualified["_rate"].rank(pct=True, method="average")
    low, high = clip
    for _, row in qualified.iterrows():
        raw = float(neutral) + (float(row["_pct"]) - 0.5) * float(span)
        tbf = float(row["_tbf"])
        weight = 1.0 if tbf >= pa_full else (tbf - pa_min) / float(pa_full - pa_min)
        adjusted = float(neutral) + (raw - float(neutral)) * weight
        multipliers[str(row["Name"])] = float(min(high, max(low, adjusted)))
    return multipliers


# --- Deterministic F4: matchup quality for hitters (v1.3) -------------------
# F4 was structurally absent: it defaulted to 1.0 unless hand-typed per row,
# leaving the two strongest matchup signals (opposing-SP quality and the
# platoon hand advantage) outside the projection. This block computes a
# deterministic hitter F4 as (opposing-SP contact-quality ratio) x (platoon
# hand prior). The quality ratio is the opposing SP's Savant xwOBA-against over
# the league mean of the supplied pitching table, PA-shrunk and clipped, so a
# hitter facing a soft-contact ace is pulled down and one facing a loud-contact
# arm is pulled up. The platoon priors are labeled priors from the standard
# platoon-split literature, not calibrated values; override the table per slate
# if a better split exists. Applied BEFORE F1/F5 it does not double count the
# implied total or the park. Pitcher F4 remains 1.0 in this version. All
# outputs are deterministic review inputs, never ROI or win-rate claims.

F4_PLATOON_PRIOR: Dict[Tuple[str, str], float] = {
    ("L", "R"): 1.04, ("L", "L"): 0.94,
    ("R", "L"): 1.03, ("R", "R"): 0.99,
    ("S", "R"): 1.02, ("S", "L"): 1.02,
}
F4_QUALITY_CLIP = (0.90, 1.10)
F4_COMBINED_CLIP = (0.85, 1.15)


def platoon_hand_factor(bat_side: Optional[str], pitch_hand: Optional[str]) -> float:
    """Platoon prior for a batter hand vs a pitcher hand; 1.0 when either is unknown."""
    key = (str(bat_side or "").strip().upper(), str(pitch_hand or "").strip().upper())
    return float(F4_PLATOON_PRIOR.get(key, 1.0))


def opposing_sp_quality_factor(
    opp_est_woba: Optional[float],
    league_mean_est_woba: Optional[float],
    opp_pa: Optional[float],
    clip: Tuple[float, float] = F4_QUALITY_CLIP,
    pa_full: int = XWOBA_PA_FULL,
    pa_min: int = XWOBA_PA_MIN,
) -> float:
    """Hitter uplift/discount from the opposing SP's expected wOBA-against.

    Ratio is opp est_woba over the league mean, PA-shrunk toward 1.0 below
    pa_full and neutral below pa_min, then clipped. Returns 1.0 whenever an
    input is missing so an absent Savant row can never invent signal.
    """
    if opp_est_woba is None or league_mean_est_woba is None or opp_pa is None:
        return 1.0
    if pd.isna(opp_est_woba) or pd.isna(league_mean_est_woba) or pd.isna(opp_pa):
        return 1.0
    if float(league_mean_est_woba) <= 0 or float(opp_est_woba) <= 0:
        return 1.0
    ratio = float(opp_est_woba) / float(league_mean_est_woba)
    return _shrink_and_clip(ratio, float(opp_pa), clip, pa_full, pa_min)


def compute_f4_factors(
    team_by_player_id: Mapping[str, str],
    opp_probable_by_team: Mapping[str, Mapping[str, Any]],
    pitching_table: Optional[pd.DataFrame] = None,
    bat_side_by_player_id: Optional[Mapping[str, str]] = None,
    quality_clip: Tuple[float, float] = F4_QUALITY_CLIP,
    combined_clip: Tuple[float, float] = F4_COMBINED_CLIP,
    pa_full: int = XWOBA_PA_FULL,
    pa_min: int = XWOBA_PA_MIN,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Return ({hitter DK Player_ID: F4}, report) for the supplied hitters.

    Inputs are plain mappings so the function stays feed-agnostic:
    ``team_by_player_id`` maps each HITTER's DK id to its DK team;
    ``opp_probable_by_team`` maps a DK team to its OPPOSING probable SP as
    ``{"id": mlbam, "name": ..., "hand": "R"/"L"}`` (see
    live_data_adapters.extract_opposing_probables); ``pitching_table`` is the
    Savant pitching expected-stats frame (load_savant_expected_stats), joined by
    MLBAM id, which supplies est_woba and pa plus the league mean;
    ``bat_side_by_player_id`` optionally supplies batter hands (see
    live_data_adapters.extract_batter_hands). The SP-quality component applies
    team-wide even when batter hands are unavailable, so TBD lineups still
    receive the matchup-quality signal. A team with no opposing probable stays
    neutral and is reported. Every emitted F4 is a labeled deterministic prior.
    """
    league_mean: Optional[float] = None
    sp_row_by_id: Dict[str, Tuple[float, float]] = {}
    if pitching_table is not None and len(pitching_table):
        table = pitching_table.copy()
        table["player_id"] = table["player_id"].astype(str).str.strip()
        est = pd.to_numeric(table["est_woba"], errors="coerce")
        pa = pd.to_numeric(table["pa"], errors="coerce")
        valid = est.notna() & (est > 0)
        if bool(valid.any()):
            league_mean = float(est[valid].mean())
        for pid, e, p in zip(table["player_id"], est, pa):
            if not pd.isna(e):
                sp_row_by_id[str(pid)] = (float(e), float(p) if not pd.isna(p) else 0.0)

    hands = {str(k): str(v).strip().upper() for k, v in (bat_side_by_player_id or {}).items()}
    quality_by_team: Dict[str, float] = {}
    opp_hand_by_team: Dict[str, Optional[str]] = {}
    teams_without_probable: list = []
    for team in sorted({str(t).strip().upper() for t in team_by_player_id.values()}):
        probable = opp_probable_by_team.get(team) or {}
        opp_hand_by_team[team] = probable.get("hand")
        mlbam = str(probable.get("id") or "").strip()
        if not probable or not probable.get("name"):
            teams_without_probable.append(team)
            quality_by_team[team] = 1.0
            continue
        est_pa = sp_row_by_id.get(mlbam)
        if est_pa is None or league_mean is None:
            quality_by_team[team] = 1.0
            continue
        quality_by_team[team] = opposing_sp_quality_factor(
            est_pa[0], league_mean, est_pa[1], clip=quality_clip, pa_full=pa_full, pa_min=pa_min,
        )

    low, high = combined_clip
    f4_by_player: Dict[str, float] = {}
    platoon_applied = 0
    for pid, team in team_by_player_id.items():
        team_key = str(team).strip().upper()
        quality = quality_by_team.get(team_key, 1.0)
        hand_factor = platoon_hand_factor(hands.get(str(pid)), opp_hand_by_team.get(team_key))
        if abs(hand_factor - 1.0) > 1e-12:
            platoon_applied += 1
        f4_by_player[str(pid)] = float(min(high, max(low, quality * hand_factor)))

    report: Dict[str, Any] = {
        "league_mean_est_woba": league_mean,
        "quality_factor_by_team": quality_by_team,
        "opp_hand_by_team": opp_hand_by_team,
        "teams_without_opposing_probable": teams_without_probable,
        "hitters_scored": len(f4_by_player),
        "platoon_component_applied": platoon_applied,
        "sp_quality_available": league_mean is not None,
        "note": (
            "Deterministic F4 prior: opposing-SP xwOBA-against quality ratio x "
            "platoon hand prior, PA-shrunk and clipped. Labeled prior, never a "
            "win-rate, ROI, or probability claim. Pitcher F4 stays 1.0 in v1.3."
        ),
    }
    return f4_by_player, report


def write_projection_bundle(projections: pd.DataFrame, audit: pd.DataFrame, output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    projection_path = root / "projections.csv"
    audit_path = root / "projection_factor_audit.csv"
    projections.to_csv(projection_path, index=False)
    audit.to_csv(audit_path, index=False)
    return {"projections": str(projection_path), "audit": str(audit_path)}
