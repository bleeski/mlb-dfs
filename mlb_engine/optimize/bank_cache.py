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
3. **Two kinds of fact live in the conditions signature, and only one of them
   invalidates** (R101). The PROJECTION values are truth: when they move, a
   stored candidate is an answer to a question nobody asked, and it is dropped
   (the 2026-07-26 incident in ``_job_key``'s docstring). The excludes and the
   stack bounds are a per-request NARROWING: they shrink the legal set for one
   caller and say nothing about anyone else's. Folding both into one signature
   meant every targeted late-swap slice deleted the general bank and the
   previous slices with it. They are separated now -- ``projection_digest``
   destroys, the conditions signature buckets -- and the union of live buckets
   is what ``as_candidates`` serves. That is safe because per-entry legality is
   enforced downstream by ``contest_allocator._entry_candidate_compatible``,
   which tests every candidate against that entry's pins and its
   ``excluded_new_teams``: the bank is a superset, the allocator is the filter.

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
    ANTI_CORRELATION_DEFAULT_MAX, ANTI_CORRELATION_STATUS_KEY,
    anti_correlation_report, build_single_lineup, _new_solver_status,
    _drop_excluded_rows, resolve_solver_time_limit,
)

VERSION = "v1.3"


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
    already ANSWERED. A job is answered when a lineup came back or when the
    solver proved infeasibility under these conditions; a proven-infeasible
    combination is recorded so a resumed run does not re-pay for it. A timeout,
    a raised exception, and an empty return that proved nothing are all
    UNANSWERED and stay retryable (R55b). ``clear_attempted`` is the escape hatch
    for a record poisoned before that distinction existed.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.candidates: List[Dict[str, Any]] = []
        self.attempted: set[str] = set()
        self._seen: set[Tuple[str, ...]] = set()
        # Keys cleared by clear_attempted and not yet persisted. save() unions
        # memory with disk, so without this a clear would be undone by the very
        # next save (R55).
        self._cleared: set[str] = set()
        # R101. conditions signature -> the projection digest it was built
        # under. Persisted, because that is the only record of WHICH kind of
        # difference separates two stored buckets: same pool truth (live, keep)
        # or different pool truth (stale, purge).
        self.conditions_index: Dict[str, str] = {}
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
            self._cleared = set()
            self.conditions_index = {}
            return
        self.attempted = set(payload.get("attempted") or [])
        self.conditions_index = {
            str(k): str(v) for k, v in (payload.get("conditions_index") or {}).items()
        }
        # R101: memory now legitimately holds several buckets at once, so a
        # roster stored twice under two signatures would reach the solve twice
        # and double-count in every exposure denominator. Deduping here keeps
        # `len(cache)` the number of distinct candidates it has always meant.
        self.candidates = []
        self._seen = set()
        for entry in (payload.get("candidates") or []):
            key = tuple(str(p) for p in (entry.get("roster") or []))
            if len(key) != 10 or not all(key) or key in self._seen:
                continue
            self._seen.add(key)
            self.candidates.append(entry)

    def register_conditions(self, conditions_sig: str, projection_digest: str) -> None:
        """Record which projection truth a conditions signature was built under."""
        if conditions_sig and projection_digest:
            self.conditions_index[str(conditions_sig)] = str(projection_digest)

    def live_buckets(self) -> List[str]:
        """The distinct conditions signatures currently held in memory, sorted."""
        return sorted({_key_conditions(c.get("job")) for c in self.candidates
                       if c.get("job")})

    def drop_stale_jobs(self, conditions_sig: str, projection_digest: str = "") -> int:
        """Forget candidates and attempts built under a different pool truth.

        A job key ends with the conditions signature. R101 splits what that
        signature encodes into two questions and answers them separately:

        * Was this built under the projections now in force? ``projection_digest``
          answers it through ``conditions_index``. No means the stored answer is
          an answer to a different question and it goes -- the 2026-07-26
          incident, where a rebuild after the DK Status filter landed certified a
          pitcher with no role out of a cache built before the filter existed.
        * Was it built under this exact request's excludes and stack bounds?
          That is a NARROWING, and a narrower request does not make another
          caller's lineups illegal. It buckets. ``as_candidates`` serves the
          union and ``contest_allocator._entry_candidate_compatible`` filters
          per entry.

        A signature the index cannot place fails CLOSED: not provably under this
        pool's truth, so it is dropped. That is what stops a cache file written
        before this change from resurrecting pre-invalidation candidates.

        Omitting ``projection_digest`` keeps the v1.2 behaviour exactly -- only
        ``conditions_sig`` survives -- which is what the maintenance callers and
        the concurrency tests rely on. Returns how many were dropped.
        """
        if not conditions_sig:
            return 0

        def _live(job: Any) -> bool:
            sig = _key_conditions(job)
            if sig == conditions_sig:
                return True
            if not projection_digest:
                return False
            return self.conditions_index.get(sig) == projection_digest

        stale_attempts = {k for k in self.attempted if not _live(k)}
        stale_candidates = [
            c for c in self.candidates if c.get("job") and not _live(c["job"])
        ]
        if not stale_attempts and not stale_candidates:
            return 0
        self.attempted -= stale_attempts
        stale_ids = {id(c) for c in stale_candidates}
        keep = [c for c in self.candidates if id(c) not in stale_ids]
        self.candidates = keep
        self._seen = {tuple(str(p) for p in c["roster"]) for c in keep}
        return len(stale_attempts) + len(stale_candidates)

    def clear_attempted(self, conditions_sig: str = "") -> int:
        """Forget the attempted-job record, keeping every candidate. Returns the count.

        The maintenance escape hatch for a poisoned bank (R55). `attempted` is
        meant to hold answered jobs, and a bug that recorded unanswered ones
        leaves a cache that reports `job_list_exhausted: True` over an empty
        candidate list and will never retry a single job -- the failure looks
        like a dry pool forever, and `drop_stale_jobs` cannot help because the
        conditions signature is unchanged.

        Pass a `conditions_sig` to clear only the jobs solved under those
        conditions; omit it to clear every attempt. Candidates are never touched:
        real lineups are real regardless of what poisoned the attempt record, and
        `add` dedupes rosters, so re-running a cleared job cannot double-count.
        """
        if conditions_sig:
            suffix = f"|{conditions_sig}"
            doomed = {k for k in self.attempted if k.endswith(suffix)}
        else:
            doomed = set(self.attempted)
        if not doomed:
            return 0
        self.attempted -= doomed
        self._cleared |= doomed
        return len(doomed)

    def save(self) -> None:
        """Reload-and-union, then tmp + os.replace (R22).

        The write was already atomic (a kill mid-save used to poison the file
        permanently), but it was a whole-file replace at the end of a
        read-modify-write window minutes long, so the later of two concurrent
        slices discarded the earlier one's candidates and attempted keys, and
        one session's drop_stale_jobs persisted the erasure of another
        session's live work. The union written here keeps every writer's work
        on disk. Memory deliberately keeps this writer's own view: it is what
        as_candidates serves and what the suffix-filtered report counts read,
        and entries built under someone else's conditions signature are not
        answers to this session's question. They survive in the file for that
        session's next resume instead of being erased by this one.

        R101: memory now holds several live buckets rather than one, and none of
        that changes here. The union is still keyed on the ordered roster, so a
        roster this writer holds under one signature and the disk holds under
        another is written once. The conditions index is unioned on the same
        principle -- another session's signature is another session's fact, and
        dropping it would make its buckets unplaceable and therefore stale.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        disk_candidates: List[Dict[str, Any]] = []
        disk_attempted: set[str] = set()
        disk_index: Dict[str, str] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                disk_candidates = list(payload.get("candidates") or [])
                disk_attempted = set(payload.get("attempted") or [])
                disk_index = {str(k): str(v) for k, v
                              in (payload.get("conditions_index") or {}).items()}
            except (OSError, ValueError):
                pass  # unreadable disk state is rebuilt, the same policy as _load
        merged_seen = set(self._seen)
        merged_candidates = list(self.candidates)
        for cand in disk_candidates:
            key = tuple(str(p) for p in (cand.get("roster") or []))
            if len(key) == 10 and all(key) and key not in merged_seen:
                merged_seen.add(key)
                merged_candidates.append(cand)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({
            "version": VERSION,
            "candidates": merged_candidates,
            # The union keeps concurrent writers' work (see above). Keys an
            # operator deliberately cleared are subtracted once, here, or the
            # union would silently reinstate them (R55).
            "attempted": sorted((self.attempted | disk_attempted) - self._cleared),
            # Sorted, because this file is read by the next session and an
            # unordered map makes two identical caches look different.
            "conditions_index": dict(sorted({**disk_index,
                                             **self.conditions_index}.items())),
        }, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        self._cleared = set()

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

        R37, v1.3: ``primary_stack_size`` is emitted alongside it, and the
        omission it repairs was not cosmetic. The allocator reads the SIZE
        through ``_candidate_primary_stack_size``, which returns 0 when the key
        is absent, and 0 is also the honest encoding of a stackless lineup. So
        every sliced-path candidate reported "no stack" no matter what it held:
        measured on the 2026-08-08 1910_9g delivery, seven bank-cache
        candidates carrying real four-man stacks all read 0. Any size-
        conditioned control reading that bank is not merely weakened, it is
        inverted -- R34's five-stack quota would have refused a bank that
        satisfied it, and R37's primary-stack floor would exclude every
        candidate it was handed. The team was emitted and the count was not,
        which is the sort of half-plumbed field that reads as working.

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

        R101, v1.3: this serves the UNION of every live conditions bucket, which
        under ``drop_stale_jobs`` means every bucket built under the projections
        now in force. It emits one payload per distinct ordered roster, first
        occurrence wins, and counts what it collapsed under
        ``duplicate_rosters_dropped`` -- two buckets can legitimately reach the
        same ten players in the same ten slots, and a candidate list that names
        it twice double-counts in every exposure denominator the allocator
        computes.
        """
        from mlb_engine.optimize.optimizer_v3 import (
            candidate_primary_stack, candidate_primary_stack_size,
            score_lineup_candidate, _mode_for_contest_shape,
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
        duplicate_rosters = 0
        emitted: set[Tuple[str, ...]] = set()
        failure_reasons: Dict[str, int] = {}
        if projections_df is not None and hasattr(projections_df, "columns"):
            frame = projections_df.copy()
            frame["__pid__"] = frame["Player_ID"].astype(str)
            by_id = frame.set_index("__pid__", drop=False)

        for i, entry in enumerate(self.candidates):
            cid = f"bank{i}"
            roster = [str(p) for p in entry["roster"]]
            if tuple(roster) in emitted:
                duplicate_rosters += 1
                continue
            emitted.add(tuple(roster))
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
                # R37. Stays 0 when the frame cannot resolve the roster, which
                # is the same value a genuinely stackless lineup carries. The
                # allocator therefore cannot tell "no stack" from "not
                # measured" per candidate, and treats a bank where NO candidate
                # reports a size as unmeasurable rather than as a bank of
                # stackless lineups.
                "primary_stack_size": 0,
            }
            if by_id is not None:
                try:
                    lineup_df = by_id.loc[[p for p in roster if p in by_id.index]]
                    if len(lineup_df) != len(roster):
                        raise KeyError(
                            f"{len(roster) - len(lineup_df)} roster ids absent from projections"
                        )
                    payload["primary_stack"] = candidate_primary_stack(lineup_df)
                    payload["primary_stack_size"] = candidate_primary_stack_size(lineup_df)
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
            # R101. `stored` minus `duplicate_rosters_dropped` is `candidates`,
            # and `scored` plus `scoring_failed` is `candidates` again when
            # projections were supplied. Every gap between the number the
            # operator reads and the number the solve gets is named on the line
            # it appears on, which is the whole point of the item.
            "stored": len(self.candidates),
            "duplicate_rosters_dropped": duplicate_rosters,
            "conditions_buckets": self.live_buckets(),
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


