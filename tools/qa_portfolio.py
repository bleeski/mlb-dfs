#!/usr/bin/env python3
"""Adversarial QA over a delivered portfolio. Report, never a gate.

Ben, 2026-08-16: run this after every certified build and try to falsify the
portfolio before uploading it, using data the build did not already price in.

Four sections, in the order that catches the most for the least reading:

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

  4. FIELD-FACING LEVERAGE (R136). Sections 2 and 3 both measure the portfolio
     against the SLATE. Neither says whether the entered set looks like
     everybody else's, which is the axis a satellite is actually won on. This
     section reports cumulative structural chalk against the field's own mean,
     the count of low-owned hitters carried, Showdown captain own-tier, and
     salary left against the archived medians -- per contest, conditioned on
     that contest's archetype and never pooled across them. Its ownership
     inputs are an UNCALIBRATED v0.1 prior, so the sign of a delta is readable
     and its magnitude is not; where the prior is missing the column says
     ABSENT and why, never zero.

Truthful labels are not optional here. Every number this tool prints is a
deterministic review proxy or a labeled prior. Nothing is a probability, a win
rate, a cash rate, or an ROI, and no finding is phrased as one.

Exit codes: 0 always, unless input is unreadable (3). This tool does not gate;
it informs a human decision and a possible second build.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SLOTS = ("P", "C", "1B", "2B", "3B", "SS", "OF")

# R136 needs one engine import: the shape-to-archetype projection, which this
# tool reads rather than copies. Run as `python tools/qa_portfolio.py`, sys.path
# starts at tools/ and `mlb_engine` is invisible, which is exactly how the first
# live run of the panel reported the projection ABSENT on a tree where it was
# fine. Same two lines ownership_pred.py already carries.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# R297(d)/R304. Five sites in this file asked `Roster Position == "P"`, the
# CLASSIC pitcher token, and a Showdown export never carries it: every Showdown
# portfolio read as holding zero arms, so the SP-repetition census counted arms
# into their team's stack, the Savant bat table admitted them, the washout axes
# recorded a stack that was partly a pitcher, and the chalk-carry and legend
# counts were taken over the wrong row set. Reports rather than gates, so no
# upload was blocked -- the same falsehood with a smaller blast radius.
# `preflight_upload` owns the predicate and imports no third-party module, so it
# is imported rather than restated; `verify_export` already imports from it.
# Imported by its package path, not off `tools/` on sys.path: run as a
# script this file already puts REPO_ROOT first, and a bare
# `import preflight_upload` would bind a SECOND module object under a
# second name whenever anything else has imported it as
# `tools.preflight_upload` -- two copies of one predicate, which is the
# shape the import exists to avoid.
from tools.preflight_upload import is_pitcher_row  # noqa: E402


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


def sha256_of(path: Path) -> str:
    """Digest of one file, or "" when it cannot be read.

    Used to ask whether a prediction priced the salary file under review. DK
    re-publishes salaries during the day, and a prior emitted from the earlier
    download prices a pool that is no longer this one.
    """
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


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
    lines.extend(per_contest_lines(brief))
    return lines


def per_contest_lines(brief: dict) -> List[str]:
    """R239(c). No clean verdict on a Showdown brief with no per-contest slice.

    A missing block is a REFUSAL and not a silent pass. The whole finding is that
    every portfolio counter can read clean on a file that duplicated captains
    inside two contests, so a qa run that cannot see the slice cannot say the
    portfolio is clean -- it can only say it does not know, which is what these
    lines make it say.

    Classic is exempt: `contest_allocator` already enforces
    `no_duplicates_within_contest` by default, and the per-contest captain slice
    is a Showdown-path concept (there is no multiplier slot to duplicate).
    """
    if (brief.get("contest_type") or "").lower() != "showdown":
        return []
    pc = brief.get("per_contest")
    if not pc:
        return ["PER-CONTEST SLICE ABSENT: this brief predates R239(c) or was "
                "built without a contest partition. No clean verdict is "
                "available -- the portfolio counters cannot see duplication "
                "inside a contest, which is the finding they missed on "
                "2026-08-28."]
    if not pc.get("available"):
        return [f"PER-CONTEST SLICE UNAVAILABLE: {pc.get('reason') or 'unstated'}. "
                f"No clean verdict is available."]
    out = [f"per contest: {pc.get('multi_entry_contests', 0)} multi-entry of "
           f"{pc.get('contests', 0)}, cap {pc.get('max_cpt_per_contest')} "
           f"captain(s) per contest"]
    for cid, b in sorted((pc.get("by_contest") or {}).items()):
        if b["n"] < 2:
            continue
        repeats = ", ".join(f"{p} x{c}" for p, c in b["captain_counts"].items() if c > 1)
        out.append(
            f"  {cid}: {b['distinct_captains']} distinct CPT / {b['n']} entries"
            f", max overlap {b['max_pairwise_overlap']}"
            f", {b['team_shape_spread']} team shape(s)"
            + (f"; {repeats}" if repeats else "; no captain repeats")
            + ("  <-- OVER CAP" if b["over_cap"] else ""))
    if pc.get("over_cap"):
        out.append(f"PER-CONTEST CAP BREACHED in {len(pc['over_cap'])} slot(s): "
                   f"NOT clean, whatever the portfolio counters say")
    return out


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
            if is_pitcher_row(p):
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
                if p and not is_pitcher_row(p):
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

def frontier_from_brief(brief: dict) -> List[str]:
    """R126's block, read from the artifact rather than recomputed here.

    The run computes apex and washout off its own ``Ceiling`` column, which this
    tool does not have: it reads a delivered CSV and a salary file, and neither
    carries a projection. So the run's numbers lead, and the structural axes
    below stay as an INDEPENDENT check off the delivered bytes.

    They are not two answers to one question and must not be read as
    disagreeing: the run's washout is a ceiling counterfactual (zero a game's
    bats, keep the arms, what percent of portfolio ceiling survives), the axes
    below are share-of-portfolio counts. Different units, same objective. What
    section 1 exists to enforce applies here too -- when the artifact states a
    number, the artifact wins over anything this tool infers.
    """
    frontier = ((brief.get("exposure") or {}).get("frontier")) or {}
    if not frontier:
        return ["THE RUN'S OWN FRONTIER: absent from this brief. Either the "
                "build predates R126 or it entered somewhere other than "
                "run_slate; the structural axes below are all there is."]
    if not frontier.get("available"):
        return [f"THE RUN'S OWN FRONTIER: unavailable "
                f"({frontier.get('unavailable_reason')})"]
    apex = frontier.get("apex") or {}
    out = [
        f"APEX (run's own Ceiling column): total {apex.get('ceiling_total')}, "
        f"mean {apex.get('ceiling_mean')} per entry, best single entry "
        f"{apex.get('ceiling_best')} ({apex.get('best_entry_id')}), worst "
        f"{apex.get('ceiling_worst')}."
    ]
    if frontier.get("unpriced_roster_players"):
        out.append(
            f"APEX IS SHORT: {len(frontier['unpriced_roster_players'])} rostered "
            f"player(s) carry no Ceiling, so every total above understates. Do "
            f"not compare this apex to another build's until the join is fixed.")
    wash = frontier.get("washout") or {}
    if wash.get("available"):
        # R247(c). This tool used to print the bare "N/n entries untouched" and
        # read nothing else, which made the adversarial reviewer the loudest
        # publisher of the one number R247(c) exists to correct: on 1605_2g the
        # weaker of two builds showed 2 of 7 untouched against the stronger
        # one's 1 of 7, and its second untouched entry was the $10,300
        # salary-left lineup. The split leads and the raw count follows it.
        intact = wash.get("entries_fully_intact_at_binding_game")
        by_design = wash.get("entries_intact_by_design_at_binding_game")
        degraded = wash.get("entries_intact_but_degraded_at_binding_game")
        ambiguous = wash.get("entries_intact_proxy_only_at_binding_game")
        untouched = f"{intact}/{frontier.get('entries')} entries untouched"
        if by_design is None:
            untouched += (" (this brief predates R247(c), so the count is NOT "
                          "split and a degraded entry in it reads as a hedge)")
        elif degraded or ambiguous:
            # by_game is sorted worst-first, so row 0 IS the binding game. Read
            # defensively anyway: this tool reads an artifact it did not write.
            binding_row = (wash.get("by_game") or [{}])[0]
            untouched += f", of which {by_design} by DESIGN"
            if degraded:
                untouched += (
                    f" and {degraded} DEGRADED: "
                    f"{binding_row.get('intact_but_degraded_entry_ids')} "
                    f"survived by having nothing at stake, which is a cost "
                    f"being counted as protection")
            if ambiguous:
                untouched += (
                    f" and {ambiguous} LOW-PROXY ONLY: "
                    f"{binding_row.get('intact_proxy_only_entry_ids')} spent "
                    f"the cap and still score low, which on a slate whose "
                    f"binding game carries the most ceiling cannot tell a "
                    f"hedge from a bad build")
        else:
            untouched += f", all {by_design} by DESIGN"
        out.append(
            f"WASHOUT binds on {wash.get('binding_game')}: zeroing that game's "
            f"bats and keeping the arms retains "
            f"{wash.get('worst_ceiling_retained_pct')}% of portfolio ceiling, "
            f"with {untouched}.")
        for row in (wash.get("by_game") or [])[:6]:
            out.append(
                f"  {row.get('game')}: retains {row.get('ceiling_retained_pct')}%, "
                f"{row.get('entries_materially_exposed')}/{frontier.get('entries')} "
                f"entries materially exposed, bats-per-entry "
                f"{row.get('bats_histogram')}")
        out.append(
            "The histogram is the part to read. A portfolio whose every entry "
            "draws bats from the binding game has nothing left when that game "
            "goes cold, and the retained percent alone will not say so -- on "
            "2026-08-15's 2138_2g the rejected and delivered builds posted the "
            "SAME apex and the SAME retained percent.")
        out.append(
            "ceiling_retained_pct falls as the slate shrinks, so it is not "
            "comparable across slates; entries untouched by DESIGN is.")
    else:
        out.append(f"WASHOUT: unavailable ({wash.get('unavailable_reason')})")
    # R247(a)+(c). The two new blocks, read from the artifact on the same rule as
    # everything above: when the brief states a number, the brief wins.
    deg = frontier.get("degraded_entries") or {}
    if deg.get("available"):
        bars = deg.get("bars") or {}
        if deg.get("flagged"):
            out.append(
                f"DEGRADED TAIL: {deg.get('flagged_count')}/{deg.get('entries')} "
                f"entries flagged against archive-derived bars "
                f"(salary-left > ${bars.get('salary_left')}, or proxy "
                f"{bars.get('proxy_margin_pct')}% below the portfolio median "
                f"{deg.get('median_proxy')}). A REPORT, never a gate: every "
                f"relaxation counter reads clean on exactly this failure.")
            for d in (deg.get("flagged") or [])[:6]:
                out.append(
                    f"  {d.get('entry_id')}: {d.get('triggers')}, "
                    f"${d.get('salary_left')} left ({d.get('salary_left_bin')}), "
                    f"proxy {d.get('proxy')}"
                    + (f", {d.get('proxy_pct_below_median')}% below median"
                       if d.get("proxy_pct_below_median") is not None else ""))
        else:
            out.append(
                f"DEGRADED TAIL: none. 0/{deg.get('entries')} entries past "
                f"${bars.get('salary_left')} salary-left or "
                f"{bars.get('proxy_margin_pct')}% below the median proxy "
                f"{deg.get('median_proxy')}.")
    block = frontier.get("correlated_block") or {}
    if block.get("available"):
        trip = block.get("worst_triple") or {}
        pair = block.get("worst_pair") or {}
        n = block.get("entries")
        out.append(
            f"CORRELATED BLOCK: worst triple {trip.get('players')} in "
            f"{trip.get('entries_sharing')}/{n} entries "
            f"({trip.get('entries_sharing_pct')}%); worst pair "
            f"{pair.get('entries_sharing')}/{n}; "
            f"{block.get('entries_with_at_most_one_of_top_trio')}/{n} entries "
            f"carry at most one of the top trio {block.get('top_trio')}.")
        out.append(
            "This is the washout objective's own axis and no cap measures it: "
            "max_shared_players bounds one PAIR of lineups and the exposure "
            "caps bound one PERSON, so a block of three in most of the entered "
            "set passes both and still fails as one thing.")
    return out


#: R343. Hitters from one team that make an entry materially exposed to it.
#: The same value `contest_allocator.TEAM_EXPOSURE_MIN_HITTERS` enforces the cap
#: at, spelled here because this tool reads delivered bytes and imports no
#: engine; a test pins the two equal.
TEAM_FOOTPRINT_MATERIAL = 2


def section_frontier(
    sal: Dict[str, dict], hdr: List[str], body: List[List[str]]
) -> List[str]:
    """Both ends of Ben's dual objective, as deterministic review proxies."""
    n = len(body)
    if not n:
        return []
    axes: Dict[str, Dict[str, int]] = {
        "game": defaultdict(int), "stack_team": defaultdict(int),
        # R343. `stack_team` counts each entry's HEAVIEST team and only at 3+,
        # so a team reaching two-thirds of the portfolio as a 2-3 bat secondary
        # is invisible on this line -- which is how 1310_9g delivered NYY in 17
        # of 21 entries with the washout section reporting something else as
        # binding. This axis counts EVERY team an entry holds
        # `TEAM_FOOTPRINT_MATERIAL`+ hitters from, which is the same threshold
        # the `max_team_exposure_pct` cap is enforced at.
        "team_footprint": defaultdict(int),
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
            if is_pitcher_row(p):
                sps.add(p["Name"])
            else:
                tm[p["TeamAbbrev"]] += 1
        if tm:
            top = max(tm.items(), key=lambda kv: kv[1])
            if top[1] >= MATERIAL:
                axes["stack_team"][top[0]] += 1
        for t, c in tm.items():
            if c >= TEAM_FOOTPRINT_MATERIAL:
                axes["team_footprint"][t] += 1
        for g, c in gm.items():
            if c >= MATERIAL:
                axes["game"][g] += 1
        for s in sps:
            axes["starting_pitcher"][s] += 1

    out = ["INDEPENDENT STRUCTURAL CHECK off the delivered bytes, in "
           "share-of-portfolio counts rather than ceiling. Deterministic "
           "properties of the entered set, not probabilities and not outcome "
           "estimates.",
           # R126, stated rather than left to be read as a bug. On the archived
           # 06-03 grid the run reported 16/18 materially exposed to SD@PHI and
           # this axis reports 18/18, and both are right about what they count.
           "The 'game' axis below counts EVERY roster spot in a game, arms "
           "included, so it can exceed the run's own count, which zeroes bats "
           "only and keeps the arms on purpose. Whether an arm in a game "
           "belongs in a washout count at all is open (an arm can benefit from "
           "the script that kills the bats); until it is decided, read the "
           "run's number as the bat exposure and this one as the roster "
           "footprint.",
           # R343 / R333. The axes now name the control that binds them, the way
           # `late_swap.py` names one on a refusal. Before this, the washout
           # section reported the game axis as binding and the reader had no way
           # to know from here that a game cap existed at all -- SKILL.md did not
           # mention it either (grep, 0 hits) and the control was unreachable
           # from every production door until R333 wired it.
           f"CONTROLS on these axes: 'game' -> max_game_exposure_pct (slate-"
           f"wide scalar, ships OFF) or max_game_exposure_pct_by_game (per "
           f"game); 'team_footprint' -> max_team_exposure_pct, counted at "
           f"{TEAM_FOOTPRINT_MATERIAL}+ hitters from one team in an entry, any "
           f"stack role; 'stack_team' -> max_primary_stack_exposure_pct, which "
           f"counts the PRIMARY stack only and is why 'team_footprint' can run "
           f"far above it; 'starting_pitcher' -> max_pitcher_exposure_pct."]
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


# ---------------------------------------------------------------- section 4

SHOWDOWN_SLOTS = ("CPT", "UTIL")
DK_SALARY_CAP = 50000.0
SUB10_THRESHOLD_PCT = 10.0

# Ledger 3.17/3.18, OBSERVED OUTCOMES from the mined archive, never predictions
# and never a target to build toward. Medians of salary left unspent.
SALARY_LEFT_MEDIANS = {
    "Classic": "winners $250, field $200, our own past entries $100",
    "Showdown": "winners $200, field $300, our own past entries $300",
}
# Ledger 3.17, paired cumulative-ownership delta (winner minus that contest's
# field mean), median percentage points, by the ledger's own contest families.
# Printed whole rather than matched to the resolved archetype: the ledger's
# families are a THIRD vocabulary, and projecting shapes onto it as well would
# put two lossy joins under one number.
LEDGER_CUM_OWN_DELTAS = ("Classic satellites +4.9, solo shots +9.5, "
                         "single-entry GPPs +8.6, mini-MAX +1.1, "
                         "supersatellites -13.2")


def is_showdown_header(hdr: List[str]) -> bool:
    return "CPT" in hdr


def showdown_cpt_to_util(sal: Mapping[str, Mapping[str, str]]) -> Dict[str, str]:
    """{CPT draftable id: the same person's UTIL id} from the salary file.

    R235. An entry row names its captain by CPT id; a prediction file is keyed
    by the person's UTIL id, because ``ownership_pred`` collapses the two roles
    at intake so its counts are counts of people. Looking a CPT id up in the
    prior therefore misses every captain unless the roles are rejoined here,
    which is what this does -- from DK's own salary file, using the engine's
    person key rather than a fourth local copy of "same name, same team".

    Only ever called from section 4, which has already returned if the engine
    will not import.
    """
    from mlb_engine.intake.slate_intake_manager import showdown_person_key
    by_person: Dict[str, Dict[str, str]] = defaultdict(dict)
    for pid, row in sal.items():
        role = str(row.get("Roster Position") or "").strip().upper()
        if role in ("CPT", "UTIL"):
            key = showdown_person_key(row.get("Name"), row.get("TeamAbbrev"))
            by_person[key][role] = str(pid)
    return {roles["CPT"]: roles["UTIL"] for roles in by_person.values()
            if "CPT" in roles and "UTIL" in roles}


def entry_slot_ids(hdr: List[str], row: List[str]) -> Tuple[List[str], Optional[str]]:
    """(all rostered ids, captain id or None) for one entry row.

    Classic reuses ``lineup_players``. Showdown is read here rather than by
    widening SLOTS, because SLOTS drives sections 2 and 3 and those measure
    stacks and arms against a Classic roster; widening it would make them
    answer for a format they were never written for.
    """
    if not is_showdown_header(hdr):
        return lineup_players(hdr, row), None
    ids: List[str] = []
    captain = None
    for i, col in enumerate(hdr):
        if col not in SHOWDOWN_SLOTS or i >= len(row) or not row[i].strip():
            continue
        pid = row[i].strip().split("(")[-1].rstrip(")")
        ids.append(pid)
        if col == "CPT" and captain is None:
            captain = pid
    return ids, captain


def read_prior(path: Optional[Path]) -> Optional[dict]:
    if not path or not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def find_prior_file(brief: dict, explicit: Optional[str],
                    root: Path) -> Tuple[Optional[Path], str]:
    """(path, how it was resolved). Ambiguity is named, never picked from.

    R70's rule on a new surface: more than one file matching an intake role is
    a question for the operator, not a race won by sort order. The tag path is
    tried first because that is what ``ownership_pred emit`` writes, and the
    glob is the fallback for a hand-named file.
    """
    if explicit:
        return Path(explicit), "operator (--ownership-pred)"
    date = str(brief.get("date") or "")
    if not date:
        return None, "no slate date in the brief, so no default path to try"
    outdir = root / "outputs" / date
    tag = str((brief.get("slate") or {}).get("tag") or "")
    if tag:
        by_tag = outdir / f"ownership_pred_{tag}.json"
        if by_tag.exists():
            return by_tag, f"brief date + slate tag ({date}/{tag})"
    found = sorted(outdir.glob("ownership_pred_*.json"))
    if len(found) == 1:
        return found[0], f"the one prediction file in outputs/{date}/"
    if len(found) > 1:
        return None, ("AMBIGUOUS: " + str(len(found)) + " prediction files in "
                      f"outputs/{date}/ (" + ", ".join(f.name for f in found)
                      + "); pass --ownership-pred to name one")
    return None, f"no prediction file in outputs/{date}/"


def _quantiles(values: Sequence[float]) -> Tuple[float, float, float]:
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = (ordered[mid] if len(ordered) % 2
              else (ordered[mid - 1] + ordered[mid]) / 2.0)
    return ordered[0], median, ordered[-1]


def field_mean_cum_own(own: Mapping[str, float]) -> float:
    """The field's own mean cumulative ownership, as an accounting identity.

    If ``own_p`` is the share of field lineups containing player p, then summing
    cumulative ownership over the field and dividing by the number of lineups
    gives sum_p own_p * (own_p * N) / N = sum_p own_p^2. Exactly, with no
    assumption about how the field builds and no independence anywhere: it is
    the same count taken along the other axis. In percent units that is
    sum(own_pct^2)/100, which is what this returns.
    """
    return sum(v * v for v in own.values()) / 100.0


def section_leverage(
    brief: dict,
    sal: Dict[str, dict],
    hdr: List[str],
    body: List[List[str]],
    prior: Optional[dict],
    prior_path: Optional[Path],
    prior_note: str,
    salary_path: Path,
    archetype_override: Optional[str] = None,
) -> List[str]:
    """R136. Where this portfolio sits against the FIELD, per contest.

    Sections 2 and 3 measure the portfolio against the slate: the market, the
    Savant expectations, and its own internal correlation. None of that says
    whether the entered set looks like everybody else's, which is the axis a
    satellite is actually won on. This section is that third axis, and every
    number in it is a deterministic function of a LABELED PRIOR (v0.1,
    uncalibrated) or of the delivered bytes. Nothing here is an ownership
    measurement, because ownership is not observable before lock.

    Conditioned on contest archetype throughout, never pooled: the same player
    on the same slate has been observed 20-31 percentage points apart across
    archetypes, so a portfolio spanning two contests gets two readings.

    The prose is emitted ONCE and the per-contest lines are numbers. The first
    cut printed every caveat under every contest and a six-contest file ran to
    forty lines of repeated paragraphs, which is how a section stops being read
    at all -- and an unread caveat protects nobody.
    """
    n = len(body)
    if not n:
        return []
    showdown = is_showdown_header(hdr)
    fmt = "Showdown" if showdown else "Classic"
    out: List[str] = [
        f"FIELD-FACING LEVERAGE ({fmt} entries). Sections 2 and 3 measure this "
        f"portfolio against the slate; this measures it against the crowd. "
        f"Every column is a deterministic review proxy over a LABELED PRIOR or "
        f"over the delivered bytes -- never a measured ownership, never a "
        f"probability."]

    # ---- salary discipline. Needs no prior, so it reports even when the rest
    # of the section cannot: an ABSENT panel with nothing in it teaches a
    # reader to skip the whole section.
    left: List[float] = []
    unpriced_rows = 0
    for row in body:
        ids, _ = entry_slot_ids(hdr, row)
        if not ids:
            continue
        spend = 0.0
        short = False
        for pid in ids:
            v = fnum(sal[pid], "Salary") if pid in sal else None
            if v is None:
                short = True
                break
            spend += v
        if short:
            unpriced_rows += 1
            continue
        left.append(DK_SALARY_CAP - spend)
    if left:
        lo, med, hi = _quantiles(left)
        out.append(
            f"SALARY LEFT across {len(left)} entries: ${lo:,.0f} / ${med:,.0f} / "
            f"${hi:,.0f} (min/median/max), {sum(1 for v in left if v <= 0):d} "
            f"spending the full cap.")
        out.append(
            f"  archived {fmt} medians, OBSERVED OUTCOMES from the mined "
            f"archive and not a target: {SALARY_LEFT_MEDIANS[fmt]}. The ledger "
            f"records this as not independent of shape and not acted on.")
    if unpriced_rows:
        out.append(
            f"  SALARY LEFT IS SHORT: {unpriced_rows} entr(ies) hold a player "
            f"the salary file does not price, so they are excluded rather than "
            f"counted at a guessed salary.")

    # ---- everything below needs the prior file.
    if prior is None:
        out.append(f"CHALK-SUM, LOW-OWNED CARRY and CAPTAIN TIER: ABSENT. "
                   f"{prior_note}.")
        out.append("  ABSENT, not zero: emit one with `python "
                   "tools/ownership_pred.py emit --salary <DKSalaries.csv> "
                   "--feed <lineups_feed.json> --odds <slate_bundle.json>` and "
                   "re-run. One fact about this review, so no per-player list "
                   "follows it.")
        return out
    if str(prior.get("schema")) != "ownership_pred/v1":
        out.append(f"CHALK-SUM, LOW-OWNED CARRY and CAPTAIN TIER: ABSENT. "
                   f"{prior_path} is schema {prior.get('schema')!r}, not "
                   f"ownership_pred/v1; this panel will not guess at a layout.")
        return out
    try:
        from mlb_engine.field.ownership_prior import (
            archetype_for_contest_shape as projector)
    except ImportError as exc:  # noqa: BLE001
        out.append(
            f"CHALK-SUM, LOW-OWNED CARRY and CAPTAIN TIER: ABSENT. The "
            f"shape-to-archetype projection lives in "
            f"mlb_engine.field.ownership_prior and will not import here "
            f"({exc}). This panel deliberately carries no second copy of that "
            f"map: two answers to 'which archetype is this contest' is how a "
            f"portfolio gets priced against the wrong crowd.")
        return out

    out.append(f"prior file: {prior_path} ({prior.get('schema')}, prior "
               f"{prior.get('prior_version')}, {prior.get('slate_date')} "
               f"{prior.get('slate_tag')}), resolved by {prior_note}.")
    recorded = str((prior.get("salary_file") or {}).get("sha256") or "")
    actual = sha256_of(salary_path)
    if recorded and actual and recorded != actual:
        out.append(
            f"  PRIOR PRICED A DIFFERENT SALARY FILE: it records sha256 "
            f"{recorded[:12]} and the file under review is {actual[:12]}. DK "
            f"re-publishes salaries during the day, so every column below is "
            f"computed against a pool that may not be this one. Re-emit before "
            f"reading them.")
    inputs = prior.get("inputs") or {}
    states = {k: bool((inputs.get(k) or {}).get("applied"))
              for k in ("batting_order", "implied_totals", "probable_sp",
                        "base_projection")}
    out.append("  prior inputs: " + ", ".join(
        f"{k} {'applied' if v else 'INERT'}" for k, v in states.items()))
    if not states["implied_totals"]:
        out.append(
            "  IMPLIED-TOTAL TILT WAS INERT, so every chalk-sum below is a "
            "salary-and-order number wearing a market label. Read it as "
            "structural crowding only.")

    have = prior.get("archetypes") or {}
    shapes = {str(c.get("contest_id")): (str(c.get("contest_shape") or ""),
                                         str(c.get("contest_name") or ""))
              for c in (brief.get("contests") or [])}
    groups: Dict[str, List[List[str]]] = defaultdict(list)
    for row in body:
        groups[(row[2].strip() if len(row) > 2 else "")].append(row)

    # Resolve every contest first, so the read-once prose can be sized to what
    # this file actually contains rather than to what the tool can do.
    resolved: List[Tuple[str, List[List[str]], str, str, str, str]] = []
    deferred: List[str] = []
    for cid in sorted(groups):
        rows = groups[cid]
        shape, cname = shapes.get(cid, ("", ""))
        if not cname and rows and len(rows[0]) > 1:
            cname = rows[0][1].strip()
        label = f"contest {cid or '(no id)'} '{cname[:52]}' | {len(rows)} entries"
        if archetype_override:
            archetype, exactness = archetype_override, "OPERATOR"
        else:
            projected = projector(shape)
            if projected is None:
                deferred.append(
                    f"{label}: archetype UNRESOLVED"
                    + ("; the brief carries no contest_shape for this id"
                       if not shape else
                       f"; shape {shape!r} is not in the projection map")
                    + ". Not defaulted, because ownership is conditioned on "
                      "archetype and the wrong one is worse than none. Pass "
                      "--archetype to name it.")
                continue
            archetype, exactness = projected
        if archetype not in have:
            deferred.append(
                f"{label}: archetype {archetype!r} ABSENT from the prediction "
                f"file, which carries {', '.join(sorted(have)) or 'none'}. "
                f"Re-emit with --archetype {archetype}.")
            continue
        resolved.append((cid, rows, shape, archetype, exactness, label))

    if resolved and not showdown:
        out.extend(_leverage_legend(sal, have,
                                    sorted({a for _, _, _, a, _, _ in resolved})))
    if showdown:
        out.append(
            "CHALK-SUM and LOW-OWNED CARRY: ABSENT for Showdown, and that is a "
            "property of the prior rather than of this portfolio. The prior "
            "budgets 800% across hitters and 200% across pitchers for a "
            "2-P-plus-8-hitter Classic roster, against a Showdown roster that "
            "seats SIX and pays its captain 1.5x. A percentage off that budget "
            "is not this contest's crowd. R235 closed the other half of this "
            "reason and it is no longer cited: the salary file's two rows per "
            "person (a CPT row and a UTIL row, different ids and different "
            "salaries -- 186 rows for 93 players on the 2026-08-14 NYY@TOR "
            "file) are collapsed to one person at emit, so the budget is no "
            "longer spread over double the rows. The roster shape is what "
            "remains, and it is the prior's own shape.")
        out.append(
            "  CAPTAIN OWN-TIER is what survives, as a RANK. ledger 3.18, "
            "OBSERVED: winner captain %Drafted median 14.8 against a field "
            "median of 13.0, and the top-owned captain won 22 of 85 sampled "
            "contests. Captain chalk is not a leak; captain chalk with nothing "
            "differentiated under it is R139's open question.")

    for cid, rows, shape, archetype, exactness, label in resolved:
        block = have[archetype]
        own = {k: float(v) for k, v in
               (block.get("own_pct_by_player_id") or {}).items()}
        tiers = block.get("tier_by_player_id") or {}
        out.append(f"{label} | {shape or '(no shape)'} -> {archetype} "
                   f"[{exactness}]")
        if exactness == "COLLAPSED":
            out.append("  COLLAPSED: several engine shapes share this "
                       "archetype, so the crowd below is priced for a coarser "
                       "contest than the one entered.")

        if showdown:
            hist: Dict[str, int] = defaultdict(int)
            unknown = 0
            cpt_to_util = showdown_cpt_to_util(sal)
            for row in rows:
                _, cap = entry_slot_ids(hdr, row)
                if cap is None:
                    continue
                # R235. The entry names a ROLE id; the prior is keyed by the
                # person. Fall back to the raw id so a prediction emitted
                # before the collapse still reads.
                tier = tiers.get(cpt_to_util.get(cap, cap), tiers.get(cap))
                if tier is None:
                    unknown += 1
                else:
                    hist[str(tier)] += 1
            if not hist and not unknown:
                continue
            out.append(
                "  captain own-tier: "
                + ", ".join(f"{t} {hist[t]}" for t in ("High", "Mid", "Low")
                            if hist.get(t))
                + (f", not in the prior {unknown}" if unknown else ""))
            continue

        chalks: List[float] = []
        carries: List[int] = []
        missing: Dict[str, str] = {}
        for row in rows:
            ids, _ = entry_slot_ids(hdr, row)
            if not ids:
                continue
            total = 0.0
            carry = 0
            for pid in ids:
                if pid not in own:
                    missing[pid] = (sal.get(pid) or {}).get("Name") or pid
                    continue
                total += own[pid]
                if (not is_pitcher_row(sal.get(pid) or {})
                        and str(tiers.get(pid)) == "Low"):
                    carry += 1
            chalks.append(total)
            carries.append(carry)
        if not chalks:
            continue
        lo, med, hi = _quantiles(chalks)
        field_mean = field_mean_cum_own(own)
        delta = med - field_mean
        out.append(
            f"  chalk-sum {lo:.1f} / {med:.1f} / {hi:.1f} (min/median/max) "
            f"against a field mean of {field_mean:.1f} | DELTA {delta:+.1f} pp, "
            f"chalk-{'positive' if delta >= 0 else 'negative'}")
        if missing:
            names = sorted(missing.values())
            out.append(
                f"  CHALK-SUM IS SHORT: {len(missing)} rostered player(s) carry "
                f"no prediction, so the totals above understate: "
                + ", ".join(names[:8])
                + (f", and {len(names) - 8} more" if len(names) > 8 else "")
                + ". Named per player, because a player missing from a present "
                  "file is one fact per player; a missing FILE is one fact and "
                  "gets no list.")
        hist_carry: Dict[int, int] = defaultdict(int)
        for c in carries:
            hist_carry[c] += 1
        out.append(
            f"  low-owned carry {sum(1 for c in carries if c)}/{len(carries)} "
            f"entries | per-entry counts "
            + "{" + ", ".join(f"{k}: {hist_carry[k]}"
                              for k in sorted(hist_carry)) + "}")

    out.extend(deferred)
    if len(resolved) > 1 and not showdown:
        ranked = []
        for _cid, rows, _, archetype, _, label in resolved:
            own = {k: float(v) for k, v in
                   (have[archetype].get("own_pct_by_player_id") or {}).items()}
            per = []
            for row in rows:
                ids, _cap = entry_slot_ids(hdr, row)
                if ids:
                    per.append(sum(own.get(p, 0.0) for p in ids))
            if per:
                ranked.append((_quantiles(per)[1] - field_mean_cum_own(own),
                               f"contest {_cid}"))
        if len(ranked) > 1:
            ranked.sort()
            out.append(
                f"ACROSS THIS FILE: chalkiest {ranked[-1][1]} at "
                f"{ranked[-1][0]:+.1f} pp, least chalky {ranked[0][1]} at "
                f"{ranked[0][0]:+.1f} pp. This comparison is the one the "
                f"uncalibrated scale supports, because both sides of it are "
                f"the same prior on the same slate.")
    return out


def _leverage_legend(sal: Dict[str, dict], have: Mapping[str, Any],
                     used: Sequence[str]) -> List[str]:
    """The read-once explanation of the two prior-fed columns.

    Sized to the file in hand: the sub-10% arithmetic below is recomputed from
    this slate's own pool rather than quoted, because the whole point of it is
    that the number depends on how many hitter rows the budget is spread over.
    """
    rows = [pid for pid, r in sal.items() if not is_pitcher_row(r)]
    priced = [pid for pid in rows
              if any(pid in (have[a].get("own_pct_by_player_id") or {})
                     for a in used)]
    out = [
        "HOW TO READ THE TWO PRIOR COLUMNS (once, not per contest):",
        "  CHALK-SUM is an entry's cumulative predicted %Drafted, against the "
        "field's own mean. That mean is an accounting identity and not a "
        "simulation: over a field whose player shares are own_p, mean "
        "cumulative ownership is exactly sum(own_p^2), the same count taken "
        "along the other axis, assuming nothing about how the field builds.",
        "  Read the SIGN and the ORDER, not the magnitude. This prior is "
        "uncalibrated and its first grade (R135, archived 06-03 grid) posted a "
        "mean signed error of -10.44 points, so it under-concentrates, while "
        "ledger 3.17's winner-minus-field medians are on the actual %Drafted "
        "scale (OBSERVED: " + LEDGER_CUM_OWN_DELTAS + "). The two scales do "
        "not meet until the prior is fit; comparing this file's contests to "
        "each other is what the prior does support.",
    ]
    if priced:
        # Per ROW, taking each row's largest share across the archetypes in
        # play. Summing across archetypes instead reported "852 of 852" for a
        # 284-row pool priced three ways, which is a row count multiplied by an
        # archetype count and reads as a pool four times the real one.
        best = {pid: max(float(have[a]["own_pct_by_player_id"][pid])
                         for a in used
                         if pid in have[a].get("own_pct_by_player_id", {}))
                for pid in priced}
        top = max(best.values()) if best else 0.0
        under = sum(1 for v in best.values() if v < SUB10_THRESHOLD_PCT)
        out.append(
            f"  LOW-OWNED CARRY counts bottom-TIER hitters (the prior's own "
            f"'Low', bottom 40% of the hitter pool by predicted share), not "
            f"3.17's absolute sub-10%, because the two are not on one scale: "
            f"this prior spreads 800% over {len(priced)} priced hitter rows, "
            f"and at its most concentrated archetype in this file the top "
            f"hitter reaches {top:.1f}% with {under} of {len(best)} rows under "
            f"10%. Where "
            f"that is every row, the literal count returns 8-of-8 on every "
            f"entry, which is a constant and not a column. The tier is a "
            f"within-pool percentile and survives an uncalibrated scale; the "
            f"absolute count returns with the fitted model.")
    out.append(
        "  What the carry counts is the OPPORTUNITY for ledger 3.17's pattern, "
        "never the pattern: 3.17 measured a player who finished top-5 in "
        "contest FPTS while under 10% drafted (winners carried one in 51% of "
        "contests against a 13% field base rate), and which player scores is "
        "not knowable before lock. A zero in every entry has foreclosed the "
        "pattern; a high count is a punt count, not a win.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entries", required=True, help="delivered DKEntries CSV")
    ap.add_argument("--salary", required=True, help="DKSalaries CSV for the slate")
    ap.add_argument("--brief", required=True, help="build_brief JSON for the run")
    ap.add_argument("--reference-dir", default="data/reference")
    ap.add_argument("--ownership-pred", default=None,
                    help="ownership_pred/v1 JSON for this slate; default is "
                         "outputs/<brief date>/ownership_pred_<slate tag>.json")
    ap.add_argument("--archetype", default=None,
                    help="force the prior archetype for every contest in the "
                         "file, instead of projecting it from each contest's "
                         "shape in the brief")
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
    # R126. The run's own measurement leads and this tool's structural axes
    # follow as an independent check. Recomputing a second washout number here
    # off data that carries no Ceiling would put two answers on one screen with
    # nothing saying which one the build actually used.
    frontier = frontier_from_brief(brief) + section_frontier(sal, hdr, body)
    # R136. The third axis: sections 2 and 3 measure this portfolio against the
    # slate, this one measures it against the crowd. Its inputs are a labeled
    # prior and the delivered bytes, and every column it cannot compute says
    # ABSENT with the reason rather than reporting a zero.
    prior_path, prior_note = find_prior_file(
        brief, a.ownership_pred, REPO_ROOT)
    prior = read_prior(prior_path)
    if prior_path is not None and prior is None:
        prior_note = f"{prior_path} is not readable JSON"
    leverage = section_leverage(brief, sal, hdr, body, prior, prior_path,
                                prior_note, Path(a.salary), a.archetype)

    if a.as_json:
        print(json.dumps({
            "entries": len(body), "applied": applied,
            "findings": findings, "frontier": frontier,
            "leverage": leverage,
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
    print("\n-- 4. FIELD-FACING LEVERAGE --")
    for line in leverage:
        print(f"  {line}")
    print("\nlabels: deterministic review proxies and labeled priors only; "
          "never ROI, win rate, cash rate, or probability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
