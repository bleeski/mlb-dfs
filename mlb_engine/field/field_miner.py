"""field_miner.py — full-field standings decomposition for MLB Classic (untracked).

STATUS: review-only companion, deliberately OUTSIDE the audited engine and
outside the 26-file cap, on the same footing as ownership_prior.py and
fetch_slate_bundle.py. Both open tracked slots stay reserved for the fitted
ownership model (see ownership_prior.py header and Backlog B-8). Nothing here
touches tracked engine bytes.

TRUTHFUL LABELS: every output of this module is either an observed outcome
read directly from a DK standings export or a deterministic descriptive
statistic computed from those observations. None of it is ROI, profitability,
win rate, cash rate, Perfect%, or a probability claim. The duplication-risk
scorer is a STRUCTURAL REVIEW PROXY: it reports features and flags, never a
duplication probability, and it is never auto-applied to candidate selection,
projections, or the optimizer. Field-frequency tables become usable as
structural priors only after patterns repeat across archetype-conditioned
slates (ledger Section 2 repeat gate); a single contest never promotes one.

WHY THIS EXISTS: the DK standings export carries the complete lineup of every
entrant in the Lineup column, not just %Drafted. The ledger's signal-rate
table classifies winning-lineup shape as one-observation-per-contest data.
Field construction is N-per-contest data: a 222-entry contest yields 222
lineup observations of how the field builds (stack shapes, salary usage,
SP pairing, exact-lineup duplication). This module turns each archived
standings export into:

  1. a full-field decomposition (per-entry construction features),
  2. field-frequency tables (duplication distribution, SP-pair frequency,
     stack-size histogram, salary-left histogram, chalk concentration),
  3. an opponent-recurrence registry keyed on EntryName usernames
     (small recurring fields have regulars; EntryName identifies them),
  4. a paste-ready ledger archive block, and
  5. a structural duplication-risk screen for candidate lineups.

PARSING CONTRACT (ledger invariant 3.1): standings schema is
  Rank, EntryId, EntryName, TimeRemaining, Points, Lineup, <empty>,
  Player, Roster Position, %Drafted, FPTS
read with encoding="utf-8-sig" (exports may carry a BOM), positionally,
never DictReader. The left block (cols 0-5) is per-entry; the right block
(cols 7-10) is per-player; either block may be longer than the other.
The right block is grained per (player, roster position): a multi-position
player appears once per drafted slot and his rows SUM to his total field
share, so mine_contest aggregates %Drafted to player grain and the raw
split is preserved in player_table. Points of 0.0 is a real
zeroed/withdrawn/late entry, not a parse error, and
its Lineup may be empty. EntryName of the form "name (4/4)" flags a
multi-entry contest. The salary CSV is authoritative for salary and team;
the join is by normalized name with collisions kept at the higher salary and
reported, mirroring the crosswalk discipline in build_dk_keyed_corrections.

CLI:
  python field_miner.py --standings X.csv [--salary DKSalaries.csv] \
      --contest-id 191787184 --slate-date 2026-06-29 \
      [--registry field_opponent_registry.json] [--emit-ledger] [--json out.json]
  python field_miner.py --selftest

Coverage tiers: with --salary the run is `full`. Without it the run is
`standings_only`: duplication tables, winner copies, chalk scores, SP pairs
(the slot tokens identify pitchers), top-owned, the ownership recompute
self-check, and the opponent registry all survive; salary-usage, stack, and
cheap-count tables report unavailable. Ben's uploaded DKEntries file embeds
the full slate salary block, so a retained DKEntries upload is a complete
salary-file recovery path for a past slate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "0.3-review"
SALARY_CAP = 50000
ROSTER_SLOTS = ("P", "C", "1B", "2B", "3B", "SS", "OF")
EXPECTED_SLOT_COUNTS = {"P": 2, "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3}
AT_CAP_SALARY_LEFT = 100          # policy constant: "at the cap" band, dollars left
SALARY_LEFT_BINS = (0, 100, 300, 700, 1500)  # bin edges for the salary-left histogram
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_ENTRYNAME_SEQ = re.compile(r"^(?P<user>.*?)\s*\((?P<k>\d+)\s*/\s*(?P<n>\d+)\)\s*$")

REVIEW_LABEL = (
    "deterministic review proxy / observed outcome; not ROI, win rate, "
    "or a probability claim; never auto-applied"
)


# ---------------------------------------------------------------------------
# Name normalization (local, stdlib-only; mirrors the crosswalk philosophy)
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace(".", " ").replace("'", "").replace("-", " ")
    toks = [t for t in s.split() if t]
    while toks and toks[-1] in _SUFFIXES:
        toks.pop()
    return " ".join(toks)


# ---------------------------------------------------------------------------
# Standings export parsing (positional, utf-8-sig; ledger invariant 3.1)
# ---------------------------------------------------------------------------

def parse_lineup_string(lineup: str) -> Tuple[List[Tuple[str, str]], bool]:
    """Parse a DK Lineup cell into [(slot, name), ...].

    Returns (players, is_complete). A complete MLB Classic lineup has the
    slot multiset 2P/1C/1B/2B/3B/SS/3OF. Empty or partial strings (zeroed or
    withdrawn entries) return ([], False) or a partial list flagged False.
    """
    toks = str(lineup or "").split()
    out: List[Tuple[str, str]] = []
    slot: Optional[str] = None
    buf: List[str] = []
    for t in toks:
        if t in ROSTER_SLOTS:
            if slot is not None and buf:
                out.append((slot, " ".join(buf)))
            slot, buf = t, []
        else:
            buf.append(t)
    if slot is not None and buf:
        out.append((slot, " ".join(buf)))
    counts = Counter(s for s, _ in out)
    complete = (len(out) == 10 and all(counts.get(k, 0) == v for k, v in EXPECTED_SLOT_COUNTS.items()))
    return out, complete


def _parse_pct(cell: str) -> Optional[float]:
    s = str(cell or "").strip().replace("%", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_standings_export(path: str) -> Dict[str, Any]:
    """Read a DK contest-standings CSV into entry rows and the player table."""
    entries: List[Dict[str, Any]] = []
    players: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        raise ValueError(f"empty standings export: {path}")
    header = [c.strip() for c in rows[0]]
    if not (len(header) >= 6 and header[0] == "Rank" and header[1] == "EntryId"):
        raise ValueError(
            "unexpected standings header; expected positional schema "
            "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,"
            "Roster Position,%Drafted,FPTS (see ledger 3.1)"
        )
    for raw in rows[1:]:
        row = list(raw) + [""] * (11 - len(raw))
        # Left block: an entry row has a non-empty EntryId.
        if str(row[1]).strip():
            name_raw = str(row[2]).strip()
            m = _ENTRYNAME_SEQ.match(name_raw)
            username = m.group("user").strip() if m else name_raw
            declared = int(m.group("n")) if m else 1
            lineup, complete = parse_lineup_string(row[5])
            try:
                points = float(row[4]) if str(row[4]).strip() else None
            except ValueError:
                points = None
            entries.append({
                "rank": str(row[0]).strip(),
                "entry_id": str(row[1]).strip(),
                "entry_name": name_raw,
                "username": username,
                "declared_max_entries": declared,
                "points": points,
                "lineup": lineup,
                "lineup_complete": complete,
                "players_norm": tuple(sorted(normalize_name(n) for _, n in lineup)),
            })
        # Right block: a player row has a non-empty Player cell.
        if len(row) > 10 and str(row[7]).strip():
            try:
                fpts = float(row[10]) if str(row[10]).strip() else None
            except ValueError:
                fpts = None
            players.append({
                "player": str(row[7]).strip(),
                "player_norm": normalize_name(row[7]),
                "roster_position": str(row[8]).strip(),
                "pct_drafted": _parse_pct(row[9]),
                "fpts": fpts,
            })
    return {"entries": entries, "player_table": players, "path": path}


# ---------------------------------------------------------------------------
# Salary join (authoritative for salary and team; ledger invariant 3.1)
# ---------------------------------------------------------------------------

def load_salary_map(path: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    collisions: List[str] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
        name_f = fields.get("name")
        sal_f = fields.get("salary")
        team_f = fields.get("teamabbrev") or fields.get("team")
        id_f = fields.get("id")
        if not (name_f and sal_f):
            raise ValueError("salary CSV missing Name/Salary columns")
        for row in reader:
            nm = normalize_name(row.get(name_f, ""))
            if not nm:
                continue
            try:
                sal = int(float(row.get(sal_f, 0) or 0))
            except ValueError:
                continue
            rec = {
                "name": row.get(name_f, "").strip(),
                "salary": sal,
                "team": (row.get(team_f, "") or "").strip() if team_f else "",
                "player_id": (row.get(id_f, "") or "").strip() if id_f else "",
            }
            if nm in out:
                collisions.append(nm)
                if sal > out[nm]["salary"]:
                    out[nm] = rec  # keep higher salary on collision, mirrored from the crosswalk
            else:
                out[nm] = rec
    out["__collisions__"] = {"names": sorted(set(collisions))}  # type: ignore[assignment]
    return out


# ---------------------------------------------------------------------------
# Per-contest mining
# ---------------------------------------------------------------------------

def _salary_left_bin(left: Optional[int]) -> str:
    if left is None:
        return "unknown"
    edges = SALARY_LEFT_BINS
    if left <= edges[0]:
        return f"<= {edges[0]}"
    for lo, hi in zip(edges, edges[1:]):
        if lo < left <= hi:
            return f"{lo + 1}-{hi}"
    return f"> {edges[-1]}"


def mine_contest(
    standings: Dict[str, Any],
    salary_map: Optional[Dict[str, Dict[str, Any]]] = None,
    contest_id: str = "",
    slate_date: str = "",
    salary_cap: int = SALARY_CAP,
    cheap_threshold: Optional[int] = None,
) -> Dict[str, Any]:
    """Full-field decomposition of one contest. Labels: see REVIEW_LABEL.

    Coverage tiers (mirroring the tail scanner's graceful degradation):
      full           salary_map supplied; every table populated.
      standings_only salary_map is None; duplication, chalk scores, SP pairs,
                     top-owned, the ownership recompute self-check, and the
                     registry inputs all survive. Salary-usage, stack, and
                     cheap-count tables report unavailable.
    """
    entries = standings["entries"]
    ptable = standings["player_table"]
    # DK's player table is grained per (player, roster position): a
    # multi-position player appears once per drafted slot and the rows SUM to
    # his total field share. Aggregate to player grain here; the raw split is
    # preserved in player_table.
    own_rows: Dict[str, List[float]] = defaultdict(list)
    fpts: Dict[str, float] = {}
    disp: Dict[str, str] = {}
    for p in ptable:
        disp.setdefault(p["player_norm"], p["player"])
        if p["pct_drafted"] is not None:
            own_rows[p["player_norm"]].append(p["pct_drafted"])
        if p["fpts"] is not None and p["player_norm"] not in fpts:
            fpts[p["player_norm"]] = p["fpts"]
    own = {nm: round(sum(v), 2) for nm, v in own_rows.items()}

    has_salary = salary_map is not None
    smap = salary_map or {}
    salaries = sorted(v["salary"] for k, v in smap.items() if not k.startswith("__"))
    if cheap_threshold is None and salaries:
        cheap_threshold = salaries[max(0, int(0.10 * (len(salaries) - 1)))]
    cheap_threshold = int(cheap_threshold or 0) if has_salary else None

    complete = [e for e in entries if e["lineup_complete"]]
    unmatched_names: Counter = Counter()

    for e in complete:
        sal_used, team_counts, sp = 0, Counter(), []
        missing = []
        for slot, name in e["lineup"]:
            nm = normalize_name(name)
            rec = smap.get(nm)
            if slot == "P":
                # The slot token identifies the SP pair; the salary join only
                # canonicalizes the name, so the pair survives a missing join.
                sp.append((rec or {}).get("name") or name)
            if not has_salary:
                continue
            if rec is None:
                missing.append(name)
                unmatched_names[name] += 1
                continue
            sal_used += rec["salary"]
            if slot != "P" and rec["team"]:
                team_counts[rec["team"]] += 1
        fully_joined = has_salary and not missing
        e["salary_used"] = sal_used if fully_joined else None
        e["salary_left"] = (salary_cap - sal_used) if fully_joined else None
        e["unmatched"] = missing
        e["sp_pair"] = tuple(sorted(sp))
        stacks = sorted(team_counts.values(), reverse=True)
        e["max_stack"] = (stacks[0] if stacks else 0) if has_salary else None
        e["stack_pattern"] = ("-".join(str(x) for x in stacks) if stacks else "") if has_salary else None
        owned = [own[normalize_name(n)] for _, n in e["lineup"] if normalize_name(n) in own]
        e["chalk_score"] = round(statistics.fmean(owned), 2) if owned else None
        e["n_cheap"] = sum(
            1 for _, n in e["lineup"]
            if smap.get(normalize_name(n), {}).get("salary", 10 ** 9) <= cheap_threshold
        ) if has_salary else None

    # Duplication (exact-lineup, slot-agnostic sorted player set).
    dup_groups: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for e in complete:
        dup_groups[e["players_norm"]].append(e["entry_id"])
    copies_hist = Counter(len(v) for v in dup_groups.values())
    n_dup_entries = sum(len(v) for v in dup_groups.values() if len(v) > 1)
    max_copies = max((len(v) for v in dup_groups.values()), default=0)
    winner = min(
        (e for e in complete if e["points"] is not None),
        key=lambda e: (-(e["points"] or 0.0)),
        default=None,
    )
    winner_copies = len(dup_groups.get(winner["players_norm"], [])) if winner else 0

    # Field-frequency tables.
    sp_pair_freq = Counter(e["sp_pair"] for e in complete if len(e["sp_pair"]) == 2)
    if has_salary:
        stack_hist: Counter = Counter(e["max_stack"] for e in complete)
        salary_left_hist: Counter = Counter(_salary_left_bin(e.get("salary_left")) for e in complete)
        at_cap_n: Optional[int] = sum(
            1 for e in complete if e.get("salary_left") is not None and e["salary_left"] <= AT_CAP_SALARY_LEFT
        )
    else:
        stack_hist, salary_left_hist, at_cap_n = Counter(), Counter(), None
    top_owned = sorted(
        ((disp[nm], pct) for nm, pct in own.items()),
        key=lambda t: -t[1],
    )[:5]

    # Parse/join diagnostics, including the ownership recompute self-check:
    # %rostered recomputed from parsed lineups must track the export's %Drafted.
    n_all, n_complete = len(entries), len(complete)
    roster_counts: Counter = Counter()
    for e in complete:
        for nm in set(e["players_norm"]):
            roster_counts[nm] += 1
    own_diffs: Dict[str, Optional[float]] = {}
    for denom_name, denom in (("all_entries", n_all), ("complete_entries", n_complete)):
        if denom:
            diffs = [abs(100.0 * roster_counts.get(nm, 0) / denom - pct) for nm, pct in own.items()]
            own_diffs[denom_name] = round(max(diffs), 2) if diffs else None
    candidates = [(v, k) for k, v in own_diffs.items() if v is not None]
    if candidates:
        own_recompute_max_diff, own_denominator = min(candidates)
    else:
        own_recompute_max_diff, own_denominator = None, None
    joined = [e for e in complete if not e["unmatched"]]
    join_rate = round(100.0 * len(joined) / n_complete, 1) if (has_salary and n_complete) else None

    return {
        "label": REVIEW_LABEL,
        "version": VERSION,
        "coverage": "full" if has_salary else "standings_only",
        "contest_id": contest_id,
        "slate_date": slate_date,
        "meta": {
            "entries_total": n_all,
            "entries_complete_lineups": n_complete,
            "winning_points": winner["points"] if winner else None,
            "winning_entry_id": winner["entry_id"] if winner else None,
            "multi_entry_flag": any(e["declared_max_entries"] > 1 for e in entries),
        },
        "duplication": {
            "distinct_lineups": len(dup_groups),
            "entries_in_duplicated_lineups": n_dup_entries,
            "share_duplicated_pct": round(100.0 * n_dup_entries / n_complete, 1) if n_complete else None,
            "max_copies": max_copies,
            "copies_histogram": dict(sorted(copies_hist.items())),
            "winner_copies": winner_copies,
        },
        "construction": {
            "cheap_salary_threshold": cheap_threshold,
            "at_cap_entries": at_cap_n,
            "at_cap_share_pct": round(100.0 * at_cap_n / n_complete, 1)
            if (at_cap_n is not None and n_complete) else None,
            "salary_left_histogram": dict(salary_left_hist),
            "max_stack_histogram": dict(sorted(stack_hist.items())),
            "sp_pair_top": [
                {"pair": list(p), "count": c, "field_share_pct": round(100.0 * c / n_complete, 1)}
                for p, c in sp_pair_freq.most_common(8)
            ] if n_complete else [],
            "top_owned": [{"player": n, "pct_drafted": v} for n, v in top_owned],
        },
        "diagnostics": {
            "salary_join_rate_pct": join_rate,
            "unmatched_names_top": unmatched_names.most_common(10),
            "salary_name_collisions": smap.get("__collisions__", {}).get("names", []),
            "ownership_recompute_max_diff_pts": own_recompute_max_diff,
            "ownership_recompute_denominator": own_denominator,
            "ownership_recompute_ok": (own_recompute_max_diff is not None and own_recompute_max_diff <= 1.5),
        },
        "entries": [
            {k: e[k] for k in (
                "entry_id", "username", "points", "salary_used", "salary_left",
                "sp_pair", "max_stack", "stack_pattern", "chalk_score", "n_cheap",
                "players_norm", "lineup_complete",
            )} for e in entries if e["lineup_complete"]
        ],
        "player_table": ptable,
        "own_by_norm": own,
        "fpts_by_norm": fpts,
    }


# ---------------------------------------------------------------------------
# Duplication-risk screen for candidate lineups (STRUCTURAL REVIEW PROXY)
# ---------------------------------------------------------------------------

def score_duplication_risk(
    player_names: Sequence[str],
    salary_map: Optional[Dict[str, Dict[str, Any]]] = None,
    field: Optional[Dict[str, Any]] = None,
    salary_cap: int = SALARY_CAP,
    sp_pair: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Feature/flag screen for a candidate lineup's duplication exposure.

    STRUCTURAL until field-frequency tables from repeated conditioned slates
    exist; with a mined `field` dict it additionally reports the observed
    field share of the candidate's SP pair and the candidate's chalk score
    against that contest's actual ownership. Without a salary_map the
    salary-side features (salary_left, max_stack, at_cap flag) report
    unavailable. Output is features plus flags, never a duplication
    probability. Never auto-applied.
    """
    has_salary = salary_map is not None
    smap = salary_map or {}
    sal_used, teams = 0, Counter()
    missing = []
    if has_salary:
        for name in player_names:
            rec = smap.get(normalize_name(name))
            if rec is None:
                missing.append(name)
                continue
            sal_used += rec["salary"]
            # Slot-agnostic here; pitchers identified by field data or caller context.
            teams[rec["team"]] += 1
    salary_left = (salary_cap - sal_used) if (has_salary and not missing) else None
    max_stack: Optional[int] = (max(teams.values()) if teams else 0) if has_salary else None

    flags: List[str] = []
    if salary_left is not None and salary_left <= AT_CAP_SALARY_LEFT:
        flags.append("at_cap_salary")
    features: Dict[str, Any] = {
        "salary_left": salary_left,
        "max_stack": max_stack,
        "unmatched": missing,
    }
    if field:
        modal_stack = None
        hist = field.get("construction", {}).get("max_stack_histogram") or {}
        if hist:
            modal_stack = max(hist.items(), key=lambda kv: kv[1])[0]
        features["modal_field_stack"] = modal_stack
        if modal_stack is not None and max_stack is not None and max_stack == int(modal_stack):
            flags.append("modal_stack_size")
        own = field.get("own_by_norm", {})
        owned = [own[normalize_name(n)] for n in player_names if normalize_name(n) in own]
        features["chalk_score_vs_field"] = round(statistics.fmean(owned), 2) if owned else None
        sp_pairs = {tuple(x["pair"]): x["field_share_pct"] for x in field.get("construction", {}).get("sp_pair_top", [])}
        share = None
        if sp_pair and len(sp_pair) == 2:
            key = tuple(sorted(smap.get(normalize_name(n), {}).get("name", n) for n in sp_pair))
            share = sp_pairs.get(key)
        features["sp_pair_field_share_pct"] = share
        if share is not None and sp_pairs and share == max(sp_pairs.values()):
            flags.append("chalk_sp_pair")
    return {
        "label": "STRUCTURAL duplication-risk review proxy: features and flags only, "
                 "not a probability; never auto-applied",
        "coverage": "full" if has_salary else "standings_only",
        "features": features,
        "flags": flags,
        "flag_count": len(flags),
    }


# ---------------------------------------------------------------------------
# Opponent-recurrence registry (EntryName usernames across archived contests)
# ---------------------------------------------------------------------------

def update_registry(registry_path: str, mined: Dict[str, Any]) -> Dict[str, Any]:
    reg: Dict[str, Any] = {}
    if os.path.exists(registry_path):
        with open(registry_path, "r", encoding="utf-8") as fh:
            reg = json.load(fh)
    reg.setdefault("_label", "opponent-recurrence registry; observed field behavior; "
                             "record-only, never a prediction")
    users = reg.setdefault("users", {})
    cid = mined["contest_id"] or mined.get("meta", {}).get("winning_entry_id", "unknown")
    dup_ids = set()
    # Recompute duplicated entry ids from players_norm groups.
    groups: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for e in mined["entries"]:
        groups[tuple(e["players_norm"])].append(e["entry_id"])
    for ids in groups.values():
        if len(ids) > 1:
            dup_ids.update(ids)
    for e in mined["entries"]:
        u = users.setdefault(e["username"], {
            "contests": [], "entries": 0, "sum_salary_used": 0, "n_salary": 0,
            "sum_max_stack": 0, "n_stack": 0, "sum_chalk": 0.0, "n_chalk": 0, "dup_entries": 0,
        })
        if cid not in u["contests"]:
            u["contests"].append(cid)
        u["entries"] += 1
        if e["salary_used"] is not None:
            u["sum_salary_used"] += e["salary_used"]
            u["n_salary"] += 1
        if e["max_stack"] is not None:
            u["sum_max_stack"] += e["max_stack"]
            u["n_stack"] = u.get("n_stack", 0) + 1
        if e["chalk_score"] is not None:
            u["sum_chalk"] += e["chalk_score"]
            u["n_chalk"] += 1
        if e["entry_id"] in dup_ids:
            u["dup_entries"] += 1
        u["last_seen"] = mined["slate_date"] or cid
    for u in users.values():
        u["avg_salary_used"] = round(u["sum_salary_used"] / u["n_salary"], 0) if u["n_salary"] else None
        n_stack = u.get("n_stack", 0)
        u["avg_max_stack"] = round(u["sum_max_stack"] / n_stack, 2) if n_stack else None
        u["avg_chalk_score"] = round(u["sum_chalk"] / u["n_chalk"], 2) if u["n_chalk"] else None
    with open(registry_path, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=1, sort_keys=True)
    return reg


# ---------------------------------------------------------------------------
# Ledger archive block emitter
# ---------------------------------------------------------------------------

def emit_ledger_block(mined: Dict[str, Any]) -> str:
    m, d, c, g = mined["meta"], mined["duplication"], mined["construction"], mined["diagnostics"]
    cov = mined.get("coverage", "full")
    lines: List[str] = []
    lines.append(f"#### Full-field decomposition — contest {mined['contest_id'] or 'UNKNOWN'} "
                 f"(field_miner {VERSION}; coverage {cov}; {REVIEW_LABEL})")
    lines.append("")
    lines.append(f"- Entries {m['entries_total']} ({m['entries_complete_lineups']} complete lineups); "
                 f"winning score {m['winning_points']}; multi-entry contest: {m['multi_entry_flag']}.")
    lines.append(f"- Duplication: {d['distinct_lineups']} distinct lineups; "
                 f"{d['share_duplicated_pct']}% of entries sat in a duplicated lineup; "
                 f"max copies {d['max_copies']}; the winning lineup had {d['winner_copies']} cop"
                 f"{'y' if d['winner_copies'] == 1 else 'ies'}. "
                 f"Copies histogram: {d['copies_histogram']}.")
    if c["at_cap_share_pct"] is not None:
        lines.append(f"- Salary usage: {c['at_cap_share_pct']}% of entries within "
                     f"${AT_CAP_SALARY_LEFT} of the cap. Salary-left bins: {c['salary_left_histogram']}.")
    if c["max_stack_histogram"]:
        lines.append(f"- Max-stack histogram: {c['max_stack_histogram']}.")
    if cov == "standings_only":
        lines.append("- Salary-usage and stack tables unavailable at this coverage tier "
                     "(no salary file); re-run at full coverage if the slate salary CSV or the "
                     "slate's DKEntries upload file (which embeds the salary block) surfaces.")
    if c["sp_pair_top"]:
        top = ", ".join(f"{'/'.join(x['pair'])} {x['field_share_pct']}%" for x in c["sp_pair_top"][:4])
        lines.append(f"- SP-pair field share (top): {top}.")
    if c["top_owned"]:
        lines.append("- Chalk (top-5 %Drafted): " + ", ".join(
            f"{t['player']} {t['pct_drafted']}%" for t in c["top_owned"]) + ".")
    join_txt = (f"salary join {g['salary_join_rate_pct']}% of complete entries fully joined; "
                if g["salary_join_rate_pct"] is not None else "salary join n/a (standings_only); ")
    lines.append(f"- Diagnostics: {join_txt}"
                 f"ownership recompute max diff {g['ownership_recompute_max_diff_pts']} pts "
                 f"({'OK' if g['ownership_recompute_ok'] else 'CHECK PARSE'}).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Selftest (synthetic fixtures; asserts the full path)
# ---------------------------------------------------------------------------

def _selftest() -> int:
    tmp = tempfile.mkdtemp(prefix="field_miner_")
    sal_path = os.path.join(tmp, "DKSalaries.csv")
    st_path = os.path.join(tmp, "standings.csv")
    reg_path = os.path.join(tmp, "registry.json")

    pool = [
        ("Braxton Ashcraft", "P", 8800, "PIT"), ("Sean Burke", "P", 7600, "CWS"),
        ("Aaron Nola", "P", 9400, "PHI"), ("Shane Baz", "P", 8200, "TB"),
        ("Endy Rodriguez", "C", 3100, "PIT"), ("J.T. Realmuto", "C", 4600, "PHI"),
        ("Ryan O'Hearn", "1B", 4200, "BAL"), ("Bryce Harper", "1B", 5800, "PHI"),
        ("Bryson Stott", "2B", 4000, "PHI"), ("Chase Meidroth", "2B", 3300, "CWS"),
        ("Miguel Vargas", "3B", 3900, "CWS"), ("Alec Bohm", "3B", 4400, "PHI"),
        ("Konnor Griffin", "SS", 3500, "PIT"), ("Trea Turner", "SS", 5600, "PHI"),
        ("Bryan Reynolds", "OF", 4700, "PIT"), ("Brandon Marsh", "OF", 4100, "PHI"),
        ("Esmerlyn Valdez", "OF", 2800, "PIT"), ("Kyle Schwarber", "OF", 5900, "PHI"),
        ("Sam Antonacci", "OF", 2600, "CWS"), ("Michael Harris II", "OF", 4900, "ATL"),
    ]
    with open(sal_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Position", "Name + ID", "Name", "ID", "Roster Position",
                    "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame"])
        for i, (n, p, s, t) in enumerate(pool):
            w.writerow([p, f"{n} ({30000 + i})", n, 30000 + i, p, s, "X@Y", t, 7.5])

    def lu(*names_by_slot):
        return " ".join(f"{slot} {name}" for slot, name in names_by_slot)

    base = [("P", "Braxton Ashcraft"), ("P", "Sean Burke"), ("C", "Endy Rodriguez"),
            ("1B", "Ryan O'Hearn"), ("2B", "Bryson Stott"), ("3B", "Miguel Vargas"),
            ("SS", "Konnor Griffin"), ("OF", "Bryan Reynolds"), ("OF", "Brandon Marsh"),
            ("OF", "Esmerlyn Valdez")]
    alt = [("P", "Aaron Nola"), ("P", "Shane Baz"), ("C", "J.T. Realmuto"),
           ("1B", "Bryce Harper"), ("2B", "Chase Meidroth"), ("3B", "Alec Bohm"),
           ("SS", "Trea Turner"), ("OF", "Kyle Schwarber"), ("OF", "Sam Antonacci"),
           ("OF", "Ryan O'Hearn")]
    entries = [
        ("1", "9001", "sharkuser (2/2)", "", "150.5", lu(*base)),
        ("2", "9002", "sharkuser (2/2)", "", "150.5", lu(*base)),      # exact duplicate
        ("3", "9003", "casualfan", "", "121.0", lu(*alt)),
        ("4", "9004", "benlee", "", "0.0", ""),                        # zeroed, empty lineup
    ]
    complete_n = 3
    slot_counts: Counter = Counter()
    for _, _, _, _, pts, l in entries:
        players, ok = parse_lineup_string(l)
        if ok:
            for slot, nm in players:
                slot_counts[(nm, slot)] += 1
    with open(st_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup", "",
                    "Player", "Roster Position", "%Drafted", "FPTS"])
        # DK grain: one right-block row per (player, roster position) drafted.
        ptab = sorted(slot_counts.items())
        for i in range(max(len(entries), len(ptab))):
            left = list(entries[i]) if i < len(entries) else ["", "", "", "", "", ""]
            if i < len(ptab):
                (n, slot), cnt = ptab[i]
                pct = round(100.0 * cnt / complete_n, 2)
                right = [n, slot, f"{pct}%", "12.0"]
            else:
                right = ["", "", "", ""]
            w.writerow(left + [""] + right)

    st = parse_standings_export(st_path)
    assert len(st["entries"]) == 4 and len(st["player_table"]) == 20
    assert normalize_name("Michael Harris II") == "michael harris"
    lp, ok = parse_lineup_string(entries[0][5])
    assert ok and len(lp) == 10 and ("1B", "Ryan O'Hearn") in lp and ("C", "Endy Rodriguez") in lp
    lp2, ok2 = parse_lineup_string(entries[2][5])
    assert ok2 and ("C", "J.T. Realmuto") in lp2 and ("OF", "Ryan O'Hearn") in lp2
    smap = load_salary_map(sal_path)
    mined = mine_contest(st, smap, contest_id="TEST-1", slate_date="2026-07-04")
    assert mined["meta"]["entries_complete_lineups"] == 3
    assert mined["duplication"]["distinct_lineups"] == 2
    assert mined["duplication"]["max_copies"] == 2
    assert mined["duplication"]["winner_copies"] == 2
    assert mined["diagnostics"]["salary_join_rate_pct"] == 100.0
    assert mined["diagnostics"]["ownership_recompute_ok"], mined["diagnostics"]
    # Position-split aggregation: O'Hearn drafted at 1B in two entries and OF in
    # one must aggregate to a single 100.0 player-grain share.
    assert mined["own_by_norm"][normalize_name("Ryan O'Hearn")] == 100.0
    top_names = [t["player"] for t in mined["construction"]["top_owned"]]
    assert len(top_names) == len(set(top_names)), "top_owned must be player-grain, not split rows"
    assert {"player": "Ryan O'Hearn", "pct_drafted": 100.0} in mined["construction"]["top_owned"]
    risk = score_duplication_risk([n for _, n in base], smap, field=mined)
    assert "features" in risk and "flags" in risk and "probab" not in json.dumps(risk["flags"])
    reg = update_registry(reg_path, mined)
    assert reg["users"]["sharkuser"]["entries"] == 2 and reg["users"]["sharkuser"]["dup_entries"] == 2
    reg2 = update_registry(reg_path, dict(mined, contest_id="TEST-2"))
    assert reg2["users"]["sharkuser"]["contests"] == ["TEST-1", "TEST-2"]
    block = emit_ledger_block(mined)
    assert "Full-field decomposition" in block and "Duplication" in block
    assert "coverage full" in block

    # Degraded tier: no salary file. Duplication, chalk, SP pairs, and the
    # recompute check must survive; salary and stack tables report unavailable.
    mined_deg = mine_contest(st, None, contest_id="TEST-DEG", slate_date="2026-07-04")
    assert mined_deg["coverage"] == "standings_only"
    assert mined_deg["duplication"] == mined["duplication"]
    assert mined_deg["diagnostics"]["ownership_recompute_ok"]
    assert mined_deg["diagnostics"]["salary_join_rate_pct"] is None
    assert mined_deg["construction"]["at_cap_share_pct"] is None
    assert mined_deg["construction"]["max_stack_histogram"] == {}
    assert mined_deg["construction"]["sp_pair_top"], "SP pairs must survive without salary"
    e0 = next(e for e in mined_deg["entries"] if e["entry_id"] == "9001")
    assert e0["sp_pair"] == ("Braxton Ashcraft", "Sean Burke")
    assert e0["max_stack"] is None and e0["salary_used"] is None
    assert e0["chalk_score"] is not None
    risk_deg = score_duplication_risk([n for _, n in base], None, field=mined_deg)
    assert risk_deg["coverage"] == "standings_only"
    assert risk_deg["features"]["salary_left"] is None and "at_cap_salary" not in risk_deg["flags"]
    reg_path2 = os.path.join(tmp, "registry_deg.json")
    reg_deg = update_registry(reg_path2, mined_deg)
    assert reg_deg["users"]["sharkuser"]["avg_max_stack"] is None
    assert reg_deg["users"]["sharkuser"]["avg_chalk_score"] is not None
    block_deg = emit_ledger_block(mined_deg)
    assert "coverage standings_only" in block_deg and "unavailable at this coverage tier" in block_deg

    print("field_miner selftest: PASS (parse, join, duplication, ownership recompute, "
          "risk screen, registry merge, ledger block, standings_only degraded tier)")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--standings")
    ap.add_argument("--salary", help="slate salary CSV; omit to run the standings_only degraded tier")
    ap.add_argument("--contest-id", default="")
    ap.add_argument("--slate-date", default="")
    ap.add_argument("--registry")
    ap.add_argument("--emit-ledger", action="store_true")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.standings:
        ap.error("--standings is required (or --selftest)")
    st = parse_standings_export(args.standings)
    if args.salary:
        smap: Optional[Dict[str, Dict[str, Any]]] = load_salary_map(args.salary)
    else:
        smap = None
        print("NOTICE: no --salary supplied; running the standings_only degraded tier "
              "(duplication, chalk, SP pairs, registry; no salary or stack tables)")
    mined = mine_contest(st, smap, contest_id=args.contest_id, slate_date=args.slate_date)
    if args.registry:
        update_registry(args.registry, mined)
        print(f"registry updated: {args.registry}")
    if args.json_out:
        slim = {k: v for k, v in mined.items() if k not in ("own_by_norm", "fpts_by_norm")}
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(slim, fh, indent=1, default=list)
        print(f"json written: {args.json_out}")
    if args.emit_ledger:
        print()
        print(emit_ledger_block(mined))
    else:
        g = mined["diagnostics"]
        join_txt = f"join {g['salary_join_rate_pct']}%" if g["salary_join_rate_pct"] is not None else "join n/a"
        print(f"contest {args.contest_id or '?'} [{mined['coverage']}]: "
              f"{mined['meta']['entries_complete_lineups']} complete entries, "
              f"{mined['duplication']['distinct_lineups']} distinct lineups, "
              f"{join_txt}, "
              f"ownership recompute {'OK' if g['ownership_recompute_ok'] else 'CHECK'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