# The projection columns the objective is built from. Hashing the VALUES rather
# than the row count matters: an enrichment pass changes Ceiling without
# changing the pool.
_PROJECTION_COLUMNS: Tuple[str, ...] = (
    "Player_ID", "Ceiling", "Floor", "Base", "Salary", "Excluded",
)


def _projection_bytes(projections_df) -> bytes:
    """The projection half of the signature, as the exact bytes both digests hash.

    Factored out of ``conditions_signature`` byte-for-byte (R101). The stored
    signatures in every live cache file are values of that function, so the
    stream it feeds sha256 is a compatibility surface: change the bytes and
    every cache on disk silently invalidates on its next read.
    """
    chunks: List[bytes] = []
    for column in _PROJECTION_COLUMNS:
        if column not in getattr(projections_df, "columns", []):
            continue
        try:
            values = projections_df.sort_values("Player_ID")[column].tolist()
        except Exception:  # noqa: BLE001 - a signature must not kill a build
            values = list(projections_df[column])
        chunks.append((column + ":" + ",".join(f"{v}" for v in values) + "\n").encode())
    return b"".join(chunks)


def projection_digest(projections_df) -> str:
    """The INVALIDATING half: the pool and projection truth, and nothing else.

    R101. A change here means every stored candidate answers a different
    question, so ``drop_stale_jobs`` destroys on a mismatch. It deliberately
    does NOT read the excludes or the stack bounds: those narrow one caller's
    search and say nothing about whether another caller's stored lineups are
    still real.
    """
    digest = hashlib.sha256()
    digest.update(b"pool-v1")
    digest.update(_projection_bytes(projections_df))
    return digest.hexdigest()[:16]


