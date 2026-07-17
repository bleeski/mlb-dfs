"""posture_allocator.py — waterfall tier policy for the contest menu (untracked).

STATUS: review-only companion, deliberately OUTSIDE the audited engine and
outside the 26-file cap, on the same footing as ownership_prior.py,
fetch_slate_bundle.py, and field_miner.py. Both open tracked slots stay
reserved for the fitted ownership model (Backlog B-8). This module never
calls run_slate, never writes entry requirements, and never auto-applies
anything; it prints a review report and a paste-ready contest_postures dict
that Ben passes explicitly, per ledger invariant 3.4.

TRUTHFUL LABELS: tier assignments are deterministic classifications of
observed contest shape (paid places over field size). The fee-share targets
are BANKROLL POLICY PRIORS, stated as policy and adjustable per slate; they
are never win-rate, cash-rate, ROI, or probability claims. "Floor" here
means fee allocation to broad-payout shapes, not a lineup-level guarantee;
no lineup-level floor exists in top-heavy contests and this module does not
pretend one does.

THE WATERFALL (from the 2026-07-04 strategic brief, approved):
  Priority 1, the floor, is purchased in fee allocation, not lineup space.
  Priority 2, the apex, is decorrelated ceiling with duplication screening.
  Priority 3, the volume, follows the concentration rule below.

TIERS (policy constants, documented and overridable):
  F (floor):  payout breadth >= 0.20, or a multi-seat satellite with
              seats >= 3 and breadth >= 0.10. Archetype: the top-script,
              highest-median, chalk-primary lineup; a won ticket is a
              realized convertible asset.
  A (apex):   paid_places == 1 (WTA), or breadth <= 0.05. Archetype: the
              decorrelated ceiling set; SP-pair spread scaled to entries
              (ledger 3.5); every Tier A candidate goes through the
              field_miner duplication-risk screen (structural until field
              tables exist).
  V (volume): everything else, typically small fields with moderate
              breadth. Concentration rule: duplicate the top lineup across
              independent, linear-payout contests (expected win count is
              linear); diversify wherever wins are substitutes (entries in
              the same satellite family) or where within-contest
              duplication splits the prize.
  UNRESOLVED: paid_places unknown. Capture it from the contest page (the
              Cowork archival runbook owns this step) before allocating.

INPUT: a JSON file containing a list of contest dicts:
  {"contest_id": "191787184", "name": "MLB $3 Pocket Cup", "entry_fee": 3.0,
   "field_size": 222, "paid_places": 30, "my_entries": 4,
   "seats": null, "posture": null}
paid_places and any satellite seat count come from the contest page (the
standings export omits them; ledger 3.1). An explicit "posture" always wins;
otherwise the engine's own infer_contest_archetype + normalize_posture are
used when importable, so there is one source of truth for posture strings.

CLI:
  python posture_allocator.py --contests menu.json [--floor-min 0.25]
      [--apex-min 0.40 --apex-max 0.60] [--json out.json]
  python posture_allocator.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

VERSION = "0.1-review"

# Tier policy constants (policy, not claims).
TIER_F_BREADTH = 0.20
TIER_A_BREADTH = 0.05
SAT_SEATS_F = 3
SAT_F_BREADTH = 0.10

# Default fee-share policy priors (bankroll policy; override per slate).
DEFAULT_FLOOR_MIN_SHARE = 0.25
DEFAULT_APEX_SHARE_BAND = (0.40, 0.60)

POLICY_LABEL = (
    "bankroll policy priors and deterministic shape classification; "
    "not win rate, cash rate, ROI, or probability claims; never auto-applied"
)

ARCHETYPE_BY_TIER = {
    "F": ("top-script primary: highest-median, chalk-primary construction; "
          "single lineup or minimal variants; deep fill by shape"),
    "A": ("decorrelated ceiling set: script coverage governs composition, "
          "SP-pair spread scaled to entries (>= 3 viable pairs when entries allow, "
          "ledger 3.5), duplication-risk screen on every candidate"),
    "V": ("distinct near-best lineups under the concentration rule: duplicate the "
          "top lineup across independent linear-payout contests; diversify within "
          "satellite families and high-duplication fields"),
}

# Engine vocabulary: single source of truth when importable.
try:  # pragma: no cover - environment dependent
    from mlb_engine.pipeline.execution_pipeline import STRATEGY_DEFAULTS, normalize_posture  # type: ignore
    from mlb_engine.entries.dk_entries_manager import infer_contest_archetype, load_archetypes  # type: ignore
    _ENGINE = True
except Exception:  # pragma: no cover
    _ENGINE = False
    STRATEGY_DEFAULTS = {k: {} for k in
                         ("single_entry", "wta_satellite", "small_gpp", "large_gpp", "mme", "cash")}

    def normalize_posture(inferred_type, payout_shape_default=None, max_entries=None):  # type: ignore
        return "large_gpp"


def classify_tier(contest: Dict[str, Any]) -> Dict[str, Any]:
    field = contest.get("field_size")
    paid = contest.get("paid_places")
    seats = contest.get("seats")
    if not field or paid is None:
        return {"tier": "UNRESOLVED", "breadth": None,
                "reason": "paid_places or field_size missing; capture from the contest page "
                          "(Cowork archival runbook, job 1) before allocating"}
    breadth = paid / field
    if paid == 1:
        return {"tier": "A", "breadth": round(breadth, 4), "reason": "winner-take-all (paid_places == 1)"}
    if seats and seats >= SAT_SEATS_F and breadth >= SAT_F_BREADTH:
        return {"tier": "F", "breadth": round(breadth, 4),
                "reason": f"multi-seat satellite (seats {seats}, breadth {breadth:.2f}); "
                          "a won ticket is a realized convertible asset"}
    if breadth >= TIER_F_BREADTH:
        return {"tier": "F", "breadth": round(breadth, 4), "reason": f"broad payout (breadth {breadth:.2f})"}
    if breadth <= TIER_A_BREADTH:
        return {"tier": "A", "breadth": round(breadth, 4), "reason": f"top-heavy payout (breadth {breadth:.2f})"}
    return {"tier": "V", "breadth": round(breadth, 4), "reason": f"moderate breadth ({breadth:.2f})"}


def resolve_posture(contest: Dict[str, Any], archetypes: Any = None) -> str:
    explicit = contest.get("posture")
    if isinstance(explicit, str) and explicit:
        return explicit
    if _ENGINE:
        inferred = infer_contest_archetype(
            str(contest.get("name", "")), float(contest.get("entry_fee", 0.0) or 0.0), archetypes
        )
        return normalize_posture(
            inferred.get("inferred_type"),
            inferred.get("payout_shape_default"),
            inferred.get("inferred_max_entries"),
        )
    return "large_gpp"


def _find_archetypes_csv() -> Optional[str]:
    import os
    for base in (
        os.path.join(os.getcwd(), "data", "reference"),
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
    ):
        p = os.path.join(base, "dk_contest_archetypes.csv")
        if os.path.exists(p):
            return p
    return None


def allocate(
    contests: Sequence[Dict[str, Any]],
    floor_min_share: float = DEFAULT_FLOOR_MIN_SHARE,
    apex_share_band: Sequence[float] = DEFAULT_APEX_SHARE_BAND,
) -> Dict[str, Any]:
    archetypes = load_archetypes(_find_archetypes_csv()) if _ENGINE else None
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    fees_by_tier: Dict[str, float] = defaultdict(float)
    families: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for c in contests:
        cls = classify_tier(c)
        posture = resolve_posture(c, archetypes)
        my = int(c.get("my_entries", 0) or 0)
        fee_total = float(c.get("entry_fee", 0.0) or 0.0) * my
        row = {
            "contest_id": str(c.get("contest_id", "")),
            "name": str(c.get("name", "")),
            "tier": cls["tier"],
            "tier_reason": cls["reason"],
            "breadth": cls["breadth"],
            "posture": posture,
            "my_entries": my,
            "fee_total": round(fee_total, 2),
            "archetype": ARCHETYPE_BY_TIER.get(cls["tier"], "resolve shape first"),
        }
        rows.append(row)
        fees_by_tier[cls["tier"]] += fee_total
        families[row["name"]].append(row)
        if cls["tier"] == "UNRESOLVED":
            warnings.append(f"{row['contest_id']} {row['name']}: {cls['reason']}")
        if posture == "cash":
            warnings.append(f"{row['contest_id']} {row['name']}: cash posture is a weak "
                            "architectural fit (ledger 3.5); flag and confirm before building")
        if posture not in STRATEGY_DEFAULTS:
            warnings.append(f"{row['contest_id']}: posture '{posture}' is not a STRATEGY_DEFAULTS key")

    total = sum(fees_by_tier.values()) or 0.0
    shares = {t: round(v / total, 3) if total else None for t, v in fees_by_tier.items()}
    policy_checks: List[str] = []
    if total:
        f_share = shares.get("F", 0.0) or 0.0
        a_share = shares.get("A", 0.0) or 0.0
        if f_share < floor_min_share:
            policy_checks.append(
                f"Tier F share {f_share:.0%} is below the floor policy minimum "
                f"{floor_min_share:.0%}: the zero-return floor is underfunded on this menu. "
                "Policy call, not a claim.")
        lo, hi = apex_share_band
        if a_share < lo:
            policy_checks.append(f"Tier A share {a_share:.0%} is below the apex policy band "
                                 f"[{lo:.0%}, {hi:.0%}].")
        elif a_share > hi:
            policy_checks.append(f"Tier A share {a_share:.0%} is above the apex policy band "
                                 f"[{lo:.0%}, {hi:.0%}].")

    family_notes: List[str] = []
    for name, rws in families.items():
        entries = sum(r["my_entries"] for r in rws)
        if entries > 1 and any(r["posture"] == "wta_satellite" for r in rws):
            family_notes.append(
                f"'{name}' family ({entries} entries): wins are substitutes; entries in this "
                "family must not share a candidate signature beyond the ticket cap "
                "(diversify, per the concentration rule)")

    contest_postures = {r["contest_id"]: r["posture"] for r in rows if r["contest_id"]}
    return {
        "label": POLICY_LABEL,
        "version": VERSION,
        "engine_vocabulary": _ENGINE,
        "rows": rows,
        "fees_by_tier": {t: round(v, 2) for t, v in fees_by_tier.items()},
        "fee_shares": shares,
        "policy": {"floor_min_share": floor_min_share, "apex_share_band": list(apex_share_band)},
        "policy_checks": policy_checks,
        "family_notes": family_notes,
        "warnings": warnings,
        "contest_postures": contest_postures,
    }


def render_report(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"posture_allocator {result['version']} "
                 f"({'engine vocabulary' if result['engine_vocabulary'] else 'FALLBACK vocabulary; run beside the engine'})")
    lines.append(f"labels: {result['label']}")
    lines.append("")
    for r in result["rows"]:
        b = f"{r['breadth']:.2f}" if r["breadth"] is not None else "?"
        lines.append(f"[{r['tier']}] {r['contest_id']} {r['name']} | breadth {b} | "
                     f"posture {r['posture']} | entries {r['my_entries']} | fees ${r['fee_total']}")
        lines.append(f"     shape: {r['tier_reason']}")
        lines.append(f"     archetype: {r['archetype']}")
    lines.append("")
    lines.append(f"fees by tier: {result['fees_by_tier']}  shares: {result['fee_shares']}  "
                 f"policy: {result['policy']}")
    for p in result["policy_checks"]:
        lines.append(f"POLICY: {p}")
    for f in result["family_notes"]:
        lines.append(f"FAMILY: {f}")
    for w in result["warnings"]:
        lines.append(f"WARNING: {w}")
    lines.append("")
    lines.append("paste-ready contest_postures (explicit, per ledger 3.4):")
    lines.append(json.dumps(result["contest_postures"], indent=1, sort_keys=True))
    return "\n".join(lines)


def _selftest() -> int:
    menu = [
        {"contest_id": "C1", "name": "MLB Single Seat Satellite", "entry_fee": 5,
         "field_size": 30, "paid_places": 1, "my_entries": 2},
        {"contest_id": "C1B", "name": "MLB Single Seat Satellite", "entry_fee": 5,
         "field_size": 30, "paid_places": 1, "my_entries": 1},
        {"contest_id": "C2", "name": "MLB 25-Seat Qualifier", "entry_fee": 3,
         "field_size": 100, "paid_places": 25, "seats": 25, "my_entries": 4},
        {"contest_id": "C3", "name": "MLB Double Up", "entry_fee": 5,
         "field_size": 200, "paid_places": 90, "my_entries": 1},
        {"contest_id": "C4", "name": "MLB $1 Single Entry", "entry_fee": 1,
         "field_size": 1000, "paid_places": 250, "my_entries": 1},
        {"contest_id": "C5", "name": "MLB Winner Take All Showdown of Champions", "entry_fee": 10,
         "field_size": 40, "paid_places": 1, "my_entries": 1},
        {"contest_id": "C6", "name": "MLB Small Shootout", "entry_fee": 2,
         "field_size": 25, "paid_places": 4, "my_entries": 3},
        {"contest_id": "C7", "name": "MLB Milly Mini", "entry_fee": 5,
         "field_size": 10000, "paid_places": 300, "my_entries": 2},
        {"contest_id": "C8", "name": "MLB Mystery Payout", "entry_fee": 5,
         "field_size": 100, "paid_places": None, "my_entries": 1},
    ]
    res = allocate(menu)
    tiers = {r["contest_id"]: r["tier"] for r in res["rows"]}
    assert tiers["C1"] == "A" and tiers["C5"] == "A" and tiers["C7"] == "A", tiers
    assert tiers["C2"] == "F" and tiers["C3"] == "F" and tiers["C4"] == "F", tiers
    assert tiers["C6"] == "V" and tiers["C8"] == "UNRESOLVED", tiers
    if res["engine_vocabulary"]:
        for r in res["rows"]:
            assert r["posture"] in STRATEGY_DEFAULTS, r
        postures = {r["contest_id"]: r["posture"] for r in res["rows"]}
        assert postures["C1"] == "wta_satellite" and postures["C2"] == "wta_satellite", postures
        assert postures["C3"] == "cash" and postures["C4"] == "single_entry", postures
    assert any("cash posture is a weak" in w for w in res["warnings"])
    assert any("Mystery Payout" in w for w in res["warnings"])
    assert any("Single Seat Satellite" in f for f in res["family_notes"]), res["family_notes"]
    assert set(res["contest_postures"]) == {r["contest_id"] for r in res["rows"]}
    assert res["fee_shares"].get("F") is not None
    print(render_report(res))
    print()
    print("posture_allocator selftest: PASS (tiers, postures, policy checks, family rule, "
          "warnings, paste-ready postures)")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--contests", help="JSON file: list of contest dicts (see module docstring)")
    ap.add_argument("--floor-min", type=float, default=DEFAULT_FLOOR_MIN_SHARE)
    ap.add_argument("--apex-min", type=float, default=DEFAULT_APEX_SHARE_BAND[0])
    ap.add_argument("--apex-max", type=float, default=DEFAULT_APEX_SHARE_BAND[1])
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.contests:
        ap.error("--contests is required (or --selftest)")
    with open(args.contests, "r", encoding="utf-8") as fh:
        menu = json.load(fh)
    res = allocate(menu, floor_min_share=args.floor_min,
                   apex_share_band=(args.apex_min, args.apex_max))
    print(render_report(res))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print(f"\njson written: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
