"""bank_cache.py

MLB Classic v2.27.0. VERSION = "v1.0".

A resumable candidate bank. The generator runs under a wall-clock budget, writes
what it produced to disk, and picks up where it left off on the next call. Nothing
here changes a projection or a MILP hard constraint: every candidate is produced by
``optimizer_v3.build_single_lineup``, the certified solve path. This module only
decides which (SP pair, stack team, locked-slot signature) jobs to spend the next
solve on and remembers which ones are already done.

Why this exists
---------------
The engine assumed unbounded wall time. Under a bounded execution environment an
unbounded bank build is not slow, it is *fatal*: the process is killed mid-solve
and produces no output and no diagnostic, so the caller cannot tell a hard slate
from a hung one. Splitting generation into budgeted, resumable slices converts
"will this finish before it is killed?" into "how many slices does this need?",
which is a schedulable question.

Two contracts that are easy to get wrong
----------------------------------------
1. **Dedupe on the ordered ten-slot roster, not the player set.** Late swap pins
   players to exact DK slots (``locked_slot_assignments``), so two lineups with the
   same ten players in different slots are genuinely different candidates. Deduping
   on a player-set frozenset silently discards the slot variant the allocator needs
   and produces "no compatible candidate" for entries that are in fact fillable.
2. **Respect ``excluded_new_teams``.** Once a game locks, a late swap may not
   introduce any *new* player from that game, even in an unlocked slot. A candidate
   generated without that exclusion is legal-looking and unusable.

Everything here is a deterministic review input. Nothing is an ROI, win-rate, cash
-rate, or probability claim.
"""
from __future__ import annotations

import itertools
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.allocate.contest_allocator import ENTRY_ROSTER_SLOTS
from mlb_engine.optimize.optimizer_v3 import build_single_lineup

VERSION = "v1.0"

# Slot buckets in DK order. ENTRY_ROSTER_SLOTS is ('P1','P2','C',...,'OF3'); the
# optimizer stamps Assigned_Position with the bare DK position token.
_SLOT_BUCKETS: Tuple[Tuple[str, int], ...] = (
    ("P", 2), ("C", 1), ("1B", 1), ("2B", 1), ("3B", 1), ("SS", 1), ("OF", 3),
)


def ordered_roster(lineup_df) -> Optional[Tuple[str, ...]]:
    """Ten Player_IDs in ENTRY_ROSTER_SLOTS order, or None if the lineup is short.

    Prefers an exact ``Assigned_Slot`` when the optimizer stamped one; otherwise
    fills the DK slot buckets in order.
    """
    if lineup_df is None or len(lineup_df) != 10:
        return None
    exact: Dict[str, str] = {}
    buckets: Dict[str, List[str]] = {}
    for _, row in lineup_df.iterrows():
        pid = str(row.get("Player_ID") or "").strip()
        if not pid:
            return None
        slot = str(row.get("Assigned_Slot") or "").strip()
        pos = str(row.get("Assigned_Position") or "").strip()
        if slot:
            exact[slot] = pid
        elif pos:
            buckets.setdefault(pos, []).append(pid)
    if exact:
        roster = tuple(exact.get(slot, "") for slot in ENTRY_ROSTER_SLOTS)
        return roster if all(roster) else None
    ordered: List[str] = []
    for pos, count in _SLOT_BUCKETS:
        got = buckets.get(pos, [])
        if len(got) < count:
            return None
        ordered.extend(got[:count])
    roster = tuple(ordered)
    return roster if len(roster) == 10 and all(roster) else None