def conditions_signature(
    projections_df,
    excludes: Optional[Sequence[str]] = None,
    stack_min: Optional[int] = None,
    stack_max: Optional[int] = None,
    max_opposing_hitters_per_sp: Optional[int] = None,
) -> str:
    """A short digest of everything outside (pair, team, locks) that moves a solve.

    Covers the excluded set, the stack bounds, and the projection values the
    objective is built from. This is the BUCKET key: it identifies the exact
    question a stored candidate answered. Whether that bucket is still live is
    :func:`projection_digest`'s call, not this one's (R101).

    The byte stream is unchanged from v1.2 on purpose, so the signatures already
    written into live cache files keep their meaning across this change.

    R288 rider. ``max_opposing_hitters_per_sp`` changes the constraint matrix,
    so a candidate built at 0 answers a different question than one built at 2 --
    reusing the first for the second would serve a bank that structurally cannot
    contain what was asked for, and the reuse would be invisible. It is appended
    ONLY when non-default, so every signature already written to a live cache file
    keeps its meaning, which is the same rule the v1.2 byte stream follows above.

    NOTE, filed and not fixed here: R246's three leverage controls are NOT in this
    signature and have the same property, so a bank built under
    `max_cumulative_ownership_pct` is reused for a build without it. Filed as
    R290; the fix is one more append and the measurement of what it invalidates
    is the part that needs a session.
    """
    digest = hashlib.sha256()
    digest.update(b"v2")
    digest.update(("|".join(sorted(str(x) for x in (excludes or []))) + "\n").encode())
    digest.update(f"{stack_min}:{stack_max}\n".encode())
    if max_opposing_hitters_per_sp not in (None, ANTI_CORRELATION_DEFAULT_MAX):
        digest.update(
            f"opp:{int(max_opposing_hitters_per_sp)}\n".encode())
    digest.update(_projection_bytes(projections_df))
    return digest.hexdigest()[:16]


