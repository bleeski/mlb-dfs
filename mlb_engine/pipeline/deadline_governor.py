"""R290(c) step 2, 2026-09-03. A clock inside the build.

D3 of `docs/2026-09-01_BUILD_no-file-at-lock-full-postmortem.md`. On 1940_9g a
session held 37 reserved entries across 16 contests, first lock at 19:40 ET,
files staged at 19:17, and delivered NOTHING -- three games left the addressable
pool permanently. CLAUDE.md's T-schedule now carries the operator half of the
remedy. This module is the other half: the same discipline inside the engine,
where it cannot be forgotten under pressure.

WHAT IT IS AND IS NOT
---------------------
It is a filter and a ladder. It decides, on a refusal the build has ALREADY
produced, whether that refusal is one a deadline should override, and if so
what to open. It never builds anything, never touches a player pool, and never
relabels a file upload-ready.

It reads `refusal_class` from the refusal's own payload -- never a site
identity, never a line number, never the `status` string. R290(c) commit 1 put
that key in every refusal payload in `build_slate.py` precisely so this module
could exist without knowing where the refusals are. A site whose class is later
corrected changes the governor's reach without editing this file.

THE LADDER IS TWO RUNGS, AND THAT IS A RECONCILIATION, NOT A SHORTCUT
--------------------------------------------------------------------
R290(c)'s Fix line says "walks a fixed documented relaxation ladder". Written
hours later, from the same post-mortem, CLAUDE.md's T-15 rung says the opposite
about STEP SIZE, with the measurement behind it:

    T-15. Open every binding control AT ONCE, not stepwise. The 1940_9g
    session moved max_sp_pair_repetition 1 -> 2 -> 10, then three exposure
    caps, then max_shared_players, one per ~2-minute call, five calls. Under a
    deadline the minimal move is the expensive one: five careful steps cost
    more than one crude step, and the crude step is reversible while the lock
    is not.

CLAUDE.md is binding and it is the instruction with a measured cost behind it,
so the ladder is fixed and documented (which is what the item actually asked
for) and it is TWO rungs, because a seven-rung stepwise walk inside a six-minute
window is the failure CLAUDE.md just finished paying for. Rung 1 is the crude
step. Rung 2 is the one thing rung 1 cannot buy.

    1. OPEN_CONTROLS      every portfolio control that can bind, to its open
                          value, in ONE move.
    2. ACCEPT_BLANK_ROWS  deliver the rows the bank can fill and leave the rest
                          blank. Ben's guardrail still blocks CERTIFICATION on a
                          blank reserved row; R290(c) is the decision that it
                          stops blocking DELIVERY, because 37 blank entries is a
                          washout with certainty 1.0 and not a hedge against one.

Past rung 2 there is nothing left to open, and a bank holding zero lineups is an
honest refusal: `deadline_exhausted`, naming the rungs walked.

WHAT IT MAY NEVER DO
--------------------
Every one of these is a wall in CLAUDE.md and none of them is reopened here:
- No reduction of the legal player pool, for any reason. A deadline is an
  infrastructure limit; it may reduce search effort and never the legal set.
- `upload_ready` stays reserved for a certified export. A governed delivery is
  labelled `review_grade_deadline_build`, and a gate failure downgrades the
  LABEL rather than withholding the file.
- Blank reserved rows still block CERTIFICATION.
- The money-and-entry wall and the manual-DK rule. This writes a FILE.
- It reaches only BADLY-SHAPED refusals. ILLEGAL and READ-IT refuse at every
  clock, and `governed_classes()` is the whole of what it can reach.
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# Mirrors build_slate.REFUSAL_* by value rather than importing them: this module
# lives in the engine and `build_slate.py` is a skill script with a test
# forbidding top-level engine imports, so the dependency runs one way only. The
# strings are the contract between them and `test_the_class_vocabularies_agree`
# asserts they have not drifted.
CLASS_ILLEGAL = "illegal"
CLASS_BADLY_SHAPED = "badly_shaped"
CLASS_READ_IT = "read_it"
CLASS_SPLIT = "split"

#: The ONLY class a deadline may override. Named as a function rather than a
#: bare constant so a caller cannot mutate it in place.
def governed_classes() -> frozenset:
    return frozenset({CLASS_BADLY_SHAPED})


#: Minutes before the deliver-by time at which the governor takes over. Six,
#: from CLAUDE.md's T-schedule, where T-6 is the rung that says hand-build if
#: the engine has not produced a file. This is the engine doing that itself.
WINDOW_MINUTES = 6.0

RUNG_OPEN_CONTROLS = "open_controls"
RUNG_ACCEPT_BLANK_ROWS = "accept_blank_rows"

#: Rung 1, and every value here is FIXED. Never derived per slate: a value
#: re-derived from this slate's structural floors is a judgment, and a judgment
#: made inside a six-minute window by code nobody is watching is the thing this
#: module exists to avoid.
#:
#: `max_shared_players` is ROSTER SIZE MINUS ONE, not roster size, and that one
#: is the difference between a legal file and an illegal one. Two lineups
#: sharing all ten slots are the SAME lineup, and two identical entries in one
#: contest are `duplicate_same_contest` -- a DK rejection, inside
#: `roster_legality_passed`. So opening overlap all the way would invite the
#: allocator to build the one thing the governor may never deliver, and would
#: convert a BADLY-SHAPED refusal it is allowed to fix into an ILLEGAL one it
#: is not. Nine is maximally permissive and still legal by construction.
#: `test_the_open_overlap_value_cannot_produce_an_identical_pair` pins it.
CLASSIC_ROSTER_SIZE = 10
SHOWDOWN_ROSTER_SIZE = 6

OPEN_CONTROL_VALUES: Dict[str, Any] = {
    "max_shared_players": CLASSIC_ROSTER_SIZE - 1,
    "max_sp_pair_repetition": 999,
    "max_player_exposure_pct": 1.0,
    "max_pitcher_exposure_pct": 1.0,
    "max_primary_stack_exposure_pct": 1.0,
    # R343 / R333, 2026-09-15. The rung's own contract is "every portfolio
    # control to its open value at once" (CLAUDE.md's T-15), so a ceiling
    # missing from this dict is a control the crude move does not make. The
    # team cap ships ON by posture default and would otherwise survive rung 1.
    "max_team_exposure_pct": 1.0,
    # The game SCALAR opens too. `max_game_exposure_pct_by_game` deliberately
    # does NOT: this dict maps a control to a VALUE and the per-game form's keys
    # are the slate's game ids, which this module does not have. Stated rather
    # than left as a silent gap -- opening the scalar does not loosen an
    # explicit per-game entry, because the two merge by MIN. That dict is only
    # ever operator-typed, so the operator who set it is the one who can open it.
    "max_game_exposure_pct": 1.0,
}

#: Showdown's three controls, same rung, same one crude move. Kept separate
#: because the Showdown roster is 6 slots, so its open overlap value is 5.
OPEN_SHOWDOWN_CONTROL_VALUES: Dict[str, Any] = {
    "max_shared_players": SHOWDOWN_ROSTER_SIZE - 1,
    "max_cpt_exposure_pct": 1.0,
    "max_player_exposure_pct": 1.0,
}

LADDER: Tuple[str, ...] = (RUNG_OPEN_CONTROLS, RUNG_ACCEPT_BLANK_ROWS)

#: The label a governed delivery carries. Never `upload_ready`.
DEADLINE_LABEL = "review_grade_deadline_build"

_HHMM = _re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$")
_ET = "America/New_York"


def _eastern() -> Any:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_ET)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Eastern timezone database unavailable; install the pinned tzdata runtime") from exc


def parse_deliver_by(text: str, *, now: Optional[_dt.datetime] = None
                     ) -> Tuple[_dt.datetime, str]:
    """Parse `--deliver-by` into an aware UTC datetime.

    Two accepted forms, because an operator under a clock types the short one
    and a scheduled caller passes the long one:
      * a full ISO timestamp, with or without an offset (naive is read as ET)
      * `HH:MM`, read as ET on the slate's own day

    Returns `(utc_datetime, tz_source)`. Raises ValueError with the two forms
    named -- a refusal that does not say what it wanted costs a second call,
    and this one is parsed inside a lock window.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("--deliver-by is empty; pass an ISO timestamp or HH:MM ET")
    tz = _eastern()
    tz_source = "zoneinfo" if tz.__class__.__name__ == "ZoneInfo" else "fixed_edt"
    reference = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(tz)

    match = _HHMM.match(raw)
    if match:
        hour, minute = int(match.group("h")), int(match.group("m"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(
                f"--deliver-by {raw!r} is not a valid time of day. Pass an ISO "
                f"timestamp or HH:MM ET, e.g. 2026-09-03T19:40:00-04:00 or 19:40")
        local = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return local.astimezone(_dt.timezone.utc), tz_source

    try:
        parsed = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"--deliver-by {raw!r} is neither an ISO timestamp nor HH:MM ET "
            f"({exc}). Examples: 2026-09-03T19:40:00-04:00, or 19:40"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(_dt.timezone.utc), tz_source


class DeadlineGovernor:
    """The clock, the ladder position, and the record of what it opened.

    One instance per build. `now_fn` is injected so every test reads a fixed
    clock: CLAUDE.md's own T-schedule rule is *read the clock from the clock*,
    and a test that reads the wall clock is a test that cannot pin a window.
    """

    def __init__(self, deliver_by_utc: _dt.datetime, *,
                 now_fn: Optional[Callable[[], _dt.datetime]] = None,
                 window_minutes: float = WINDOW_MINUTES,
                 tz_source: str = "zoneinfo") -> None:
        if deliver_by_utc.tzinfo is None:
            raise ValueError("deliver_by_utc must be timezone-aware")
        self.deliver_by_utc = deliver_by_utc.astimezone(_dt.timezone.utc)
        self.window_minutes = float(window_minutes)
        self.tz_source = tz_source
        self._now_fn = now_fn or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._walked: List[Dict[str, Any]] = []

    # -- the clock ------------------------------------------------------- #
    def now(self) -> _dt.datetime:
        return self._now_fn().astimezone(_dt.timezone.utc)

    def minutes_remaining(self) -> float:
        return (self.deliver_by_utc - self.now()).total_seconds() / 60.0

    def in_window(self) -> bool:
        """True from T-6 onward, INCLUDING past the deadline.

        Past-deadline is deliberately inside the window and not outside it. A
        negative clock means the draftgroup is closed and the file cannot be
        entered, which SKILL.md already instructs the operator to say first --
        but a build that has already spent the bank should still produce the
        file rather than refuse, because a late swap and the next slate both
        read better against a file than against nothing.
        """
        return self.minutes_remaining() <= self.window_minutes

    # -- the filter ------------------------------------------------------ #
    def governs(self, payload: Optional[Mapping[str, Any]]) -> bool:
        """Whether this refusal is one a deadline may override.

        Three conditions, all required: the payload names its class, that class
        is BADLY-SHAPED, and the clock is inside the window. A payload with NO
        `refusal_class` is never governed -- an absent key is not an answer
        (R237), and the safe reading of "this refusal did not say" is "do not
        override it".
        """
        if not payload:
            return False
        klass = payload.get("refusal_class")
        if klass not in governed_classes():
            return False
        return self.in_window()

    # -- the ladder ------------------------------------------------------ #
    @property
    def walked(self) -> List[Dict[str, Any]]:
        return list(self._walked)

    def rungs_walked(self) -> List[str]:
        return [r["rung"] for r in self._walked]

    def next_rung(self) -> Optional[str]:
        for rung in LADDER:
            if rung not in self.rungs_walked():
                return rung
        return None

    def take_rung(self, rung: str, *, contest_type: str = "classic",
                  before: Optional[Mapping[str, Any]] = None,
                  reason: str = "") -> Dict[str, Any]:
        """Record a rung and return the controls it opens.

        The record is the deliverable half. A governed file that does not say
        which controls were opened, from what, is the false-reassurance failure
        this item is filed against wearing a different hat.
        """
        if rung not in LADDER:
            raise ValueError(f"{rung!r} is not a rung of the fixed ladder "
                             f"{LADDER}")
        if rung in self.rungs_walked():
            raise ValueError(f"rung {rung!r} was already walked; the ladder is "
                             f"walked once and its record is the artifact")
        opened: Dict[str, Any] = {}
        if rung == RUNG_OPEN_CONTROLS:
            opened = dict(OPEN_SHOWDOWN_CONTROL_VALUES
                          if str(contest_type).lower().startswith("showdown")
                          else OPEN_CONTROL_VALUES)
        record = {
            "rung": rung,
            "at_utc": self.now().isoformat().replace("+00:00", "Z"),
            "minutes_remaining": round(self.minutes_remaining(), 2),
            "opened": opened,
            "from": {k: (before or {}).get(k) for k in opened} if opened else {},
            "reason": reason,
        }
        self._walked.append(record)
        return opened

    def exhausted(self) -> bool:
        return self.next_rung() is None

    # -- the record ------------------------------------------------------ #
    def stamp(self) -> Dict[str, Any]:
        """The brief block. `deadline_forced` is False until a rung is taken.

        Present on every build that passed `--deliver-by`, forced or not, so
        "did a deadline move this build" is answerable from the artifact rather
        than from the absence of a key.
        """
        return {
            "deadline_forced": bool(self._walked),
            "deliver_by_utc": self.deliver_by_utc.isoformat().replace(
                "+00:00", "Z"),
            "deadline_tz_source": self.tz_source,
            "window_minutes": self.window_minutes,
            "minutes_remaining": round(self.minutes_remaining(), 2),
            "in_window": self.in_window(),
            "deadline_ladder": self.walked,
            "rungs_walked": self.rungs_walked(),
            "ladder_available": list(LADDER),
            "label": DEADLINE_LABEL if self._walked else None,
            "governed_classes": sorted(governed_classes()),
            "note": "a governed delivery is review-grade and never certified; "
                    "blank reserved rows still block certification and no rung "
                    "reduces the legal player pool",
        }


def merge_open_controls(existing: Optional[Mapping[str, Any]],
                        opened: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply a rung's values ON TOP of the operator's own overrides.

    Deliberately this direction, and it is the one place the governor outranks
    a person. An operator who passed `--controls-override` chose those numbers
    before the window; the governor fires only inside it, and inside it the
    choice is the operator's numbers or no file. The `from` block in the rung
    record preserves what was displaced, so nothing is lost silently.
    """
    merged = dict(existing or {})
    merged.update(opened)
    return merged
