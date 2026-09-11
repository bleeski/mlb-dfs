"""Point-in-time evidence and provider boundaries. No network or LLM calls."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from .contracts import Controls, EdgeGateOutput, EvidenceBundle, Player
from .csvio import MAX_INPUT_BYTES


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a timezone-aware clock is required")
    return value.astimezone(timezone.utc)


def read_bounded(path: Path) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds the size limit")
    return raw


def confined_source(root: Path, relative: str) -> Path:
    from pathlib import PureWindowsPath

    rel = Path(relative)
    win = PureWindowsPath(relative)
    if (
        rel.is_absolute()
        or win.is_absolute()
        or win.drive
        or ".." in rel.parts
        or ".." in win.parts
    ):
        raise ValueError(
            "source artifact must be relative and confined to the evidence directory"
        )
    target = (root / rel).resolve(strict=True)
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError("source artifact escapes the evidence directory")
    if target.name.lower() in {".env", ".netrc"} or target.suffix.lower() not in {
        ".json",
        ".csv",
        ".txt",
        ".html",
    }:
        raise ValueError(
            "unsupported source artifact; credential files are never evidence"
        )
    return target


class SnapshotProvider(Protocol):
    def read(self) -> tuple[bytes, dict[str, bytes]]: ...


class FileProvider:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def read(self) -> tuple[bytes, dict[str, bytes]]:
        raw = read_bounded(self.path)
        bundle = EvidenceBundle.model_validate_json(raw)
        captured = {}
        for source in bundle.sources:
            payload = read_bounded(confined_source(self.path.parent, source.artifact))
            if sha256(payload).hexdigest() != source.sha256:
                raise ValueError(f"source artifact hash mismatch: {source.source_id}")
            captured[source.source_id] = payload
        return raw, captured


class UnavailableLiveProvider:
    def read(self) -> tuple[bytes, dict[str, bytes]]:
        raise RuntimeError(
            "LIVE_PROVIDER_UNAVAILABLE: supply a verified local evidence snapshot"
        )


@dataclass(frozen=True)
class Prepared:
    bundle: EvidenceBundle
    eligible: frozenset[str]
    reasons: dict[str, str]
    game_caps: dict[str, float]
    warnings: tuple[str, ...]
    market_checks: tuple[dict, ...]


def freshness_deadline(bundle: EvidenceBundle, controls: Controls) -> datetime:
    sources = {s.source_id: s for s in bundle.sources}
    limits = [s.expires_at for s in bundle.sources]
    participation = {p.source_id for p in bundle.players} | {
        g.source_id for g in bundle.games
    }
    participation |= {side.source_id for g in bundle.games for side in g.lineups}
    weather = {g.weather_source_id for g in bundle.games}
    projections = {p.source_id for p in bundle.projections}
    for ids, age in (
        (participation, timedelta(minutes=controls.participation_max_age_minutes)),
        (weather, timedelta(minutes=controls.weather_max_age_minutes)),
        (projections, timedelta(hours=controls.projection_max_age_hours)),
    ):
        limits.extend(sources[sid].observed_at + age for sid in ids)
    return min(limits)


def prepare(
    bundle: EvidenceBundle,
    players: dict[str, Player],
    controls: Controls,
    now: datetime,
    fixture_mode: bool,
) -> Prepared:
    now = aware(now)
    if bundle.fixture != fixture_mode:
        raise ValueError("fixture/live evidence mode mismatch")
    sources = {x.source_id: x for x in bundle.sources}
    for source in sources.values():
        if source.observed_at > now or now >= source.expires_at:
            raise ValueError(f"STALE_OR_FUTURE_SOURCE: {source.source_id}")
    if now >= freshness_deadline(bundle, controls):
        raise ValueError(
            "STALE_SOURCE_POLICY: a source exceeded the configured participation, weather or projection age"
        )
    games = {g.game_id: g for g in bundle.games}
    salary_games = {p.game_id for p in players.values()}
    if set(games) != salary_games:
        raise ValueError("evidence game identities differ from the salary slate")
    if len({g.event_id for g in bundle.games}) != len(games):
        raise ValueError("two salary games claim the same provider event ID")
    people = {p.person_id for p in players.values()}
    status = {p.player_id: p for p in bundle.players}
    projections = {p.player_id: p for p in bundle.projections}
    if (set(status) | set(projections)) - people:
        raise ValueError(
            "evidence/projection IDs must be canonical IDs in the salary pool"
        )
    canonical = {p.person_id: p for p in players.values()}
    if set(projections) == people and all(
        p.ownership is not None for p in projections.values()
    ):
        groups = (
            [(people, 6.0)]
            if any(p.role == "CPT" for p in players.values())
            else [
                ({pid for pid, p in canonical.items() if "P" in p.positions}, 2.0),
                ({pid for pid, p in canonical.items() if "P" not in p.positions}, 8.0),
            ]
        )
        for group, expected in groups:
            if not math.isclose(
                sum(projections[pid].ownership for pid in group),
                expected,
                rel_tol=0,
                abs_tol=max(0.001, 0.0001 * len(group)),
            ):
                raise ValueError(
                    "complete ownership marginals do not reconcile to roster-slot budgets"
                )
        if any(p.role == "CPT" for p in players.values()) and all(
            p.captain_ownership is not None for p in projections.values()
        ):
            if not math.isclose(
                sum(p.captain_ownership for p in projections.values()),
                1.0,
                rel_tol=0,
                abs_tol=max(0.001, 0.0001 * len(people)),
            ):
                raise ValueError(
                    "complete captain ownership does not sum to one captain slot"
                )
    sides = {}
    for game in games.values():
        roster_players = [p for p in players.values() if p.game_id == game.game_id]
        if {p.team for p in roster_players} - {game.away, game.home}:
            raise ValueError("evidence teams disagree with salary teams")
        if any(p.start != game.start for p in roster_players):
            raise ValueError(
                "evidence date/time differs from the salary event; it cannot unlock a game"
            )
        if game.state == "unknown" or game.weather == "unknown":
            raise ValueError("unknown game or weather state")
        for side in game.lineups:
            for pid in side.ordered_ids:
                matches = [
                    p
                    for p in roster_players
                    if p.person_id == pid and p.team == side.team
                ]
                if not matches or any("P" in p.positions for p in matches):
                    raise ValueError(
                        "batting-order ID is absent, on the wrong team, or a pitcher"
                    )
            sides[(game.game_id, side.team)] = side
    eligible, reasons, warnings = set(), {}, []
    for pid, player in players.items():
        rec = status.get(player.person_id)
        game = games[player.game_id]
        reason = ""
        if rec and (rec.team != player.team or rec.game_id != player.game_id):
            raise ValueError("player evidence identity conflicts with the salary file")
        if player.status_out or player.excluded:
            reason = "salary_out_or_excluded"
        elif (
            game.state in {"postponed", "cancelled", "suspended"}
            or game.weather == "high"
        ):
            reason = "game_unavailable"
        elif rec is None or rec.status in {"unknown", "bench", "confirmed_out"}:
            reason = "participation_unavailable" if rec is None else rec.status
        elif "P" in player.positions:
            if rec.status not in {"probable_pitcher", "confirmed_starter"}:
                reason = "pitcher_not_probable_or_confirmed"
        else:
            side = sides.get((player.game_id, player.team))
            if side and side.confirmed and player.person_id not in side.ordered_ids:
                reason = "omitted_from_confirmed_lineup"
            elif rec.status not in {"confirmed_starter", "projected_starter"}:
                reason = "hitter_status_not_eligible"
            elif (
                rec.status == "projected_starter"
                and not controls.allow_projected_hitters
            ):
                reason = "confirmed_starter_required"
            elif rec.status == "projected_starter":
                warnings.append(f"projected starter: {player.person_id}")
        if reason:
            reasons[pid] = reason
        else:
            if player.person_id not in projections:
                raise ValueError(
                    f"eligible salary player lacks a projection: {player.person_id}"
                )
            if "P" not in player.positions and projections[player.person_id].mean < 0:
                raise ValueError("a hitter's expected fantasy score cannot be negative")
            eligible.add(pid)
    caps = dict(controls.max_game_exposure)
    for game in games.values():
        if game.weather == "medium":
            caps[game.game_id] = min(caps.get(game.game_id, 1.0), 0.25)
    if set(caps) - salary_games:
        raise ValueError("game exposure control references a game outside the slate")
    if set(controls.max_team_exposure) - {p.team for p in players.values()}:
        raise ValueError("team exposure control references an unknown team")
    if controls.stack_team and controls.stack_team not in {
        p.team for p in players.values()
    }:
        raise ValueError("stack team is absent from the salary slate")
    checks = []
    for market in bundle.markets:
        if market.game_id not in games:
            raise ValueError("market is for a different slate")
        residual_rows = market.residual_observations
        if len({r.event_id for r in residual_rows}) != len(residual_rows):
            raise ValueError("duplicate calibration residual event")
        valid_residual = (
            len(residual_rows) >= 30
            and market.residual_source_id
            and market.residual_model_id
            and market.residual_fitted_before is not None
            and market.residual_fitted_before < sources[market.source_id].observed_at
            and all(
                r.settled_at <= market.residual_fitted_before for r in residual_rows
            )
        )
        residual_sd = (
            statistics.stdev(r.prediction - r.outcome for r in residual_rows)
            if valid_residual
            else None
        )
        if residual_sd is not None and residual_sd <= 0:
            residual_sd = None
        if (
            residual_sd is not None
            and market.residual_stddev is not None
            and not math.isclose(
                residual_sd, market.residual_stddev, rel_tol=1e-8, abs_tol=1e-10
            )
        ):
            raise ValueError(
                "declared residual sigma differs from the frozen calibration observations"
            )
        if residual_rows and market.residual_sample_size not in {0, len(residual_rows)}:
            raise ValueError(
                "declared residual sample size differs from the frozen observations"
            )
        z = (
            (market.model_total - market.market_total) / residual_sd
            if residual_sd
            else None
        )
        fair = None
        if market.decimal_odds:
            implied = [1 / x for x in market.decimal_odds]
            fair = [x / sum(implied) for x in implied]
        check = {
            "game_id": market.game_id,
            "z": z,
            "fair_probabilities": fair,
            "residual_stddev": residual_sd,
            "residual_sample_size": len(residual_rows),
            "residual_estimator": "sample SD of timestamped out-of-time residuals"
            if residual_sd
            else None,
            "state": "UNAVAILABLE"
            if z is None
            else "BLOCKED"
            if abs(z) > 1.5
            else "PASS",
        }
        checks.append(check)
        if check["state"] == "BLOCKED":
            raise ValueError(
                f"MARKET_DISCREPANCY: {market.game_id} exceeds 1.5 residual standard deviations"
            )
        if z is None:
            warnings.append(
                f"market residual uncertainty unavailable: {market.game_id}"
            )
    return Prepared(
        bundle,
        frozenset(eligible),
        reasons,
        caps,
        tuple(sorted(set(warnings))),
        tuple(checks),
    )


def validate_edge_output(
    raw: str, bundle: EvidenceBundle, players: dict[str, Player]
) -> EdgeGateOutput:
    # Parse JSON, never extract a code fence or evaluate model-written text.
    json.loads(raw)
    result = EdgeGateOutput.model_validate_json(raw)
    if result.source_id not in {s.source_id for s in bundle.sources}:
        raise ValueError("LLM source is not part of the frozen evidence")
    if result.player_id and result.player_id not in {
        p.person_id for p in players.values()
    }:
        raise ValueError("LLM player ID is outside the salary pool")
    if result.game_id and result.game_id not in {g.game_id for g in bundle.games}:
        raise ValueError("LLM event is outside the salary slate")
    return result
