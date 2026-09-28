"""R98(3) + F18, 2026-09-28. One deadline per build, with a publication reserve.

Before this module a Classic build's only clock was ``started + --max-seconds``.
The first lock never bounded it (at T-12 the F-1 deadline was 420s away and the
build planned 600s), and each budget was a leftover: the sliced bank took
``remaining - 8.0`` and the direct door's auto-bank ``deadline - started - 6.0``,
two literals standing in for what the build spends after its search stops.

A ``Deadline`` is created ONCE, in ``build_slate.main``, and every budget is a
``slice`` of it:

* ``end`` is the earliest of ``--max-seconds``, ``--deliver-by`` and the first
  lock minus the F-1 buffer (``slate_intake_manager.DELIVERY_BUFFER_MINUTES``),
  and the brief names which one bound.
* ``reserve_s`` is the publication phase (allocate, certify, export, write),
  MEASURED per host at the build's entry count by
  ``tools/benchmark_engine.py --publication``, stored in
  ``repo_env.PUBLICATION_RESERVE_MEASURED`` and folded into
  ``repo_env.host_profile()`` (R349). It is never a literal here and never a
  runtime call.
* ``slice(requested)`` grants at most what is left before ``end - reserve``.
  The object is frozen, so no retry, rung or recursion can reset it.

A past ``end`` is not a refusal. ``slice`` returns 0 and the caller's own floor
(``build_slate.resolve_bank_budget``'s, R98(1)) decides, audibly: the deadline
governor's contract is to produce the file past the deadline rather than refuse.

Deterministic bookkeeping, never a claim: the stamp says how the clock was
spent, not whether the build was good.
"""
from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

BOUND_MAX_SECONDS = "max_seconds"
BOUND_DELIVER_BY = "deliver_by"
BOUND_FIRST_LOCK = "first_lock_minus_buffer"


@dataclass(frozen=True, eq=False)
class Deadline:
    """A build's one clock. ``started`` and ``end`` are ``clock()`` readings."""

    started: float
    end: float
    reserve_s: float
    bound: str
    bounds_s: Dict[str, float] = field(default_factory=dict)
    reserve_source: str = ""
    clock: Callable[[], float] = field(default=time.monotonic, repr=False,
                                       compare=False)
    # The record, appended to; the object's clock fields are what stay frozen.
    _log: List[Dict[str, Any]] = field(default_factory=list, repr=False,
                                       compare=False)

    def now(self) -> float:
        return float(self.clock())

    def elapsed(self) -> float:
        return self.now() - self.started

    def remaining(self) -> float:
        """Seconds to ``end``, negative once it has passed."""
        return self.end - self.now()

    def not_after(self) -> float:
        """The absolute reading no search may run past: ``end - reserve``."""
        return self.end - self.reserve_s

    def spendable(self) -> float:
        """Seconds a search may still take, never negative."""
        return max(0.0, self.not_after() - self.now())

    def slice(self, requested: Optional[float] = None, *, label: str) -> float:
        """At most ``requested`` seconds, and never past ``not_after``.

        ``requested`` None asks for everything spendable. ``starved`` on the
        record means the clock granted less than was asked for, and is None
        when nothing was asked for."""
        spendable = self.spendable()
        granted = spendable if requested is None else min(max(0.0, float(requested)),
                                                          spendable)
        self._log.append({
            "kind": "slice", "label": label,
            "at_s": round(self.elapsed(), 1),
            "requested_s": None if requested is None else round(float(requested), 1),
            "granted_s": round(granted, 1),
            "spendable_s": round(spendable, 1),
            # None when nothing was requested: there is no ask to fall short of,
            # and `caps_vs_bank` says whether the bank itself was starved.
            "starved": (None if requested is None
                        else granted < float(requested)),
        })
        return granted

    def mark(self, stage: str) -> None:
        self._log.append({"kind": "stage", "stage": stage,
                          "at_s": round(self.elapsed(), 1),
                          "left_s": round(self.remaining(), 1),
                          "spendable_s": round(self.spendable(), 1)})

    def stamp(self) -> Dict[str, Any]:
        """The brief block: the bound, the reserve and how the clock went."""
        return {
            "bound": self.bound,
            "bounds_s": {k: round(v, 1) for k, v in sorted(self.bounds_s.items())},
            "window_s": round(self.end - self.started, 1),
            "reserve_s": round(self.reserve_s, 1),
            "reserve_source": self.reserve_source,
            "elapsed_s": round(self.elapsed(), 1),
            "left_s": round(self.remaining(), 1),
            "past_end": self.remaining() < 0,
            "stages": [dict(r) for r in self._log if r["kind"] == "stage"],
            "slices": [dict(r) for r in self._log if r["kind"] == "slice"],
            "note": "one clock per build: every budget is a slice of it and "
                    "none resets it; the reserve is the measured publication "
                    "phase, not a promise that the build meets the end",
        }


def resolve_deadline(*, started: float, max_seconds: float, reserve_s: float,
                     reserve_source: str = "",
                     now_utc: Optional[_dt.datetime] = None,
                     deliver_by_utc: Optional[_dt.datetime] = None,
                     first_lock_utc: Optional[_dt.datetime] = None,
                     buffer_minutes: Optional[float] = None,
                     clock: Callable[[], float] = time.monotonic) -> Deadline:
    """The build's Deadline from its three bounds.

    A wall-clock bound becomes a ``clock()`` reading as ``now + (t - now_utc)``,
    both read here, together. ``first_lock_utc`` is None on a past-slate
    replay, which has no clock to respect. ``buffer_minutes`` defaults to F-1's
    delivery buffer, the one ``slate_clock`` uses.
    """
    if buffer_minutes is None:
        from mlb_engine.intake.slate_intake_manager import (  # noqa: PLC0415
            DELIVERY_BUFFER_MINUTES)
        buffer_minutes = DELIVERY_BUFFER_MINUTES
    now_mono = float(clock())
    now_wall = now_utc or _dt.datetime.now(_dt.timezone.utc)
    offset = now_mono - float(started)
    bounds: Dict[str, float] = {BOUND_MAX_SECONDS: float(max_seconds)}
    if deliver_by_utc is not None:
        bounds[BOUND_DELIVER_BY] = offset + (deliver_by_utc - now_wall).total_seconds()
    if first_lock_utc is not None:
        target = first_lock_utc - _dt.timedelta(minutes=float(buffer_minutes))
        bounds[BOUND_FIRST_LOCK] = offset + (target - now_wall).total_seconds()
    bound = min(bounds, key=lambda k: (bounds[k], k))
    return Deadline(started=float(started), end=float(started) + bounds[bound],
                    reserve_s=float(reserve_s), bound=bound, bounds_s=bounds,
                    reserve_source=reserve_source, clock=clock)
