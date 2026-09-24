"""R389(a), 2026-09-24. The baseline core: an entry-mapped Classic candidate set
built before research, enrichment, the bank and joint allocation.

WHY IT EXISTS
-------------
`run_classic` resolves reference data, venues, odds, weather, enrichment and
leverage before its first solve, and the first entry-mapped structure anywhere
on the build path is `execute_portfolio`'s allocation. Reproduced on the
vendored 2026-06-03 slate at b14a946: a crash at `run_slate` entry left zero
files, and the timing probe's lineup (`build_single_lineup(projections,
target="ceiling")`, a bare expression statement) was thrown away. Delivery
first needs an entry-mapped set, legal under the solver's rules, in hand
before any of that.

WHAT IT IS AND IS NOT
---------------------
A pure function. It reads the salary file, the entries file and the frame it
is handed, and it writes nothing: no file, no directory, no lock, no cache
(measured by a Python-level audit hook, which cannot see C-level writes).
Since R389(b) (Session 11) `execution_pipeline.run_baseline` calls it from
`run_classic`, before any research, and exports what it built through
`run_slate`; this module still writes nothing itself.

What it returns is a CONSTRUCTION PROXY: lineups legal under the solver's
rules on the frame it was given (the unenriched emergency_proxy frame, in
production), mapped onto the reserved rows. It is not a projection claim, not
certified, not upload-ready, and not the essential-validity verdict, which is
a verdict on exported bytes and belongs to the export.

HOW
---
1. Candidate #1 is the probe: `build_single_lineup(frame, target="ceiling")`,
   the call shape `run_classic` already pays for, bounded by the window.
2. Then one `extend_bank` pass in an in-memory BankCache: breadth first over
   (SP pair, stack team), so the set is not near-clones.
3. Then, while any contest is short, distinct solves: each must differ from
   every lineup already held by at least one player (`overlap_reference`,
   `max_overlap = ROSTER_SIZE - 1`). These are near-duplicates by
   construction, and the record says so.
4. Per contest, fillable entries take candidates in order, skipping any lineup
   that contest already holds, so one lineup is never twice in one contest
   (F-3, never relaxed). One lineup may appear in two contests.

A limit shrinks search effort and nothing else. The frame is never filtered,
copied or narrowed here: every solve gets the caller's frame object and none
passes `excludes`, so the only player removal left is the optimizer's own
reading of the frame's `Excluded` column (`_drop_excluded_rows`). The window
ends a search, never a player.

The baseline-then-enhancement pattern is copied from the production
strangler's workflow (mlb_engine/production/workflow.py, the `_finish` before
`simulate`/`enhance` block), never imported: R302's isolation test fails any
module outside that package that imports it.

Everything here is a deterministic review input. Nothing is an ROI, win-rate,
cash-rate or probability claim.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from mlb_engine import repo_env
from mlb_engine.determinism import stable_union
from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
from mlb_engine.optimize.bank_cache import (
    BankCache, extend_bank, ordered_roster, projection_digest,
)
from mlb_engine.optimize.optimizer_v3 import (
    ROSTER_SIZE, _drop_excluded_rows, _new_solver_status, build_single_lineup,
    resolve_solver_time_limit,
)

VERSION = "v1.0"

#: What the result IS. Never a certification value: `upload_manifest.
#: passed_its_gates` reads any label it does not know as passing, so this
#: string must never reach a manifest's `certification` field.
CONSTRUCTION_LABEL = "baseline_construction_proxy"

CONSTRUCTION_NOTE = (
    "Lineups legal under the solver's rules on the frame supplied (the "
    "unenriched emergency_proxy frame in production), mapped onto the reserved "
    "rows before research, enrichment, the bank and joint allocation. A "
    "construction proxy, not a projection claim: not certified, not "
    "upload-ready, and not the essential-validity verdict, which is read off "
    "exported bytes. distinct_fill lineups differ from every earlier lineup by "
    "at least one player, so they are near-duplicates by construction.")

#: Every value `stop_reason` can take. It says why the search ENDED; `covered`
#: means every fillable row is covered AND `target` lineups exist.
STOP_REASONS = ("covered", "nothing_to_fill", "time_budget", "solve_time_limit",
                "search_exhausted", "solver_unanswered", "solver_error")

#: The frame columns every solve reads. A frame without them is a caller error.
FRAME_COLUMNS = ("Player_ID", "Position", "Team", "Game_ID", "Salary", "Ceiling")

#: R389(b). The share of `run_classic`'s window left at the call that the
#: baseline's search may spend: a fraction of the build's own deadline, never
#: a number of seconds. Measured on this container it spent 0.4s of a 600s
#: window on 06-03 and 3.7s on 06-28 blanked (11 games), so the share binds only
#: a pathological slate, and the deadline itself is never moved: enhancement
#: keeps everything the baseline did not spend. Session 15's frozen Deadline
#: replaces the arithmetic, not the share.
BASELINE_WINDOW_SHARE = 0.25


# --------------------------------------------------------------------------- #
# The frame
# --------------------------------------------------------------------------- #

def unenriched_frame(salary_csv, projection_rows, *,
                     projected_order_by_player_id: Optional[Mapping[str, int]] = None):
    """The emergency_proxy frame with every enrichment input None.

    Exactly the call `run_classic`'s ValueError branch makes when enrichment
    fails, and the one `run_classic` calls through this helper. Returns
    ``(frame, enrichment)`` as ``_assemble_projection_frame`` does.

    The pipeline module is imported here, not at the top, so a test that
    patches its ``_assemble_projection_frame`` still intercepts this call and
    the pipeline can import this module without a cycle.
    """
    from mlb_engine.pipeline import execution_pipeline as epi
    return epi._assemble_projection_frame(
        str(salary_csv), projection_rows, "emergency_proxy", None, None, None,
        projected_order_by_player_id=projected_order_by_player_id)


# --------------------------------------------------------------------------- #
# The in-memory bank
# --------------------------------------------------------------------------- #

class _MemoryBankCache(BankCache):
    """A BankCache that owns no file.

    ``BankCache`` needs a path (``BankCache(None)`` raises TypeError) and
    ``extend_bank`` calls ``save()`` unconditionally, so the class has no
    in-memory mode of its own. This one overrides every method that reads
    ``self.path`` -- ``_load``, ``save`` and ``_save_locked`` -- and holds
    ``path = None`` afterwards, so a base-class path that tried to persist
    would fail loudly instead of writing. It never sees the shared
    ``runs/bank_cache_<date>_<sig>.json``, so it cannot read, write or
    tombstone that file's jobs (``drop_stale_jobs`` retires jobs only in the
    memory of the cache it is called on).
    """

    def __init__(self) -> None:
        # The base constructor stats its path and loads it when it exists;
        # `_load` is a no-op here, so the stat of os.devnull is the only
        # filesystem contact, and it reads nothing.
        super().__init__(os.devnull)
        self.path = None

    def _load(self) -> None:
        return None

    def save(self) -> None:
        return None

    def _save_locked(self) -> None:
        raise RuntimeError("the baseline's in-memory bank has no file to write")


# --------------------------------------------------------------------------- #
# Requirements
# --------------------------------------------------------------------------- #

def _id_key(value: str) -> Tuple[int, str]:
    text = str(value)
    return (len(text), text)


def lineup_signature(roster: Sequence[str]) -> str:
    """Sorted player IDs, the form ``DKEntryRow.lineup_signature`` uses.

    Distinct means distinct PLAYER SETS: two slot orders of one set are one
    lineup for F-3, even though BankCache keeps both as different candidates.
    """
    return "|".join(stable_union(roster))


@dataclass(frozen=True)
class ContestRequirement:
    contest_id: str
    fillable_entry_ids: Tuple[str, ...]
    held_signatures: Tuple[str, ...] = ()
    partial_entry_ids: Tuple[str, ...] = ()


def requirements_from_entries(entries_csv) -> Tuple[ContestRequirement, ...]:
    """Reserved rows per contest, off the DKEntries file.

    A blank row is fillable. A complete row's lineup is HELD in its contest, so
    the baseline never assigns it there again (F-3). A partially filled row is
    named and never filled: pinning its slots is late swap's job. A file whose
    rows are not Classic's ten slots (a Showdown file) is a caller error.
    """
    by_contest: Dict[str, Dict[str, list]] = {}
    for row in parse_dk_entry_rows(str(entries_csv)):
        if len(row.roster_cells) != ROSTER_SIZE:
            raise ValueError(
                f"{entries_csv}: Entry ID {row.entry_id} has {len(row.roster_cells)} "
                f"roster slots, not Classic's {ROSTER_SIZE}")
        slot = by_contest.setdefault(str(row.contest_id),
                                     {"fillable": [], "held": [], "partial": []})
        if row.is_blank:
            slot["fillable"].append(str(row.entry_id))
        elif row.is_complete:
            slot["held"].append(row.lineup_signature)
        else:
            slot["partial"].append(str(row.entry_id))
    return _normalize_requirements([
        ContestRequirement(cid, tuple(v["fillable"]), tuple(v["held"]),
                           tuple(v["partial"]))
        for cid, v in by_contest.items()])


def every_row_requirements(entries_csv) -> Dict[str, Tuple[str, ...]]:
    """R389(b). ``{contest_id: (entry_id, ...)}`` with EVERY reserved row
    fillable, the shape ``build_baseline(requirements=)`` takes.

    `run_slate` refills every reserved row on an initial build, complete and
    partial ones included, so a baseline that held complete rows or skipped
    partial ones (``requirements_from_entries``, the core's own reading) would
    come up short or read ``nothing_to_fill`` on a re-downloaded DKEntries
    file that `run_slate` rebuilds whole. A file whose rows are not Classic's
    ten slots is a caller error, as there.
    """
    by_contest: Dict[str, list] = {}
    for row in parse_dk_entry_rows(str(entries_csv)):
        if len(row.roster_cells) != ROSTER_SIZE:
            raise ValueError(
                f"{entries_csv}: Entry ID {row.entry_id} has {len(row.roster_cells)} "
                f"roster slots, not Classic's {ROSTER_SIZE}")
        by_contest.setdefault(str(row.contest_id), []).append(str(row.entry_id))
    return {cid: tuple(ids) for cid, ids in by_contest.items()}


def _ids(values, what: str) -> Tuple[str, ...]:
    """IDs as strings. A bare string is refused rather than read per character."""
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{what} must be a sequence of IDs, not the string {values!r}")
    return tuple(str(v) for v in (values or ()))


def _held_signature(value) -> str:
    """One held lineup, canonical: its IDs sorted, as ``lineup_signature`` does."""
    if not isinstance(value, str):
        raise ValueError(f"a held signature is a '|'-joined ID string, not {value!r}")
    return "|".join(stable_union(value.split("|")))


def _normalize_requirements(requirements) -> Tuple[ContestRequirement, ...]:
    """Sort, canonicalize, and refuse any shape that could hide an F-3 breach.

    A contest named twice (``1`` and ``"1"`` are one contest once stringified)
    would be assigned as two, putting one lineup twice in it, so it raises; so
    does an Entry ID that appears in two contests or as both fillable and
    partial.
    """
    if isinstance(requirements, Mapping):
        requirements = [ContestRequirement(str(cid), _ids(ids, f"contest {cid}'s entries"))
                        for cid, ids in requirements.items()]
    out = []
    contests: set = set()
    entries: Dict[str, str] = {}
    for req in requirements:
        cid = str(req.contest_id)
        if cid in contests:
            raise ValueError(f"contest {cid} is named twice in the requirements")
        contests.add(cid)
        fillable = _ids(req.fillable_entry_ids, f"contest {cid}'s fillable entries")
        partial = _ids(req.partial_entry_ids, f"contest {cid}'s partial entries")
        for entry_id in fillable + partial:
            if entry_id in entries:
                raise ValueError(f"Entry ID {entry_id} appears twice (contest "
                                 f"{entries[entry_id]} and contest {cid})")
            entries[entry_id] = cid
        if isinstance(req.held_signatures, (str, bytes)):
            raise ValueError(f"contest {cid}'s held signatures must be a sequence")
        out.append(ContestRequirement(
            cid,
            tuple(sorted(fillable, key=_id_key)),
            tuple(stable_union(_held_signature(h) for h in req.held_signatures)),
            tuple(sorted(partial, key=_id_key))))
    return tuple(sorted(out, key=lambda r: _id_key(r.contest_id)))


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BaselineCandidate:
    index: int
    roster: Tuple[str, ...]            # ten IDs, DK slot order P P C 1B 2B 3B SS OF OF OF
    signature: str
    objective: float
    source: str                        # probe | grid | distinct_fill
    # The probe's and each fill solve's own status. None for a grid lineup:
    # BankCache stores no per-solve status, and inventing one would be a
    # false label. The grid's aggregate counts ride in `BaselineResult.grid`.
    solver: Optional[Mapping[str, Any]]
    max_shared_with_earlier: int


@dataclass(frozen=True)
class EntryAssignment:
    contest_id: str
    entry_id: str
    candidate_index: int


@dataclass(frozen=True)
class ContestCoverage:
    contest_id: str
    fillable: int
    filled: int
    held: int
    partial: int


@dataclass(frozen=True)
class BaselineResult:
    """What the core built. Frozen at the field level; the record dicts inside
    (`probe`, `grid`, `pool`, `timings`, a candidate's `solver`) are plain
    dicts, so the freeze is shallow."""
    construction_label: str
    note: str
    status: str                        # covered | short
    stop_reason: str                   # one of STOP_REASONS
    # The typed short count. `required` is the fillable rows of the largest
    # contest; `short` is the largest per-contest count of fillable rows left
    # uncovered, 0 when covered. An uncovered row is never in `assignments`
    # (there is no blank row); it is named in `uncovered`.
    required: int
    target: int
    distinct: int
    short: int
    target_met: bool                   # distinct >= target
    candidates: Tuple[BaselineCandidate, ...]
    assignments: Tuple[EntryAssignment, ...]
    uncovered: Tuple[Tuple[str, str], ...]
    by_contest: Tuple[ContestCoverage, ...]
    probe: Mapping[str, Any]
    grid: Mapping[str, Any]
    pool: Mapping[str, Any]
    timings: Mapping[str, Any]
    version: str = VERSION

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> Dict[str, Any]:
        """R389(b). The typed count and timings for a brief, without the
        rosters: what was built, how far it got, and why it stopped."""
        return {
            "construction_label": self.construction_label,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "required": self.required,
            "target": self.target,
            "distinct": self.distinct,
            "short": self.short,
            "target_met": self.target_met,
            "uncovered": len(self.uncovered),
            "by_contest": [asdict(c) for c in self.by_contest],
            "sources": {src: sum(1 for c in self.candidates if c.source == src)
                        for src in sorted({c.source for c in self.candidates})},
            "timings": dict(self.timings),
            "probe_wall_s": (self.probe or {}).get("wall_s"),
            "version": self.version,
        }

    def allocator_candidates(self, projections, requested_n: int,
                             contest_shapes: Optional[Sequence[str]] = None
                             ) -> List[Dict[str, Any]]:
        """The allocator's payload, shaped by BankCache's own ``as_candidates``.

        ``bank<i>`` is candidate ``i``, so ``bank0`` is the probe when it
        solved. Stored with an empty job key, which no ``drop_stale_jobs`` can
        purge. This is what Session 11 hands to ``run_slate`` as
        ``candidates_override``.
        """
        cache = _MemoryBankCache()
        for cand in self.candidates:
            cache.add(cand.roster, cand.objective, job="")
        if len(cache) != len(self.candidates):
            # `add` dedupes on the ordered roster; distinct player sets never
            # collide there, and if they ever did bank<i> would stop meaning
            # candidate i.
            raise RuntimeError("the payload would not line up with candidate_index")
        return cache.as_candidates(projections, requested_n=int(requested_n),
                                   contest_shapes=contest_shapes)


# --------------------------------------------------------------------------- #
# The core
# --------------------------------------------------------------------------- #

def _solver_record(status: Mapping[str, Any], wall_s: float) -> Dict[str, Any]:
    return {
        "status": status.get("status"),
        "optimality": status.get("optimality"),
        "mip_gap": status.get("mip_gap"),
        "timed_out": bool(status.get("timed_out")),
        "proven_infeasible": bool(status.get("proven_infeasible")),
        "elapsed_s": status.get("elapsed_s"),
        "wall_s": round(float(wall_s), 4),
    }


def _assign(requirements: Sequence[ContestRequirement],
            candidates: Sequence[BaselineCandidate]):
    assignments: List[EntryAssignment] = []
    uncovered: List[Tuple[str, str]] = []
    coverage: List[ContestCoverage] = []
    for req in requirements:
        held = set(req.held_signatures)
        usable = [c for c in candidates if c.signature not in held]
        filled = 0
        for entry_id, cand in zip(req.fillable_entry_ids, usable):
            assignments.append(EntryAssignment(req.contest_id, entry_id, cand.index))
            filled += 1
        uncovered.extend((req.contest_id, e) for e in req.fillable_entry_ids[filled:])
        coverage.append(ContestCoverage(req.contest_id, len(req.fillable_entry_ids),
                                        filled, len(req.held_signatures),
                                        len(req.partial_entry_ids)))
    return tuple(assignments), tuple(uncovered), tuple(coverage)


def build_baseline(
    salary_csv,
    projections,
    *,
    entries_csv=None,
    requirements=None,
    deadline: Optional[float] = None,
    budget_s: Optional[float] = None,
    max_opposing_hitters_per_sp: Optional[int] = None,
    target_distinct: Optional[int] = None,
    clock: Callable[[], float] = time.monotonic,
) -> BaselineResult:
    """Build an entry-mapped, per-contest-distinct candidate set. Never raises
    for a solver outcome; raises ValueError only for a caller error.

    ``entries_csv`` or ``requirements`` (a ``{contest_id: [entry_id, ...]}``
    mapping, or the tuple ``requirements_from_entries`` returns), exactly one.
    ``deadline`` is a ``clock()`` value to finish by (``time.monotonic()``, the
    unit ``run_classic`` holds); ``budget_s`` is seconds from now; with
    neither the window is ``repo_env.call_budget_s()``, and with both the
    earlier end wins. ``max_opposing_hitters_per_sp`` reaches every solve
    (None is the optimizer's default). ``target_distinct`` asks for more
    lineups than the largest contest needs, for an allocator to choose among.
    """
    started_wall = time.monotonic()
    if (entries_csv is None) == (requirements is None):
        raise ValueError("build_baseline takes exactly one of entries_csv or requirements")
    if max_opposing_hitters_per_sp is not None and int(max_opposing_hitters_per_sp) < 0:
        raise ValueError(
            f"max_opposing_hitters_per_sp must be >= 0, got {max_opposing_hitters_per_sp}")
    reqs = (requirements_from_entries(entries_csv) if entries_csv is not None
            else _normalize_requirements(requirements))

    missing = [c for c in FRAME_COLUMNS if c not in getattr(projections, "columns", ())]
    if missing:
        raise ValueError(f"the frame lacks {missing}; every solve reads them")
    salary_ids = {str(p.player_id) for p in parse_dk_salary_csv(str(salary_csv))}
    off_salary = sorted(set(projections["Player_ID"].astype(str)) - salary_ids)
    if off_salary:
        # The DKSalaries CSV is authoritative for IDs: a frame carrying players
        # it does not list was built from another file, and every solve would
        # be spent on lineups the backstop below throws away.
        raise ValueError(f"the frame carries {len(off_salary)} Player_IDs the salary "
                         f"file does not list, e.g. {off_salary[:3]}")

    now = clock()
    window = []
    if deadline is not None:
        window.append((float(deadline), "deadline"))
    if budget_s is not None:
        window.append((now + float(budget_s), "budget_s"))
    if not window:
        window.append((now + float(repo_env.call_budget_s()), "repo_env.call_budget_s"))
    end, window_source = min(window)

    required = max((len(r.fillable_entry_ids) for r in reqs), default=0)
    target = max(required, int(target_distinct or 0))
    held_max = max((len(r.held_signatures) for r in reqs), default=0)

    digest_in = projection_digest(projections)
    pool = {
        "frame_rows": int(len(projections)),
        "rows_not_excluded": int(len(_drop_excluded_rows(projections))),
        "projection_digest_in": digest_in,
        "salary_ids": len(salary_ids),
        "salary_id_misses": 0,
        "malformed_rosters": 0,
        "note": "the frame is handed whole to every solve and no solve here "
                "passes excludes; the optimizer's own reading of the Excluded "
                "column is the only removal",
    }

    candidates: List[BaselineCandidate] = []
    seen: set = set()
    rejected: List[Tuple[str, ...]] = []
    worst = 0.0
    timings: Dict[str, Any] = {"window_s": round(end - now, 3),
                               "window_source": window_source,
                               "probe_s": 0.0, "grid_s": 0.0, "fill_s": 0.0}
    probe: Dict[str, Any] = {"attempted": False}
    grid: Dict[str, Any] = {"attempted": False}
    stop_reason: Optional[str] = None

    def admit(roster, objective, source, solver) -> bool:
        """True when the roster became a candidate."""
        if roster is None:
            return False
        roster = tuple(str(p) for p in roster)
        if len(roster) != ROSTER_SIZE or len(set(roster)) != ROSTER_SIZE:
            pool["malformed_rosters"] += 1
            return False
        if any(p not in salary_ids for p in roster):
            pool["salary_id_misses"] += 1
            rejected.append(roster)
            return False
        sig = lineup_signature(roster)
        if sig in seen:
            return False
        members = set(roster)
        shared = max((len(members & set(c.roster)) for c in candidates), default=0)
        seen.add(sig)
        candidates.append(BaselineCandidate(
            len(candidates), roster, sig, float(objective), source, solver, shared))
        return True

    def satisfied() -> bool:
        if len(candidates) < target:
            return False
        for req in reqs:
            held = set(req.held_signatures)
            usable = sum(1 for c in candidates if c.signature not in held)
            if usable < len(req.fillable_entry_ids):
                return False
        return True

    if target == 0:
        stop_reason = "nothing_to_fill"

    # 1. The probe, candidate #1.
    probe_infeasible = False
    if stop_reason is None:
        remaining = end - clock()
        if remaining <= 0:
            stop_reason = "time_budget"
        else:
            probe["attempted"] = True
            status = _new_solver_status()
            t0 = time.monotonic()
            try:
                lineup, objective = build_single_lineup(
                    projections, target="ceiling",
                    max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
                    time_limit_s=resolve_solver_time_limit(None, remaining),
                    status_out=status)
                wall = time.monotonic() - t0
                record = _solver_record(status, wall)
                probe.update(record)
                roster = ordered_roster(lineup) if lineup is not None else None
                probe["admitted"] = admit(roster, objective, "probe", record)
                probe_infeasible = bool(status.get("proven_infeasible"))
                if not status.get("timed_out"):
                    worst = max(worst, wall)
            except Exception as exc:  # noqa: BLE001 - a solver outcome, recorded
                wall = time.monotonic() - t0
                probe.update(_solver_record(status, wall))
                probe["error"] = f"{type(exc).__name__}: {exc}"[:300]
                probe["admitted"] = False
                worst = max(worst, wall)
            probe["note"] = ("a timing proxy on the unenriched frame; not "
                             "run_classic's single_s, which is timed on the "
                             "enriched frame with ownership attached")
            timings["probe_s"] = round(time.monotonic() - t0, 4)

    # 2. The grid, in memory.
    if stop_reason is None and not satisfied():
        remaining = end - clock()
        if remaining <= worst:
            stop_reason = "time_budget"
        else:
            grid["attempted"] = True
            t0 = time.monotonic()
            cache = _MemoryBankCache()
            try:
                report = extend_bank(
                    cache, projections, time_budget_s=float(remaining),
                    max_candidates=int(target + held_max),
                    max_opposing_hitters_per_sp=max_opposing_hitters_per_sp)
                grid.update({k: report.get(k) for k in (
                    "stop_reason", "jobs_total", "jobs_attempted", "built_this_slice",
                    "attempted_this_slice", "job_list_exhausted", "jobs_timed_out",
                    "time_limited_accepted", "elapsed_s", "max_candidates")})
            except Exception as exc:  # noqa: BLE001 - a solver outcome, recorded
                grid["error"] = f"{type(exc).__name__}: {exc}"[:300]
            # Outside the try: a raise after jobs ran keeps what they built.
            for entry in cache.candidates:
                admit(entry.get("roster"), entry.get("objective", 0.0), "grid", None)
            timings["grid_s"] = round(time.monotonic() - t0, 4)

    # 3. Distinct fill.
    if stop_reason is None and not satisfied():
        if probe_infeasible and not candidates:
            # The probe is this solve with no overlap rows; every fill solve is
            # the same problem with more rows, so it cannot be feasible.
            stop_reason = "search_exhausted"
    if stop_reason is None and not satisfied():
        t0 = time.monotonic()
        while not satisfied():
            remaining = end - clock()
            if remaining <= worst:
                stop_reason = "time_budget"
                break
            status = _new_solver_status()
            limit = resolve_solver_time_limit(None, remaining)
            s0 = time.monotonic()
            reference = [list(c.roster) for c in candidates] + [list(r) for r in rejected]
            try:
                lineup, objective = build_single_lineup(
                    projections, target="ceiling",
                    overlap_reference=reference, max_overlap=ROSTER_SIZE - 1,
                    max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
                    time_limit_s=limit, status_out=status)
            except Exception as exc:  # noqa: BLE001 - a solver outcome, recorded
                grid.setdefault("fill_errors", []).append(
                    f"{type(exc).__name__}: {exc}"[:300])
                stop_reason = "solver_error"
                break
            wall = time.monotonic() - s0
            if not status.get("timed_out"):
                worst = max(worst, wall)
            roster = ordered_roster(lineup) if lineup is not None else None
            if roster is None:
                if status.get("proven_infeasible"):
                    stop_reason = "search_exhausted"
                elif status.get("timed_out"):
                    stop_reason = ("time_budget" if limit >= remaining
                                   else "solve_time_limit")
                else:
                    stop_reason = "solver_unanswered"
                break
            before = len(candidates) + len(rejected)
            admit(roster, objective, "distinct_fill", _solver_record(status, wall))
            if len(candidates) + len(rejected) == before:
                # A returned lineup the overlap rows should have excluded.
                stop_reason = "solver_unanswered"
                break
        timings["fill_s"] = round(time.monotonic() - t0, 4)

    if satisfied():
        stop_reason = stop_reason if stop_reason == "nothing_to_fill" else "covered"
    elif stop_reason is None:
        stop_reason = "search_exhausted"

    assignments, uncovered, coverage = _assign(reqs, candidates)
    short = max((c.fillable - c.filled for c in coverage), default=0)
    pool["projection_digest_after"] = projection_digest(projections)
    timings["total_s"] = round(time.monotonic() - started_wall, 4)
    timings["left_s"] = round(end - clock(), 3)
    return BaselineResult(
        construction_label=CONSTRUCTION_LABEL,
        note=CONSTRUCTION_NOTE,
        status="covered" if short == 0 and not uncovered else "short",
        stop_reason=stop_reason,
        required=required,
        target=target,
        distinct=len(candidates),
        short=short,
        target_met=len(candidates) >= target,
        candidates=tuple(candidates),
        assignments=assignments,
        uncovered=uncovered,
        by_contest=coverage,
        probe=probe,
        grid=grid,
        pool=pool,
        timings=timings,
    )
