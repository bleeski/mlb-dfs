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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

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
        self._retired: set[str] = set()
        # R101. conditions signature -> the projection digest it was built
        # under. Persisted, because that is the only record of WHICH kind of
        # difference separates two stored buckets: same pool truth (live, keep)
        # or different pool truth (stale, purge).
        self.conditions_index: Dict[str, str] = {}
        # R465. conditions signature -> the facts it was built under
        # (`conditions_facts`). A SIBLING of the index, not a change to its
        # values, and absent for any bucket a pre-R465 file registered: an
        # absent entry reads as UNKNOWN, never as a guess.
        self.conditions_facts: Dict[str, Dict[str, Any]] = {}
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
            self.conditions_facts = {}
            return
        self.attempted = set(payload.get("attempted") or [])
        self._retired = set(payload.get("retired_jobs") or [])
        self.attempted -= self._retired
        self.conditions_index = {
            str(k): str(v) for k, v in (payload.get("conditions_index") or {}).items()
        }
        self.conditions_facts = _read_facts_map(payload.get("conditions_facts"))
        # R101: memory now legitimately holds several buckets at once, so a
        # roster stored twice under two signatures would reach the solve twice
        # and double-count in every exposure denominator. Deduping here keeps
        # `len(cache)` the number of distinct candidates it has always meant.
        self.candidates = []
        self._seen = set()
        for entry in (payload.get("candidates") or []):
            if entry.get("job") in self._retired:
                continue
            key = tuple(str(p) for p in (entry.get("roster") or []))
            if len(key) != 10 or not all(key) or key in self._seen:
                continue
            self._seen.add(key)
            self.candidates.append(entry)

    def register_conditions(self, conditions_sig: str, projection_digest: str,
                            facts: Optional[Mapping[str, Any]] = None) -> None:
        """Record which projection truth a conditions signature was built under.

        R465. ``facts`` (``conditions_facts``) is what the bucket was built
        under, kept beside the index so a brief can NAME a served bucket. It is
        round-tripped through JSON here so the in-memory view is exactly what a
        reload will read (an int stays an int, a float stays a float). A caller
        that passes none leaves any facts already registered for the signature
        alone: the same signature is the same question, so a later request for
        it fills in a bucket an older file held without facts.
        """
        if conditions_sig and projection_digest:
            self.conditions_index[str(conditions_sig)] = str(projection_digest)
            if facts is not None:
                self.conditions_facts[str(conditions_sig)] = json.loads(
                    json.dumps(facts, sort_keys=True, allow_nan=False))

    def live_buckets(self) -> List[str]:
        """The distinct conditions signatures currently held in memory, sorted."""
        return sorted({_key_conditions(c.get("job")) for c in self.candidates
                       if c.get("job")})

    def count_outside_buckets(self, conditions_sigs: Iterable[str]) -> int:
        """R453. Stored candidates built under a conditions bucket NOT in ``conditions_sigs``.

        ``as_candidates`` serves the union of every live bucket, so a caller that
        asked for some questions can be handed answers to others (an earlier
        build's, on a shared cache). This is how many, and it says nothing about
        WHAT those buckets were built under: the signature is a hash. A keyless
        candidate (a cache written before job keys carried a signature) belongs
        to no bucket and counts as outside.
        """
        asked = {str(sig) for sig in conditions_sigs}
        return sum(1 for c in self.candidates
                   if _key_conditions(c.get("job")) not in asked)

    def describe_outside_buckets(self, conditions_sigs: Iterable[str]) -> List[Dict[str, Any]]:
        """R465. The buckets :meth:`count_outside_buckets` counts, NAMED.

        One row per bucket outside ``conditions_sigs``: its signature, how many
        stored candidates it holds, and what it was built under (``conditions_facts``
        in display form, ``excludes`` shown as a count because a late-swap bucket
        carries hundreds of ids and this list rides in the brief). ``built_under``
        is ``None`` where no facts are registered (a file written before R465, or
        a keyless candidate, signature ``""``): unknown, never a guess. The
        candidate counts sum to ``count_outside_buckets``. Largest bucket first,
        then signature, so the list is deterministic.
        """
        asked = {str(sig) for sig in conditions_sigs}
        held: Dict[str, int] = {}
        for c in self.candidates:
            sig = _key_conditions(c.get("job"))
            if sig not in asked:
                held[sig] = held.get(sig, 0) + 1
        rows = []
        for sig, n in sorted(held.items(), key=lambda kv: (-kv[1], kv[0])):
            facts = self.conditions_facts.get(sig) if sig else None
            rows.append({"conditions_signature": sig, "candidates": n,
                         "built_under": _display_facts(facts)})
        return rows

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

        **Dropping and RETIRING are two different acts (R338 repair (1)).** The
        F11 tombstone was applied to every dropped job, which made the v1.2
        memory-only narrowing above erase a sibling session's bucket from the
        shared file -- the R55/R130 incident arriving through the fix for the
        opposite one. A job is tombstoned only where this call can PROVE the
        stored answer answers a different question: ``projection_digest`` is
        supplied AND ``conditions_index`` places that signature under a
        different digest. Everything else is dropped from memory and left on
        disk for its own writer, which is what the union is for. Note the
        asymmetry with ``_live`` above and it is deliberate: a signature the
        index cannot place fails CLOSED for the DROP (this caller must not
        serve it) and OPEN for the tombstone (this caller cannot prove it is
        dead, and an unregistered signature is what a concurrent writer's
        bucket looks like before it registers).
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

        def _provably_dead(job: Any) -> bool:
            if not projection_digest:
                return False
            sig = _key_conditions(job)
            if sig == conditions_sig:
                return False
            placed = self.conditions_index.get(sig)
            return placed is not None and placed != projection_digest

        stale_attempts = {k for k in self.attempted if not _live(k)}
        stale_candidates = [
            c for c in self.candidates if c.get("job") and not _live(c["job"])
        ]
        if not stale_attempts and not stale_candidates:
            return 0
        self.attempted -= stale_attempts
        self._retired.update(k for k in stale_attempts if _provably_dead(k))
        self._retired.update(c["job"] for c in stale_candidates
                             if _provably_dead(c["job"]))
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
        """Serialize reload/merge/replace and preserve invalidation tombstones."""
        import sqlite3
        from contextlib import closing
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path.with_suffix(self.path.suffix + ".lock.sqlite3"), timeout=5)) as db:
            db.execute("BEGIN IMMEDIATE")
            self._save_locked()
            db.commit()

    def _save_locked(self) -> None:
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
        disk_facts: Dict[str, Dict[str, Any]] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                disk_candidates = list(payload.get("candidates") or [])
                disk_attempted = set(payload.get("attempted") or [])
                disk_index = {str(k): str(v) for k, v
                              in (payload.get("conditions_index") or {}).items()}
                disk_facts = _read_facts_map(payload.get("conditions_facts"))
                self._retired.update(payload.get("retired_jobs") or [])
            except (OSError, ValueError):
                pass  # unreadable disk state is rebuilt, the same policy as _load
        merged_candidates = [c for c in self.candidates if c.get("job") not in self._retired]
        merged_seen = {tuple(str(p) for p in c["roster"]) for c in merged_candidates}
        for cand in disk_candidates:
            if cand.get("job") in self._retired:
                continue
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
            "attempted": sorted((self.attempted | disk_attempted) - self._cleared - self._retired),
            "retired_jobs": sorted(self._retired),
            # Sorted, because this file is read by the next session and an
            # unordered map makes two identical caches look different.
            "conditions_index": dict(sorted({**disk_index,
                                             **self.conditions_index}.items())),
            # R465. Unioned on the same principle as the index: another
            # session's bucket keeps the facts it registered.
            "conditions_facts": dict(sorted({**disk_facts,
                                             **self.conditions_facts}.items())),
        }, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        self._cleared = set()

    def add(self, roster: Sequence[str], objective: float, job: str = "",
            job_class: Optional[str] = None) -> bool:
        """Store a candidate. Dedupes on the ordered roster, never the player set.

        R405(c). ``job_class`` names a job built under a non-default search
        constraint (``consensus_limited``); it is stored only when set, so an
        ordinary entry keeps the three keys every cache file on disk holds.
        """
        key = tuple(str(p) for p in roster)
        if len(key) != 10 or not all(key) or key in self._seen:
            return False
        self._seen.add(key)
        entry: Dict[str, Any] = {"roster": list(key), "objective": float(objective),
                                 "job": job}
        if job_class:
            entry["job_class"] = str(job_class)
        self.candidates.append(entry)
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
            # R405(c). The allocator derives the consensus cluster from the
            # candidates WITHOUT a class, so a limited job's lineup cannot dilute
            # the definition it was limited against.
            if entry.get("job_class"):
                payload["bank_job_class"] = str(entry["job_class"])
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
    # Schema/version change intentionally invalidates older caches. Every field
    # can affect eligibility, shape scoring, ownership or the constraint matrix.
    columns = sorted(projections_df.columns)
    ordered = projections_df.sort_values("Player_ID", kind="stable")
    rows = [[[type(value).__name__, repr(value)] for value in row]
            for row in ordered[columns].itertuples(index=False, name=None)]
    return json.dumps({"schema": 2, "columns": columns, "rows": rows},
                      sort_keys=True, separators=(",", ":")).encode()


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


