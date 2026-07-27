"""bank_cache.py

MLB Classic v2.27.0. VERSION = "v1.1".

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
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.allocate.contest_allocator import ENTRY_ROSTER_SLOTS
from mlb_engine.optimize.optimizer_v3 import (
    build_single_lineup, _new_solver_status, resolve_solver_time_limit,
)

VERSION = "v1.2"


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
        self.corrupt_on_load = False
        # Filled by as_candidates: scored/failed counts for the payload it just
        # emitted, so a silent scoring failure is countable (F15).
        self.last_payload_report: Dict[str, Any] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A cache killed mid-save is unreadable, and an unreadable cache
            # used to be a fatal error on every later run for the same slate:
            # the file is derived data and rebuilding it costs a slice, so
            # discard and start over rather than block the build.
            self.corrupt_on_load = True
            self.candidates, self.attempted, self._seen = [], set(), set()
            return
        self.candidates = list(payload.get("candidates") or [])
        self.attempted = set(payload.get("attempted") or [])
        self._seen = {tuple(c["roster"]) for c in self.candidates}

    def drop_stale_jobs(self, conditions_sig: str) -> int:
        """Forget candidates and attempts built under different conditions.

        A job key ends with the conditions signature. Anything carrying a
        different one was solved against a different exclude set, different
        stack bounds, or different projections, and serving it now is serving
        an answer to a question nobody asked. Returns how many were dropped.
        """
        if not conditions_sig:
            return 0
        suffix = f"|{conditions_sig}"
        stale_attempts = {k for k in self.attempted if not k.endswith(suffix)}
        stale_candidates = [
            c for c in self.candidates
            if c.get("job") and not str(c["job"]).endswith(suffix)
        ]
        if not stale_attempts and not stale_candidates:
            return 0
        self.attempted -= stale_attempts
        keep = [c for c in self.candidates if c not in stale_candidates]
        self.candidates = keep
        self._seen = {tuple(c["roster"]) for c in keep}
        return len(stale_attempts) + len(stale_candidates)

    def save(self) -> None:
        """tmp + os.replace: a kill mid-save used to poison the file permanently."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({
            "version": VERSION,
            "candidates": self.candidates,
            "attempted": sorted(self.attempted),
        }, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

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

    def as_candidates(self, projections_df=None, requested_n: int = 1,
                      contest_shapes: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Shape the allocator and run_late_swap consume.

        Supply ``projections_df`` to attach contest-shape scoring. Without it
        the payload carries roster and objective only, and
        ``contest_allocator._candidate_shape_score`` falls back to raw objective:
        no stack-correlation bonus, no batting-order-cluster bonus, no
        salary-uniqueness or field-pressure adjustment, and floor_sum reads 0.0
        so the cash branch cannot distinguish a high-floor lineup from any
        other. That fallback was silently in force on every big slate, because
        big slates are exactly when build_slate.py chooses the sliced path, and
        big slates are exactly when shape scoring matters most.

        v1.2 (F15) fixes three seams into the allocator.

        ``primary_stack`` and ``sp_ids`` are emitted. The allocator's
        primary-stack exposure cap reads ``primary_stack``; with the field
        absent the cap added zero MILP rows and the concentration it exists to
        prevent surfaced at the export gate instead, after the budget was spent.
        The no-stack case is the empty string, never the DU signature's 'NONE'
        sentinel, which the allocator would read as a team.

        ``contest_shapes`` populates ``contest_fit_by_shape``. The single
        ``mode="wta"`` score is a ceiling-max ranking, and the allocator's cash
        branch then applies its floor weighting on top of it, so a cash entry
        ranked on a ceiling score with a floor adjustment bolted on. Passing the
        shapes the reserved CSV actually contains scores each one in its own
        mode. Default None keeps the single-score behavior exactly.

        Scoring failures are counted in ``self.last_payload_report`` instead of
        vanishing into ``except: pass``. Degrading to the unscored payload is
        still right, because a short bank leaves a blank reserved row and a
        blank row blocks certification. Doing it silently is not.
        """
        from mlb_engine.optimize.optimizer_v3 import (
            candidate_primary_stack, score_lineup_candidate,
            _mode_for_contest_shape,
        )

        shapes: List[str] = []
        for shape in (contest_shapes or []):
            key = str(shape).strip().lower()
            if key and key not in shapes:
                shapes.append(key)

        out = []
        by_id = None
        scored_count = 0
        failed_count = 0
        failure_reasons: Dict[str, int] = {}
        if projections_df is not None and hasattr(projections_df, "columns"):
            frame = projections_df.copy()
            frame["__pid__"] = frame["Player_ID"].astype(str)
            by_id = frame.set_index("__pid__", drop=False)

        for i, entry in enumerate(self.candidates):
            cid = f"bank{i}"
            roster = [str(p) for p in entry["roster"]]
            payload: Dict[str, Any] = {
                "lineup_id": cid,
                "candidate_id": cid,
                "roster_slot_ids": list(roster),
                "player_ids": list(roster),
                "objective": float(entry["objective"]),
                # The cache stores rosters in ENTRY_ROSTER_SLOTS order, so the
                # first two entries are P1 and P2 by construction.
                "sp_ids": list(roster[:2]),
                "primary_stack": "",
            }
            if by_id is not None:
                try:
                    lineup_df = by_id.loc[[p for p in roster if p in by_id.index]]
                    if len(lineup_df) != len(roster):
                        raise KeyError(
                            f"{len(roster) - len(lineup_df)} roster ids absent from projections"
                        )
                    payload["primary_stack"] = candidate_primary_stack(lineup_df)
                    score = score_lineup_candidate(
                        lineup_df, projections_df, mode="wta",
                        candidate_id=cid, requested_n=requested_n)
                    payload["contest_fit"] = {
                        "contest_fit_score": score.get("contest_fit_score"),
                        "floor_sum": score.get("floor_sum"),
                        "ceiling_sum": score.get("ceiling_sum"),
                        "right_tail_volatility_counts":
                            score.get("right_tail_volatility_counts") or {},
                    }
                    payload["contest_fit_score"] = score.get("contest_fit_score")
                    payload["floor_sum"] = score.get("floor_sum")
                    if shapes:
                        by_shape: Dict[str, Any] = {}
                        for shape in shapes:
                            shape_score = score_lineup_candidate(
                                lineup_df, projections_df,
                                mode=_mode_for_contest_shape(shape, "wta"),
                                candidate_id=cid, requested_n=requested_n,
                                contest_shape=shape)
                            by_shape[shape] = shape_score.get("contest_fit_score")
                        payload["contest_fit_by_shape"] = by_shape
                    scored_count += 1
                except Exception as exc:  # noqa: BLE001 - never lose a candidate
                    failed_count += 1
                    reason = f"{type(exc).__name__}: {exc}"[:120]
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            out.append(payload)

        self.last_payload_report = {
            "candidates": len(out),
            "scored": scored_count,
            "scoring_failed": failed_count,
            "scoring_failure_reasons": dict(failure_reasons),
            "shapes_scored": list(shapes),
            "projections_supplied": by_id is not None,
            "note": "an unscored candidate still allocates, on raw objective; "
                    "deterministic bookkeeping, never a claim",
        }
        return out

    def __len__(self) -> int:
        return len(self.candidates)


def _job_key(pair: Sequence[str], team: str, lock_sig: str = "",
             conditions_sig: str = "") -> str:
    """Identify a solve by everything that changes its answer.

    The key was (pair, team, lock signature) only. It omitted excludes, the
    stack bounds, and any signature of the projections, so two solves that
    would produce different lineups shared a key: a late-swap slice served
    pre-exclusion candidates, and an enriched rerun served the unenriched
    answers from before enrichment landed. That is not a stale cache in the
    ordinary sense, it is the cache answering a question it was never asked.

    It is not hypothetical. On 2026-07-26 a rebuild after the DK Status filter
    landed failed certification on a pitcher with no role, served from a cache
    built before the filter existed.
    """
    return "|".join([
        "+".join(sorted(str(p) for p in pair)), str(team), lock_sig, conditions_sig,
    ])


def conditions_signature(
    projections_df,
    excludes: Optional[Sequence[str]] = None,
    stack_min: Optional[int] = None,
    stack_max: Optional[int] = None,
) -> str:
    """A short digest of everything outside (pair, team, locks) that moves a solve.

    Covers the excluded set, the stack bounds, and the projection values the
    objective is built from. Hashing the values rather than the row count
    matters: an enrichment pass changes Ceiling without changing the pool.
    """
    digest = hashlib.sha256()
    digest.update(b"v2")
    digest.update(("|".join(sorted(str(x) for x in (excludes or []))) + "\n").encode())
    digest.update(f"{stack_min}:{stack_max}\n".encode())
    for column in ("Player_ID", "Ceiling", "Floor", "Base", "Salary", "Excluded"):
        if column not in getattr(projections_df, "columns", []):
            continue
        try:
            values = projections_df.sort_values("Player_ID")[column].tolist()
        except Exception:  # noqa: BLE001 - a signature must not kill a build
            values = list(projections_df[column])
        digest.update((column + ":" + ",".join(f"{v}" for v in values) + "\n").encode())
    return digest.hexdigest()[:16]


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
    solver_time_limit_s: Optional[float] = None,
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
    conditions_sig = ""  # computed below, once the stack bounds are settled

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

    # Everything outside (pair, team, locks) that changes a solve's answer, fixed
    # now that the stack bounds are settled and used as part of every job key.
    conditions_sig = conditions_signature(projections_df, excl, stack_min, stack_max)
    superseded = cache.drop_stale_jobs(conditions_sig)

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

    # Two starters in the same game cannot both be right. An unknown game is not
    # the same game: str(nan) == str(nan), so two pitchers whose Game_ID did not
    # parse compared equal and the pair was discarded, which is the opposite of
    # the optimizer's own documented guard (it keeps the pair and reports it).
    # Silently dropping pairs shrinks the legal search on a data condition.
    def _known(gid: Any) -> bool:
        text = str(gid).strip().lower()
        return bool(text) and text not in ("nan", "none", "nat", "<na>")

    usable_pairs = []
    unknown_game_pairs = 0
    for a, b in pair_space:
        ga, gb = game_of.get(a), game_of.get(b)
        if not _known(ga) or not _known(gb):
            unknown_game_pairs += 1
            usable_pairs.append((a, b))
            continue
        if ga != gb:
            usable_pairs.append((a, b))
    # Breadth before depth: give every SP pair one lineup before any pair gets a
    # second. Portfolio controls cap SP-pair repetition (often at 1), so a bank
    # that deepens one pair at a time can hold hundreds of candidates and still
    # leave the selection MILP infeasible for want of distinct pairs. Rotating the
    # stack team alongside keeps team diversity climbing at the same rate.
    # Ordered by combined ceiling, with an ID tiebreak for determinism. Rank-sum
    # treats the gap between the best and second-best arm as identical to the gap
    # between the twentieth and twenty-first, which it is not: on a budgeted
    # slice the ordering decides which pairs get solved at all.
    ceiling_of: Dict[str, float] = {}
    if "Ceiling" in getattr(pitchers, "columns", []):
        for row in pitchers.itertuples():
            try:
                ceiling_of[str(row.Player_ID)] = float(row.Ceiling)
            except (TypeError, ValueError):
                continue
    rank = {pid: i for i, pid in enumerate(sp_ids)}

    def _pair_order(pair: Tuple[str, str]):
        a, b = pair
        if ceiling_of:
            combined = ceiling_of.get(a, 0.0) + ceiling_of.get(b, 0.0)
            return (-combined, a, b)
        return (rank.get(a, 999) + rank.get(b, 999), a, b)

    usable_pairs.sort(key=_pair_order)
    jobs: List[Tuple[Tuple[str, str], str]] = []
    if teams:
        for round_idx in range(len(teams)):
            for pair_idx, pair in enumerate(usable_pairs):
                jobs.append((pair, teams[(pair_idx + round_idx) % len(teams)]))

    built = 0
    attempted_now = 0
    worst = 0.0
    timed_out_jobs = 0
    time_limited_accepted = 0
    exhausted = True
    for pair, team in jobs:
        if max_candidates is not None and len(cache) >= max_candidates:
            exhausted = False
            break
        remaining = time_budget_s - (time.monotonic() - started)
        if remaining <= worst:
            exhausted = False
            break
        key = _job_key(pair, team, lock_sig, conditions_sig)
        if key in cache.attempted:
            continue
        attempted_now += 1
        attempt_started = time.monotonic()
        status = _new_solver_status()
        try:
            lineup_df, objective = build_single_lineup(
                projections_df, target=target,
                locks=list(pair),
                locked_slot_assignments=dict(locked_slot_assignments or {}) or None,
                excludes=excl or None,
                stack_constraints=({"team": team, "min_size": stack_min,
                                    "max_size": stack_max} if stack_min >= 2 else None),
                # F13: never let one solve overrun the slice's budget. Shrinking
                # the per-solve limit reduces search effort and nothing else.
                time_limit_s=resolve_solver_time_limit(solver_time_limit_s, remaining),
                status_out=status,
            )
        except Exception:  # noqa: BLE001 - an infeasible combination is data, not an error
            worst = max(worst, time.monotonic() - attempt_started)
            # A proven-infeasible combination will be infeasible again under the
            # same conditions, so it is recorded and never retried.
            cache.attempted.add(key)
            continue
        if status.get("timed_out"):
            # F13: a timeout is not an answer about this job, so it is not
            # recorded as attempted and the next slice retries it. It also does
            # not set the reserve: the reserve is what a completed solve costs,
            # and a timeout costs exactly the limit, which would end the slice.
            timed_out_jobs += 1
            if lineup_df is None:
                continue
            time_limited_accepted += 1
        else:
            worst = max(worst, time.monotonic() - attempt_started)
        # Recorded only after the solve returned. Keys used to enter `attempted`
        # BEFORE the solve and persist, so a job that hit the time limit was
        # marked done forever and never retried on a later slice: the sliced path
        # is the big-slate path, and this quietly dropped exactly the jobs a
        # second slice exists to finish.
        if not status.get("timed_out"):
            cache.attempted.add(key)
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
    # Count only jobs for this lock signature AND these conditions. Both are
    # suffixes of the key; a global count reads as more jobs done than the
    # current list contains.
    suffix = f"|{lock_sig}|{conditions_sig}"
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
        "conditions_signature": conditions_sig,
        # Named so a reviewer can see the cache decided some of its stored work
        # no longer answers this build's question, rather than wondering why the
        # candidate count fell.
        "superseded_jobs_dropped": superseded,
        "cache_was_corrupt_on_load": bool(getattr(cache, "corrupt_on_load", False)),
        "unknown_game_pairs_kept": unknown_game_pairs,
        "free_hitter_slots": free_hitter_slots,
        "stack_min_relaxed_to": stack_relaxed_to,
        # F13: named so a thin slice reads as the clock rather than as a pool
        # that could not produce lineups. These jobs are retryable and a second
        # slice will pick them up.
        "jobs_timed_out": timed_out_jobs,
        "time_limited_accepted": time_limited_accepted,
        "solver_time_limit_s": resolve_solver_time_limit(solver_time_limit_s),
        "note": "deterministic candidate generation through the certified MILP path; "
                "never an ROI, win-rate, or probability claim",
    }
