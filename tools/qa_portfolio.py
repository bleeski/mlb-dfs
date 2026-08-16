#!/usr/bin/env python3
"""Adversarial QA over a delivered portfolio. Report, never a gate.

Ben, 2026-08-16: run this after every certified build and try to falsify the
portfolio before uploading it, using data the build did not already price in.

Three sections, in the order that catches the most for the least reading:

  1. WHAT THE BUILD ACTUALLY APPLIED. Read from the brief's own enrichment
     self-report, not from documentation. This section exists because on
     2026-08-16 a session claimed F1 was neutral, having inferred it from a
     --odds help string, and rebuilt under deadline on that basis. The brief
     in hand said `f1_league_mean_implied_total: 4.125` and every input had
     applied. A diagnosis that contradicts the artifact is wrong about the
     artifact; check here first, always.

  2. ADVERSARIAL CHECKS. Stack allocation against market implied totals, and
     arm and bat allocation against Savant expected stats. Each finding names
     its evidence and its magnitude so it can be argued with.

  3. THE DUAL-OBJECTIVE FRONTIER. Ben's standing objective is to maximize
     large wins while minimizing total washouts. Those are not two independent
     maxima: concentration is what wins a winner-take-all satellite and it is
     also exactly what loses every entry at once. This section measures both
     ends as deterministic review proxies and shows where the portfolio sits.

Truthful labels are not optional here. Every number this tool prints is a
deterministic review proxy or a labeled prior. Nothing is a probability, a win
rate, a cash rate, or an ROI, and no finding is phrased as one.

Exit codes: 0 always, unless input is unreadable (3). This tool does not gate;
it informs a human decision and a possible second build.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SLOTS = ("P", "C", "1B", "2B", "3B", "SS", "OF")


def norm(s: str) -> str:
    d = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in d if c.isalnum() and not unicodedata.combining(c)).lower()


def read_salary(path: Path) -> Dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {r["ID"]: r for r in csv.DictReader(fh)}


def read_entries(path: Path) -> Tuple[List[str], List[List[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    hdr = rows[0]
    body = [r for r in rows[1:] if r and r[0].strip().isdigit()]
    return hdr, body


def lineup_players(hdr: List[str], row: List[str]) -> List[str]:
    out = []
    for i, col in enumerate(hdr):
        if col in SLOTS and i < len(row) and row[i].strip():
            out.append(row[i].strip().split("(")[-1].rstrip(")"))
    return out


def read_savant(path: Optional[Path]) -> Dict[str, dict]:
    if not path or not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            name = r.get("last_name, first_name") or ""
            if "," in name:
                last, first = [p.strip() for p in name.split(",", 1)]
                out[norm(first + last)] = r
    return out


def fnum(r: dict, key: str) -> Optional[float]:
    try:
        return float(r.get(key))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- section 1

def section_applied(brief: dict) -> List[str]:
    """What the build actually applied, from its own self-report."""
    lines = []
    en = brief.get("enrichment") or {}
    if en.get("degraded"):
        lines.append(f"DEGRADED: {en.get('degraded_reason') or 'unspecified'}")
    unapplied = en.get("requested_but_unapplied") or []
    if unapplied:
        lines.append(f"REQUESTED BUT NOT APPLIED: {unapplied}")
    applied = en.get("signal_applied")
    if applied:
        lines.append(f"signal_applied: {json.dumps(applied)[:300]}")
    f1mean = en.get("f1_league_mean_implied_total")
    odds = en.get("f1_odds") or {}
    if f1mean:
        lines.append(
            f"F1 LIVE: league mean implied total {f1mean}, "
            f"source {odds.get('source')}, {odds.get('games_with_moneyline')}"
            f"/{odds.get('games')} games with a moneyline"
        )
    else:
        lines.append("F1 NEUTRAL: no implied totals reached the projections")
    for w in (en.get("warnings") or [])[:6]:
        lines.append(f"enrichment warning: {w}")
    gates = brief.get("gates") or {}
    lines.append(f"gates: {json.dumps(gates)}")
    if brief.get("caller_asserted_gates"):
        lines.append(f"CALLER-ASSERTED (not derived): {brief['caller_asserted_gates']}")
    if brief.get("pool_blockers_overridden"):
        lines.append(f"POOL BLOCKERS OVERRIDDEN: {len(brief['pool_blockers_overridden'])}")
    if brief.get("controls_override_applied"):
        lines.append(f"CONTROLS RELAXED: {brief['controls_override_applied']}")
    else:
        lines.append("controls relaxed: none")
    return lines


# ---------------------------------------------------------------- section 2

def section_adversarial(
    brief: dict, sal: Dict[str, dict], hdr: List[str], body: List[List[str]],
    bat: Dict[str, dict], pit: Dict[str, dict],
) -> List[str]:
    findings = []
    en = brief.get("enrichment") or {}
    implied: Dict[str, float] = en.get("f1_implied_total_by_team") or {}

    stack_ct: Dict[str, int] = defaultdict(int)
    sp_ct: Dict[str, int] = defaultdict(int)
    n = len(body)
    for row in body:
        ids = lineup_players(hdr, row)
        tm: Dict[str, int] = defaultdict(int)
        for pid in ids:
            p = sal.get(pid)
            if not p:
                continue
            if p.get("Roster Position") == "P":
                sp_ct[p["Name"]] += 1
            else:
                tm[p["TeamAbbrev"]] += 1
        if tm:
            top = max(tm.items(), key=lambda kv: kv[1])
            if top[1] >= 3:
                stack_ct[top[0]] += 1

    # Stacks against the market's implied totals.
    if implied and stack_ct:
        slate_teams = {p["TeamAbbrev"] for p in sal.values()}
        ranked = sorted(
            ((t, v) for t, v in implied.items() if t in slate_teams),
            key=lambda kv: -kv[1],
        )
        top_third = {t for t, _ in ranked[: max(1, len(ranked) // 3)]}
        bot_third = {t for t, _ in ranked[-max(1, len(ranked) // 3):]}
        heavy_low = [(t, c, implied.get(t)) for t, c in stack_ct.items() if t in bot_third]
        light_high = [
            (t, stack_ct.get(t, 0), v) for t, v in ranked
            if t in top_third and stack_ct.get(t, 0) <= max(1, n // 12)
        ]
        for t, c, v in sorted(heavy_low, key=lambda x: -x[1]):
            findings.append(
                f"STACK vs MARKET: {t} carries {c}/{n} primary stacks at an implied "
                f"total of {v}, in the slate's bottom third. Concentration in a low "
                f"projected run environment is a deliberate leverage play or an "
                f"oversight; the build cannot tell you which."
            )
        for t, c, v in light_high:
            findings.append(
                f"STACK vs MARKET: {t} implied {v} (slate top third) carries only "
                f"{c}/{n} primary stacks."
            )

    # Arms against Savant xERA.
    if pit:
        for name, c in sorted(sp_ct.items(), key=lambda kv: -kv[1])[:6]:
            r = pit.get(norm(name))
            if not r:
                continue
            era, xera = fnum(r, "era"), fnum(r, "xera")
            if era is None or xera is None:
                continue
            if xera - era >= 0.55:
                findings.append(
                    f"ARM vs SAVANT: {name} at {c}/{n} entries has ERA {era} against "
                    f"xERA {xera} (+{xera - era:.2f}); the surface line is ahead of "
                    f"the contact-quality estimate."
                )

    # Bats against Savant est_woba.
    if bat:
        exp: Dict[str, int] = defaultdict(int)
        for row in body:
            for pid in lineup_players(hdr, row):
                p = sal.get(pid)
                if p and p.get("Roster Position") != "P":
                    exp[p["Name"]] += 1
        for name, c in sorted(exp.items(), key=lambda kv: -kv[1])[:8]:
            r = bat.get(norm(name))
            if not r:
                continue
            woba, est = fnum(r, "woba"), fnum(r, "est_woba")
            if woba is None or est is None:
                continue
            if woba - est >= 0.030 and c / n >= 0.25:
                findings.append(
                    f"BAT vs SAVANT: {name} at {c}/{n} ({c / n:.0%}) has wOBA {woba} "
                    f"against xwOBA {est} ({woba - est:+.3f}); results are ahead of "
                    f"contact quality."
                )
    return findings


# ---------------------------------------------------------------- section 3

def section_frontier(
    sal: Dict[str, dict], hdr: List[str], body: List[List[str]]
) -> List[str]:
    """Both ends of Ben's dual objective, as deterministic review proxies."""
    n = len(body)
    if not n:
        return []
    axes: Dict[str, Dict[str, int]] = {
        "game": defaultdict(int), "stack_team": defaultdict(int),
        "starting_pitcher": defaultdict(int),
    }
    # A lineup is only WASHED OUT by an axis it is materially exposed to. Counting
    # every game a lineup merely touches reported 100% on an 8-game slate where a
    # ten-man roster inevitably reaches most games, which is noise, not a finding.
    MATERIAL = 3
    for row in body:
        ids = lineup_players(hdr, row)
        tm: Dict[str, int] = defaultdict(int)
        gm: Dict[str, int] = defaultdict(int)
        sps = set()
        for pid in ids:
            p = sal.get(pid)
            if not p:
                continue
            gm[(p.get("Game Info") or "").split(" ")[0]] += 1
            if p.get("Roster Position") == "P":
                sps.add(p["Name"])
            else:
                tm[p["TeamAbbrev"]] += 1
        if tm:
            top = max(tm.items(), key=lambda kv: kv[1])
            if top[1] >= MATERIAL:
                axes["stack_team"][top[0]] += 1
        for g, c in gm.items():
            if c >= MATERIAL:
                axes["game"][g] += 1
        for s in sps:
            axes["starting_pitcher"][s] += 1

    out = ["Both proxies are deterministic properties of the entered set, not "
           "probabilities and not outcome estimates."]
    worst = []
    for axis, ct in axes.items():
        if not ct:
            continue
        name, c = max(ct.items(), key=lambda kv: kv[1])
        share = c / n
        worst.append((share, axis, name, c))
        out.append(
            f"washout axis '{axis}': most-shared value is {name} at {c}/{n} "
            f"({share:.0%}). A single adverse outcome on it touches that share "
            f"of the portfolio."
        )
    if worst:
        share, axis, name, c = max(worst)
        out.append(
            f"WASHOUT-EXPOSURE PROXY = {share:.0%} (binding axis '{axis}', {name}). "
            f"Lower means one bad game script takes down less of the entered set."
        )
    stack_ct = axes["stack_team"]
    if stack_ct:
        top_share = max(stack_ct.values()) / n
        out.append(
            f"APEX-CONCENTRATION PROXY = {top_share:.0%} on the heaviest primary "
            f"stack, across {len(stack_ct)} distinct stacks. Higher concentrates "
            f"correlated upside, which is what a winner-take-all ticket needs."
        )
        out.append(
            "These two move together by construction: raising apex concentration "
            "raises washout exposure on the same axis. The build chooses a point on "
            "that frontier, it does not optimize both independently."
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entries", required=True, help="delivered DKEntries CSV")
    ap.add_argument("--salary", required=True, help="DKSalaries CSV for the slate")
    ap.add_argument("--brief", required=True, help="build_brief JSON for the run")
    ap.add_argument("--reference-dir", default="data/reference")
    ap.add_argument("--json", dest="as_json", action="store_true")
    a = ap.parse_args()

    try:
        sal = read_salary(Path(a.salary))
        hdr, body = read_entries(Path(a.entries))
        brief = json.loads(Path(a.brief).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"qa_portfolio: cannot read input: {exc}", file=sys.stderr)
        return 3

    ref = Path(a.reference_dir)
    bat = read_savant(ref / "expected_stats_batting.csv")
    pit = read_savant(ref / "expected_stats_pitching.csv")

    applied = section_applied(brief)
    findings = section_adversarial(brief, sal, hdr, body, bat, pit)
    frontier = section_frontier(sal, hdr, body)

    if a.as_json:
        print(json.dumps({
            "entries": len(body), "applied": applied,
            "findings": findings, "frontier": frontier,
            "labels": "deterministic review proxies and labeled priors only; "
                      "never ROI, win rate, cash rate, or probability",
        }, indent=1))
        return 0

    print(f"qa_portfolio  {len(body)} entries  {Path(a.entries).name}")
    print("\n-- 1. WHAT THE BUILD APPLIED (from the artifact, not the docs) --")
    for line in applied:
        print(f"  {line}")
    print(f"\n-- 2. ADVERSARIAL FINDINGS ({len(findings)}) --")
    if not findings:
        print("  none of the checks fired against this portfolio")
    for line in findings:
        print(f"  * {line}")
    print("\n-- 3. DUAL-OBJECTIVE FRONTIER --")
    for line in frontier:
        print(f"  {line}")
    print("\nlabels: deterministic review proxies and labeled priors only; "
          "never ROI, win rate, cash rate, or probability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
