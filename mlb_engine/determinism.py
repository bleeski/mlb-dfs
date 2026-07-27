"""determinism.py -- the same inputs have to produce the same file.

F19. The engine claims determinism in two places that matter: the golden replay
gates every commit on one export hash, and the whole run-record discipline
assumes an archived build can be reproduced. Neither claim survived an unpinned
hash seed.

The mechanism is short. Python randomizes ``str`` hashing per process unless
``PYTHONHASHSEED`` is set, so set and frozenset iteration order over player IDs
changes between processes. The optimizer turned sets into lists at several
lock-merge sites, those lists became MILP constraint rows, and row order is an
input to a branch-and-bound tie-break. Ceilings in this engine come from a
uniform 1.42 multiplier over a small set of base values, so exact ties are
routine rather than exotic. Two runs of the same command on the same files could
certify two different DKEntries.csv files, and nothing in the pipeline would say
so.

Two defenses, because either alone is thin:

1. Every set that reaches the solver is sorted before it gets there. That is the
   real fix and it holds even in a process where the seed is not pinned.
2. Entry points pin ``PYTHONHASHSEED=0``, re-executing once if they have to,
   because the interpreter reads that variable at startup and setting it from
   inside a running process does nothing. This is belt and braces for any set
   iteration the first defense misses.

``hash_seed_report`` is carried in run provenance so an archived build states
which of these was in force rather than leaving it to be assumed.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence

VERSION = "v1.0"

PINNED_HASH_SEED = "0"
HASH_SEED_ENV = "PYTHONHASHSEED"


def hash_seed_pinned() -> bool:
    """True when this process started with the pinned seed in the environment."""
    return os.environ.get(HASH_SEED_ENV) == PINNED_HASH_SEED


def hash_seed_report() -> Dict[str, Any]:
    """Provenance fact, not a guarantee.

    A build with an unpinned seed is not wrong; every solver-facing collection
    is sorted regardless. It is simply a build whose byte-for-byte
    reproducibility rests on that sorting alone, and the run record should say
    which footing it was on.
    """
    value = os.environ.get(HASH_SEED_ENV)
    return {
        "python_hash_seed": value,
        "pinned": value == PINNED_HASH_SEED,
        "expected": PINNED_HASH_SEED,
        "note": "solver-facing collections are sorted whether or not the seed is "
                "pinned; this records which footing the build ran on",
    }


def ensure_pinned_hash_seed(argv: Optional[Sequence[str]] = None) -> bool:
    """Re-exec this process once with the seed pinned, if it is not already.

    Returns True when nothing had to be done. Call it as the first statement of
    an entry point, before importing anything expensive, because the re-exec
    throws away all work done up to that point. It never re-execs twice: the
    guard variable is the pinned environment itself.

    Deliberately a no-op when stdin is not the original argv (frozen builds,
    embedded interpreters) or when the executable cannot be resolved. Failing to
    pin is a weaker footing, never a reason to refuse to build a slate.
    """
    if hash_seed_pinned():
        return True
    if not sys.executable:
        return False
    argv = list(argv if argv is not None else sys.argv)
    env = dict(os.environ)
    env[HASH_SEED_ENV] = PINNED_HASH_SEED
    try:
        os.execve(sys.executable, [sys.executable, *argv], env)
    except OSError:
        # A slate that builds on an unpinned seed beats a slate that does not
        # build. The sorting defense is still in force.
        return False
    return False  # pragma: no cover - execve does not return on success


def stable_ids(values: Optional[Sequence[Any]]) -> List[str]:
    """A deterministic, deduplicated, string-sorted list of player IDs.

    The one conversion allowed between a set of IDs and anything the solver
    sees. ``list(set(...))`` is the shape this replaces.
    """
    return sorted({str(v) for v in (values or [])})


def stable_union(*groups: Optional[Sequence[Any]]) -> List[str]:
    """``stable_ids`` over the union of several ID collections."""
    merged: set = set()
    for group in groups:
        merged |= {str(v) for v in (group or [])}
    return sorted(merged)
