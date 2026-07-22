"""contest_library.py -- name-keyed DraftKings contest library (untracked companion).

STATUS: review-only companion, deliberately OUTSIDE the audited engine, on the
same footing as posture_allocator.py, ownership_prior.py, and field_miner.py. It
never calls run_slate, never writes an entry requirement, and never auto-applies
anything. It resolves the tier inputs a contest menu needs and emits a paste-ready
``waterfall`` (a posture_allocator.allocate result) that Ben passes explicitly to
``run_slate(waterfall=...)``.

WHY THIS EXISTS: posture_allocator classifies a contest's tier from payout breadth
and seat count, which live on the DK contest page and are absent from DKSalaries
and DKEntries. Supplying that menu by hand every slate is the friction this module
removes. DK uses stable contest-name conventions, so a contest's type and payout
shape are inferable from its name, and its exact field size and paid places become
knowable once the same contest has been observed in the post-slate archive.

RESOLUTION TRUST ORDER (highest trust first), per contest:
  1. provided  -- an explicit menu entry Ben passes this slate. Exact, wins always.
  2. library   -- observed field_size/paid_places/seats for this exact recurring
                  contest (normalized name + entry fee), accumulated from the
                  post-slate archive. Exact history.
  3. name      -- payout breadth inferred from the contest name via
                  dk_contest_archetypes.csv (the payout_breadth column). A LABELED
                  PRIOR: the tier is classified from an inferred breadth, tagged as
                  inferred, and exact field size stays unknown.
  4. unresolved-- name unmatched and no history. Blocks the tier (unchanged today).

TRUTHFUL LABELS: observed field_size/paid_places are observed history, not
predictions. An inferred breadth is a labeled prior. A resolved tier carries its
``resolution`` and ``confidence`` so the checkpoint never mistakes an inferred tier
for a confirmed one. Nothing here is a win-rate, cash-rate, ROI, or probability
claim, and nothing auto-applies to a build.

CLI:
  python -m mlb_engine.field.contest_library --entries DKEntries.csv \
      [--registry data/reference/contest_library.json] [--archetypes path.csv] \
      [--provided menu.json] [--json out.json]
  python -m mlb_engine.field.contest_library --selftest
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

VERSION = "0.1-review"

LABEL = (
    "observed contest history and name-inferred payout shape; observed values are "
    "observed history and inferred values are labeled priors; never win rate, cash "
    "rate, ROI, or probability; review-only, nothing auto-applies"
)

_ARCHETYPE_FILE = "dk_contest_archetypes.csv"
_DEFAULT_REGISTRY = os.path.join("data", "reference", "contest_library.json")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _today() -> str:
    return date.today().isoformat()


def normalize_name(name: str) -> str:
    """Lowercase, collapse whitespace. Conservative on purpose: the library keys on
    the exact recurring contest (name + fee), so distinct buy-in tiers stay distinct.
    Family-level generalization is the job of the name-archetype layer, not the key."""
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _money(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.findall(r"\d+(?:\.\d+)?", str(value))
    return float(m[0]) if m else None


def _fee_bucket(entry_fee: Any) -> str:
    fee = _money(entry_fee)
    return f"{fee:.2f}" if fee is not None else "na"


def contest_key(name: str, entry_fee: Any) -> str:
    return f"{normalize_name(name)}|{_fee_bucket(entry_fee)}"


def _default_archetypes_path() -> Optional[str]:
    for base in (os.path.join(os.getcwd(), "data", "reference"), os.getcwd()):
        p = os.path.join(base, _ARCHETYPE_FILE)
        if os.path.exists(p):
            return p
    return None


# --------------------------------------------------------------------------- #
# Name-archetype layer: breadth straight from dk_contest_archetypes.csv
# --------------------------------------------------------------------------- #
def load_archetype_rows(archetypes_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read the archetype CSV into rows carrying the payout_breadth column, which
    load_archetypes/ContestArchetype drop. Defensive: missing file returns []."""
    path = archetypes_path or _default_archetypes_path()
    if not path or not Path(path).exists():
        return []
    rows: List[Dict[str, Any]] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            pattern = str(r.get("pattern") or "").strip()
            if not pattern:
                continue
            breadth = None
            raw = r.get("payout_breadth")
            if raw not in (None, ""):
                try:
                    breadth = float(raw)
                except (TypeError, ValueError):
                    breadth = None
            max_entries = None
            if r.get("inferred_max_entries") not in (None, ""):
                try:
                    max_entries = int(float(r["inferred_max_entries"]))
                except (TypeError, ValueError):
                    max_entries = None
            rows.append({
                "pattern": pattern,
                "payout_breadth": breadth,
                "confidence": str(r.get("confidence") or "unknown"),
                "inferred_type": str(r.get("inferred_type") or "unknown"),
                "payout_shape_default": str(r.get("payout_shape_default") or "unknown"),
                "inferred_max_entries": max_entries,
            })
    return rows