def conditions_facts(
    excludes: Optional[Sequence[str]] = None,
    stack_min: Optional[int] = None,
    stack_max: Optional[int] = None,
    max_opposing_hitters_per_sp: Optional[int] = None,
    *, target: str = "ceiling", leverage: Optional[Mapping[str, Any]] = None,
    max_selected_from: Optional[Tuple[Sequence[str], int]] = None,
    stack_teams: Optional[Sequence[str]] = None,
    secondary_stack: Optional[Tuple[str, int]] = None,
) -> Dict[str, Any]:
    """R465. What a conditions bucket was built under: ``conditions_signature``'s
    INPUTS, normalized once, JSON-safe, and the only thing
    :func:`signature_from_facts` reads.

    A conditions signature is a hash, so a stored bucket could not say what it
    answered, and the brief could count the candidates a build was handed from
    questions it did not ask but not name them. These facts are registered beside
    the index (``register_conditions``) and read back by ``describe_outside_buckets``.
    Every distinction the signature's bytes make survives here, because the
    reconstruction test would otherwise pass on a normalizer that had drifted:
    ``stack_teams`` None versus ``[]`` (the second appends ``teams:``), the
    allowance as the effective int (the signature already reads None as the
    engine default), leverage with its numeric types (``json.dumps`` writes 90 and
    90.0 differently), the named stack's team upper-cased. ``job_class`` is NOT
    here: it is a tag stored on each candidate, not a signature input, and two
    families can share one signature (the R469 pair slice shares the ordinary
    bucket's), so a bucket-level job class would flip with whichever call
    registered last.
    """
    selected = None
    if max_selected_from is not None:
        ids, m = max_selected_from
        selected = {"members": sorted(str(x) for x in (ids or [])), "m": int(m)}
    secondary = None
    if secondary_stack is not None:
        secondary = {"team": str(secondary_stack[0]).strip().upper(),
                     "min": int(secondary_stack[1])}
    return {
        "target": target,
        "excludes": sorted(str(x) for x in (excludes or [])),
        "stack_min": stack_min,
        "stack_max": stack_max,
        "max_opposing_hitters_per_sp": (
            ANTI_CORRELATION_DEFAULT_MAX if max_opposing_hitters_per_sp is None
            else int(max_opposing_hitters_per_sp)),
        "leverage": _leverage_kwargs(leverage),
        "max_selected_from": selected,
        "stack_teams": (None if stack_teams is None
                        else sorted(str(t) for t in stack_teams)),
        "secondary_stack": secondary,
    }


