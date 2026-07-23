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

import csv
import hashlib
import itertools
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.allocate.contest_allocator import ENTRY_ROSTER_SLOTS
from mlb_engine.optimize.optimizer_v3 import build_single_lineup

VERSION = "v1.0"


def pool_signature(salary_csv: str | Path, length: int = 10) -> str:
    """Short deterministic signature of a DK salary file's player-ID pool.

    The resumable bank cache used to be keyed on date alone
    (``bank_cache_<date>.json``). Two DK exports that share a calendar date but
    cover different games -- a day slate built earlier and a night slate built
    later, or two different satellite draftgroups -- have almost entirely
    different Player_ID sets. A date-only key let the second build silently
    reuse the first build's cache and certify against IDs that do not exist in
    its own salary file, which surfaces as "invalid Player_ID(s)" at export
    verification, well after the wasted solve time.

    Folding this signature into the cache filename means an unrelated pool
    gets its own file and simply never collides, rather than corrupting the
    next build's. It is a filesystem-hygiene fix, not a strategy change: it
    does not alter what candidates are generated or which players are legal,
    only which cache file two different pools land in.
    """
    ids: List[str] = []
    with open(salary_csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = str(row.get("ID") or "").strip()
            if pid:
                ids.append(pid)
    digest = hashlib.sha256(",".join(sorted(ids)).encode("utf-8")).hexdigest()
    return digest[:length]

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

    # A DK Classic roster has 8 hitter slots. When a late-swap entry pins enough of
    # them, a 4-5 man stack no longer fits in what is left and every solve is
    # infeasible no matter how long the budget runs. Relax the stack demand to the
    # room actually available rather than burning the slice on impossible jobs.
    pinned_hitter_slots = sum(
        1 for slot in (locked_slot_assignments or {})
        if slot in ENTRY_ROSTER_SLOTS and not slot.startswith("P")
    )
    free_hitter_slots = 8 - pinned_hitter_slots
    stack_relaxed_to = None
    if free_hitter_slots < stack_min:
        stack_relaxed_to = max(0, free_hitter_slots)
        stack_min = stack_relaxed_to
        stack_max = max(stack_max, stack_min)

    pitchers = projections_df[projections_df["Position"] == "P"]
    if "Ceiling" in pitchers.columns:
        pitchers = pitchers.sort_values("Ceiling", ascending=False)
    sp_ids = [str(p) for p in pitchers["Player_ID"] if str(p) not in set(excl)]
    game_of = {str(r.Player_ID): str(r.Game_ID) for r in projections_df.itertuples()}
    hitters = projections_df[projections_df["Position"] != "P"]
    teams = sorted({str(t) for t in hitters["Team"]})

    # A pinned pitcher slot makes every SP pair that excludes it infeasible, so
    # enumerating them burns the budget on guaranteed failures. Constrain the pair
    # space to the pins up front. Same for a pinned hitter's team: a 4-5 stack of a
    # different team can still be legal, so teams are left alone.
    pinned_sps = {
        str(pid) for slot, pid in (locked_slot_assignments or {}).items()
        if slot in ("P1", "P2")
    }
    if len(pinned_sps) >= 2:
        pair_space = [tuple(sorted(pinned_sps))[:2]]
    elif len(pinned_sps) == 1:
        pinned = next(iter(pinned_sps))
        pair_space = [(pinned, other) for other in sp_ids if other != pinned]
    else:
        pair_space = list(itertools.combinations(sp_ids, 2))

    usable_pairs = [
        (a, b) for a, b in pair_space if game_of.get(a) != game_of.get(b)
    ]  # two starters in the same game cannot both be right
    # Breadth before depth: give every SP pair one lineup before any pair gets a
    # second. Portfolio controls cap SP-pair repetition (often at 1), so a bank
    # that deepens one pair at a time can hold hundreds of candidates and still
    # leave the selection MILP infeasible for want of distinct pairs. Rotating the
    # stack team alongside keeps team diversity climbing at the same rate.
    rank = {pid: i for i, pid in enumerate(sp_ids)}
    usable_pairs.sort(key=lambda p: rank.get(p[0], 999) + rank.get(p[1], 999))
    jobs: List[Tuple[Tuple[str, str], str]] = []
    if teams:
        for round_idx in range(len(teams)):
            for pair_idx, pair in enumerate(usable_pairs):
                jobs.append((pair, teams[(pair_idx + round_idx) % len(teams)]))

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
                stack_constraints=({"team": team, "min_size": stack_min,
                                    "max_size": stack_max} if stack_min >= 2 else None),
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
    # Count only jobs for this lock signature. cache.attempted spans every
    # signature the cache has seen, so a global count reads as more jobs done
    # than the current list contains.
    suffix = f"|{lock_sig}"
    done_here = sum(1 for key in cache.attempted if key.endswith(suffix))
    return {
        "version": VERSION,
        "built_this_slice": built,
        "attempted_this_slice": attempted_now,
        "total_candidates": len(cache),
        "jobs_total": len(jobs),
        "jobs_attempted": done_here,
        "job_list_exhausted": exhausted,
        "elapsed_s": round(time.monotonic() - started, 3),
        "time_budget_s": float(time_budget_s),
        "lock_signature": lock_sig,
        "free_hitter_slots": free_hitter_slots,
        "stack_min_relaxed_to": stack_relaxed_to,
        "note": "deterministic candidate generation through the certified MILP path; "
                "never an ROI, win-rate, or probability claim",
    }