def _key_conditions(job: Any) -> str:
    """The conditions signature a job key ends with. Empty for a keyless entry."""
    return str(job or "").rpartition("|")[2]


def _lock_signature(locked_slot_assignments: Optional[Mapping[str, str]]) -> str:
    if not locked_slot_assignments:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(locked_slot_assignments.items()))


#: R246. The three R154 solver controls, named once so every caller that
#: forwards them forwards the same set. A key absent from the mapping stays
#: absent from the call, so the solver sees `None` and builds no constraint --
#: opt-in, and a build that passes nothing solves exactly the MILP it always did.
LEVERAGE_KEYS = ("max_cumulative_ownership_pct", "min_low_owned_hitters",
                 "low_owned_threshold_pct")


def _leverage_kwargs(leverage: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Only the keys actually supplied, so nothing is passed as an explicit None.

    A caller who sets a cumulative cap and no floor gets the cap constraint and
    no floor constraint; the two are independently settable because
    `min_low_owned_hitters` has a real infeasibility edge (measured on 1605_2g:
    a floor of 6 under a 6.0% threshold is infeasible on a pool whose best
    lineup carries zero hitters that cheap) and an operator has to be able to
    back one off without losing the other.
    """
    out: Dict[str, Any] = {}
    for key in LEVERAGE_KEYS:
        value = (leverage or {}).get(key)
        if value is not None:
            out[key] = value
    return out


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
    leverage: Optional[Mapping[str, Any]] = None,
    max_opposing_hitters_per_sp: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate candidates across (SP pair, stack team) until the budget runs out.

    Returns a report with what was built and whether the job list is exhausted, so
    the caller knows whether another slice is worth running. ``locked_slot_assignments``
    pins DK slots for a late-swap entry; ``excludes`` carries that entry's
    ``excluded_new_teams`` player IDs.

    R101: calling this repeatedly with different ``excludes`` or different pins
    ADDS buckets to the cache. It no longer discards the previous calls' work,
    which is what made ``tools/late_swap.py`` hand its joint solve a bank two
    orders of magnitude smaller than the one it had just paid to build. What
    still discards is a change in the projections themselves -- see
    :func:`projection_digest`.

    One consequence to hold onto, because it is not obvious from the call site:
    the stack bounds are relaxed to the free hitter slots BEFORE the signature is
    computed, so a heavily pinned entry buckets under bounds that are looser than
    the general slice's, and the union can therefore contain candidates carrying
    a smaller primary stack than the general call asked for. That is not a
    loophole in the stack rule -- generation bounds were never the enforcement
    point. The allocator's ``primary_stack_min_size`` floor is (R37 stage 1,
    4 on every posture), it is applied to whatever bank it is handed, and every
    relaxation of it is counted in the report.
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
    # R101 splits it in two: the pool digest is the half that INVALIDATES, the
    # full signature is the bucket this slice writes into. Register before the
    # drop, so the bucket this call is about to fill is placeable by the next one.
    conditions_sig = conditions_signature(
        projections_df, excl, stack_min, stack_max,
        max_opposing_hitters_per_sp=max_opposing_hitters_per_sp)
    pool_digest = projection_digest(projections_df)
    cache.register_conditions(conditions_sig, pool_digest)
    superseded = cache.drop_stale_jobs(conditions_sig, projection_digest=pool_digest)

    # R291(d) / R164's third member. The job grid is enumerated from the LEGAL
    # pool, not from every salary row. `build_single_lineup` drops an excluded
    # row inside `_prepare_single_lineup_df`, so an excluded arm or an
    # all-excluded stack team was never going to produce a candidate -- the grid
    # simply paid a full `proven_infeasible` solve per job to find that out, and
    # then recorded the key as attempted so no later slice could tell the
    # difference between "answered" and "never legal".
    #
    # `projections_df` itself is deliberately NOT narrowed: the signature and
    # the digest above hash the whole frame including the Excluded column (which
    # is what keeps a restricted build off an unrestricted bank's bucket), and
    # every solve below is handed the full frame so the ONE removal site stays
    # `optimizer_v3._drop_excluded_rows`.
    eligible = _drop_excluded_rows(projections_df)
    excluded_dropped = int(len(projections_df) - len(eligible))
    pitchers = eligible[eligible["Position"] == "P"]
    if "Ceiling" in pitchers.columns:
        pitchers = pitchers.sort_values("Ceiling", ascending=False)
    sp_ids = [str(p) for p in pitchers["Player_ID"] if str(p) not in set(excl)]
    game_of = {str(r.Player_ID): str(r.Game_ID) for r in eligible.itertuples()}
    hitters = eligible[eligible["Position"] != "P"]
    teams = sorted({str(t) for t in hitters["Team"]})
    all_pitchers = projections_df[projections_df["Position"] == "P"]
    excluded_arms_dropped = int(len(all_pitchers) - len(pitchers))
    all_hitters = projections_df[projections_df["Position"] != "P"]
    excluded_teams_dropped = sorted(
        {str(t) for t in all_hitters["Team"]} - set(teams))

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

    # R103. When both P slots are pinned, `pair_space` is already the one pair
    # this repair job must use -- a fact about a file DK already accepted, not
    # a candidate for bank diversity. The same-game filter below exists to keep
    # a FRESH bank from wasting jobs on an anti-correlated pair; it has nothing
    # to say about a pair that is no longer a choice. Without this, a pinned
    # same-game pair (both P slots locked to one matchup) was silently
    # filtered to an empty job list and the slice reported "+0 targeted
    # candidates" on an entry that was never repairable for a pool reason.
    both_pinned = len(pinned_sps) >= 2
    pinned_pair_same_game_kept = False
    usable_pairs = []
    unknown_game_pairs = 0
    for a, b in pair_space:
        if both_pinned:
            ga, gb = game_of.get(a), game_of.get(b)
            if _known(ga) and _known(gb) and ga == gb:
                pinned_pair_same_game_kept = True
            usable_pairs.append((a, b))
            continue
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
    # R293. One entry per completed solve, read out of that solve's status.
    anti_corr_observed: List[Optional[int]] = []
    # R55(b). `attempted` means "this job has been ANSWERED", and only two
    # answers qualify: a lineup came back, or the solver PROVED infeasibility
    # under these conditions. Everything else is unanswered and retryable, and
    # each kind is counted here so a systematic failure cannot read as a dry
    # pool -- the exact misdiagnosis F13 exists to prevent.
    raised_by_reason: Dict[str, int] = {}
    raised_examples: List[str] = []
    unanswered_by_status: Dict[str, int] = {}
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
                # R246. This is the bank `build_slate.py` actually delivers from
                # -- it hands the result to `run_slate` as `candidates_override`,
                # which skips `build_diverse_candidate_bank` entirely. A
                # `--leverage` that reached only the auto-bank path would be a
                # silent no-op on every sliced build, which is most of them.
                **_leverage_kwargs(leverage),
                # R288. Reaches the sliced path for R246's reason: this is
                # the bank build_slate.py actually delivers from, and a
                # control that reached only the auto-bank would be a silent
                # no-op on most builds.
                max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
            )
            # R293. Recorded from the SOLVE, on the same "on every rung"
            # reasoning as the two lines above: this path was already wired, and
            # the report is what lets a reader tell a wired rung from an unwired
            # one without reading the source.
            anti_corr_observed.append(status.get(ANTI_CORRELATION_STATUS_KEY))
        except Exception as exc:  # noqa: BLE001
            worst = max(worst, time.monotonic() - attempt_started)
            # An exception is NEVER data (R55b). This handler's old comment said
            # "an infeasible combination is data, not an error" and then recorded
            # the key as attempted-forever -- but build_single_lineup returns
            # (None, None) for infeasibility and never raises for it. Anything
            # that reaches here is a NaN objective, a schema drift, a dtype
            # mismatch, or a bug: causes that a later slice CAN retry once
            # they are fixed, and none of which this job list has answered.
            # Recording them made a poisoned bank read as a completed one.
            reason = type(exc).__name__
            raised_by_reason[reason] = raised_by_reason.get(reason, 0) + 1
            if len(raised_examples) < 3:
                raised_examples.append(f"{reason}: {exc}"[:300])
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
        roster = ordered_roster(lineup_df)
        # Recorded only after the solve returned. Keys used to enter `attempted`
        # BEFORE the solve and persist, so a job that hit the time limit was
        # marked done forever and never retried on a later slice: the sliced path
        # is the big-slate path, and this quietly dropped exactly the jobs a
        # second slice exists to finish.
        #
        # R55(b): and a solve that came back empty WITHOUT proving infeasibility
        # is not an answer either. A returned lineup or a proven_infeasible
        # verdict is; anything else (roster_size_mismatch, a rejected incumbent,
        # a control that could not be matched) is counted by status and left
        # retryable, so 0-built-16-attempted-exhausted cannot happen again
        # without saying why.
        if not status.get("timed_out"):
            if roster is not None or bool(status.get("proven_infeasible")):
                cache.attempted.add(key)
            else:
                label = str(status.get("status") or "unknown")
                unanswered_by_status[label] = unanswered_by_status.get(label, 0) + 1
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
    live_buckets = cache.live_buckets()
    this_bucket = sum(1 for c in cache.candidates
                      if _key_conditions(c.get("job")) == conditions_sig)
    return {
        "version": VERSION,
        "built_this_slice": built,
        "attempted_this_slice": attempted_now,
        # R101: the union this cache will serve, which is now what the joint
        # solve receives. Before the split it was whatever the LAST slice
        # happened to leave behind, and the gap between the two is the whole
        # defect -- 1,007 stored, 8 solved, on 2026-08-03.
        "total_candidates": len(cache),
        "jobs_total": len(jobs),
        "jobs_attempted": done_here,
        "job_list_exhausted": exhausted,
        "elapsed_s": round(time.monotonic() - started, 3),
        "time_budget_s": float(time_budget_s),
        "lock_signature": lock_sig,
        "conditions_signature": conditions_sig,
        # The half that invalidates, named separately from the half that
        # buckets, so a reviewer can tell a purge from a new slice.
        "projection_digest": pool_digest,
        "conditions_buckets_live": len(live_buckets),
        "candidates_this_conditions": this_bucket,
        # Named so a reviewer can see the cache decided some of its stored work
        # no longer answers this build's question, rather than wondering why the
        # candidate count fell. Post-R101 a non-zero value here means the
        # PROJECTIONS moved (or a legacy cache held signatures this file cannot
        # place), never that a sibling slice ran.
        "superseded_jobs_dropped": superseded,
        "cache_was_corrupt_on_load": bool(getattr(cache, "corrupt_on_load", False)),
        "unknown_game_pairs_kept": unknown_game_pairs,
        # R291(d). What the operator's Excluded column removed from the JOB GRID,
        # named so a thin job list reads as the restriction it is rather than as
        # a dry pool -- the F13 misdiagnosis one door over. `rows` is every
        # excluded row, `arms` the pitchers that left the pair space, and
        # `stack_teams` the teams that lost every hitter and so cannot be a
        # stack target at all.
        "excluded_column_dropped": {
            "rows": excluded_dropped,
            "arms": excluded_arms_dropped,
            "stack_teams": excluded_teams_dropped,
            "note": "operator Excluded rows are removed from the pitcher/team "
                    "enumeration only; the frame handed to every solve is "
                    "unchanged and optimizer_v3._drop_excluded_rows is still "
                    "the one site that removes a player from a lineup",
        },
        # R293. The sliced path's rung of "what did these solves actually run
        # under". `requested` is this call's argument, `observed` comes off the
        # solves; the two agreeing is a measurement, not a restatement.
        "anti_correlation": anti_correlation_report(
            anti_corr_observed, requested=max_opposing_hitters_per_sp),
        # R103. Named so a +0-candidate slice on a fully-pinned entry reads as
        # the pin it is, not as a dry pool: True means both P slots were
        # pinned to a same-game pair and the same-game filter was bypassed to
        # keep it, because the file already fixed this pair as a fact.
        "pinned_pair_same_game_kept": pinned_pair_same_game_kept,
        "free_hitter_slots": free_hitter_slots,
        "stack_min_relaxed_to": stack_relaxed_to,
        # F13: named so a thin slice reads as the clock rather than as a pool
        # that could not produce lineups. These jobs are retryable and a second
        # slice will pick them up.
        "jobs_timed_out": timed_out_jobs,
        "time_limited_accepted": time_limited_accepted,
        "solver_time_limit_s": resolve_solver_time_limit(solver_time_limit_s),
        # R55(b): a raised exception is a defect, not a dry pool. Counted per
        # reason with up to three verbatim examples, and never entered in
        # `attempted`, so a later slice retries once the cause is fixed.
        "jobs_raised": sum(raised_by_reason.values()),
        "raised_by_reason": dict(sorted(raised_by_reason.items())),
        "raised_examples": list(raised_examples),
        # Solves that returned no lineup and proved nothing. Also retryable.
        "jobs_unanswered": sum(unanswered_by_status.values()),
        "unanswered_by_status": dict(sorted(unanswered_by_status.items())),
        "note": "deterministic candidate generation through the certified MILP path; "
                "never an ROI, win-rate, or probability claim",
    }
