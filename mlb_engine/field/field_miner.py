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
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

VERSION = "0.5-review"
SALARY_CAP = 50000
ROSTER_SLOTS = ("P", "C", "1B", "2B", "3B", "SS", "OF")
EXPECTED_SLOT_COUNTS = {"P": 2, "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3}

# Showdown is a second roster contract on the same export format, not a second
# format. One captain at 1.5x plus five UTIL, all from one game. Before v0.5 this
# module knew only the Classic slot tokens, so every Showdown lineup parsed to
# zero players and the structural gate — which compared two numbers that were
# both zero — called the result sound. Showdown archetypes never pool with
# Classic in the ledger or the ownership work, so the contest type is carried
# through the emitted block rather than inferred again downstream.
SHOWDOWN_SLOTS = ("CPT", "UTIL")
SHOWDOWN_EXPECTED_SLOT_COUNTS = {"CPT": 1, "UTIL": 5}
ROSTER_CONTRACTS = {
    "classic": {"slots": ROSTER_SLOTS, "expected": EXPECTED_SLOT_COUNTS},
    "showdown": {"slots": SHOWDOWN_SLOTS, "expected": SHOWDOWN_EXPECTED_SLOT_COUNTS},
}

# Withdrawn and zeroed entries legitimately fail to parse, but only a few per
# contest. Past this share the likelier explanation is that the roster contract
# is wrong, and archiving would record a field that was never read.
MAX_UNPARSED_ENTRY_SHARE = 0.20
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

def detect_contest_type(lineups: Sequence[str]) -> str:
    """Return 'showdown' or 'classic' from the lineup cells themselves.

    The export format is identical between the two; only the slot tokens differ,
    and they are disjoint, so counting which vocabulary appears is decisive. Ties
    and empty input fall back to Classic, which is the overwhelmingly common case
    and the assumption every caller made implicitly before v0.5.
    """
    classic_hits = showdown_hits = 0
    for lineup in lineups:
        for token in str(lineup or "").split():
            if token in SHOWDOWN_SLOTS:
                showdown_hits += 1
            elif token in ROSTER_SLOTS:
                classic_hits += 1
    return "showdown" if showdown_hits > classic_hits else "classic"


def parse_lineup_string(lineup: str,
                        contest_type: str = "classic") -> Tuple[List[Tuple[str, str]], bool]:
    """Parse a DK Lineup cell into [(slot, name), ...].

    Returns (players, is_complete). A complete Classic lineup has the slot
    multiset 2P/1C/1B/2B/3B/SS/3OF; a complete Showdown lineup is 1CPT/5UTIL.
    Empty or partial strings (zeroed or withdrawn entries) return ([], False) or
    a partial list flagged False.

    ``contest_type`` selects the roster contract. Parsing a Showdown cell under
    the Classic contract yields ([], False) rather than a wrong answer, because
    the token vocabularies are disjoint — which is safe on its own but was NOT
    safe in aggregate until the structural gate learned to fail on an empty
    parse.
    """
    contract = ROSTER_CONTRACTS.get(str(contest_type or "classic").lower(),
                                    ROSTER_CONTRACTS["classic"])
    slots, expected = contract["slots"], contract["expected"]
    size = sum(expected.values())
    toks = str(lineup or "").split()
    out: List[Tuple[str, str]] = []
    slot: Optional[str] = None
    buf: List[str] = []
    for t in toks:
        if t in slots:
            if slot is not None and buf:
                out.append((slot, " ".join(buf)))
            slot, buf = t, []
        else:
            buf.append(t)
    if slot is not None and buf:
        out.append((slot, " ".join(buf)))
    counts = Counter(s for s, _ in out)
    complete = (len(out) == size
                and all(counts.get(k, 0) == v for k, v in expected.items()))
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
    # Decide the roster contract before parsing anything. The export format is
    # identical for Classic and Showdown and only the slot tokens differ, so the
    # file answers this itself and nobody has to pass a flag that can be wrong.
    contest_type = detect_contest_type(
        (list(raw) + [""] * (11 - len(raw)))[5]
        for raw in rows[1:] if len(raw) > 1 and str(raw[1]).strip()
    )
    for raw in rows[1:]:
        row = list(raw) + [""] * (11 - len(raw))
        # Left block: an entry row has a non-empty EntryId.
        if str(row[1]).strip():
            name_raw = str(row[2]).strip()
            m = _ENTRYNAME_SEQ.match(name_raw)
            username = m.group("user").strip() if m else name_raw
            declared = int(m.group("n")) if m else 1
            lineup, complete = parse_lineup_string(row[5], contest_type)
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
    return {"entries": entries, "player_table": players, "path": path,
            "contest_type": contest_type}


# ---------------------------------------------------------------------------
# Salary join (authoritative for salary and team; ledger invariant 3.1)
# ---------------------------------------------------------------------------

_SALARY_MAP_CACHE: Dict[Tuple[str, int, int], Dict[str, Dict[str, Any]]] = {}


def load_salary_map(path: str) -> Dict[str, Dict[str, Any]]:
    """Load a DK salary CSV into {normalized name: record}, memoized on mtime+size.

    ``resolve_salary_file`` scores every candidate on disk against one contest,
    and the archival loop runs it once per contest. With 102 candidates that is
    102 CSV parses per contest and roughly ten seconds each, which put a full
    registry rebuild over three minutes for twenty-one contests. The cache key
    is (path, mtime_ns, size), so a file edited between calls is reloaded and a
    stale map is never served.

    Showdown needs a second key. DK ships each Showdown player TWICE, once as
    CPT at 1.5x and once as UTIL at base, so a name-keyed map has a collision on
    literally every player. The pre-v0.5 collision rule kept the higher salary,
    which is always the captain row, and a six-man lineup that cost $82,100
    joined at $111,900 because five of its six slots were charged captain
    prices. Every salary-derived table downstream was wrong by that much.

    So for a Showdown file the map carries both layers: the flat name key holds
    the UTIL (base) record, which is what the cheap-count and SP-pair lookups
    want, and ``"<name>|<slot>"`` holds the exact per-slot price for the entry
    salary math. Classic files are unchanged and keep only the flat key, because
    Classic Roster Position is a multi-position token like "OF/1B" and keying on
    it would break the join it is supposed to fix.
    """
    try:
        stat = os.stat(path)
        cache_key: Optional[Tuple[str, int, int]] = (
            str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        cache_key = None
    if cache_key is not None and cache_key in _SALARY_MAP_CACHE:
        return _SALARY_MAP_CACHE[cache_key]

    out: Dict[str, Dict[str, Any]] = {}
    collisions: List[str] = []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
        name_f = fields.get("name")
        sal_f = fields.get("salary")
        team_f = fields.get("teamabbrev") or fields.get("team")
        id_f = fields.get("id")
        slot_f = fields.get("roster position")
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
            rows.append({
                "norm": nm,
                "slot": (row.get(slot_f, "") or "").strip().upper() if slot_f else "",
                "rec": {
                    "name": row.get(name_f, "").strip(),
                    "salary": sal,
                    "team": (row.get(team_f, "") or "").strip() if team_f else "",
                    "player_id": (row.get(id_f, "") or "").strip() if id_f else "",
                },
            })

    slots_seen = {r["slot"] for r in rows}
    is_showdown = bool({"CPT", "UTIL"} & slots_seen) and "UTIL" in slots_seen
    for r in rows:
        nm, slot, rec = r["norm"], r["slot"], r["rec"]
        if is_showdown:
            out[f"{nm}|{slot}"] = rec
            # Base layer is the UTIL price, never the captain price.
            if slot == "UTIL" or nm not in out:
                out[nm] = rec
            continue
        if nm in out:
            collisions.append(nm)
            if rec["salary"] > out[nm]["salary"]:
                out[nm] = rec  # keep higher salary on collision, mirrored from the crosswalk
        else:
            out[nm] = rec

    out["__collisions__"] = {"names": sorted(set(collisions))}  # type: ignore[assignment]
    out["__contest_type__"] = {"value": "showdown" if is_showdown else "classic"}  # type: ignore[assignment]
    if cache_key is not None:
        _SALARY_MAP_CACHE[cache_key] = out
    return out


# ---------------------------------------------------------------------------
# Salary-file resolution
# ---------------------------------------------------------------------------

# Below this share of joined player references the candidate is not this
# contest's slate. Real files join at 100%; a wrong-draftgroup file from the
# same date still joins on the players the two slates share, which is exactly
# why "some join rate" is not evidence and a threshold is needed.
MIN_AUTO_JOIN_RATE = 0.95
# A winner must also beat the runner-up by this much, so two plausible files are
# reported as ambiguous rather than silently resolved by a rounding difference.
MIN_AUTO_JOIN_MARGIN = 0.02
# A correct salary file has its teams drafted almost exhaustively by the field.
# A superset file (a larger draftgroup on the same date that contains this one)
# joins just as well but leaves whole teams untouched. Not 1.0, because a small
# field can legitimately ignore one bad team.
MIN_AUTO_TEAM_COVERAGE = 0.80
# R49(3). The sanity floor a salary file must clear however it was chosen: below
# this, it is a different slate's file and the record must not claim coverage
# "full". Distinct from MIN_AUTO_JOIN_RATE above, which selects between
# candidates; see the comment at the gate for why the two numbers differ by so
# much and what this floor deliberately does not catch.
MIN_SALARY_JOIN_RATE = 0.50


def score_salary_candidate(standings: Dict[str, Any],
                           salary_path: str) -> Dict[str, Any]:
    """Score one candidate salary file against one contest's standings.

    Returns contest-type agreement and the share of player references in
    complete lineups that the file can price. No mining, no tables; this is
    cheap enough to run across every candidate on disk.
    """
    result: Dict[str, Any] = {"path": str(salary_path), "usable": False,
                              "join_rate": 0.0, "contest_type_matches": False,
                              "error": None}
    try:
        smap = load_salary_map(str(salary_path))
    except Exception as exc:
        result["error"] = str(exc)
        return result
    standings_type = str(standings.get("contest_type") or "classic").lower()
    salary_type = str((smap.get("__contest_type__") or {}).get("value") or "classic").lower()
    result["salary_contest_type"] = salary_type
    result["contest_type_matches"] = salary_type == standings_type
    if not result["contest_type_matches"]:
        return result
    seen = matched = 0
    drafted_teams: set = set()
    for entry in standings.get("entries") or []:
        if not entry.get("lineup_complete"):
            continue
        for slot, name in entry["lineup"]:
            nm = normalize_name(name)
            seen += 1
            rec = smap.get(f"{nm}|{slot}") or smap.get(nm)
            if rec:
                matched += 1
                if rec.get("team"):
                    drafted_teams.add(rec["team"])
    result["join_rate"] = round(matched / seen, 4) if seen else 0.0
    result["references"] = seen

    # Join rate alone cannot tell a correct file from a SUPERSET of it. On
    # 2026-07-24 the night slate's four games were all inside the main slate's
    # ten, so a night contest joined 100% against both files. The asymmetry that
    # does discriminate: a field drafting from the whole draftgroup touches
    # nearly every team in its own salary file, and only a fraction of the teams
    # in a larger one. The reverse direction needs no help, because a main-slate
    # contest cannot join at all against a file missing six of its games.
    salary_teams = {v["team"] for k, v in smap.items()
                    if not k.startswith("__") and v.get("team")}
    result["salary_teams"] = len(salary_teams)
    # The same slate is routinely on disk several times: the staged copy, the
    # promoted run's inputs, the archived copy. Those are not competing answers,
    # so identify a candidate by what it CONTAINS rather than where it lives.
    result["signature"] = hash(frozenset(
        (k, v["salary"]) for k, v in smap.items() if not k.startswith("__")))
    result["drafted_teams"] = len(drafted_teams)
    result["team_coverage"] = (round(len(drafted_teams) / len(salary_teams), 4)
                               if salary_teams else 0.0)
    result["usable"] = (result["join_rate"] >= MIN_AUTO_JOIN_RATE
                        and result["team_coverage"] >= MIN_AUTO_TEAM_COVERAGE)
    return result


def resolve_salary_file(standings: Dict[str, Any],
                        candidates: Sequence[str]) -> Dict[str, Any]:
    """Pick the salary file that actually belongs to this contest, or refuse.

    Contest type is read off the standings, so the only open question is WHICH
    slate's salary file this is. On 2026-07-24 a single date carried three
    draftgroups plus a Showdown, and the ten Classic exports needed two
    different salary files; matching them by hand is the last step in the
    archival loop where a human can pick the wrong file and get plausible
    numbers instead of an error.

    Returns ``{"path": str|None, "reason": str, "scored": [...]}``. A None path
    means mine the standings_only tier: ownership, duplication, chalk, and SP
    pairs all survive without salary, and that is strictly better than joining
    against the wrong slate.
    """
    scored = sorted(
        (score_salary_candidate(standings, path) for path in candidates),
        key=lambda s: (-s["join_rate"], -s.get("team_coverage", 0.0), s["path"]),
    )
    usable = [s for s in scored if s["usable"]]
    if not usable:
        best = scored[0] if scored else None
        detail = (f"best candidate {Path(best['path']).name} joined "
                  f"{best['join_rate']:.0%} with "
                  f"{best.get('team_coverage', 0.0):.0%} team coverage"
                  if best else "no candidates supplied")
        return {"path": None, "scored": scored,
                "reason": (f"no salary file joined at least {MIN_AUTO_JOIN_RATE:.0%} "
                           f"({detail}); mine the standings_only tier or supply "
                           "--salary explicitly")}
    if len(usable) > 1 and (usable[0]["join_rate"] - usable[1]["join_rate"]) < MIN_AUTO_JOIN_MARGIN:
        # Two files price this contest equally well. Usually they are the same
        # slate on disk in two places, which is not a decision at all. Only a
        # genuine difference in the player universe is ambiguous, and guessing
        # there is how evidence gets silently mislabeled.
        tied = [u for u in usable
                if usable[0]["join_rate"] - u["join_rate"] < MIN_AUTO_JOIN_MARGIN]
        if len({u["signature"] for u in tied}) > 1:
            names = sorted({Path(u["path"]).name for u in tied})
            return {"path": None, "scored": scored,
                    "reason": (f"ambiguous: {', '.join(names)} differ in content but "
                               f"both join at {usable[0]['join_rate']:.0%}; supply "
                               "--salary explicitly")}
    return {"path": usable[0]["path"], "scored": scored,
            "reason": f"joined {usable[0]['join_rate']:.0%} of player references"}


def default_salary_candidates(root: Path) -> List[str]:
    """Every salary CSV the repo has on disk, newest first.

    Promoted run inputs are the authoritative copies because they are what the
    build actually used; staged slate files and archived copies fill the gaps.
    """
    root = Path(root)
    seen: List[Path] = []
    for pattern in ("runs/*/inputs/DKSalaries*.csv",
                    "data/slates/*/DKSalaries*.csv",
                    "data/archive/*/DKSalaries*.csv"):
        seen.extend(root.glob(pattern))
    return [str(p) for p in sorted(set(seen), key=lambda p: -p.stat().st_mtime)]


def manifest_salary_candidates(root: Path, slate_date: str,
                               contest_id: str = "") -> List[str]:
    """The salary files the upload manifest says this contest was built from (R49).

    This is the authoritative tier and it exists because scoring cannot find it.
    A same-family SUPERSET defeats `--auto-salary` outright: a 9-game slate's
    players all sit inside the 10-game file, so several candidates join 100% and
    the resolver correctly declines rather than guessing. Meanwhile the manifest
    already knows the answer without scoring anything -- each delivery records
    its `run_id`, and `runs/<run_id>/inputs/DKSalaries.csv` is by construction the
    file the build actually used for every contest in that delivery.

    Non-superseded deliveries come first: when a slate was delivered twice, the
    surviving delivery is the one whose file was entered. Superseded ones follow
    rather than being dropped, because a superseded run for the same slate still
    staged the same slate's salary file, and a stale-but-correct file beats
    falling through to a repo-wide scan.

    Returns [] when there is no manifest, no matching delivery, or no staged
    input -- all three of which are ordinary and simply mean the next tier runs.
    """
    root = Path(root)
    manifest_path = root / "outputs" / str(slate_date) / "upload_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    wanted = str(contest_id or "").strip()
    live: List[str] = []
    superseded: List[str] = []
    for record in manifest.get("deliveries", []):
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            continue
        if wanted:
            covered = {str(c) for c in (record.get("contest_ids") or [])}
            # A delivery that names contests and does not name this one is a
            # different contest's file. One that names none is not evidence
            # either way, so it stays a candidate.
            if covered and wanted not in covered:
                continue
        bucket = superseded if record.get("status") == "superseded" else live
        for path in sorted((root / "runs" / run_id / "inputs").glob("DKSalaries*.csv")):
            bucket.append(str(path))
    out: List[str] = []
    for path in live + superseded:
        if path not in out:
            out.append(path)
    return out


def in_date_salary_candidates(root: Path, slate_date: str) -> List[str]:
    """Salary CSVs staged under this slate's own date (R30(c)).

    The middle tier. `--auto-salary` used to scan all 170 salary CSVs in the
    repo, which runs 7-25s where a date-scoped scan runs under a second, and the
    join-and-team-coverage checks still guard against the wrong slate either way.
    """
    root = Path(root)
    out: List[str] = []
    for sub in ("data/slates", "data/archive"):
        for path in sorted((root / sub / str(slate_date)).glob("DKSalaries*.csv")):
            if str(path) not in out:
                out.append(str(path))
    return out


def resolve_salary_tiered(standings: Dict[str, Any], root: Path,
                          slate_date: str = "",
                          contest_id: str = "") -> Dict[str, Any]:
    """Resolve this contest's salary file MANIFEST-FIRST, then in-date, then wide.

    R49. The 2026-08-04 mine resolved 11 of 94 contests by hand; the 2026-08-08
    tranche validated this order by hand across 31. The tiers are tried in
    sequence and the FIRST tier that yields a usable file wins -- they are not
    pooled and scored together, because pooling is what lets a superset outrank
    the authoritative file. The returned ``tier`` says which one answered, so a
    mine that fell through to the wide scan is visibly different from one the
    manifest resolved.
    """
    root = Path(root)
    tiers: List[Tuple[str, List[str]]] = []
    if slate_date:
        tiers.append(("manifest", manifest_salary_candidates(root, slate_date, contest_id)))
        tiers.append(("in_date", in_date_salary_candidates(root, slate_date)))
    tiers.append(("repo_wide", default_salary_candidates(root)))
    attempts: List[Dict[str, Any]] = []
    for tier, candidates in tiers:
        if not candidates:
            attempts.append({"tier": tier, "candidates": 0, "reason": "no candidates"})
            continue
        resolved = resolve_salary_file(standings, candidates)
        attempts.append({"tier": tier, "candidates": len(candidates),
                         "reason": resolved["reason"]})
        if resolved["path"]:
            resolved["tier"] = tier
            resolved["attempts"] = attempts
            return resolved
    return {"path": None, "tier": None, "attempts": attempts, "scored": [],
            "reason": "; ".join(f"{a['tier']}: {a['reason']}" for a in attempts)}


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
    contest_type = str(standings.get("contest_type") or "classic").lower()
    contract = ROSTER_CONTRACTS.get(contest_type, ROSTER_CONTRACTS["classic"])
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
    # A salary file for the wrong contest type joins by name and produces
    # plausible-looking nonsense rather than an error, which is the same
    # fail-open class as the structural gate. Catch it before any table is
    # built, because "certified but wrong" is the expensive outcome here.
    salary_contest_type = str(
        (smap.get("__contest_type__") or {}).get("value") or "classic").lower()
    contest_type_mismatch = has_salary and salary_contest_type != contest_type
    salaries = sorted(v["salary"] for k, v in smap.items()
                      if not k.startswith("__") and "|" not in k)
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
            # Showdown prices the same player differently by slot, so the slot
            # key wins when the salary file carries one. Classic has no slot
            # layer and falls straight through to the name key.
            rec = smap.get(f"{nm}|{slot}") or smap.get(nm)
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

    # v0.4 verification split. Two distinct questions were previously conflated:
    #   (a) is OUR parse structurally sound? Hard gate; a real parse bug blocks
    #       archiving (this is what caught the v0.3 position-grain error).
    #   (b) does DK's %Drafted table agree with it? Advisory only. DraftKings
    #       omits position rows for some multi-position players, so their table
    #       can sum short of the structural total while our parse is exact. In
    #       that case the lineup-derived recompute is the authoritative ownership.
    roster_size = sum(contract["expected"].values())
    intra_entry_dupes = [
        e["entry_id"] for e in complete
        if len(e["players_norm"]) != len(set(e["players_norm"]))
    ]
    observed_slots = sum(roster_counts.values())
    expected_slots = roster_size * n_complete
    # v0.5: the slot-count equality alone is fail-open. When NOTHING parses,
    # n_complete is 0, both sides are 0, and a total parse failure certified
    # itself as "structurally sound" while emitting an empty archive block. That
    # is exactly what a Showdown export did before this module knew the Showdown
    # contract: CPT/UTIL are not Classic slot tokens, so every row parsed to zero
    # players and the gate waved it through. A gate that cannot fail on an empty
    # parse is not a gate. Two additions: some entries must parse, and the share
    # that did not must stay small.
    unparsed = n_all - n_complete
    unparsed_share = (unparsed / n_all) if n_all else 0.0
    parsed_nothing = n_all > 0 and n_complete == 0
    mostly_unparsed = n_all > 0 and unparsed_share > MAX_UNPARSED_ENTRY_SHARE
    # R49(3): the join rate is computed here rather than after the gate, because
    # the gate needs it. `contest_type_mismatch` caught the Showdown-salary-on-a
    # -Classic-export case and nothing caught the SAME-TYPE wrong slate: on
    # 2026-08-08 five 1910_4g contests were mined against the 1235_5g Classic
    # file, joined 0.0%, and archived as `coverage: "full"` at exit 0 with every
    # stack_pattern empty and salary_left null. `full` with an empty join is the
    # misleading middle -- worse than standings_only, which is honest -- because
    # downstream shape aggregation reads empty patterns as an 'other' bucket, so
    # the defect surfaces as a shape finding rather than as a coverage failure.
    joined = [e for e in complete if not e["unmatched"]]
    join_rate = round(100.0 * len(joined) / n_complete, 1) if (has_salary and n_complete) else None
    # Deliberately far below MIN_AUTO_JOIN_RATE (0.95). That one is a SELECTION
    # threshold, picking the best of many candidates; this is a SANITY threshold,
    # asking whether this file describes this slate at all. A wrong-slate file
    # joins near 0%; a correct file with name collisions or withdrawn players
    # joins high. A floor between the two catches the gross case without
    # second-guessing a legitimately imperfect file. What it does NOT catch is a
    # partial overlap (a 5-game file against a 4-game contest sharing 3 games);
    # picking the right file in the first place is R49's manifest-first
    # resolution, and this gate is only its backstop.
    salary_join_collapsed = (has_salary and join_rate is not None
                             and join_rate < MIN_SALARY_JOIN_RATE * 100.0)
    parse_structural_ok = (
        (not intra_entry_dupes)
        and (observed_slots == expected_slots)
        and not parsed_nothing
        and not mostly_unparsed
        and not contest_type_mismatch
        and not salary_join_collapsed
    )
    denom_used = n_all if own_denominator == "all_entries" else n_complete
    recomputed_total_pct = round(100.0 * observed_slots / denom_used, 1) if denom_used else None
    dk_total_pct = round(sum(own.values()), 1) if own else None
    dk_deficit_pts = (round(recomputed_total_pct - dk_total_pct, 1)
                      if (recomputed_total_pct is not None and dk_total_pct is not None) else None)
    dk_table_agrees = (own_recompute_max_diff is not None and own_recompute_max_diff <= 1.5)
    if contest_type_mismatch:
        verification_note = (
            f"WRONG SALARY FILE: the standings export is {contest_type} but the "
            f"salary CSV is {salary_contest_type}. Joining across contest types "
            "matches on name and silently misprices every entry. Supply the "
            f"{contest_type} salary file for this slate, or omit --salary to mine "
            "the standings_only tier. Do not archive anything downstream of this.")
    elif salary_join_collapsed:
        verification_note = (
            f"WRONG SALARY FILE: the salary CSV is the right contest type "
            f"({contest_type}) but priced only {join_rate}% of complete entries, "
            f"below the {MIN_SALARY_JOIN_RATE:.0%} floor. It is a different "
            "slate's file. Every stack pattern would archive empty and every "
            "salary_left null while the record claimed coverage 'full'. Supply "
            "this slate's salary file, or omit --salary to mine the honest "
            "standings_only tier. Do not archive anything downstream of this.")
    elif parsed_nothing:
        verification_note = (
            f"PARSE FAILURE: none of the {n_all} entry rows parsed into a complete "
            f"{roster_size}-player lineup. The lineup strings do not match the "
            f"{contest_type} roster contract this run assumed. If the Lineup cells "
            "read 'CPT ... UTIL ...' this is a Showdown export; mine it as Showdown. "
            "Do not archive anything downstream of this parse.")
    elif mostly_unparsed:
        verification_note = (
            f"PARSE FAILURE: {unparsed} of {n_all} entry rows ({unparsed_share:.0%}) "
            f"did not parse into a complete {roster_size}-player lineup, above the "
            f"{MAX_UNPARSED_ENTRY_SHARE:.0%} tolerance. Withdrawn and zeroed entries "
            "are expected at low rates; this is too many to be that. "
            "Do not archive anything downstream of this parse.")
    elif not parse_structural_ok:
        verification_note = ("PARSE FAILURE: structural check failed "
                             f"(slots {observed_slots} vs expected {expected_slots}, "
                             f"{len(intra_entry_dupes)} entries with a duplicated player). "
                             "Do not archive anything downstream of this parse.")
    elif dk_table_agrees:
        verification_note = "parse structurally sound; DK %Drafted agrees with the lineup recompute"
    else:
        verification_note = (
            f"parse structurally sound (every complete entry carries {roster_size} distinct "
            f"players); DK's %Drafted table sums {dk_deficit_pts} pts short, which is DK "
            "omitting position rows for multi-position players. Lineup-derived ownership is "
            "authoritative for this contest.")

    return {
        "label": REVIEW_LABEL,
        "version": VERSION,
        "coverage": "full" if has_salary else "standings_only",
        "contest_id": contest_id,
        "slate_date": slate_date,
        # Carried explicitly so nothing downstream has to re-infer it. Showdown
        # archetypes never pool with Classic in the ledger or the ownership work.
        "contest_type": contest_type,
        "meta": {
            "entries_total": n_all,
            "entries_complete_lineups": n_complete,
            "roster_size": roster_size,
            "entries_unparsed": unparsed,
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
            "ownership_recompute_ok": dk_table_agrees,
            "parse_structural_ok": parse_structural_ok,
            # The individual reasons, so the caller can pin an exit code per
            # failure mode instead of re-deriving it from the note text.
            "parsed_nothing": parsed_nothing,
            "mostly_unparsed": mostly_unparsed,
            "contest_type_mismatch": contest_type_mismatch,
            "salary_join_collapsed": salary_join_collapsed,
            "entries_unparsed_share": round(unparsed_share, 4),
            "intra_entry_duplicate_entry_ids": intra_entry_dupes[:5],
            "roster_slots_observed": observed_slots,
            "roster_slots_expected": expected_slots,
            "recomputed_total_pct": recomputed_total_pct,
            "dk_table_total_pct": dk_total_pct,
            "dk_table_deficit_pts": dk_deficit_pts,
            "dk_table_agrees": dk_table_agrees,
            "verification_note": verification_note,
        },
        "entries": [
            {k: e[k] for k in (
                # ``rank`` was parsed and then dropped here, so the project could
                # not answer "where did my entries finish" and therefore could not
                # answer "are we winning" (G4). It is the cheapest column in the
                # file and it was the only one thrown away.
                "rank", "entry_id", "username", "points", "salary_used", "salary_left",
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

def harvest_own_entry_ids(slate_date: str, contest_id: str = "") -> List[str]:
    """Ben's Entry IDs for a contest, read from that date's upload manifest.

    The manifest records every delivered file and the contests it covered, so
    the delivered file itself is the record of which Entry IDs were entered
    where. Asking the operator to retype them at archival time is how this step
    gets skipped.
    """
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "outputs" / str(slate_date) / "upload_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows

    wanted = str(contest_id or "").strip()
    out: List[str] = []
    for record in manifest.get("deliveries", []):
        if record.get("status") == "superseded":
            continue
        if wanted and wanted not in {str(c) for c in (record.get("contest_ids") or [])}:
            continue
        delivered = root / str(record.get("delivered_file") or "")
        if not delivered.exists():
            continue
        try:
            rows = parse_dk_entry_rows(delivered)
        except (OSError, ValueError):
            continue
        out.extend(r.entry_id for r in rows
                   if not wanted or r.contest_id == wanted)
    return sorted(set(out))


def paid_places_from_file(
    path: str,
    contest_id: Optional[str],
) -> Tuple[Optional[int], str]:
    """``paid_places`` for one contest out of a parked JSON export (R30a).

    Accepts either a flat ``{contest_id: {...}}`` mapping or one wrapped under a
    ``contests`` key, which is the shape
    ``data/reference/dk_contest_paid_places.json`` uses. Returns
    ``(paid_places, note)`` and never raises: a missing file, an unreadable one,
    or a contest the export does not cover all resolve to ``(None, why)``, and
    the caller prints the note. Silence is the one thing this must not do --
    parking these numbers in a file nothing reads is the state R30(a) exists to
    end, and "the file did not have it" and "the file was never read" have to be
    different sentences.
    """
    p = Path(path)
    if not p.exists():
        return None, f"{path} does not exist; paid_places stays unknown"
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path} is unreadable ({exc}); paid_places stays unknown"
    table = payload.get("contests") if isinstance(payload, Mapping) else None
    if not isinstance(table, Mapping):
        table = payload if isinstance(payload, Mapping) else {}
    key = str(contest_id or "").strip()
    if not key:
        return None, "no contest id to look up; paid_places stays unknown"
    row = table.get(key)
    if row is None:
        return None, (f"{key} is not in {p.name} ({sum(1 for k in table if not str(k).startswith('_'))} "
                      f"contests covered); paid_places stays unknown")
    value = row.get("paid_places") if isinstance(row, Mapping) else row
    if value is None:
        return None, f"{key} is in {p.name} but carries no paid_places"
    try:
        return int(value), f"{key} -> {int(value)} paid place(s), from {p.name}"
    except (TypeError, ValueError):
        return None, f"{key} in {p.name} has a non-integer paid_places ({value!r})"


def summarize_own_entries(
    mined: Mapping[str, Any],
    my_entry_ids: Sequence[str],
    entry_fee: Optional[float] = None,
    winnings: Optional[float] = None,
    paid_places: Optional[int] = None,
) -> Dict[str, Any]:
    """Where Ben's own entries finished, against the field he was in.

    G4: ``parse_standings_export`` read the rank column and the entries
    projection dropped it, ``grade_against_actuals`` had never run, and no
    archived contest carried a fee. The project could not answer "are we
    winning", which makes the stakes decision undecidable for want of a number.

    Everything here is an observed outcome read off a completed contest. It is
    not a graded prediction, an ROI model, a win rate, or a probability claim,
    and it says nothing about whether any of it was skill.

    R30(a): ``paid_places`` is how many places the contest paid, which for a
    satellite is the ticket count it awarded. Nothing in the archival path could
    write it, so ``posture_allocator.classify_tier`` returned UNRESOLVED on every
    archived contest and a rank-1 satellite finish could not be graded as a seat.
    It is an observed count off the contest page or Ben's entry-history export,
    never inferred here: ``breadth`` is recorded only when both it and
    ``field_size`` are real, and ``paid_places_source`` names where it came from
    so an exact count is never confused with the contest library's name-inferred
    breadth.
    """
    wanted = {str(x).strip() for x in (my_entry_ids or []) if str(x).strip()}
    all_entries = list(mined.get("entries") or [])
    field_size = int((mined.get("meta") or {}).get("entries_total") or len(all_entries))
    mine = [e for e in all_entries if str(e.get("entry_id")) in wanted]
    if not mine:
        return {"matched": 0, "requested": len(wanted), "field_size": field_size,
                "paid_places": (int(paid_places) if paid_places is not None else None),
                "note": "none of the supplied entry ids appear in this contest's "
                        "standings; check the contest id"}

    def _rank(entry) -> Optional[int]:
        try:
            return int(str(entry.get("rank")).strip())
        except (TypeError, ValueError):
            return None

    ranks = [r for r in (_rank(e) for e in mine) if r is not None]
    points = [e["points"] for e in mine if e.get("points") is not None]
    # Duplication against the field, which is the number that matters in a
    # satellite: clearing the cut line undbuplicated is the whole game.
    groups: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for entry in all_entries:
        groups[tuple(entry["players_norm"])].append(str(entry.get("entry_id")))
    dup_counts = []
    for entry in mine:
        copies = len(groups.get(tuple(entry["players_norm"]), []))
        dup_counts.append(copies)
    fees = (float(entry_fee) * len(mine)) if entry_fee is not None else None
    return {
        "matched": len(mine),
        "requested": len(wanted),
        "field_size": field_size,
        "best_rank": min(ranks) if ranks else None,
        "worst_rank": max(ranks) if ranks else None,
        "best_finish_percentile": (round(100.0 * (1 - (min(ranks) - 1) / field_size), 2)
                                   if ranks and field_size else None),
        "median_finish_percentile": (
            round(100.0 * (1 - (statistics.median(ranks) - 1) / field_size), 2)
            if ranks and field_size else None),
        "best_points": max(points) if points else None,
        "winning_points": (mined.get("meta") or {}).get("winning_points"),
        "own_lineups_duplicated_by_field": sum(1 for c in dup_counts if c > 1),
        "max_copies_of_an_own_lineup": max(dup_counts) if dup_counts else None,
        "entry_fee": entry_fee,
        "fees_total": fees,
        "winnings_total": winnings,
        # R30(a). An observed count, and the breadth derived from it only when
        # both halves are real. A satellite's paid_places IS its ticket count,
        # which is what makes a rank-1 finish gradeable as a seat.
        "paid_places": (int(paid_places) if paid_places is not None else None),
        "payout_breadth_observed": (
            round(int(paid_places) / field_size, 4)
            if paid_places is not None and field_size else None),
        "cashed_entries": (
            sum(1 for r in ranks if r <= int(paid_places))
            if paid_places is not None and ranks else None),
        "net": (round(float(winnings) - fees, 2)
                if winnings is not None and fees is not None else None),
        "labels": "observed outcomes from a completed contest; never a graded "
                  "prediction, ROI model, win rate, or probability claim",
    }


DEFAULT_REGISTRY_PATH = "data/reference/field_opponent_registry.json"


def default_registry_path() -> str:
    """The one registry path, resolved module-relative.

    ``--registry`` was a bare cwd-relative argument with no default, so the
    registry forked: ledger/field_opponent_registry.json held 534 users and
    data/reference/ held 1986, 230 of them shared and disagreeing, with neither
    a superset of the other. Two authorities for one fact is this project's
    named no-op failure class.
    """
    return str(Path(__file__).resolve().parents[2] / DEFAULT_REGISTRY_PATH)


def update_registry(registry_path: Optional[str], mined: Dict[str, Any]) -> Dict[str, Any]:
    """Accumulate one contest into the opponent registry, idempotently.

    Accumulation had no dedupe at all, so re-mining a contest, which the
    post-slate runbook invites whenever a mine is re-run, inflated every
    aggregate silently. A contest is mined as a whole, so contest id is the
    right dedupe grain: if a user already carries this contest, their totals
    already include it and this pass adds nothing.
    """
    registry_path = registry_path or default_registry_path()
    reg: Dict[str, Any] = {}
    if os.path.exists(registry_path):
        with open(registry_path, "r", encoding="utf-8") as fh:
            reg = json.load(fh)
    reg.setdefault("_label", "opponent-recurrence registry; observed field behavior; "
                             "record-only, never a prediction")
    users = reg.setdefault("users", {})
    # R74(a): `.get(key, "unknown")` never defaults when the key EXISTS as None,
    # which is exactly what a mine with no winner produces. So `cid` came out
    # None, `contests_mined` accumulated JSON nulls, and a second no-id mine was
    # silently skipped as already-mined because None was already in the list. A
    # registry entry with no contest identity is not a record of anything, so it
    # is refused rather than folded in under a placeholder.
    cid = mined.get("contest_id") or (mined.get("meta") or {}).get("winning_entry_id") or ""
    cid = str(cid).strip()
    if not cid:
        raise ValueError(
            "refusing to update the registry for a mine with no contest identity: "
            "contest_id is empty and the standings carry no winning entry id, so "
            "this mine cannot be deduped against any other. Pass --contest-id."
        )
    mined_contests = reg.setdefault("contests_mined", [])
    if cid in mined_contests:
        # Already folded in. Recompute the derived averages and return, so a
        # re-mine is a genuine no-op rather than a quiet double count.
        _finalize_registry_averages(users)
        _write_registry(registry_path, reg)
        return reg
    mined_contests.append(cid)
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
    if mined.get("forced_override"):
        reg.setdefault("forced_contests", []).append({
            "contest_id": cid,
            "note": mined["forced_override"]["verification_note"],
        })
    _finalize_registry_averages(users)
    _write_registry(registry_path, reg)
    return reg


def _finalize_registry_averages(users: Dict[str, Any]) -> None:
    for u in users.values():
        u["avg_salary_used"] = round(u["sum_salary_used"] / u["n_salary"], 0) if u["n_salary"] else None
        n_stack = u.get("n_stack", 0)
        u["avg_max_stack"] = round(u["sum_max_stack"] / n_stack, 2) if n_stack else None
        u["avg_chalk_score"] = round(u["sum_chalk"] / u["n_chalk"], 2) if u["n_chalk"] else None


def _write_registry(registry_path: str, reg: Dict[str, Any]) -> None:
    """tmp + os.replace. A kill mid-write used to leave a truncated registry."""
    target = Path(registry_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=1, sort_keys=True)
    os.replace(tmp, target)


# ---------------------------------------------------------------------------
# Ledger archive block emitter
# ---------------------------------------------------------------------------

# Pinned exit codes, one per structural failure mode. They are distinct so a
# scheduled task can tell "this is the wrong file" from "this file is unreadable"
# without parsing prose, and so the runbook can name a fix per code.
EXIT_OK = 0
EXIT_WRONG_SALARY_FILE = 4      # standings and salary are different contest types
EXIT_PARSED_NOTHING = 5         # zero entry rows produced a complete lineup
EXIT_MOSTLY_UNPARSED = 6        # unparsed share above the tolerance
EXIT_STRUCTURAL_OTHER = 3       # slot-count or intra-entry duplicate failure
# R30(b): money was supplied that nothing could consume. Distinct from the
# structural exits above, because the parse succeeded and the archive is fine;
# what failed is the caller's expectation that a fee would be recorded.
EXIT_MONEY_WITHOUT_OWN_ENTRIES = 7
# R93: the requested --json destination cannot be written. Distinct again,
# because nothing about the standings or the salary file is wrong; the mine was
# asked to report to a place it cannot reach, and it has to say so BEFORE it
# starts appending to shared records.
EXIT_OUTPUT_PATH_UNUSABLE = 8


def check_output_path(json_out: str) -> Optional[str]:
    """Return a reason string if ``json_out`` cannot be written, else None (R93).

    Checked BEFORE the mine touches anything shared. The original failure mode
    was ordering, not a missing ``mkdir``: ``open(json_out, "w")`` is the last
    thing ``main`` does, so a nonexistent ``data/archive/<date>/`` raised
    ``FileNotFoundError`` only after the ``own_results`` append and the ledger
    fragment had already landed. The operator saw a traceback saying the mine
    did not happen while the durable records said it partly did, and re-running
    after a manual ``mkdir -p`` appended a second time. An operation that
    mutates shared state cannot discover an unusable output path at the end.

    Creating the parent here rather than at write time is deliberate: the
    directory is the part that can fail for reasons the caller must fix
    (unwritable ancestor, a FILE sitting where the directory should be), and
    those are exactly what has to surface early. ``data/archive/<date>/`` is
    created by a successful mine's archive move anyway, so materializing it a
    few steps sooner adds no state the mine would not have written.
    """
    target = Path(json_out)
    if target.is_dir():
        return f"{target} is a directory, not a file path"
    parent = target.parent if str(target.parent) else Path(".")
    if parent.exists() and not parent.is_dir():
        return f"{parent} exists and is not a directory"
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"cannot create {parent}: {exc}"
    if not os.access(parent, os.W_OK):
        return f"{parent} is not writable"
    return None


def structural_exit_code(diagnostics: Mapping[str, Any]) -> int:
    """Map a failed structural gate to its pinned exit code."""
    if diagnostics.get("contest_type_mismatch"):
        return EXIT_WRONG_SALARY_FILE
    # R49(3). Same verdict as a type mismatch and deliberately the same code:
    # from the caller's side both mean "you handed me another slate's file", and
    # the remedy is identical. A separate code would imply a different fix.
    if diagnostics.get("salary_join_collapsed"):
        return EXIT_WRONG_SALARY_FILE
    if diagnostics.get("parsed_nothing"):
        return EXIT_PARSED_NOTHING
    if diagnostics.get("mostly_unparsed"):
        return EXIT_MOSTLY_UNPARSED
    return EXIT_STRUCTURAL_OTHER


def emit_ledger_block(mined: Dict[str, Any]) -> str:
    m, d, c, g = mined["meta"], mined["duplication"], mined["construction"], mined["diagnostics"]
    cov = mined.get("coverage", "full")
    lines: List[str] = []
    lines.append(f"#### Full-field decomposition — contest {mined['contest_id'] or 'UNKNOWN'} "
                 f"(field_miner {VERSION}; coverage {cov}; {REVIEW_LABEL})")
    lines.append("")
    # The verification note is line 1 of the block, always. It used to be
    # computed, used to pick a string, and then omitted from the emitted block,
    # so a block tagged "coverage full" could sit in the archive with a
    # fabricated stack histogram and nothing in the archive saying so. A reader
    # of the ledger must not have to go back to the run to learn this.
    lines.append(f"- Verification: {g.get('verification_note') or 'no note recorded'}")
    override = mined.get("forced_override")
    if override:
        lines.append(f"- **ARCHIVED UNDER OVERRIDE**: {override['warning']}. "
                     f"Suppressed exit code {override['exit_code_suppressed']}. "
                     f"Treat every number below as unverified.")
    lines.append("")
    lines.append(f"- Entries {m['entries_total']} ({m['entries_complete_lineups']} complete lineups); "
                 f"winning score {m['winning_points']}; multi-entry contest: {m['multi_entry_flag']}.")
    lines.append(f"- Duplication: {d['distinct_lineups']} distinct lineups; "
                 f"{d['share_duplicated_pct']}% of entries sat in a duplicated lineup; "
                 f"max copies {d['max_copies']}; the winning lineup had {d['winner_copies']} cop"
                 f"{'y' if d['winner_copies'] == 1 else 'ies'}. "
                 f"Copies histogram: {d['copies_histogram']}.")
    # Every table below this line is a salary join. On a contest-type mismatch
    # the join matched on name across two different contests, so the numbers are
    # not merely uncertain, they are wrong. Report them unavailable rather than
    # print a plausible-looking histogram nobody can later distinguish from a
    # real one.
    # R49(3) adds the same-type wrong slate to the same suppression. A file that
    # priced under half the field leaves the histograms mostly empty, and an
    # empty stack_pattern aggregates downstream as an 'other' bucket rather than
    # as missing data -- which is how five contests read as a shape finding for
    # four days. This branch is only reachable under --force, since the gate
    # otherwise blocks the mine.
    salary_tables_valid = not (g.get("contest_type_mismatch")
                               or g.get("salary_join_collapsed"))
    if not salary_tables_valid:
        why = ("resolved to a different contest type, so the join matched on name "
               "across contests"
               if g.get("contest_type_mismatch") else
               f"priced only {g.get('salary_join_rate_pct')}% of complete entries, "
               f"so it is a different slate's file")
        lines.append("- Salary usage, stack histogram and SP-pair tables: **unavailable**. "
                     f"The salary file {why} and every salary-derived "
                     "number would be wrong.")
    if salary_tables_valid and c["at_cap_share_pct"] is not None:
        lines.append(f"- Salary usage: {c['at_cap_share_pct']}% of entries within "
                     f"${AT_CAP_SALARY_LEFT} of the cap. Salary-left bins: {c['salary_left_histogram']}.")
    if salary_tables_valid and c["max_stack_histogram"]:
        lines.append(f"- Max-stack histogram: {c['max_stack_histogram']}.")
    if cov == "standings_only":
        # R49(1): this used to name "the slate's DKEntries upload file (which
        # embeds the salary block)" as a recovery path. That is true only of DK's
        # own downloaded template; the engine's delivered DKEntries_*.csv carries
        # no Name or Salary columns at all and load_salary_map raises on it. The
        # real recovery path is the run inputs the manifest points at.
        lines.append("- Salary-usage and stack tables unavailable at this coverage tier "
                     "(no salary file); re-run with --auto-salary if this slate's "
                     "DKSalaries.csv surfaces, in runs/<run_id>/inputs/ via the date's "
                     "upload manifest or staged under data/slates/<date>/. A delivered "
                     "DKEntries_*.csv is NOT a salary source.")
    if salary_tables_valid and c["sp_pair_top"]:
        top = ", ".join(f"{'/'.join(x['pair'])} {x['field_share_pct']}%" for x in c["sp_pair_top"][:4])
        lines.append(f"- SP-pair field share (top): {top}.")
    own = mined.get("own_results")
    if own and own.get("matched"):
        # R50: three states, not two. The old sentence read "fees and winnings
        # not supplied" whenever `net` was None, which is also true when the FEE
        # was supplied and only the winnings were missing -- and that is the
        # common case, 94 contests with $35.87 of captured fees all carrying the
        # false half in the permanent archive. A later reader asking "which
        # contests have a known cost" concluded wrongly. Same class as R38 one
        # layer down.
        if own.get("net") is not None:
            net = (f"; fees ${own['fees_total']:.2f}, "
                   f"winnings ${own['winnings_total']:.2f}, net ${own['net']:.2f}")
        elif own.get("fees_total") is not None:
            net = (f"; fee ${own['entry_fee']:.2f}/entry, "
                   f"${own['fees_total']:.2f} total; winnings not captured, so no "
                   f"net line for this contest")
        elif own.get("winnings_total") is not None:
            net = (f"; winnings ${own['winnings_total']:.2f}; fee not supplied, so "
                   f"no net line for this contest")
        else:
            net = "; neither fee nor winnings supplied, so no net line for this contest"
        # R30(a): the paid line is what makes a finish gradeable as a cash or a
        # seat, so it belongs in the permanent block rather than only in JSON.
        if own.get("paid_places") is not None:
            net += (f". Paid places {own['paid_places']} of {own['field_size']} "
                    f"(observed breadth {own['payout_breadth_observed']})")
            if own.get("cashed_entries") is not None:
                net += f"; {own['cashed_entries']} own entr"
                net += "y" if own["cashed_entries"] == 1 else "ies"
                net += " inside the paid line"
        lines.append(
            f"- **Self vs field**: {own['matched']} own entries; best rank "
            f"{own['best_rank']}/{own['field_size']} "
            f"({own['best_finish_percentile']}th pct), median "
            f"{own['median_finish_percentile']}th pct; best {own['best_points']} pts "
            f"against a winning {own['winning_points']}; "
            f"{own['own_lineups_duplicated_by_field']} own lineup(s) duplicated by "
            f"the field (max {own['max_copies_of_an_own_lineup']} copies){net}. "
            f"Observed outcomes, never a graded prediction.")
    elif own:
        lines.append(f"- Self vs field: {own.get('note')}")
    if c["top_owned"]:
        lines.append("- Chalk (top-5 %Drafted): " + ", ".join(
            f"{t['player']} {t['pct_drafted']}%" for t in c["top_owned"]) + ".")
    join_txt = (f"salary join {g['salary_join_rate_pct']}% of complete entries fully joined; "
                if g["salary_join_rate_pct"] is not None else "salary join n/a (standings_only); ")
    parse_txt = "parse OK" if g.get("parse_structural_ok", True) else "PARSE FAILED"
    if g.get("dk_table_agrees", g.get("ownership_recompute_ok")):
        dk_txt = "DK %Drafted agrees"
    else:
        dk_txt = (f"DK %Drafted table short {g.get('dk_table_deficit_pts')} pts "
                  "(DK omits multi-position rows; lineup-derived ownership used)")
    lines.append(f"- Diagnostics: {join_txt}"
                 f"ownership recompute max diff {g['ownership_recompute_max_diff_pts']} pts; "
                 f"{parse_txt}; {dk_txt}.")
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
    ap.add_argument("--auto-salary", action="store_true",
                    help="pick the salary CSV by scoring candidates against this "
                         "contest's lineups; declines to standings_only rather "
                         "than joining against the wrong slate")
    ap.add_argument("--salary-dir",
                    help="restrict --auto-salary to DKSalaries*.csv in this "
                         "directory (default: every salary CSV in the repo)")
    ap.add_argument("--contest-id", default="")
    ap.add_argument("--slate-date", default="")
    ap.add_argument("--registry",
                    help="override the opponent-registry location. The registry "
                         "is accumulated on EVERY mine (R94); omit this and it "
                         "resolves to data/reference/field_opponent_registry.json, "
                         "which is the one registry. Pass a path only to write "
                         "somewhere else deliberately -- a bare relative path is "
                         "what forked it into two diverging copies once already.")
    ap.add_argument("--emit-ledger", action="store_true")
    ap.add_argument("--no-archive-move", action="store_true",
                    help="leave a mined inbox CSV in place instead of moving it "
                         "to data/archive/<slate_date>/ (R23; the move only ever "
                         "applies to files inside data/standings/inbox/)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--my-entry-ids",
                    help="comma-separated Entry IDs of Ben's own entries. Omit and "
                         "they are harvested from outputs/<slate-date>/"
                         "upload_manifest.json, which records what was actually "
                         "delivered to each contest.")
    ap.add_argument("--entry-fee", type=float,
                    help="fee per entry for this contest, for the net line")
    ap.add_argument("--winnings", type=float,
                    help="total winnings for Ben's entries in this contest")
    ap.add_argument("--paid-places", type=int, dest="paid_places",
                    help="how many places this contest paid; for a satellite, the "
                         "ticket count it awarded (R30a). An observed count off the "
                         "contest page or the entry-history export, never inferred. "
                         "Without it posture_allocator.classify_tier returns "
                         "UNRESOLVED for this contest forever.")
    ap.add_argument("--paid-places-from", dest="paid_places_from",
                    help="JSON mapping contest_id -> {paid_places, ...} to read "
                         "--paid-places from, so a bulk re-mine is one command "
                         "rather than one per contest. "
                         "data/reference/dk_contest_paid_places.json is the parked "
                         "export; --paid-places still wins if both are given.")
    ap.add_argument("--force", action="store_true",
                    help="archive despite a failed structural parse check. The "
                         "override is recorded verbatim as line 2 of the emitted "
                         "ledger block and in the registry entry, so a forced "
                         "archive is never indistinguishable from a clean one. "
                         "Exit codes when not forced: "
                         f"{EXIT_WRONG_SALARY_FILE} wrong salary file, "
                         f"{EXIT_PARSED_NOTHING} zero entries parsed, "
                         f"{EXIT_MOSTLY_UNPARSED} unparsed share over tolerance, "
                         f"{EXIT_STRUCTURAL_OTHER} other structural failure, "
                         f"{EXIT_MONEY_WITHOUT_OWN_ENTRIES} money flags supplied "
                         f"with no resolvable own entry ids (R30b).")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.standings:
        ap.error("--standings is required (or --selftest)")
    # R93: fail on an unusable --json destination BEFORE anything shared is
    # touched. Everything below this line can append to ledger/own_results.json,
    # write a ledger fragment, update the registry and move the standings file;
    # the JSON write used to be last, so an unreachable path turned a mine into
    # a partial one. See check_output_path for the full incident.
    if args.json_out:
        reason = check_output_path(args.json_out)
        if reason:
            print(f"ERROR  --json destination unusable: {reason}\n"
                  f"       Nothing was written. No mine ran, so no own-results row, "
                  f"no ledger fragment and no registry update exist to undo.",
                  file=sys.stderr)
            return EXIT_OUTPUT_PATH_UNUSABLE
    st = parse_standings_export(args.standings)
    salary_path = args.salary
    if not salary_path and args.auto_salary:
        root = Path(__file__).resolve().parents[2]
        if args.salary_dir:
            # An explicit directory is the operator overriding the tiers; honour
            # it exactly, and the join-and-team-coverage check still applies.
            resolved = resolve_salary_file(
                st, [str(p) for p in sorted(Path(args.salary_dir).glob("DKSalaries*.csv"))])
            resolved.setdefault("tier", "salary_dir")
        else:
            # R49: manifest -> in-date -> repo-wide, first usable tier wins.
            resolved = resolve_salary_tiered(
                st, root, slate_date=args.slate_date,
                contest_id=args.contest_id or st.get("contest_id") or "")
        salary_path = resolved["path"]
        if salary_path:
            print(f"salary auto-resolved [{resolved.get('tier')}]: "
                  f"{Path(salary_path).name} ({resolved['reason']})")
        else:
            print(f"NOTICE: salary auto-resolution declined: {resolved['reason']}")
    if salary_path:
        smap: Optional[Dict[str, Dict[str, Any]]] = load_salary_map(salary_path)
    else:
        smap = None
        print("NOTICE: no --salary supplied; running the standings_only degraded tier "
              "(duplication, chalk, SP pairs, registry; no salary or stack tables)")
    mined = mine_contest(st, smap, contest_id=args.contest_id, slate_date=args.slate_date)

    # F9: the structural gate is computed and then, until now, ignored. main()
    # called update_registry, emit_ledger_block and returned 0 with no branch on
    # parse_structural_ok; the only use of the flag selected a note string that
    # emit_ledger_block then omitted. A wrong-salary mine produced join 0.0%,
    # "PARSE FAILED" in diagnostics, exit 0, a written registry, and a block
    # tagged "coverage full" with a fabricated stack histogram.
    #
    # This matters more than the exit code suggests. The archive is the training
    # data for the ownership model, which is the project's single gating
    # dependency, and the scheduled task mines unattended. One bad mine poisons
    # ownership rows, duplication tables and the registry in one clean-looking
    # run, and nothing downstream can tell which rows came from it.
    diagnostics = mined.get("diagnostics") or {}
    if not diagnostics.get("parse_structural_ok", True):
        note = diagnostics.get("verification_note") or "structural parse check failed"
        code = structural_exit_code(diagnostics)
        print()
        print(f"BLOCKED (exit {code}): {note}")
        if not args.force:
            print("Nothing was written: no registry update, no ledger block, no JSON. "
                  "Fix the input and re-run, or pass --force to record the override "
                  "verbatim in the emitted block.")
            return code
        print("--force supplied: writing anyway. The override is recorded verbatim "
              "in the emitted block and in the registry entry.")
        mined["forced_override"] = {
            "verification_note": note,
            "exit_code_suppressed": code,
            "warning": "this contest was archived downstream of a structural parse "
                       "failure by explicit operator override",
        }

    # G4: own results. Evidence decays, and DK exports age out; five contests are
    # already unrecoverable. Capturing this at mining time is the only chance.
    # R30(a): resolve paid_places before the own-results stage. An explicit flag
    # beats the file, and a file that does not carry this contest says so rather
    # than leaving the caller to wonder whether it was read at all.
    paid_places = args.paid_places
    if paid_places is None and args.paid_places_from:
        paid_places, note = paid_places_from_file(
            args.paid_places_from, args.contest_id or mined.get("contest_id"))
        print(f"paid places: {note}")
    own_ids = [x.strip() for x in (args.my_entry_ids or "").split(",") if x.strip()]
    if not own_ids and args.slate_date:
        own_ids = harvest_own_entry_ids(args.slate_date, args.contest_id)
        if own_ids:
            print(f"own entries: {len(own_ids)} harvested from the upload manifest")
    # R30(b): --entry-fee, --winnings and --paid-places are consumed ONLY inside
    # the own-results stage, which runs only when own entry ids resolve. Those
    # are harvested from outputs/<date>/upload_manifest.json, which existed for
    # 4 of 10 backfilled dates; on the other 6 the mine printed no own-results
    # line, exited 0, and left entry_fee null with nothing said. It cost ARCHIVE
    # a full pass. Passing money for a contest whose entries cannot be
    # identified is a caller error, not a no-op.
    money_flags = [name for name, value in (
        ("--entry-fee", args.entry_fee), ("--winnings", args.winnings),
        ("--paid-places", args.paid_places),
        ("--paid-places-from", args.paid_places_from)) if value is not None]
    if money_flags and not own_ids:
        manifest = (Path(__file__).resolve().parents[2] / "outputs"
                    / str(args.slate_date or "<slate-date>") / "upload_manifest.json")
        print(f"ERROR  {', '.join(money_flags)} supplied but no own entry ids "
              f"resolved, so nothing would consume them and this mine would "
              f"record no fee, no winnings and no paid line while exiting 0.\n"
              f"       Pass --my-entry-ids explicitly (source them from the entry "
              f"history's Entry_Key column), or make {manifest} resolvable.",
              file=sys.stderr)
        return EXIT_MONEY_WITHOUT_OWN_ENTRIES
    if own_ids:
        mined["own_results"] = summarize_own_entries(
            mined, own_ids, entry_fee=args.entry_fee, winnings=args.winnings,
            paid_places=paid_places)
        summary = mined["own_results"]
        if summary.get("matched"):
            print(f"own results: {summary['matched']}/{summary['requested']} entries "
                  f"matched; best rank {summary['best_rank']} of "
                  f"{summary['field_size']} "
                  f"({summary['best_finish_percentile']}th pct); "
                  f"{summary['own_lineups_duplicated_by_field']} own lineup(s) "
                  f"duplicated by the field")
        else:
            print(f"own results: {summary.get('note')}")
        if summary.get("matched"):
            # Persisted per contest so net-to-date is a lookup, not a rebuild.
            # DK exports age out; five contests are already unrecoverable, and
            # anything not captured at mining time is captured never.
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
                from net_to_date import append_record

                append_record({
                    "contest_id": args.contest_id or mined.get("contest_id"),
                    "slate_date": args.slate_date or mined.get("slate_date"),
                    "contest_name": (mined.get("meta") or {}).get("contest_name"),
                    **{k: summary.get(k) for k in (
                        "matched", "field_size", "best_rank", "best_finish_percentile",
                        "median_finish_percentile", "best_points", "winning_points",
                        "own_lineups_duplicated_by_field", "entry_fee",
                        "fees_total", "winnings_total", "net",
                        "paid_places", "payout_breadth_observed",
                        "cashed_entries")},
                })
                print("own results appended to ledger/own_results.json "
                      "(python tools/net_to_date.py for the cumulative table)")
            except Exception as exc:  # noqa: BLE001 - bookkeeping never blocks
                print(f"own results not persisted: {exc}")

    # R94: accumulate by DEFAULT. This was `if args.registry:`, so the runbook's
    # own instruction -- "Do not pass --registry. It defaults to
    # data/reference/field_opponent_registry.json" -- described a mine that never
    # touched the registry, and `update_registry`'s internal
    # `registry_path or default_registry_path()` was unreachable unless the flag
    # had been passed with some value. All 31 mines of the 2026-08-08 tranche
    # skipped accumulation silently; it was caught only by comparing registry
    # contests_mined (236) against own_results (267).
    #
    # The code moved rather than the runbook, because the runbook's wording is
    # load-bearing: it says not to pass a path precisely BECAUSE passing a bare
    # relative one forked the registry into two diverging copies once already.
    # "One registry, resolved by the tool" is the intent, and the flag now only
    # overrides the location.
    registry_target = args.registry or default_registry_path()
    try:
        update_registry(args.registry or None, mined)
        print(f"registry updated: {registry_target}")
    except ValueError as exc:
        # R74(a) refuses a mine with no contest identity rather than folding it
        # in under a placeholder, and that invariant holds. What must not happen
        # is the refusal killing an otherwise-good mine now that the call is
        # unconditional: the JSON, the ledger block and the own-results row are
        # all still valid. Loud, named, and non-fatal.
        print(f"NOTICE: registry NOT updated: {exc}")
    if args.json_out:
        slim = {k: v for k, v in mined.items() if k not in ("own_by_norm", "fpts_by_norm")}
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(slim, fh, indent=1, default=list)
        print(f"json written: {args.json_out}")
    if args.emit_ledger:
        block = emit_ledger_block(mined)
        fragment = write_ledger_fragment(
            block, args.slate_date or mined.get("slate_date") or "",
            args.contest_id or mined.get("contest_id") or "")
        print()
        print(f"ledger block written to {fragment}")
        print("ARCHIVE merges it into the ledger and deletes the fragment; the "
              "block is deliberately not printed here, so it cannot be pasted "
              "twice (R23)")
    else:
        g = mined["diagnostics"]
        join_txt = f"join {g['salary_join_rate_pct']}%" if g["salary_join_rate_pct"] is not None else "join n/a"
        print(f"contest {args.contest_id or '?'} [{mined['coverage']}]: "
              f"{mined['meta']['entries_complete_lineups']} complete entries, "
              f"{mined['duplication']['distinct_lineups']} distinct lineups, "
              f"{join_txt}, "
              f"ownership recompute {'OK' if g['ownership_recompute_ok'] else 'CHECK'}")
    if args.standings and not args.no_archive_move:
        moved = archive_mined_standings(
            args.standings, args.slate_date or mined.get("slate_date") or "")
        if moved:
            print(f"standings archived: {moved}")
    return 0


def archive_mined_standings(standings_path: str | Path, slate_date: str,
                            repo_root: str | Path | None = None) -> Optional[str]:
    """Move a successfully mined inbox CSV to data/archive/<slate_date>/ (R23).

    The runbook documented this move; nothing performed it, so the inbox
    accumulated mined-but-present CSVs (122 on 2026-07-28) and only the
    per-contest dedupe stood between a re-run and a double count. The miner
    owns the move now, and only for files that actually live in the repo's
    inbox: a fixture, a tmp file, or any ad-hoc path is never moved. Fail-open
    on OSError, because a mount without the delete grant can refuse the
    rename, and a completed mine must not report failure over housekeeping.
    Returns the destination path, or None when no move applies.
    """
    if not slate_date:
        return None
    src = Path(standings_path).resolve()
    root = (Path(repo_root).resolve() if repo_root
            else Path(__file__).resolve().parents[2])
    inbox = (root / "data" / "standings" / "inbox").resolve()
    try:
        if src.parent != inbox or not src.is_file():
            return None
    except OSError:
        return None
    dest_dir = root / "data" / "archive" / str(slate_date)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        os.replace(str(src), str(dest))
    except OSError as exc:
        print(f"standings not archived ({exc}); the file stays in the inbox "
              f"and the per-contest dedupe still holds")
        return None
    return str(dest)


def write_ledger_fragment(block: str, slate_date: str, contest_id: str,
                          repo_root: str | Path | None = None) -> str:
    """Write the emitted ledger block to ledger/inbox/ as a fragment (R23).

    Printing the block made the paste a human step, and a block pasted twice
    double-counts in the one file whose archetype-conditioned counts feed the
    R10 gate. A fragment is consumed on merge: ARCHIVE applies it to the
    ledger and deletes it, so the same block cannot land twice. A re-mine of
    the same contest overwrites its own fragment, the same replace-not-append
    rule own_results.json follows.
    """
    root = (Path(repo_root).resolve() if repo_root
            else Path(__file__).resolve().parents[2])
    frag_dir = root / "ledger" / "inbox"
    frag_dir.mkdir(parents=True, exist_ok=True)
    date_part = str(slate_date or "undated")
    cid_part = str(contest_id or "unknown")
    dest = frag_dir / f"{date_part}_miner_{cid_part}.md"
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    tmp.write_text(str(block).rstrip() + "\n", encoding="utf-8")
    os.replace(str(tmp), str(dest))
    return str(dest)


if __name__ == "__main__":
    sys.exit(main())