def infer_from_name(name: str, archetype_rows: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Match a contest name to an archetype row, returning the payout_breadth the tier
    logic needs.

    Ranking is CONFIDENCE FIRST (the CSV's own confidence column), then pattern length.
    That implements the archetype CSV's own notes ("if title says Qualifier treat as
    satellite") and fixes the ledger 3.4 recurring-family trap: a high-confidence
    contest-type token (Satellite, Qualifier, WTA) now outranks a low-confidence
    recurring-family name (Pocket Cup, Relay Throw, Knuckleball). Measured on the
    2026-06/07 archive, plain longest-match mis-tiered 6 of 9 satellites as Volume
    when they are Floor. Disagreements are still flagged in ambiguous_types."""
    low = str(name or "").lower()
    matches = [r for r in archetype_rows if r["pattern"].lower() in low]
    if not matches:
        return None
    conf_rank = {"inferred_high": 3, "inferred_medium": 2, "inferred_low": 1}

    def _rank(r):
        return (conf_rank.get(str(r.get("confidence", "")).strip().lower(), 0), len(r["pattern"]))

    selected = dict(max(matches, key=_rank))
    types = sorted({r["inferred_type"] for r in matches})
    selected["ambiguous_types"] = types if len(types) > 1 else []
    selected["matched_patterns"] = sorted({r["pattern"] for r in matches})
    return selected


# --------------------------------------------------------------------------- #
# Registry: observed contest history, grown from the post-slate archive
# --------------------------------------------------------------------------- #
def empty_registry() -> Dict[str, Any]:
    return {"version": VERSION, "label": LABEL, "updated": None, "contests": {}}


def load_registry(path: Optional[str]) -> Dict[str, Any]:
    if not path or not Path(path).exists():
        return empty_registry()
    reg = json.loads(Path(path).read_text(encoding="utf-8"))
    reg.setdefault("contests", {})
    return reg


def save_registry(path: str, registry: Mapping[str, Any]) -> None:
    reg = dict(registry)
    reg["updated"] = _today()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(reg, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def record_observation(
    registry: Dict[str, Any], name: str, entry_fee: Any,
    field_size: Optional[int] = None, paid_places: Optional[int] = None,
    seats: Optional[int] = None, date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert one observed contest into the registry. Observed values are observed
    history, never a prediction."""
    key = contest_key(name, entry_fee)
    rec = registry.setdefault("contests", {}).get(key) or {
        "name": str(name), "entry_fee": _money(entry_fee),
        "observations": 0, "history": [],
    }
    rec["observations"] = int(rec.get("observations", 0)) + 1
    rec["last_seen"] = date_str or _today()
    if field_size is not None:
        rec["field_size"] = int(field_size)
    if paid_places is not None:
        rec["paid_places"] = int(paid_places)
    if seats is not None:
        rec["seats"] = int(seats)
    if rec.get("field_size") and rec.get("paid_places") is not None:
        rec["breadth"] = round(rec["paid_places"] / rec["field_size"], 4)
    rec["history"] = (rec.get("history") or [])[-11:] + [{
        "date": rec["last_seen"], "field_size": field_size,
        "paid_places": paid_places, "seats": seats,
    }]
    registry["contests"][key] = rec
    return rec


def update_registry_from_observations(
    registry: Dict[str, Any], observations: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    for obs in observations:
        record_observation(
            registry, obs.get("name"), obs.get("entry_fee"),
            field_size=obs.get("field_size"), paid_places=obs.get("paid_places"),
            seats=obs.get("seats"), date_str=obs.get("date"),
        )
    return registry


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def resolve_contest(
    reserved: Mapping[str, Any], registry: Mapping[str, Any],
    archetype_rows: Sequence[Mapping[str, Any]], provided: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve one reserved contest to posture_allocator inputs in trust order."""
    name = reserved.get("name")
    fee = reserved.get("entry_fee")
    out: Dict[str, Any] = {
        "contest_id": str(reserved.get("contest_id", "")),
        "name": name, "entry_fee": _money(fee),
        "my_entries": int(reserved.get("my_entries", 0) or 0),
    }

    # 1. provided this slate
    if provided:
        for k in ("field_size", "paid_places", "seats"):
            if provided.get(k) is not None:
                out[k] = provided[k]
        if provided.get("posture"):
            out["posture"] = provided["posture"]
        out["resolution"] = "provided"
        out["confidence"] = "provided"
        return out

    # 2. library history for this exact recurring contest
    rec = registry.get("contests", {}).get(contest_key(name, fee))
    if rec and rec.get("field_size") and rec.get("paid_places") is not None:
        out["field_size"] = rec["field_size"]
        out["paid_places"] = rec["paid_places"]
        if rec.get("seats") is not None:
            out["seats"] = rec["seats"]
        out["resolution"] = "library"
        out["confidence"] = f"library:{rec.get('observations', 0)}obs;last_seen={rec.get('last_seen')}"
        return out

    # 3. name-inferred payout breadth (labeled prior)
    inf = infer_from_name(name, archetype_rows)
    if inf and inf.get("payout_breadth") is not None:
        out["breadth"] = inf["payout_breadth"]
        out["resolution"] = "name_archetype"
        out["confidence"] = f"name:{inf.get('confidence')};shape={inf.get('payout_shape_default')}"
        out["inferred_type"] = inf.get("inferred_type")
        out["inferred_max_entries"] = inf.get("inferred_max_entries")
        if inf.get("ambiguous_types"):
            out["note"] = (
                "multiple contest-type tokens in the name ("
                + ", ".join(inf["ambiguous_types"])
                + "); tier may be wrong (ledger 3.4). Provide or confirm from the contest page.")
        return out

    # 4. unresolved
    out["resolution"] = "unresolved"
    out["confidence"] = "none"
    return out


def resolve_menu(
    reserved_contests: Sequence[Mapping[str, Any]],
    registry: Optional[Mapping[str, Any]] = None,
    archetypes_path: Optional[str] = None,
    provided_menu: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    registry = registry or empty_registry()
    archetype_rows = load_archetype_rows(archetypes_path)
    provided_by_id = {str(c.get("contest_id")): c for c in (provided_menu or [])}
    return [
        resolve_contest(rc, registry, archetype_rows, provided_by_id.get(str(rc.get("contest_id"))))
        for rc in reserved_contests
    ]


def reserved_contests_from_entries(entries_csv: str) -> List[Dict[str, Any]]:
    """Distinct reserved contests (contest_id, name, entry_fee, my_entries) from a
    DKEntries file, in first-seen order. Uses the engine's own parser."""
    from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
    agg: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for r in parse_dk_entry_rows(str(entries_csv)):
        cid = str(r.contest_id)
        if cid not in agg:
            agg[cid] = {"contest_id": cid, "name": r.contest_name, "entry_fee": r.entry_fee, "my_entries": 0}
            order.append(cid)
        agg[cid]["my_entries"] += 1
    return [agg[c] for c in order]


def _resolution_summary(menu: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for c in menu:
        r = str(c.get("resolution") or "unresolved")
        counts[r] = counts.get(r, 0) + 1
    return counts


def build_waterfall(
    entries_csv: Optional[str] = None,
    reserved_contests: Optional[Sequence[Mapping[str, Any]]] = None,
    registry_path: Optional[str] = None,
    archetypes_path: Optional[str] = None,
    provided_menu: Optional[Sequence[Mapping[str, Any]]] = None,
    floor_min_share: float = None,  # type: ignore
    apex_share_band: Sequence[float] = None,  # type: ignore
) -> Dict[str, Any]:
    """One call: reserved contests -> resolved menu -> posture_allocator.allocate,
    ready to pass to run_slate(waterfall=...). Adds a resolution_summary so the review
    sees how each tier was resolved."""
    from mlb_engine.allocate import posture_allocator as pa
    if reserved_contests is None:
        if not entries_csv:
            raise ValueError("build_waterfall needs entries_csv or reserved_contests")
        reserved_contests = reserved_contests_from_entries(entries_csv)
    registry = load_registry(registry_path)
    menu = resolve_menu(reserved_contests, registry, archetypes_path, provided_menu)
    kwargs: Dict[str, Any] = {}
    if floor_min_share is not None:
        kwargs["floor_min_share"] = floor_min_share
    if apex_share_band is not None:
        kwargs["apex_share_band"] = apex_share_band
    result = pa.allocate(menu, **kwargs)
    lib_warnings = [
        f"{c['contest_id']} {c.get('name')}: {c['note']}" for c in menu if c.get("note")
    ]
    if lib_warnings:
        result["warnings"] = list(result.get("warnings") or []) + [
            f"contest_library: {w}" for w in lib_warnings
        ]
    result["resolution_summary"] = _resolution_summary(menu)
    result["library_version"] = VERSION
    return result


# --------------------------------------------------------------------------- #
# CLI + selftest
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    rows = load_archetype_rows()
    if not rows:
        print("contest_library selftest: SKIP (dk_contest_archetypes.csv not found from cwd)")
        return 0
    reserved = [
        {"contest_id": "A1", "name": "MLB $5 Winner Take All Shootout", "entry_fee": 5, "my_entries": 2},
        {"contest_id": "F1", "name": "MLB $10 Double Up", "entry_fee": 10, "my_entries": 1},
        {"contest_id": "V1", "name": "MLB $30 Quarter Jukebox", "entry_fee": 0.25, "my_entries": 4},
        {"contest_id": "U1", "name": "MLB Totally Novel Contest Name", "entry_fee": 3, "my_entries": 1},
    ]
    reg = empty_registry()
    menu = resolve_menu(reserved, reg, provided_menu=None)
    by_id = {c["contest_id"]: c for c in menu}
    assert by_id["A1"]["resolution"] == "name_archetype" and by_id["A1"]["breadth"] <= 0.05, by_id["A1"]
    assert by_id["F1"]["resolution"] == "name_archetype" and by_id["F1"]["breadth"] >= 0.20, by_id["F1"]
    assert by_id["V1"]["resolution"] == "name_archetype", by_id["V1"]
    assert by_id["U1"]["resolution"] == "unresolved", by_id["U1"]

    # Growth: observe the unresolved contest, then it resolves from library history.
    record_observation(reg, "MLB Totally Novel Contest Name", 3,
                       field_size=100, paid_places=25, date_str="2026-07-18")
    menu2 = {c["contest_id"]: c for c in resolve_menu(reserved, reg)}
    assert menu2["U1"]["resolution"] == "library", menu2["U1"]
    assert menu2["U1"]["field_size"] == 100 and menu2["U1"]["paid_places"] == 25, menu2["U1"]

    # Provided overrides everything.
    menu3 = {c["contest_id"]: c for c in resolve_menu(
        reserved, reg, provided_menu=[{"contest_id": "A1", "field_size": 50, "paid_places": 1}])}
    assert menu3["A1"]["resolution"] == "provided" and menu3["A1"]["paid_places"] == 1, menu3["A1"]

    # End to end: a waterfall the allocator accepts, tiers sane.
    wf = build_waterfall(reserved_contests=reserved, registry_path=None)
    tiers = {r["contest_id"]: r["tier"] for r in wf["rows"]}
    assert tiers["A1"] == "A" and tiers["F1"] == "F", tiers
    assert wf["resolution_summary"].get("name_archetype", 0) >= 1, wf["resolution_summary"]
    print("contest_library selftest: PASS (trust order, growth, provided override, waterfall)")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entries", help="DKEntries reserved-entries CSV")
    ap.add_argument("--registry", default=None, help="contest_library.json path")
    ap.add_argument("--archetypes", default=None, help="dk_contest_archetypes.csv path")
    ap.add_argument("--provided", default=None, help="JSON file: list of explicit menu entries")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.entries:
        ap.error("--entries is required (or --selftest)")
    provided = None
    if args.provided:
        provided = json.loads(Path(args.provided).read_text(encoding="utf-8"))
    wf = build_waterfall(entries_csv=args.entries, registry_path=args.registry,
                         archetypes_path=args.archetypes, provided_menu=provided)
    print(f"contest_library {VERSION}  resolution: {wf['resolution_summary']}")
    from mlb_engine.allocate.posture_allocator import render_report
    print(render_report(wf))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(wf, indent=1), encoding="utf-8")
        print(f"\njson written: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
