"""Strict input contracts for the DraftKings MLB production pipeline.

All numeric work is local. A source reference is evidence provenance, never an
assertion that a model has been calibrated. Supplied distributions remain priors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

ID = Annotated[str, Field(pattern=r"^[0-9]+$", min_length=1)]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Mode = Literal["CLASSIC", "SHOWDOWN"]
Status = Literal[
    "confirmed_starter",
    "projected_starter",
    "probable_pitcher",
    "confirmed_out",
    "bench",
    "unknown",
]
SHAPE = Literal[
    "cash",
    "small_gpp",
    "large_gpp",
    "wta",
    "single_entry_gpp",
    "small_field_gpp",
    "mid_field_gpp",
    "large_field_gpp",
    "portfolio_gpp",
    "mme_gpp",
    "small_wta",
    "mid_wta",
    "large_wta",
    "wta_ticket_satellite",
    "satellite",
]


def infer_shape(name: str) -> str | None:
    """Conservative title inference. An unknown title never becomes a GPP by default."""
    text = name.casefold()
    if "satellite" in text or "qualifier" in text:
        return "satellite"  # A ticket count of one needs explicit contest evidence.
    if any(
        token in text
        for token in ("double up", "50/50", "head-to-head", "head to head", "h2h")
    ):
        return "cash"
    if "wta" in text or "winner take all" in text or "winner-take-all" in text:
        return "wta"
    if "single entry" in text or "single-entry" in text:
        return "single_entry_gpp"
    if "150-max" in text:
        return "mme_gpp"
    if "20-max" in text:
        return "portfolio_gpp"
    if "gpp" in text:
        return "large_gpp"
    return None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Source(StrictModel):
    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    tier: Literal[1, 2, 3]
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    artifact: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def chronology(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("source expiry must be after its observation")
        return self


class LineupSide(StrictModel):
    team: str = Field(min_length=1)
    # A partial order is a projected order; it cannot assert confirmation.
    ordered_ids: list[ID]
    confirmed: StrictBool = False
    source_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_order(self):
        if len(set(self.ordered_ids)) != len(self.ordered_ids):
            raise ValueError("duplicate player in a batting order")
        if len(self.ordered_ids) > 9 or (self.confirmed and len(self.ordered_ids) != 9):
            raise ValueError("a confirmed batting order requires nine unique IDs")
        return self


class GameEvidence(StrictModel):
    game_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    away: str = Field(min_length=1)
    home: str = Field(min_length=1)
    start: AwareDatetime
    state: Literal[
        "scheduled",
        "in_progress",
        "final",
        "postponed",
        "cancelled",
        "suspended",
        "unknown",
    ]
    weather: Literal["clear", "closed_roof", "medium", "high", "unknown"]
    source_id: str = Field(min_length=1)
    weather_source_id: str = Field(min_length=1)
    lineups: list[LineupSide] = Field(default_factory=list)

    @model_validator(mode="after")
    def teams(self):
        if self.away == self.home:
            raise ValueError("a game must have two different teams")
        sides = [x.team for x in self.lineups]
        if len(set(sides)) != len(sides) or set(sides) - {self.away, self.home}:
            raise ValueError("lineup side does not belong to this game")
        return self


class PlayerEvidence(StrictModel):
    player_id: ID  # Classic ID or Showdown UTIL ID (the canonical person ID).
    team: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    status: Status
    source_id: str = Field(min_length=1)


class Projection(StrictModel):
    player_id: ID
    mean: Finite
    stddev: Positive | None = None
    ownership: Probability | None = None
    captain_ownership: Probability | None = None
    source_id: str = Field(min_length=1)
    method: Literal["supplied_dk_points", "opportunity_model", "emergency_prior"]
    # No free-form expression is evaluated. Features document model inputs.
    features: dict[str, Finite] = Field(default_factory=dict)

    @model_validator(mode="after")
    def role_marginals(self):
        if self.captain_ownership is not None:
            if self.ownership is None or self.captain_ownership > self.ownership:
                raise ValueError("captain ownership must not exceed roster ownership")
        return self


class ResidualObservation(StrictModel):
    event_id: str = Field(min_length=1)
    prediction: Finite
    outcome: Finite
    predicted_at: AwareDatetime
    settled_at: AwareDatetime

    @model_validator(mode="after")
    def temporal_holdout(self):
        if self.predicted_at >= self.settled_at:
            raise ValueError(
                "a calibration prediction must precede its observed outcome"
            )
        return self


class MarketObservation(StrictModel):
    game_id: str
    source_id: str
    model_total: Finite
    market_total: Finite
    residual_stddev: Positive | None = None
    residual_sample_size: int = Field(default=0, ge=0)
    residual_model_id: str | None = None
    residual_fitted_before: AwareDatetime | None = None
    residual_source_id: str | None = None
    residual_observations: list[ResidualObservation] = Field(default_factory=list)
    decimal_odds: list[Positive] | None = None

    @field_validator("decimal_odds")
    @classmethod
    def odds(cls, values):
        if values is not None and (len(values) != 2 or any(x <= 1 for x in values)):
            raise ValueError(
                "two mutually exclusive decimal odds greater than 1 required"
            )
        return values


class ContestSpec(StrictModel):
    contest_id: ID
    shape: SHAPE = "large_gpp"
    field_size: int | None = Field(default=None, ge=1)
    # Rank ordered, in integer cents. Include zero payouts through field_size.
    payouts_cents: list[int] | None = None
    # Opponent lineups, including duplicates as separate entries; never own entries.
    field_rosters: list[list[ID]] | None = None
    source_id: str | None = None
    payout_kind: Literal["cash", "ticket_face_value"] = "cash"

    @model_validator(mode="after")
    def settlement(self):
        if self.payouts_cents is not None:
            if not self.source_id or not self.field_size:
                raise ValueError("payouts require a source and the total field size")
            if len(self.payouts_cents) != self.field_size:
                raise ValueError(
                    "supply the complete rank payout curve including zeros"
                )
            if any(x < 0 for x in self.payouts_cents):
                raise ValueError("negative payout")
            if any(a < b for a, b in zip(self.payouts_cents, self.payouts_cents[1:])):
                raise ValueError("payouts must be nonincreasing")
        if self.field_rosters is not None and self.payouts_cents is None:
            raise ValueError("opponent field requires a payout curve")
        return self


class EvidenceBundle(StrictModel):
    schema_version: Literal[1] = 1
    fixture: StrictBool = False
    sources: list[Source]
    games: list[GameEvidence]
    players: list[PlayerEvidence]
    projections: list[Projection]
    contests: list[ContestSpec] = Field(default_factory=list)
    markets: list[MarketObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def identities(self):
        for items, attr in (
            (self.sources, "source_id"),
            (self.games, "game_id"),
            (self.players, "player_id"),
            (self.projections, "player_id"),
            (self.contests, "contest_id"),
        ):
            keys = [getattr(x, attr) for x in items]
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {attr}")
        if (
            not self.sources
            or not self.games
            or not self.players
            or not self.projections
        ):
            raise ValueError("empty evidence, game, player, or projection table")
        sources = {x.source_id for x in self.sources}
        for item in [*self.games, *self.players, *self.projections, *self.markets]:
            if item.source_id not in sources:
                raise ValueError("unresolved source reference")
        for game in self.games:
            if game.weather_source_id not in sources:
                raise ValueError("weather source missing")
            if any(x.source_id not in sources for x in game.lineups):
                raise ValueError("lineup source missing")
        for contest in self.contests:
            if contest.source_id is not None and contest.source_id not in sources:
                raise ValueError("contest source missing")
        for market in self.markets:
            if (
                market.residual_source_id is not None
                and market.residual_source_id not in sources
            ):
                raise ValueError("calibration residual source missing")
        return self


class Controls(StrictModel):
    salary_floor: int = Field(default=0, ge=0, le=50000)
    max_player_exposure: Probability = 1.0
    max_pitcher_exposure: Probability = 1.0
    max_captain_exposure: Probability = 1.0
    max_primary_stack_exposure: Probability = 1.0
    max_sp_pair_repetition: int | None = Field(default=None, ge=0)
    primary_stack_min_size: int = Field(default=0, ge=0, le=5)
    max_team_exposure: dict[str, Probability] = Field(default_factory=dict)
    max_game_exposure: dict[str, Probability] = Field(default_factory=dict)
    max_shared_players: int | None = Field(default=None, ge=0, le=10)
    # A configurable project policy, separate from DraftKings legality.
    max_opposing_hitters_per_sp: int | None = Field(default=None, ge=0, le=8)
    stack_team: str | None = None
    stack_min: int = Field(default=0, ge=0, le=5)
    stack_max: int = Field(default=5, ge=0, le=5)
    bringback_min: int = Field(default=0, ge=0, le=5)
    allow_projected_hitters: StrictBool = True
    participation_max_age_minutes: Positive = 30.0
    weather_max_age_minutes: Positive = 60.0
    projection_max_age_hours: Positive = 24.0
    max_candidates_per_entry: int = Field(default=8, ge=1, le=100)
    total_seconds: Positive = 120.0
    per_solve_seconds: Positive = 15.0
    simulations: int = Field(default=2048, ge=128, le=50000)
    seed: int = Field(default=20260909, ge=0, le=2**32 - 1)
    qa_iterations: int = Field(default=3, ge=0, le=3)
    enhance: StrictBool = True
    # Explicit prior factor loadings; variances, not "correlation percentages".
    team_loading: Probability = 0.4
    game_loading: Probability = 0.15
    opposing_pitcher_loading: Probability = 0.3

    @model_validator(mode="after")
    def feasible_controls(self):
        if self.stack_min > self.stack_max:
            raise ValueError("stack minimum exceeds maximum")
        if (self.stack_min or self.bringback_min) and not self.stack_team:
            raise ValueError("stack/bring-back minimum requires a stack team")
        if self.team_loading**2 + self.game_loading**2 >= 1:
            raise ValueError("hitter factor variance must be below one")
        if self.opposing_pitcher_loading**2 + self.game_loading**2 >= 1:
            raise ValueError("pitcher factor variance must be below one")
        return self


class EdgeGateOutput(StrictModel):
    """Optional LLM output. It can propose facts/constraints, never a lineup."""

    schema_version: Literal[1] = 1
    source_id: str
    player_id: ID | None = None
    game_id: str | None = None
    status: Status | None = None
    proposed_player_cap: Probability | None = None
    confidence: Literal["confirmed", "ambiguous"]
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def admissible(self):
        if self.confidence != "confirmed":
            raise ValueError("ambiguous extraction is not admissible")
        if self.status is not None and self.player_id is None:
            raise ValueError("player status requires an exact player ID")
        if self.status is None and self.proposed_player_cap is None:
            raise ValueError("no structured fact or constraint proposed")
        return self


@dataclass(frozen=True)
class Player:
    player_id: str
    person_id: str
    name: str
    team: str
    opponent: str
    game_id: str
    positions: tuple[str, ...]
    role: str
    salary: int
    start: datetime
    status_out: bool
    excluded: bool


@dataclass(frozen=True)
class Entry:
    entry_id: str
    contest_id: str
    name: str
    fee_cents: int
    record_index: int
    roster: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    roster: tuple[str, ...]
    signature: tuple[str, ...]
    people: frozenset[str]
    pitchers: frozenset[str]
    teams: frozenset[str]
    games: frozenset[str]
    captain: str | None
    mean: float
    primary_stack: str = ""
