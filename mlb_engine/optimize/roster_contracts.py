"""roster_contracts.py -- declarative roster contracts (Classic + Showdown).

One place that carries roster geometry, the salary rule, team representation,
per-slot scoring multipliers, and the DKEntries export header for each DK contest
type. CLASSIC mirrors the shipped Classic engine's constants (asserted by a test);
SHOWDOWN defines DK Captain Mode (1 CPT + 5 UTIL).

Deterministic contract data. Nothing here is a projection, a win-rate, or a
probability claim.

SEQUENCING (v3.0.0-pre): Showdown consumes SHOWDOWN through
``mlb_engine.optimize.showdown``. The Classic solver still uses its own in-module
constants; rewiring Classic to consume CLASSIC here is a separate, golden-replay-
preserving refactor (guide Appendix) and is intentionally NOT done in this change,
so no certified Classic byte changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

VERSION = "0.1"


@dataclass(frozen=True)
class RosterContract:
    name: str
    slots: Tuple[str, ...]              # ordered DKEntries roster slot labels
    salary_cap: int
    min_players_per_team: int           # team-representation floor (0 = no floor)
    entry_roster_start_col: int         # 0-based column of the first roster cell
    export_header: Tuple[str, ...]      # full DKEntries header row
    slot_multiplier: Dict[str, float]   # slot label -> scoring multiplier
    captain_slot: Optional[str] = None  # slot taking the multiplier + its own salary/id

    @property
    def roster_size(self) -> int:
        return len(self.slots)

    @property
    def roster_end_col_exclusive(self) -> int:
        return self.entry_roster_start_col + self.roster_size

    def multiplier_for(self, slot: str) -> float:
        return float(self.slot_multiplier.get(slot, 1.0))


CLASSIC = RosterContract(
    name="CLASSIC",
    slots=("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"),
    salary_cap=50000,
    min_players_per_team=0,   # Classic uses a max-hitters-per-team CAP, not a floor
    entry_roster_start_col=4,
    export_header=(
        "Entry ID", "Contest Name", "Contest ID", "Entry Fee",
        "P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "", "Instructions",
    ),
    slot_multiplier={s: 1.0 for s in ("P", "C", "1B", "2B", "3B", "SS", "OF")},
    captain_slot=None,
)

SHOWDOWN = RosterContract(
    name="SHOWDOWN",
    slots=("CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL"),
    salary_cap=50000,
    min_players_per_team=1,   # at least one player from each team (DK Captain Mode)
    entry_roster_start_col=4,
    export_header=(
        "Entry ID", "Contest Name", "Contest ID", "Entry Fee",
        "CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL", "", "Instructions",
    ),
    slot_multiplier={"CPT": 1.5, "UTIL": 1.0},
    captain_slot="CPT",
)

CONTRACTS: Dict[str, RosterContract] = {"CLASSIC": CLASSIC, "SHOWDOWN": SHOWDOWN}


def get_contract(name: str) -> RosterContract:
    key = str(name or "").strip().upper()
    if key not in CONTRACTS:
        raise KeyError(f"unknown roster contract: {name!r} (have {sorted(CONTRACTS)})")
    return CONTRACTS[key]