class BankCache:
    """Persistent, resumable candidate store.

    ``path`` holds a JSON document: the candidate rosters plus the set of jobs
    already attempted. Attempted-but-failed jobs are recorded too, so a resumed
    run does not re-pay for infeasible combinations.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.candidates: List[Dict[str, Any]] = []
        self.attempted: set[str] = set()
        self._seen: set[Tuple[str, ...]] = set()
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.candidates = list(payload.get("candidates") or [])
        self.attempted = set(payload.get("attempted") or [])
        self._seen = {tuple(c["roster"]) for c in self.candidates}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "version": VERSION,
            "candidates": self.candidates,
            "attempted": sorted(self.attempted),
        }, indent=1), encoding="utf-8")

    def add(self, roster: Sequence[str], objective: float, job: str = "") -> bool:
        """Store a candidate. Dedupes on the ordered roster, never the player set."""
        key = tuple(str(p) for p in roster)
        if len(key) != 10 or not all(key) or key in self._seen:
            return False
        self._seen.add(key)
        self.candidates.append(
            {"roster": list(key), "objective": float(objective), "job": job}
        )
        return True

    def as_candidates(self) -> List[Dict[str, Any]]:
        """Shape the allocator and run_late_swap consume."""
        out = []
        for i, entry in enumerate(self.candidates):
            cid = f"bank{i}"
            out.append({
                "lineup_id": cid,
                "candidate_id": cid,
                "roster_slot_ids": list(entry["roster"]),
                "player_ids": list(entry["roster"]),
                "objective": float(entry["objective"]),
            })
        return out

    def __len__(self) -> int:
        return len(self.candidates)


def _job_key(pair: Sequence[str], team: str, lock_sig: str = "") -> str:
    return "|".join(["+".join(sorted(str(p) for p in pair)), str(team), lock_sig])


def _lock_signature(locked_slot_assignments: Optional[Mapping[str, str]]) -> str:
    if not locked_slot_assignments:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(locked_slot_assignments.items()))


def extend_bank(
    cache: BankCache,
    projections_df,
    *,
    time_budget_s: float = 30.0,
    target: str = "ceiling",
    locked_slot_assignments: Optional[Mapping[str, str]] = None,
    excludes: Optional[Iterable[str]] = None,
    stack_min: int = 4,
    stack_max: int = 5,
    max_candidates: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate candidates across (SP pair, stack team) until the budget runs out.

    Returns a report with what was built and whether the job list is exhausted, so
    the caller knows whether another slice is worth running. ``locked_slot_assignments``
    pins DK slots for a late-swap entry; ``excludes`` carries that entry's
    ``excluded_new_teams`` player IDs.
    """
    started = time.monotonic()
    lock_sig = _lock_signature(locked_slot_assignments)
    excl = [str(x) for x in (excludes or [])]

    pitchers = projections_df[projections_df["Position"] == "P"]
    if "Ceiling" in pitchers.columns:
        pitchers = pitchers.sort_values("Ceiling", ascending=False)
    sp_ids = [str(p) for p in pitchers["Player_ID"] if str(p) not in set(excl)]
    game_of = {str(r.Player_ID): str(r.Game_ID) for r in projections_df.itertuples()}
    hitters = projections_df[projections_df["Position"] != "P"]
    teams = sorted({str(t) for t in hitters["Team"]})

    jobs: List[Tuple[Tuple[str, str], str]] = []
    for a, b in itertools.combinations(sp_ids, 2):
        if game_of.get(a) == game_of.get(b):
            continue  # two starters in the same game cannot both be right
        for team in teams:
            jobs.append(((a, b), team))
    # Best pitchers first, then rotate stacks, so a truncated slice still covers
    # the strongest breadth rather than an arbitrary corner of the space.
    rank = {pid: i for i, pid in enumerate(sp_ids)}
    jobs.sort(key=lambda j: (rank[j[0][0]] + rank[j[0][1]], teams.index(j[1])))

    built = 0
    attempted_now = 0
    worst = 0.0
    exhausted = True
    for pair, team in jobs:
        if max_candidates is not None and len(cache) >= max_candidates:
            exhausted = False
            break
        remaining = time_budget_s - (time.monotonic() - started)
        if remaining <= worst:
            exhausted = False
            break
        key = _job_key(pair, team, lock_sig)
        if key in cache.attempted:
            continue
        cache.attempted.add(key)
        attempted_now += 1
        attempt_started = time.monotonic()
        try:
            lineup_df, objective = build_single_lineup(
                projections_df, target=target,
                locks=list(pair),
                locked_slot_assignments=dict(locked_slot_assignments or {}) or None,
                excludes=excl or None,
                stack_constraints={"team": team, "min_size": stack_min, "max_size": stack_max},
            )
        except Exception:  # noqa: BLE001 - an infeasible combination is data, not an error
            worst = max(worst, time.monotonic() - attempt_started)
            continue
        worst = max(worst, time.monotonic() - attempt_started)
        roster = ordered_roster(lineup_df)
        if roster is None:
            continue
        if locked_slot_assignments:
            # Defensive: the solve should honor the pins, but a candidate that
            # does not is silently unusable, so drop it here rather than at
            # allocation time.
            bad = any(
                roster[ENTRY_ROSTER_SLOTS.index(slot)] != str(pid)
                for slot, pid in locked_slot_assignments.items()
                if slot in ENTRY_ROSTER_SLOTS
            )
            if bad:
                continue
        if cache.add(roster, objective, job=key):
            built += 1

    cache.save()
    return {
        "version": VERSION,
        "built_this_slice": built,
        "attempted_this_slice": attempted_now,
        "total_candidates": len(cache),
        "jobs_total": len(jobs),
        "jobs_attempted": len(cache.attempted),
        "job_list_exhausted": exhausted,
        "elapsed_s": round(time.monotonic() - started, 3),
        "time_budget_s": float(time_budget_s),
        "lock_signature": lock_sig,
        "note": "deterministic candidate generation through the certified MILP path; "
                "never an ROI, win-rate, or probability claim",
    }