def signature_from_facts(projections_df, facts: Mapping[str, Any]) -> str:
    """R465. The ONE place the conditions signature's byte stream is written.

    ``conditions_signature`` is ``signature_from_facts(df, conditions_facts(...))``
    and ``extend_bank`` computes its bucket the same way, so the facts a cache
    file stores and the signature stored beside them cannot disagree about what
    the bucket is. The byte stream is unchanged from v1.2 on purpose: the
    signatures already written into live cache files keep their meaning.
    """
    digest = hashlib.sha256()
    digest.update(b"v2")
    digest.update(json.dumps({"target": facts["target"], "leverage": facts["leverage"]},
                             sort_keys=True, allow_nan=False).encode())
    digest.update(("|".join(facts["excludes"]) + "\n").encode())
    digest.update(f"{facts['stack_min']}:{facts['stack_max']}\n".encode())
    # R288 rider. ``max_opposing_hitters_per_sp`` changes the constraint matrix,
    # so a candidate built at 0 answers a different question than one built at 2.
    # Appended ONLY when non-default, so every signature already written to a
    # live cache file keeps its meaning (the same rule as the v1.2 stream above).
    if facts["max_opposing_hitters_per_sp"] != ANTI_CORRELATION_DEFAULT_MAX:
        digest.update(f"opp:{int(facts['max_opposing_hitters_per_sp'])}\n".encode())
    # R405(c). A cluster-limited job answers a different question (at most m
    # of these players together), so its candidates bucket apart: the ids and
    # m are hashed, sorted, and appended ONLY when set (the R288 rule above).
    selected = facts.get("max_selected_from")
    if selected is not None:
        digest.update(
            f"sel:{int(selected['m'])}:{'|'.join(selected['members'])}\n".encode())
    # R406. A job grid restricted to some stack teams answers a narrower
    # question and buckets apart; appended only when set, for the rule above.
    if facts.get("stack_teams") is not None:
        digest.update(f"teams:{'|'.join(facts['stack_teams'])}\n".encode())
    # R434. A job grid whose lineups must carry a NAMED team as a secondary
    # stack answers a different question and buckets apart. Without this term
    # its job keys would equal the ordinary bucket's and every job would be
    # skipped as already attempted. Appended only when set, for the rule above.
    secondary = facts.get("secondary_stack")
    if secondary is not None:
        digest.update(f"sec:{secondary['team']}:{int(secondary['min'])}\n".encode())
    digest.update(_projection_bytes(projections_df))
    return digest.hexdigest()[:16]


def conditions_signature(
    projections_df,
    excludes: Optional[Sequence[str]] = None,
    stack_min: Optional[int] = None,
    stack_max: Optional[int] = None,
    max_opposing_hitters_per_sp: Optional[int] = None,
    *, target: str = "ceiling", leverage: Optional[Mapping[str, Any]] = None,
    max_selected_from: Optional[Tuple[Sequence[str], int]] = None,
    stack_teams: Optional[Sequence[str]] = None,
    secondary_stack: Optional[Tuple[str, int]] = None,
) -> str:
    """A short digest of everything outside (pair, team, locks) that moves a solve.

    Covers the excluded set, the stack bounds, and the projection values the
    objective is built from. This is the BUCKET key: it identifies the exact
    question a stored candidate answered. Whether that bucket is still live is
    :func:`projection_digest`'s call, not this one's (R101).

    R465: the byte stream lives in :func:`signature_from_facts` and the inputs
    are normalized by :func:`conditions_facts`, so this is their composition. The
    stream is unchanged from v1.2, so the signatures already written into live
    cache files keep their meaning across this change.

    R288 rider. ``max_opposing_hitters_per_sp`` changes the constraint matrix,
    so a candidate built at 0 answers a different question than one built at 2 --
    reusing the first for the second would serve a bank that structurally cannot
    contain what was asked for, and the reuse would be invisible. It is appended
    ONLY when non-default (see :func:`signature_from_facts`).

    NOTE, filed and not fixed here: R246's three leverage controls are NOT in this
    signature and have the same property, so a bank built under
    `max_cumulative_ownership_pct` is reused for a build without it. Filed as
    R290; the fix is one more append and the measurement of what it invalidates
    is the part that needs a session.
    """
    return signature_from_facts(projections_df, conditions_facts(
        excludes, stack_min, stack_max, max_opposing_hitters_per_sp,
        target=target, leverage=leverage, max_selected_from=max_selected_from,
        stack_teams=stack_teams, secondary_stack=secondary_stack))


def _key_conditions(job: Any) -> str:
    """The conditions signature a job key ends with. Empty for a keyless entry."""
    return str(job or "").rpartition("|")[2]


def _read_facts_map(raw: Any) -> Dict[str, Dict[str, Any]]:
    """R465. A file's ``conditions_facts`` as ``{signature: facts}``; anything that
    is not a mapping of mappings (an absent key, a hand edit) reads as no facts."""
    if not isinstance(raw, dict):
        return {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def _display_facts(facts: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """R465. Facts as the brief shows them: the ``excludes`` list as a count."""
    if facts is None:
        return None
    shown = {k: v for k, v in facts.items() if k != "excludes"}
    shown["excludes_count"] = len(facts.get("excludes") or [])
    return shown


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


def _normalize_other_held(
        other_held: Optional[Union[int, Mapping[str, int]]]
) -> Optional[Union[int, Dict[str, int]]]:
    """R453. ``extend_bank``'s ``other_held`` as ``None``, a count, or a
    ``{conditions signature: count}`` map, refused when any count is negative.
    Called before anything in the cache is touched."""
    if other_held is None:
        return None
    if isinstance(other_held, Mapping):
        out = {str(sig): int(n) for sig, n in other_held.items()}
        if any(n < 0 for n in out.values()):
            raise ValueError(f"other_held counts must be >= 0, got {dict(other_held)}")
        return out
    if int(other_held) < 0:
        raise ValueError(f"other_held must be >= 0, got {other_held}")
    return int(other_held)


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
    max_selected_from: Optional[Tuple[Sequence[str], int]] = None,
    job_class: Optional[str] = None,
    stack_teams: Optional[Sequence[str]] = None,
    other_held: Optional[Union[int, Mapping[str, int]]] = None,
    secondary_stack: Optional[Tuple[str, int]] = None,
) -> Dict[str, Any]:
    """Generate candidates across (SP pair, stack team) until the budget runs out.

    R453. ``max_candidates`` is a ceiling on what the CALLER holds, and
    ``other_held`` says which candidates count toward it. ``None`` (the default)
    counts the whole cache, every conditions bucket under this projection
    digest, which is what a caller passing a RELATIVE cap (``len(cache) +
    need``, the R406 sleeves) means. An integer counts this call's own bucket
    plus that many the caller already holds in its other buckets; a
    ``{conditions signature: count}`` map does the same and leaves out the entry
    for THIS call's own bucket, so two slices that share a signature (stack
    sizes ``[4, 4]``) are never counted twice. The sliced build door passes the
    map: without it a build that asks a NEW question
    (another ``--max-opposing-hitters-per-sp``, a five-stack request, a cluster
    limit) on a cache an earlier build filled to the cap gets zero solves for it
    and is served the old bucket, silently. The cap still bounds the caller's
    own bank; it stops counting answers to questions the caller did not ask.
    Nothing here reads the player pool: a cap reduces how many candidates a
    bucket may add and never which players are legal.

    R405(c). ``max_selected_from=(ids, m)`` solves every job in this call with
    at most ``m`` of ``ids`` together (``build_single_lineup``'s argument, m >=
    1), in its own conditions bucket, and ``job_class`` tags what it stores.
    Both default to None, which is this function's behaviour before R405.

    R406. ``stack_teams`` restricts which teams the job grid STACKS (the
    environment sleeve's games), never who may be rostered: every player stays
    legal as a filler in every job, and the restriction is its own bucket.

    R434. ``secondary_stack=(team, m)`` is the operator-named secondary stack:
    every job stacks a primary team OTHER than ``team`` and carries exactly ``m``
    of ``team``'s hitters (``build_single_lineup``'s ``bringback_constraint``,
    ``max`` named explicitly because its default is 2), so ``team`` can never
    tie or outsize the primary. The primary's floor is raised to ``m + 1`` as a
    guard for a caller that lowered it; at the default 4 and ``m`` of 2 or 3 it
    is already there, so the bucket is separated by its own signature term, not
    by the stack bounds. A constraint on the LINEUP, never on the pool: every
    player stays legal. A team with fewer than ``m`` legal hitters builds
    nothing and the report says so. ``None`` (the default) is this function
    before R434, byte for byte.

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
    held = _normalize_other_held(other_held)  # R453: refused before the cache is touched
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

    # R434. The primary must be strictly larger than the named secondary, so
    # the floor is at least m + 1 BEFORE the signature is computed (a no-op at
    # the production default of 4 for m of 2 or 3).
    secondary: Optional[Tuple[str, int]] = None
    if secondary_stack is not None:
        secondary = (str(secondary_stack[0]).strip().upper(), int(secondary_stack[1]))
        stack_min = max(stack_min, secondary[1] + 1)
        stack_max = max(stack_max, stack_min)

    # Everything outside (pair, team, locks) that changes a solve's answer, fixed
    # now that the stack bounds are settled and used as part of every job key.
    # R101 splits it in two: the pool digest is the half that INVALIDATES, the
    # full signature is the bucket this slice writes into. Register before the
    # drop, so the bucket this call is about to fill is placeable by the next one.
    # R465. The facts and the signature come from ONE normalizer, so the bucket
    # this call writes into and what the cache file says it was built under
    # cannot disagree: the settled stack bounds and the R434 floor are in both.
    facts = conditions_facts(
        excl, stack_min, stack_max, max_opposing_hitters_per_sp,
        target=target, leverage=leverage, max_selected_from=max_selected_from,
        stack_teams=stack_teams, secondary_stack=secondary)
    conditions_sig = signature_from_facts(projections_df, facts)
    pool_digest = projection_digest(projections_df)
    # R453. What the caller holds in buckets other than this call's own.
    others: Optional[int] = None
    if isinstance(held, dict):
        others = sum(n for sig, n in held.items() if sig != conditions_sig)
    elif held is not None:
        others = held
    cache.register_conditions(conditions_sig, pool_digest, facts)
    superseded = cache.drop_stale_jobs(conditions_sig, projection_digest=pool_digest)

    # R453. What counts toward `max_candidates`, fixed once: every add below
    # lands in THIS bucket (the job key ends with `conditions_sig`), so the
    # bucket-scoped count is this base plus `built`, never a per-job re-scan.
    cap_scope = "cache" if others is None else "bucket"
    own_held_at_entry = (0 if others is None else sum(
        1 for c in cache.candidates
        if _key_conditions(c.get("job")) == conditions_sig))

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
    legal_teams = list(teams)
    if stack_teams is not None:
        wanted_teams = {str(t) for t in stack_teams}
        teams = [t for t in teams if t in wanted_teams]
    secondary_report: Optional[Dict[str, Any]] = None
    if secondary is not None:
        # R434. The primary is any team but the named one, and the named team
        # needs m LEGAL hitters (after the Excluded column) or no job can be
        # answered with a lineup: say so and build nothing, rather than pay a
        # proven-infeasible solve per pair to find it out.
        legal_named = int((hitters["Team"].astype(str).str.upper() == secondary[0]).sum())
        teams = [t for t in teams if str(t).upper() != secondary[0]]
        secondary_report = {"team": secondary[0], "min": secondary[1],
                            "primary_min_size": int(stack_min),
                            "legal_hitters_on_team": legal_named,
                            "primary_teams": len(teams), "status": "jobs_enumerated"}
        if legal_named < secondary[1]:
            teams = []
            secondary_report["status"] = "team_has_fewer_than_min_legal_hitters"
    all_pitchers = projections_df[projections_df["Position"] == "P"]
    excluded_arms_dropped = int(len(all_pitchers) - len(pitchers))
    all_hitters = projections_df[projections_df["Position"] != "P"]
    excluded_teams_dropped = sorted(
        {str(t) for t in all_hitters["Team"]} - set(legal_teams))

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

    def _cap_counted() -> int:
        """R453. The figure `max_candidates` is compared against right now."""
        if others is None:
            return len(cache)
        return others + own_held_at_entry + built

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
    # R415. WHICH limit ended the walk, because the two breaks below call for
    # different levers: a bank stopped at its candidate cap does not grow when
    # the same command is re-run, and one stopped at its time budget does.
    # `job_list_exhausted` alone cannot tell them apart; it reads False for both.
    stopped_by: Optional[str] = None
    for pair, team in jobs:
        # The cap binds only on a job that would run: an answered job is
        # skipped first, so a fully answered list re-run at its cap still reads
        # exhausted rather than capped (R415 review).
        key = _job_key(pair, team, lock_sig, conditions_sig)
        if key in cache.attempted:
            continue
        if max_candidates is not None and _cap_counted() >= max_candidates:
            exhausted = False
            stopped_by = "candidate_cap"
            break
        remaining = time_budget_s - (time.monotonic() - started)
        if remaining <= worst:
            exhausted = False
            stopped_by = "time_budget"
            break
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
                # R405(c). None on every ordinary slice.
                max_selected_from=max_selected_from,
                # R434. Present only for the named secondary stack, so every
                # other slice's call is exactly the call it was.
                **({"bringback_constraint": {"bringback_team": secondary[0],
                                             "min": secondary[1],
                                             "max": secondary[1]}}
                   if secondary is not None else {}),
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
        if cache.add(roster, objective, job=key, job_class=job_class):
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
    job_list_exhausted = exhausted and done_here == len(jobs)
    return {
        "version": VERSION,
        "built_this_slice": built,
        "attempted_this_slice": attempted_now,
        # R101: the union this cache will serve, which is now what the joint
        # solve receives. Before the split it was whatever the LAST slice
        # happened to leave behind, and the gap between the two is the whole
        # defect -- 1,007 stored, 8 solved, on 2026-08-03.
        "total_candidates": len(cache),
        # R453. What `max_candidates` was compared against, and which count it
        # was: `cache` is the union of every bucket (a relative-cap caller),
        # `bucket` is this call's own bucket plus `other_held`. A slice that
        # reads `candidate_cap` with `candidates_this_conditions` 0 was starved
        # by its caller's other buckets, never by an earlier build's.
        "cap_scope": cap_scope,
        "cap_counted": _cap_counted(),
        "other_held": others,
        "jobs_total": len(jobs),
        "jobs_attempted": done_here,
        "job_list_exhausted": job_list_exhausted,
        # R415. `candidate_cap` or `time_budget` when one of them broke the
        # walk; `job_list_exhausted` when every job is answered; and
        # `jobs_retryable` when the walk reached the end of the list but some
        # jobs raised, timed out or went unanswered, which a re-run retries.
        "stop_reason": stopped_by or (
            "job_list_exhausted" if job_list_exhausted else "jobs_retryable"),
        "max_candidates": int(max_candidates) if max_candidates is not None else None,
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
        # R405(c). What this call's jobs were limited to, so a reader can tell
        # the limited bucket from the ordinary one without the signature.
        "max_selected_from": (
            {"members": sorted(str(x) for x in (max_selected_from[0] or [])),
             "m": int(max_selected_from[1])} if max_selected_from is not None
            else None),
        "job_class": job_class,
        "stack_teams": sorted(str(t) for t in stack_teams) if stack_teams is not None else None,
        # R434. Only when a named secondary stack was asked for.
        **({"secondary_stack": secondary_report} if secondary_report else {}),
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


# --------------------------------------------------------------------------- #
# R285. ONE reader of the bank's job facts, wherever a brief carries them.
# --------------------------------------------------------------------------- #
#: Where a build's brief (or a bare report) keeps the sliced bank's job facts,
#: in the order `bank_job_facts` reads them: `solve.bank` is the delivered
#: brief's; `bank_exploration` is the refusal and partial briefs' (R285 writes it
#: on both doors); `bank_diagnostics` is the run metadata's copy of the report.
_BANK_FACT_KEYS = ("job_list_exhausted", "jobs_attempted", "jobs_total")


def bank_job_facts(brief: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The bank block a brief carries, as a dict copy plus ``source``.

    R285. The supervisor read ``solve.bank`` off a brief, the exit-3 refusal
    wrote ``bank_exploration``, and the run metadata wrote ``bank_diagnostics``:
    three writers of one fact with one hard-coded reader, so a refusal that
    carried the fact under the other name read as "no job facts" and the
    bank-growth remedy CLAUDE.md lists first never fired. A block is taken when
    it carries any of the job keys (a direct-door ``bank_exploration`` carries
    them as None on purpose: "this door has no job list" is an answer, and an
    absent block is not). A bare extend_bank report (job keys at the top level)
    is read as itself. ``source`` is None and the job keys are None when
    nothing carries them.
    """
    brief = brief or {}
    solve = brief.get("solve") if isinstance(brief.get("solve"), Mapping) else {}
    for name, block in (("solve.bank", (solve or {}).get("bank")),
                        ("bank_exploration", brief.get("bank_exploration")),
                        ("bank_diagnostics", brief.get("bank_diagnostics")),
                        ("report", brief)):
        if isinstance(block, Mapping) and any(k in block for k in _BANK_FACT_KEYS):
            return {**{k: None for k in _BANK_FACT_KEYS}, **dict(block), "source": name}
    return {**{k: None for k in _BANK_FACT_KEYS}, "source": None}


def bank_remedy(facts: Mapping[str, Any], *, door: Optional[str] = None,
                bank_limited: bool = False) -> str:
    """The search-effort remedy the bank facts license, as an enum.

    ``grow_bank`` (re-run the same command), ``raise_bank_cap`` and
    ``at_ceiling`` (the cap bound; the second means raising it is Ben's call),
    ``take_sliced_door`` (a BANK-LIMITED refusal on the direct door, whose
    auto-bank is rebuilt per run and cannot grow; ``--bank-max-candidates``
    selects the persistent sliced bank), else ``none``. Never a strategy
    change: CLAUDE.md delegates growing the bank and nothing else here.
    """
    if facts.get("job_list_exhausted") is False:
        if facts.get("bank_stop_reason") == "candidate_cap":
            return ("at_ceiling" if (facts.get("bank_cap") or {}).get("at_ceiling")
                    else "raise_bank_cap")
        return "grow_bank"
    if (door == "direct" and bank_limited
            and facts.get("job_list_exhausted") is not True):
        return "take_sliced_door"
    return "none"
