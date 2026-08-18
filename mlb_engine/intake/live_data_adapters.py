"""Live data adapters v1.2 for MLB Classic v2.26.0.

Converts external data into the pipeline's input contracts so production
inputs are derived, not hand-transcribed in chat:

- MLB Stats API lineups feed (the ``mlb-lineups`` skill output) ->
  ``status_by_player_id`` keyed by DraftKings Player_ID with lock times from
  game start, plus confirmed teams/hitters/orders for the projection refresh
  and per-team confirmed-hitter validation. v1.1 adds two matchup extractors
  for the deterministic F4: ``extract_opposing_probables`` (DK team -> the
  opposing probable SP with MLBAM id and hand) and ``extract_batter_hands``
  (DK Player_ID -> bat side for posted hitters).
- v1.2 adds ``build_slate_pool``, THE required intake step for every build:
  it restricts the slate to the players who can actually take the field.
  Hitters are the nine in each confirmed lineup plus the platoon-projected
  nine for each TBD team; pitchers are the feed's probables plus anything
  explicitly declared. Every other salary row is dropped before the engine
  sees it (absent, not Excluded), which ends both the full-CSV projection
  waste and the recurring non-starter pitcher-role confusion. The salary CSV
  stays authoritative for Player_ID, salary, team, positions, and game of
  the players kept. Output bundles run_slate-ready kwargs, the F4 building
  blocks, the slate clock, and a pool report with per-team status, warnings,
  and blockers.
- the-odds-api.com v4 (the ``mlb-game-odds`` skill's API) -> the odds packet
  entries the slate-context odds gate validates ({total, source, fetched_at}
  per game), and per-event player props -> implied probabilities.
- odds-api.io v3 (the ``mlb-hr-prop-arb`` skill's API) -> HR prop rows with
  decimal-odds implied probabilities.

Design rules:
- Every ``fetch_*`` has a ``parse_*`` counterpart that takes already-fetched
  JSON, so the adapters work without network egress when a skill or operator
  supplies the payload.
- Fetchers use only the standard library (urllib), never log or echo API keys,
  and scrub keys from error text.
- Free-tier facts, verified 2026-06-11: the-odds-api featured markets
  (h2h/spreads/totals) cost markets x regions per call covering all events
  (DK+FD totals = 1 credit); player props are non-featured and cost
  markets x regions PER EVENT via /events/{id}/odds. Free plan is 500
  credits/month; quota headers are surfaced. odds-api.io rate limits
  5,000 requests/hour on all plans. sportsdata.io's free trial scrambles
  scores, stats, and odds by their own documentation, so nothing here
  consumes it; do not wire decision paths to scrambled data.
- Implied probabilities are deterministic transforms of posted prices. They
  are review inputs for F3/F4/right-tail judgment, never win-rate or ROI
  claims (truthful-labels rule).
"""
from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.swap.late_swap_manager import (
    CONFIRMED_STARTER, PROJECTED_STARTER, UNKNOWN, PlayerLineupStatus,
)
from mlb_engine.intake.slate_intake_manager import normalize_name

VERSION = "v1.6"

# F17. The platoon reference's own staleness was measured against its own
# collected_date, which is the one date it can never be stale against, so a file
# collected weeks ago reported zero stale teams on every build. Age is measured
# against the slate being built. A projected batting order predates trades,
# call-ups and role changes; past the block threshold it is not thin signal, it
# is a fabricated order that a stack would be built on.
PLATOON_AGE_WARN_DAYS = 3
PLATOON_AGE_BLOCK_DAYS = 7
STALE_PLATOON_POLICIES = ("block", "warn")

# DraftKings' Starting column tokens for arms. 'SP' is a declared starter. 'PO'
# is a probable opener: one or two innings by design, and a two-pitcher Classic
# roster priced on a starter's workload is a material error. 'PLR' is a
# PROJECTED LONG RELIEVER -- a role claim, not a generic listed-player tag. This
# module asserted the opposite until R104 while showdown.py:131-133 documented
# the same token correctly in the same repo, and because Classic intake attached
# no meaning to it, a PLR arm who was not also the feed probable never entered
# the pool at all.
#
# R104. The two tokens are different facts and get different treatment, because
# the confirm step differs. PO needs no judgment: an opener is barred from
# pitcher slots outright, role BARRED_OPENER_ROLE. PLR needs a web search to
# resolve, which is non-deterministic and must not live inside a replayable
# build, so intake SURFACES it as a named soft blocker per arm and the operator
# decides via declared_pitchers (build_slate.py's repeatable --declare-pitcher).
DK_STARTING_OPENER_TOKENS = frozenset({"PO"})
DK_STARTING_LONG_RELIEVER_TOKENS = frozenset({"PLR"})

# R104. The role a barred opener carries. Deliberately absent from
# dk_entries_manager.ALLOWED_PITCHER_ROLES, optimizer_v3.OPTIONAL_SP_AUDIT_STATUSES
# and execution_pipeline.ALLOWED_PITCHER_ROLES_FOR_GATE: it names an arm that was
# audited and BARRED, not one that may be rostered. It is therefore never written
# into ``pitcher_roles``, whose three consumers all read that mapping as "the arms
# that may be rostered" -- a barred arm placed there would fail the pitcher-audit
# gate on every slate carrying an opener. Barred arms ride the pool report's
# ``non_rosterable_arms`` instead, so the arm stays visible without being legal.
#
# ``viable_bulk_or_alt_sp`` survives this change and PO stops being its producer:
# it is now reachable only by explicit operator declaration, which is what the
# role always meant. That is the answer to the entry's open question.
BARRED_OPENER_ROLE = "declared_opener"

THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_IO_BASE = "https://api.odds-api.io/v3"

# Team-code normalization moved to mlb_engine.team_codes (R59/R82) and is
# re-exported here so every existing import path is unchanged. It left this
# module because normalizing a code has nothing to do with fetching one, and
# tools/lineups_from_paste.py -- which carries a pinned zero-network contract --
# needs the normalizer without this module's urllib import graph.
from mlb_engine.team_codes import (  # noqa: E402,F401
    DK_ABBREV_REMAP, MLB_TEAM_NAME_TO_DK, to_dk_abbrev, team_name_to_dk_abbrev,
)


def _scrub(text: str, secret: Optional[str]) -> str:
    if secret:
        text = text.replace(secret, "***")
        text = text.replace(urllib.parse.quote(secret, safe=""), "***")
    return text


def _http_get_json(url: str, timeout: float = 20.0, secret: Optional[str] = None) -> Tuple[Any, Dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "mlb-classic-adapters/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            return json.loads(response.read().decode("utf-8")), headers
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(_scrub(f"HTTP {exc.code} from {url}: {detail}", secret)) from None
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise RuntimeError(_scrub(f"network error fetching {url}: {exc.reason}", secret)) from None


def _record_get(record: Any, key: str, default: Any = "") -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _load_salary_players(salary_players: Any) -> Dict[str, Any]:
    """Accept a pid->record mapping or a DK salary CSV path."""
    if isinstance(salary_players, (str, Path)):
        from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
        return {p.player_id: p for p in parse_dk_salary_csv(str(salary_players))}
    return dict(salary_players)


def _parse_utc(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _salary_game_times(players: Mapping[str, Any]) -> Dict[str, datetime]:
    """DK game_id -> earliest UTC start parsed from the salary Game Info column.

    The salary CSV is authoritative for which leg of a doubleheader is on the
    slate. DK ships one leg per draftgroup, so the earliest parseable start for
    a matchup is that leg.
    """
    from mlb_engine.intake.slate_intake_manager import parse_game_info_datetime

    out: Dict[str, datetime] = {}
    for record in players.values():
        gid = str(_record_get(record, "game_id") or "").strip().upper()
        info = _record_get(record, "game_info")
        if not gid or not info:
            continue
        parsed = parse_game_info_datetime(info)
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if gid not in out or parsed < out[gid]:
            out[gid] = parsed
    return out


def select_one_leg_per_matchup(
    entries: Sequence[Any],
    key_of,
    start_of,
    slate_game_times: Mapping[str, datetime],
    tolerance_minutes: int = 10,
) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """Keep exactly the doubleheader leg that is on the DK slate.

    Any source keyed only by ``AWAY@HOME`` collapses both legs of a doubleheader
    onto one key, and a naive last-write-wins loop silently adopts the night
    game's numbers for a matinee draftgroup. That is a wrong-game bug, not a
    cosmetic one, so leg selection is resolved against the salary file rather
    than by iteration order.

    This is the one implementation. The lineups feed and the odds packet both
    call it, because two copies of a leg rule are two answers to one question.
    ``key_of`` returns ``AWAY@HOME`` (or None to skip the entry) and ``start_of``
    returns the leg's UTC start (or None when it cannot be parsed).

    Legs whose start disagrees with the salary file by more than
    ``tolerance_minutes`` are still resolved to the closest one, and the reason
    says so. When the salary file has no time for a matchup the earliest leg is
    kept, which is first-wins rather than last-wins and matches DK's
    one-leg-per-draftgroup behavior.

    Returns ``(kept, dropped)`` where each dropped record carries the entry
    itself under ``entry`` so the caller can name it in its own vocabulary.
    """
    by_key: Dict[str, List[Any]] = {}
    for entry in entries:
        key = key_of(entry)
        if not key:
            continue
        by_key.setdefault(str(key), []).append(entry)

    kept: List[Any] = []
    dropped: List[Dict[str, Any]] = []
    for game_id in sorted(by_key):
        legs = by_key[game_id]
        if len(legs) == 1:
            kept.append(legs[0])
            continue
        target = (slate_game_times or {}).get(game_id)
        dated = [(entry, start_of(entry)) for entry in legs]
        dated = [(entry, start) for entry, start in dated if start is not None]
        if not dated:
            kept.append(legs[0])
            continue
        # R58(a): the reason is written from the DROPPED leg's point of view.
        # It used to describe why the KEPT leg won and then be stamped on every
        # dropped record, so a matinee dropped in favour of a night leg carried
        # "matched salary start <night time>" -- a true sentence about a
        # different leg, and false about the record it was attached to. That
        # text is quoted in the R58 report as evidence, which is how it was
        # found.
        def _off(start: Any) -> float:
            return abs((start - target).total_seconds()) / 60.0

        if target is None:
            chosen, chosen_start = min(dated, key=lambda pair: pair[1])
            def _reason(_start: Any) -> str:
                return ("no salary start time to choose on; kept the earliest leg "
                        f"({chosen_start.isoformat()})")
        else:
            chosen, chosen_delta = min(
                ((entry, _off(start)) for entry, start in dated),
                key=lambda pair: pair[1],
            )
            if chosen_delta > tolerance_minutes:
                def _reason(start: Any) -> str:
                    return (f"no leg within {tolerance_minutes}m of the salary start "
                            f"{target.isoformat()}; kept the closest at "
                            f"{chosen_delta:.0f}m off, this leg is {_off(start):.0f}m off")
            else:
                def _reason(start: Any) -> str:
                    return (f"another leg matched the salary start "
                            f"{target.isoformat()} to within {tolerance_minutes}m; "
                            f"this leg is {_off(start):.0f}m off it")
        kept.append(chosen)
        for entry, start in dated:
            if entry is chosen:
                continue
            dropped.append({
                "game_id": game_id,
                "start_utc": start.isoformat(),
                "reason": _reason(start),
                "entry": entry,
            })
    return kept, dropped


def _legs_for_extraction(
    feed: Mapping[str, Any],
    salary_game_times: Optional[Mapping[str, datetime]] = None,
) -> List[Mapping[str, Any]]:
    """The feed games an extractor should read: one leg per matchup when the
    caller supplied salary game times, every game as-is when it did not (R58b).

    One place, so the three team-keyed extractors cannot drift from each other
    or from the status map.
    """
    games = list(feed.get("games") or [])
    if not salary_game_times:
        return games
    kept, _dropped = _select_slate_legs(games, salary_game_times)
    return list(kept)


def _select_slate_legs(
    games: Sequence[Mapping[str, Any]],
    salary_game_times: Mapping[str, datetime],
    tolerance_minutes: int = 10,
) -> Tuple[List[Mapping[str, Any]], List[Dict[str, Any]]]:
    """Lineups-feed wrapper over ``select_one_leg_per_matchup``."""

    def _key(game_entry: Mapping[str, Any]) -> Optional[str]:
        away = to_dk_abbrev((game_entry.get("away") or {}).get("team_abbrev"))
        home = to_dk_abbrev((game_entry.get("home") or {}).get("team_abbrev"))
        return f"{away}@{home}" if away and home else None

    def _start(entry: Mapping[str, Any]) -> Optional[datetime]:
        try:
            return _parse_utc(entry.get("game_date_utc"))
        except (TypeError, ValueError):
            return None

    kept, dropped_raw = select_one_leg_per_matchup(
        list(games), _key, _start, salary_game_times, tolerance_minutes)
    dropped = [{
        "game_id": record["game_id"],
        "game_pk": (record["entry"] or {}).get("game_pk"),
        "start_utc": record["start_utc"],
        "reason": record["reason"],
    } for record in dropped_raw]
    return kept, dropped


def salary_game_times(salary_players: Any) -> Dict[str, datetime]:
    """Public wrapper: DK game_id -> the slate's start time, from a salary CSV.

    This is what a caller outside this module passes to
    ``parse_the_odds_api_totals`` so the odds packet resolves the same
    doubleheader leg the lineups feed does.
    """
    return _salary_game_times(_load_salary_players(salary_players))


# ---------------------------------------------------------------------------
# R143: the salary file is the FIRST source for batting order
# ---------------------------------------------------------------------------
# Ben, 2026-08-17: DK's salary CSV first, a paste second, an API call third, and
# do not spend a fetch on a side an earlier source already covers.
#
# DK publishes the batting order in the `Starting` column, 1-9 per posted side,
# next to the Player_ID the build already treats as authoritative. Until now
# Classic read that column only as a CROSSWALK CHECK (see the blocker further
# down) and sourced its hitters from the feed instead, so on 2026-08-16 fifteen
# of sixteen posted sides carried a complete 1-9 in the authoritative file while
# the build went to a paste or the API for the same fact.
#
# Taking DK first also removes the name crosswalk for those sides: the order
# arrives already keyed by DK Player_ID, so a Kike/Enrique Hernandez mismatch
# cannot happen on a side DK posted.
#
# Two limits, both deliberate:
#   * ONLY a complete 1-9 counts. A partial DK side is a projection, it stays
#     out of the confirmed set, and the side falls through to the feed exactly
#     as before.
#   * DK ships no handedness. So this MERGES over a feed side rather than
#     replacing it, keeping `bat_side` where the feed has it; a side DK covers
#     and no feed does is named in `f4_handedness_unavailable`, because F4
#     platoon silently zeroing is the failure this repo has already paid for.
DK_ORDER_SLOTS = 9


def dk_confirmed_sides(salary_players: Any) -> Dict[str, List[Dict[str, Any]]]:
    """DK team -> its batting order from the salary file, complete sides only.

    A side is returned only when the ``Starting`` column supplies every slot 1
    through 9 exactly once. Anything short of that is a partial posting and is
    not a confirmed lineup, so it is not returned at all.
    """
    players = _load_salary_players(salary_players)
    by_team: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for pid, record in players.items():
        team = str(_record_get(record, "team") or "").strip().upper()
        token = str(_record_get(record, "starting") or "").strip()
        if not team or not token.isdigit():
            continue
        slot = int(token)
        if not 1 <= slot <= DK_ORDER_SLOTS:
            continue
        slots = by_team.setdefault(team, {})
        if slot in slots:
            # Two players on one slot is a malformed file, not a lineup. Drop
            # the whole side rather than pick one and call it confirmed.
            slots[slot] = None  # type: ignore[assignment]
            continue
        slots[slot] = {"order": slot, "dk_id": str(pid),
                       "name": str(_record_get(record, "name") or "")}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for team, slots in by_team.items():
        if len(slots) != DK_ORDER_SLOTS or any(v is None for v in slots.values()):
            continue
        out[team] = [slots[i] for i in range(1, DK_ORDER_SLOTS + 1)]
    return out


# SP/P only. PO is an opener and R104 settled that he is not a declared
# starter; PLR is a projected long reliever and CLAUDE.md makes rostering one an
# explicit call, not something a merge decides on a team's behalf. Neither
# belongs in an automatic probable.
DK_STARTING_PROBABLE_TOKENS = frozenset({"SP", "P"})


def dk_declared_probables(salary_players: Any) -> Dict[str, str]:
    """DK team -> Player_ID of the arm DK's ``Starting`` column marks SP/P."""
    players = _load_salary_players(salary_players)
    out: Dict[str, str] = {}
    for pid, record in sorted(players.items(), key=lambda kv: str(kv[0])):
        team = str(_record_get(record, "team") or "").strip().upper()
        token = str(_record_get(record, "starting") or "").strip().upper()
        if team and token in DK_STARTING_PROBABLE_TOKENS and team not in out:
            out[team] = str(pid)
    return out


def dk_order_coverage(salary_csv: str | Path) -> Tuple[List[str], List[str]]:
    """(teams DK has posted a full 1-9 for, teams it has not) from a salary CSV.

    One definition of "covered", shared by the pool and by any caller deciding
    whether a fetch is worth making, so the build cannot skip a fetch on one
    rule and then find the pool applying another.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    rows = parse_dk_salary_csv(str(salary_csv))
    covered = set(dk_confirmed_sides({p.player_id: p for p in rows}))
    teams = {str(p.team).strip().upper() for p in rows if p.team}
    return sorted(covered), sorted(teams - covered)


def merge_dk_starting_into_feed(
    feed: Optional[Mapping[str, Any]],
    salary_players: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Put DK's own posted orders into the feed ahead of whatever else is in it.

    Returns ``(feed, report)``. The feed keeps every side DK does not cover, so
    a paste or an API pull still supplies the rest; this only ever ADDS
    confirmed sides or upgrades one the feed had. Games absent from the feed
    entirely are synthesized from the salary file's ``Game Info``, which is what
    lets a fully posted slate build with no paste and no fetch at all.

    ``report`` carries ``dk_sides`` (teams sourced from DK), ``upgraded``
    (sides the feed also had), ``disagreements`` (same side, different names:
    DK wins per Ben's order and the difference is NAMED, never silently
    resolved), ``f4_handedness_unavailable`` and ``sides_left_to_feed``.
    """
    players = _load_salary_players(salary_players)
    sides = dk_confirmed_sides(players)
    probables = dk_declared_probables(players)
    out_feed: Dict[str, Any] = dict(feed or {})
    games = [dict(g) for g in (out_feed.get("games") or [])]
    report: Dict[str, Any] = {
        "dk_sides": sorted(sides), "upgraded": [], "disagreements": [],
        "f4_handedness_unavailable": [], "sides_left_to_feed": [],
        "games_synthesized": [], "source": "dk_salary_starting",
    }
    if not sides:
        report["sides_left_to_feed"] = sorted(
            {str(_record_get(r, "team") or "").strip().upper()
             for r in players.values()} - {""})
        out_feed["games"] = games
        return out_feed, report

    # Which game each DK team belongs to, and when it starts, off the salary
    # file alone -- the same columns the pool already treats as authoritative.
    team_game: Dict[str, str] = {}
    for record in players.values():
        team = str(_record_get(record, "team") or "").strip().upper()
        gid = str(_record_get(record, "game_id") or "").strip().upper()
        if team and gid and team not in team_game:
            team_game[team] = gid
    game_times = _salary_game_times(players)

    def _side_of(game: Mapping[str, Any], team: str) -> Optional[str]:
        for key in ("away", "home"):
            side = game.get(key) or {}
            if to_dk_abbrev(side.get("team_abbrev")) == team:
                return key
        return None

    covered: set = set()
    for game in games:
        for team, order in sides.items():
            key = _side_of(game, team)
            if key is None:
                continue
            covered.add(team)
            side = dict(game.get(key) or {})
            # R151. Both the disagreement read and the carry-forward lookup key
            # on the SAME normalized name the rest of the intake uses. They used
            # to key on `.strip().lower()`, which folds case and nothing else, so
            # a feed's "Jose Ramirez" (MLB Stats API ships diacritics) never
            # matched DK's plain-ASCII "Jose Ramirez" spelling. Two costs, and
            # the second is the expensive one: every accented name on a posted
            # side reported as a DISAGREEMENT (7 of 15 sides on the 2026-08-16
            # 1335_8g slate, all 7 false), and `prior` came back empty, so the
            # merged row silently dropped the feed's MLBAM `id` and `bat_side` --
            # R117's defect exactly, both F4 terms dead for that hitter. Ten
            # hitters lost both on that one slate, and `f4_handedness_unavailable`
            # stayed empty because it only fires when a side loses ALL nine.
            existing = {normalize_name(h.get("name")): h
                        for h in (side.get("lineup") or [])}
            if existing:
                report["upgraded"].append(team)
                dk_by_norm = {normalize_name(h["name"]): h["name"] for h in order}
                # Compared on the normalized key, REPORTED as each source spelled
                # it: an operator reading this list is checking a roster move, so
                # the useful string is the one the source printed.
                only_feed = sorted(str(existing[n].get("name") or n)
                                   for n in set(existing) - set(dk_by_norm))
                only_dk = sorted(dk_by_norm[n]
                                 for n in set(dk_by_norm) - set(existing))
                if only_feed or only_dk:
                    report["disagreements"].append({
                        "team": team, "resolved_to": "dk_salary_starting",
                        "in_feed_not_dk": only_feed, "in_dk_not_feed": only_dk})
            merged = []
            for hitter in order:
                prior = existing.get(normalize_name(hitter["name"]), {})
                row = {"order": hitter["order"], "name": hitter["name"],
                       "dk_id": hitter["dk_id"]}
                # Everything DK does not ship, kept from whatever did.
                for extra in ("id", "position", "bat_side"):
                    if prior.get(extra) not in (None, ""):
                        row[extra] = prior[extra]
                if not row.get("bat_side"):
                    row["bat_side"] = ""
                merged.append(row)
            if not any(h.get("bat_side") for h in merged):
                report["f4_handedness_unavailable"].append(team)
            side["lineup"] = merged
            side["lineup_status"] = "confirmed"
            side["lineup_source"] = "dk_salary_starting"
            if probables.get(team) and not side.get("probable_pitcher"):
                side["probable_pitcher"] = {"dk_id": probables[team]}
            game[key] = side

    # Games DK posted that the feed never mentioned: build them from salary.
    for team, order in sorted(sides.items()):
        if team in covered:
            continue
        gid = team_game.get(team)
        if not gid or "@" not in gid:
            continue
        away, _, home = gid.partition("@")
        game = next((g for g in games
                     if f"{to_dk_abbrev((g.get('away') or {}).get('team_abbrev'))}@"
                        f"{to_dk_abbrev((g.get('home') or {}).get('team_abbrev'))}" == gid),
                    None)
        if game is None:
            start = game_times.get(gid)
            game = {"game_pk": None, "venue": None, "status": "Scheduled",
                    "game_date_utc": start.astimezone(timezone.utc).isoformat()
                    if start else "",
                    "away": {"team_abbrev": away}, "home": {"team_abbrev": home}}
            games.append(game)
            report["games_synthesized"].append(gid)
        key = "away" if team == away else "home"
        side = dict(game.get(key) or {})
        side["team_abbrev"] = team
        side["lineup"] = [{"order": h["order"], "name": h["name"],
                           "dk_id": h["dk_id"], "bat_side": ""} for h in order]
        side["lineup_status"] = "confirmed"
        side["lineup_source"] = "dk_salary_starting"
        if probables.get(team):
            side["probable_pitcher"] = {"dk_id": probables[team]}
        report["f4_handedness_unavailable"].append(team)
        game[key] = side
        covered.add(team)

    report["upgraded"] = sorted(set(report["upgraded"]))
    report["f4_handedness_unavailable"] = sorted(
        set(report["f4_handedness_unavailable"]))
    report["sides_left_to_feed"] = sorted(set(team_game) - covered)
    out_feed["games"] = games
    return out_feed, report


# ---------------------------------------------------------------------------
# MLB Stats API lineups feed -> late-swap and confirmation contracts
# ---------------------------------------------------------------------------

def build_status_map_from_lineups_feed(
    feed: Mapping[str, Any],
    salary_players: Any,
    unlisted_status: str = UNKNOWN,
) -> Dict[str, Any]:
    """Derive the late-swap status map from the lineups feed plus the salary CSV.

    Every salary player whose game appears in the feed receives a
    ``PlayerLineupStatus`` keyed by DraftKings Player_ID, with ``lock_time``
    taken from the game's ``game_date_utc``. Hitters on a side the feed marks
    ``confirmed`` are ``Confirmed_Starter`` (with batting order); hitters on a
    side the feed marks ``partial`` are ``Projected_Starter``, because a
    partial lineup is a projection and calling it confirmed is a false label;
    probable pitchers are ``Projected_Starter``; everyone else gets
    ``unlisted_status`` (default ``Unknown``, which counts as TBD). Partial
    sides are reported in ``partial_lineup_teams``. Salary players whose game is absent
    from the feed are returned in ``uncovered_salary_player_ids`` and are NOT
    given a status, so the default fail-closed late-swap policy blocks rather
    than guessing their lock state.

    Returns a dict with: status_by_player_id, confirmed_teams,
    confirmed_hitter_ids, confirmed_order_by_player_id, starter_player_ids,
    probable_pitcher_ids, excluded_game_ids (postponed/cancelled),
    lock_time_by_game_id, unmatched_feed_players, uncovered_salary_player_ids.
    """
    players = _load_salary_players(salary_players)
    salary_by_name_team: Dict[Tuple[str, str], List[str]] = {}
    for pid, record in players.items():
        key = (normalize_name(_record_get(record, "name")), str(_record_get(record, "team")).strip().upper())
        salary_by_name_team.setdefault(key, []).append(str(pid))

    games, doubleheader_legs_dropped = _select_slate_legs(
        list(feed.get("games") or []), _salary_game_times(players)
    )
    lock_time_by_game_id: Dict[str, datetime] = {}
    game_meta: Dict[str, Dict[str, Any]] = {}
    excluded_game_ids: List[str] = []
    status_by_player_id: Dict[str, PlayerLineupStatus] = {}
    confirmed_teams: List[str] = []
    confirmed_hitter_ids: List[str] = []
    confirmed_order: Dict[str, int] = {}
    probable_pitcher_ids: List[str] = []
    partial_lineup_teams: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, str]] = []

    def match_dk_id(name: str, dk_team: str,
                    dk_id: Optional[str] = None) -> Optional[str]:
        # R143: a row that already carries a DK Player_ID skips the name
        # crosswalk entirely. DK's own `Starting` column supplies the id with
        # the order, so the side it posted cannot fail on a name variant the
        # way a paste or an API row can.
        if dk_id and str(dk_id) in players:
            return str(dk_id)
        hits = salary_by_name_team.get((normalize_name(name), dk_team), [])
        if len(hits) == 1:
            return hits[0]
        unmatched.append({"name": str(name), "team": dk_team,
                          "reason": "no salary match" if not hits else "ambiguous salary match"})
        return None

    for game_entry in games:
        away = game_entry.get("away") or {}
        home = game_entry.get("home") or {}
        away_team = to_dk_abbrev(away.get("team_abbrev"))
        home_team = to_dk_abbrev(home.get("team_abbrev"))
        if not away_team or not home_team:
            continue
        game_id = f"{away_team}@{home_team}"
        lock_time = _parse_utc(game_entry.get("game_date_utc"))
        lock_time_by_game_id[game_id] = lock_time
        game_meta[game_id] = {
            "game_pk": game_entry.get("game_pk"),
            "venue": game_entry.get("venue"),
            "status": game_entry.get("status"),
            "lock_time_utc": lock_time.isoformat(),
        }
        state = str(game_entry.get("status") or "").strip().lower()
        if "postpon" in state or "cancel" in state or "suspend" in state:
            excluded_game_ids.append(game_id)

        for side, dk_team in ((away, away_team), (home, home_team)):
            # F17: one reading of the side's lineup state, used for the status
            # stamp as well as for the confirmed sets. It used to be read twice
            # and only the second read was gated: every hitter in a posted
            # lineup was stamped Confirmed_Starter even on a side the feed calls
            # 'partial', which tools/fetch_slate_bundle.py emits for any side
            # with one to eight hitters posted. A projected slot is a labelled
            # prior; stamping it 'Confirmed' is the labels rule broken at the
            # front door.
            posted = str(side.get("lineup_status") or "").strip().lower()
            is_confirmed = posted == "confirmed"
            lineup_rows = side.get("lineup") or []
            if is_confirmed:
                confirmed_teams.append(dk_team)
            elif lineup_rows:
                partial_lineup_teams.append(
                    {"team": dk_team, "game_id": game_id,
                     "hitters_posted": len(lineup_rows),
                     "lineup_status": posted or "unknown"}
                )
            for hitter in lineup_rows:
                dk_id = match_dk_id(hitter.get("name"), dk_team,
                                    hitter.get("dk_id"))
                if dk_id is None:
                    continue
                order = hitter.get("order")
                status_by_player_id[dk_id] = PlayerLineupStatus(
                    player_id=dk_id, name=str(hitter.get("name") or ""), team=dk_team,
                    game_id=game_id, lock_time=lock_time,
                    status=CONFIRMED_STARTER if is_confirmed else PROJECTED_STARTER,
                    batting_order=int(order) if order is not None else None,
                )
                if is_confirmed:
                    confirmed_hitter_ids.append(dk_id)
                    if order is not None:
                        confirmed_order[dk_id] = int(order)
            probable = side.get("probable_pitcher") or None
            # R143: a probable identified by DK Player_ID needs no name at all.
            # Requiring one here is what made a DK-sourced side arrive with 9
            # confirmed bats and no arm, which blocks every team on the slate.
            if probable and (probable.get("name") or probable.get("dk_id")):
                dk_id = match_dk_id(probable.get("name"), dk_team,
                                    probable.get("dk_id"))
                if dk_id is not None:
                    status_by_player_id[dk_id] = PlayerLineupStatus(
                        player_id=dk_id, name=str(probable.get("name") or ""), team=dk_team,
                        game_id=game_id, lock_time=lock_time, status=PROJECTED_STARTER,
                    )
                    probable_pitcher_ids.append(dk_id)

    uncovered: List[str] = []
    for pid, record in players.items():
        pid_text = str(pid)
        if pid_text in status_by_player_id:
            continue
        team = to_dk_abbrev(_record_get(record, "team"))
        game_id = str(_record_get(record, "game_id") or "")
        lock_time = lock_time_by_game_id.get(game_id)
        if lock_time is None:
            for candidate_gid, candidate_lock in lock_time_by_game_id.items():
                if team and team in candidate_gid.split("@"):
                    game_id, lock_time = candidate_gid, candidate_lock
                    break
        if lock_time is None:
            uncovered.append(pid_text)
            continue
        status_by_player_id[pid_text] = PlayerLineupStatus(
            player_id=pid_text, name=str(_record_get(record, "name") or ""), team=team,
            game_id=game_id, lock_time=lock_time, status=unlisted_status,
        )

    return {
        "status_by_player_id": status_by_player_id,
        "confirmed_teams": sorted(set(confirmed_teams)),
        "confirmed_hitter_ids": sorted(set(confirmed_hitter_ids)),
        "confirmed_order_by_player_id": confirmed_order,
        "starter_player_ids": sorted(set(confirmed_hitter_ids)),
        "probable_pitcher_ids": sorted(set(probable_pitcher_ids)),
        "excluded_game_ids": sorted(set(excluded_game_ids)),
        "lock_time_by_game_id": {k: v.isoformat() for k, v in lock_time_by_game_id.items()},
        "game_meta": game_meta,
        "unmatched_feed_players": unmatched,
        "uncovered_salary_player_ids": sorted(uncovered),
        "partial_lineup_teams": sorted(partial_lineup_teams,
                                       key=lambda r: (r["team"], r["game_id"])),
        "doubleheader_legs_dropped": doubleheader_legs_dropped,
        "feed_date": feed.get("date"),
        "feed_fetched_at": feed.get("fetched_at"),
    }


def extract_opposing_probables(
    feed: Mapping[str, Any],
    salary_game_times: Optional[Mapping[str, datetime]] = None,
) -> Dict[str, Dict[str, Any]]:
    """From an mlb-lineups feed, map each DK team abbrev to the OPPOSING probable SP.

    Returns ``{team: {"id": mlbam_id_str, "name": ..., "hand": "R"/"L"}}``. The
    away team gets the home probable and vice versa. The MLBAM ``id`` joins
    directly to the Savant pitching expected-stats table, so the F4 quality
    component needs no name matching. Teams whose opponent has no posted
    probable are simply absent; projection_builder.compute_f4_factors treats
    them as neutral and reports them. Feed probables are usually populated even
    when batting orders are still TBD.

    R58(b): pass ``salary_game_times`` on a doubleheader slate. This function
    writes into a TEAM-keyed dict while iterating the feed's games, so two legs
    of one matchup are last-write-wins and a matinee build silently took the
    night starter. The status map and the odds packet already leg-select through
    ``select_one_leg_per_matchup``; these extractors did not, so the same feed
    produced a leg-correct status map and a leg-wrong platoon view. Omitting the
    argument keeps the previous behavior exactly.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for game_entry in _legs_for_extraction(feed, salary_game_times):
        away = game_entry.get("away") or {}
        home = game_entry.get("home") or {}
        away_team = to_dk_abbrev(away.get("team_abbrev"))
        home_team = to_dk_abbrev(home.get("team_abbrev"))
        away_probable = away.get("probable_pitcher") or {}
        home_probable = home.get("probable_pitcher") or {}
        if away_team and home_probable.get("name"):
            out[away_team] = {
                "id": str(home_probable.get("id") or "").strip(),
                "name": str(home_probable.get("name") or ""),
                "hand": home_probable.get("hand"),
            }
        if home_team and away_probable.get("name"):
            out[home_team] = {
                "id": str(away_probable.get("id") or "").strip(),
                "name": str(away_probable.get("name") or ""),
                "hand": away_probable.get("hand"),
            }
    return out


def extract_batter_hands(
    feed: Mapping[str, Any],
    salary_players: Any,
    salary_game_times: Optional[Mapping[str, datetime]] = None,
) -> Dict[str, str]:
    """From an mlb-lineups feed, map DK Player_ID -> bat side ("L"/"R"/"S").

    Uses the same name+team salary match as the status map, so the crosswalk
    cannot drift from it. Only hitters present in a posted lineup carry a
    ``bat_side``, so TBD teams are absent; the F4 platoon component simply
    stays neutral for them while the team-level SP-quality component still
    applies. Ambiguous or unmatched feed hitters are skipped, never guessed.

    R58(b): pass ``salary_game_times`` on a doubleheader slate. This function
    writes into a TEAM-keyed dict while iterating the feed's games, so two legs
    of one matchup are last-write-wins and a matinee build silently took the
    night starter. The status map and the odds packet already leg-select through
    ``select_one_leg_per_matchup``; these extractors did not, so the same feed
    produced a leg-correct status map and a leg-wrong platoon view. Omitting the
    argument keeps the previous behavior exactly.
    """
    players = _load_salary_players(salary_players)
    salary_by_name_team: Dict[Tuple[str, str], List[str]] = {}
    for pid, record in players.items():
        key = (normalize_name(_record_get(record, "name")), str(_record_get(record, "team")).strip().upper())
        salary_by_name_team.setdefault(key, []).append(str(pid))
    out: Dict[str, str] = {}
    for game_entry in _legs_for_extraction(feed, salary_game_times):
        for side in (game_entry.get("away") or {}, game_entry.get("home") or {}):
            dk_team = to_dk_abbrev(side.get("team_abbrev"))
            if not dk_team:
                continue
            for hitter in side.get("lineup") or []:
                bat_side = str(hitter.get("bat_side") or "").strip().upper()
                if bat_side not in ("L", "R", "S"):
                    continue
                hits = salary_by_name_team.get((normalize_name(hitter.get("name")), dk_team), [])
                if len(hits) == 1:
                    out[hits[0]] = bat_side
    return out



# ---------------------------------------------------------------------------
# v1.2 pool contract: only players who can actually take the field
# ---------------------------------------------------------------------------

def _pool_row(sp: Any, batting_order: Optional[int] = None) -> Dict[str, Any]:
    """One run_slate-ready projection row from a SalaryPlayer, salary-authoritative."""
    appg: Optional[float] = None
    raw = getattr(sp, "raw", {}) or {}
    for key in ("AvgPointsPerGame", "AvgPointsPerContest"):
        value = raw.get(key)
        if value not in (None, ""):
            try:
                appg = float(value)
            except (TypeError, ValueError):
                appg = None
            break
    row: Dict[str, Any] = {
        "Player_ID": str(sp.player_id),
        "Name": sp.name,
        "Team": sp.team,
        "Opponent": sp.opponent,
        "Position": "/".join(sp.positions),
        "Salary": float(sp.salary),
        "Game_ID": sp.game_id or sp.game_info,
        "AvgPointsPerGame": appg,
        "Excluded": False,
        # Carried so every downstream consumer, including the checkpoint and the
        # export validators, can re-derive availability without re-reading the
        # salary CSV. Rows reaching here are already status-filtered, so a
        # non-empty value is a watch tier, never an out tier.
        "DK_Status": str(getattr(sp, "status", "") or ""),
        "DK_Starting": str(getattr(sp, "starting", "") or ""),
    }
    if batting_order is not None:
        row["Batting_Order"] = int(batting_order)
    return row


def build_slate_pool(
    salary_csv: str | Path,
    lineups_feed: Mapping[str, Any],
    platoon_json: Optional[Mapping[str, Any]] = None,
    declared_pitchers: Optional[Mapping[str, str]] = None,
    tbd_fallback: str = "top9_appg",
    now: Optional[datetime] = None,
    lock_buffer_minutes: int = 5,
    stale_platoon_policy: str = "block",
) -> Dict[str, Any]:
    """Restrict the slate to the players who can actually take the field.

    THE pool contract (v2.26.0): hitters are the nine in each confirmed lineup
    plus the platoon-projected nine for each TBD team; pitchers are the feed's
    probables plus anything explicitly declared via ``declared_pitchers``
    ({DK Player_ID: role}). Every other salary row is dropped before the engine
    sees it, absent rather than Excluded, so no downstream step pays for bench
    bats or non-starting arms and the only P rows in the frame are the starters.
    The salary CSV stays authoritative for Player_ID, salary, team, positions,
    and game of the players kept.

    Mechanics: confirmed teams and orders come from the lineups feed through
    ``build_status_map_from_lineups_feed`` (the canonical name+team salary
    crosswalk). Confirmed hitters carry Batting_Order and a stamped
    F2 = batting_order_factor(slot), so confirmed and projected orders get
    symmetric F2 treatment. TBD teams take the platoon projected order when
    ``platoon_json`` is supplied (slots flow through
    ``platoon_order_by_player_id``, never Batting_Order, so a posted lineup
    still supersedes); a TBD team the platoon data cannot fill falls back to
    its top-9 salary hitters by AvgPointsPerGame with a loud warning, or is
    excluded when ``tbd_fallback='exclude'``. Postponed or cancelled games are
    excluded with a warning. A team left with no probable and no declared arm
    is surfaced as a blocker because declaring that starter is a real decision.

    Returns projection rows, ``run_slate_kwargs`` ready to splat into
    ``run_slate``, the F4 building blocks (``team_by_player_id``,
    ``opposing_probables``, ``batter_hands`` for
    ``projection_builder.compute_f4_factors``), the slate clock, and a
    ``pool_report`` with per-team status, warnings, and blockers. Deterministic
    intake bookkeeping; it moves no projection and is never a win-rate, ROI, or
    probability claim.

    ``stale_platoon_policy`` (F17) decides what happens when the platoon
    reference is older than ``PLATOON_AGE_BLOCK_DAYS`` against the slate date
    AND at least one TBD team on this slate is being filled from it. 'block'
    (default) emits a pool blocker naming the refresh; 'warn' degrades it to a
    warning. Age was previously measured against the file's own
    ``collected_date``, so a file collected a month ago read as zero days
    stale on every build.
    """
    from mlb_engine.intake.slate_intake_manager import (
        parse_dk_salary_csv, salary_status_coverage, salary_status_tier,
        slate_clock,
    )
    from mlb_engine.projections.projection_builder import batting_order_factor

    all_players = parse_dk_salary_csv(str(salary_csv))

    # R69(a): whether the Status/Starting read is armed at all, computed on the
    # raw file before the tiering below consumes it. Appended to the pool
    # report's warnings once that list exists.
    status_coverage = salary_status_coverage(all_players)

    # F1: DK's own Status column, read before anything selects a player.
    #
    # This has to happen here, ahead of the confirmed/platoon/APPG branches
    # rather than inside any of them, because the failure it closes is that the
    # APPG fallback sorts by AvgPointsPerGame and a shelved star has the highest
    # APPG on his team. The platoon path had the same hole from the other
    # direction: it kept whatever it matched. Both are exactly the early-build
    # path the fallback exists to serve.
    #
    # Shelved players are dropped from the legal pool. This is not the forbidden
    # compute-limited pool reduction: it removes players who cannot take the
    # field, which is a fact in the authoritative file, not a search-effort
    # trade. Day-to-day players stay eligible and warn.
    # R133(3): hoisted above the status loop, which is now its first caller --
    # a dropped player leaves `players` here and `by_id` can no longer answer
    # "was that a pitcher" later. One definition, five callers, unchanged rule.
    def is_pitcher(sp: Any) -> bool:
        return "P" in tuple(sp.positions)

    status_out_rows: List[Dict[str, Any]] = []
    status_watch_ids: set[str] = set()
    players = []
    for p in all_players:
        tier = salary_status_tier(p.status)
        if tier == "out":
            # R133(3): `is_pitcher` travels with the row because the shelved
            # player is dropped from `players` here and `by_id` cannot answer
            # the question later. The thin-team blocker needs it -- it used to
            # list IL PITCHERS as reasons a team was short of HITTERS.
            status_out_rows.append(
                {"player_id": p.player_id, "name": p.name, "team": p.team,
                 "status": p.status, "is_pitcher": bool(is_pitcher(p))}
            )
            continue
        if tier == "watch":
            status_watch_ids.add(p.player_id)
        players.append(p)

    by_id = {p.player_id: p for p in players}
    salary_map = {p.player_id: p for p in players}
    # R143, Ben 2026-08-17: the salary file is the FIRST source for batting
    # order, a paste is second, an API pull is third. This runs before the
    # status map so every entry path gets it -- the front door is the only
    # place a precedence rule cannot be bypassed by a caller. It only ever adds
    # or upgrades a confirmed side; sides DK has not posted still come from
    # whatever the caller supplied.
    lineups_feed, dk_order_report = merge_dk_starting_into_feed(
        lineups_feed, salary_map)
    status = build_status_map_from_lineups_feed(lineups_feed, salary_map)

    confirmed_teams = set(status["confirmed_teams"])
    confirmed_hitter_ids = list(status["confirmed_hitter_ids"])
    confirmed_order = dict(status["confirmed_order_by_player_id"])
    probable_ids = list(status["probable_pitcher_ids"])
    excluded_game_ids = set(status["excluded_game_ids"])

    def appg_of(sp: Any) -> float:
        try:
            return float((sp.raw or {}).get("AvgPointsPerGame") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    slate_teams = sorted({p.team for p in players if p.team})
    team_game = {p.team: (p.game_id or p.game_info) for p in players if p.team}

    warnings: List[str] = []
    blockers: List[str] = []
    # R69(a): a disarmed availability read is the first thing the pool report
    # says, because every count below it is computed as if the read worked.
    warnings.extend(status_coverage["warnings"])
    teams_report: Dict[str, Dict[str, Any]] = {}

    # R26: a postponed game is excluded on either of two independent signals,
    # because the 2026-07-28 incident (ATL@NYM, Chris Sale reaching the bank
    # as P1) was exactly their disagreement. DK marks a postponed game's Game
    # Info with the literal string 'Postponed', so the parsed game_id is empty
    # and team_game carries the literal, which can never equal a feed-derived
    # id like 'ATL@NYM'. Matching only id-to-id let both teams fall through to
    # tbd_teams and take platoon-projected orders, silently.
    #
    # Signal 1, the salary file: a non-blank Game Info that does not parse as
    # a matchup (no 'AWY@HOM' first token, the same predicate
    # infer_opponent_and_game_id applies) is DK stating the game is not
    # schedulable on this slate, and the CSV is authoritative for eligibility.
    # Signal 2, the feed: a game the feed marks postponed/cancelled/suspended
    # excludes its teams BY TEAM NAME, not by game-id equality, so the match
    # survives the salary side carrying a literal instead of an id. A blank
    # Game Info excludes nothing, because a blank cell never removes a player;
    # it warns below, and Signal 2 can still exclude the team.
    feed_excluded_team_status: Dict[str, str] = {}
    for gid in excluded_game_ids:
        state = str(((status.get("game_meta") or {}).get(gid) or {}).get("status")
                    or "postponed/cancelled/suspended")
        for side_team in str(gid).split("@"):
            feed_excluded_team_status[side_team] = state
    salary_unparsed_game: Dict[str, str] = {
        t: str(g) for t, g in team_game.items()
        if str(g or "").strip() and "@" not in str(g).strip().split()[0]
    }
    if salary_unparsed_game and set(salary_unparsed_game) == set(team_game):
        # A whole slate of postponements is implausible; every Game Info
        # failing at once is a DK format change or the wrong file. Excluding
        # everything would relabel a parser failure as weather, so Signal 1
        # stands down and this blocker carries the cause instead.
        sample = next(iter(sorted(salary_unparsed_game.values())))
        blockers.append(
            "every salary row's Game Info failed to parse as a matchup "
            f"(sample: '{sample}'); DK format change or wrong file, not a "
            "slate of postponements. No team excluded on it; fix the input."
        )
        salary_unparsed_game = {}
    excluded_teams = {t for t, g in team_game.items() if g in excluded_game_ids}
    excluded_teams |= set(salary_unparsed_game)
    excluded_teams |= {t for t in team_game if t in feed_excluded_team_status}
    for team in sorted(t for t, g in team_game.items() if not str(g or "").strip()):
        if team not in excluded_teams:
            warnings.append(
                f"{team}: salary Game Info is blank; the game cannot be "
                "matched against the feed. Not excluded on a blank cell; "
                "verify the salary file."
            )

    # One line per shelved player, naming player and team. A count alone is not
    # reviewable: the operator has to be able to see that the name he expected to
    # be in the pool is the name that was dropped, and why.
    for rec in sorted(status_out_rows, key=lambda r: (r["team"], r["name"])):
        warnings.append(
            f"{rec['team']} {rec['name']} ({rec['player_id']}): DK Status "
            f"{rec['status']}; dropped from the pool before selection"
        )
    for pid in sorted(status_watch_ids):
        sp = by_id.get(pid)
        if sp is not None:
            warnings.append(
                f"{sp.team} {sp.name} ({pid}): DK Status {sp.status}; eligible, "
                f"watch for a late scratch"
            )

    if stale_platoon_policy not in STALE_PLATOON_POLICIES:
        raise ValueError(
            f"stale_platoon_policy must be one of {list(STALE_PLATOON_POLICIES)}"
        )

    # F17: the date this pool is for, used to age the platoon reference. The
    # feed states its own date; fall back to the caller's clock.
    slate_date = None
    for candidate in (status.get("feed_date"), None):
        if candidate:
            try:
                y, m, d = (int(x) for x in str(candidate)[:10].split("-"))
                slate_date = date(y, m, d)
            except (TypeError, ValueError):
                slate_date = None
            break
    if slate_date is None:
        slate_date = (now or datetime.now(timezone.utc)).date()

    tbd_teams = [t for t in slate_teams if t not in confirmed_teams and t not in excluded_teams]
    platoon_order: Dict[str, int] = {}
    platoon_report: Optional[Dict[str, Any]] = None
    platoon_source: Optional[str] = None
    platoon_age_days: Optional[int] = None
    if tbd_teams:
        try:
            from mlb_engine.intake.platoon_order_adapter import (
                DEFAULT_PLATOON_REFERENCE, build_projected_order,
                extract_opp_throws_from_lineups, load_platoon_lineups,
            )
            resolved = platoon_json
            if resolved is None:
                # A TBD team with no projected order falls back to top-9 by
                # AvgPointsPerGame, which is a worse prior than the reference
                # platoon file and silently discards the batting order. Load the
                # reference by default so TBD games stay in the pool with a real
                # projected order instead of being guessed at or dropped.
                ref = DEFAULT_PLATOON_REFERENCE
                if not ref.is_absolute():
                    ref = Path(__file__).resolve().parents[2] / ref
                if ref.exists():
                    resolved = load_platoon_lineups(ref)
                    platoon_source = str(ref)
                else:
                    warnings.append(
                        f"no platoon reference at {ref}; TBD teams fall back to "
                        "top-9 AvgPointsPerGame. Refresh it from FanGraphs "
                        "RosterResource to restore projected orders."
                    )
            else:
                platoon_source = "caller_supplied"
            if resolved is not None:
                opp_throws = extract_opp_throws_from_lineups(
                    lineups_feed, _salary_game_times(salary_map))
                platoon_order, platoon_report = build_projected_order(
                    resolved, salary_csv, opp_throws, only_teams=list(tbd_teams),
                )
                platoon_order = {str(k): int(v) for k, v in platoon_order.items()}
                # F17: all four report keys reach the operator. Three of the
                # four were computed and never read, so a team the file did not
                # cover, a team whose page predates the file, and a team whose
                # opponent hand was guessed all looked identical to a clean
                # fill.
                report = platoon_report or {}
                for team in report.get("zero_fill_teams") or []:
                    warnings.append(
                        f"{team}: covered by the platoon file but filled 0 hitters; "
                        "team-code or name crosswalk failure, not thin data"
                    )
                for team in report.get("teams_missing_from_file") or []:
                    warnings.append(
                        f"{team}: TBD and absent from the platoon reference; "
                        "no projected order exists for it"
                    )
                for rec in report.get("stale_teams") or []:
                    warnings.append(
                        f"{rec.get('team')}: platoon page last updated "
                        f"{rec.get('page_updated')} ({rec.get('days_old')} days "
                        f"before the file was collected)"
                    )
                for team in report.get("hand_assumed_teams") or []:
                    warnings.append(
                        f"{team}: opposing pitcher hand unknown; platoon order "
                        f"taken from the default-hand view"
                    )
                collected = str(report.get("collected_date") or "")
                if collected:
                    try:
                        y, m, d = (int(x) for x in collected.split("-"))
                        platoon_age_days = (slate_date - date(y, m, d)).days
                    except (TypeError, ValueError):
                        platoon_age_days = None
        except Exception as exc:  # defensive: pool must degrade, not die
            warnings.append(f"platoon projected order unavailable: {exc}")
            platoon_order = {}

    keep: Dict[str, Dict[str, Any]] = {}

    # Confirmed hitters: Batting_Order + stamped F2 from the posted slot.
    for pid in confirmed_hitter_ids:
        sp = by_id.get(str(pid))
        if sp is None or is_pitcher(sp) or sp.team in excluded_teams:
            continue
        slot = confirmed_order.get(str(pid))
        row = _pool_row(sp, batting_order=slot)
        if slot is not None:
            row["F2"] = batting_order_factor(int(slot))
            row["Notes"] = "confirmed_order: F2 from posted batting order"
        keep[str(pid)] = row
    # The lineups feed covers the whole day; the salary file defines the
    # draftgroup. A team the feed confirms but the salary file does not carry is
    # not on this slate, so it is silent rather than a warning. Reporting it buried
    # real intake failures under noise: on 2026-07-24 the feed held 15 games and
    # the night draftgroup held 4, producing 22 "0/9" lines about teams that could
    # never have been in the pool.
    slate_team_set = set(slate_teams)
    for team in sorted((confirmed_teams & slate_team_set) - excluded_teams):
        n = sum(1 for r in keep.values() if r["Team"] == team)
        teams_report[team] = {"status": "confirmed", "hitters": n}
        if n == 9:
            continue
        detail = f"{team}: confirmed lineup matched {n}/9 salary hitters"
        if n < 5:
            # A posted lineup that crosswalks to almost nothing is a name/team
            # join failure, not thin data. Building anyway silently substitutes a
            # projected or APPG order while real information sits unused.
            blockers.append(detail + "; crosswalk failure, real lineup went unused")
        else:
            warnings.append(detail)

    # F17: a side the feed marks 'partial' is not confirmed and never was, but
    # nothing said so. Its posted hitters are stamped Projected_Starter and the
    # team routes through the TBD path; the operator should see which teams are
    # mid-post rather than infer it from their absence from the confirmed list.
    for rec in status.get("partial_lineup_teams") or []:
        if rec["team"] in slate_team_set and rec["team"] not in excluded_teams:
            warnings.append(
                f"{rec['team']}: lineup {rec['lineup_status']} with "
                f"{rec['hitters_posted']}/9 hitters posted; treated as TBD and "
                f"stamped Projected_Starter, not confirmed"
            )

    # Feed/draftgroup alignment. Keyed on whether the feed contains the slate's
    # games at all, never on how many lineups have posted, because an early build
    # legitimately has zero confirmed teams and must not be blocked for it.
    feed_teams = {
        side
        for gid in (status.get("lock_time_by_game_id") or {})
        for side in str(gid).split("@")
    }
    if feed_teams:
        eligible = slate_team_set - excluded_teams
        missing = sorted(eligible - feed_teams)
        if missing and len(missing) * 2 >= len(eligible):
            blockers.append(
                f"lineups feed covers {len(eligible) - len(missing)}/{len(eligible)} "
                "slate teams; it does not match this draftgroup. Refetch and pass "
                "--lineups before trusting this pool."
            )
        elif missing:
            warnings.append(
                "slate teams absent from the lineups feed: " + ", ".join(missing)
            )

    # R60: a PARTIAL side's posted starters are observed fact and outrank both
    # priors below them. The side routes through the TBD path because it is not
    # confirmed, and until this seeding existed the path never consulted the
    # status map: the fill ranked the whole roster by APPG, so a posted starter
    # having a worse season than a bench bat left the posted starter
    # unrosterable while the bench bat entered the pool. Nothing said so —
    # the team reported 'fallback_top9_appg, 9 hitters', which is the defect
    # class this contract exists to prevent, certifying clean and invisible in
    # the output. Ordered by posted slot so the seed is deterministic when a
    # side posts more than nine.
    partial_teams = {
        rec["team"] for rec in (status.get("partial_lineup_teams") or [])
        if rec.get("team") in slate_team_set and rec.get("team") not in excluded_teams
    }
    posted_partial_by_team: Dict[str, List[str]] = {}
    if partial_teams:
        ranked: List[Tuple[str, int, str]] = []
        for pid, stat in (status.get("status_by_player_id") or {}).items():
            team = getattr(stat, "team", None)
            if team not in partial_teams:
                continue
            if getattr(stat, "status", None) != PROJECTED_STARTER:
                continue
            sp = by_id.get(str(pid))
            if sp is None or is_pitcher(sp) or sp.team in excluded_teams:
                continue
            slot = getattr(stat, "batting_order", None)
            ranked.append((team, int(slot) if slot is not None else 99, str(pid)))
        for team, _slot, pid in sorted(ranked):
            posted_partial_by_team.setdefault(team, []).append(pid)

    # TBD teams: posted starters first, then platoon projected nine, then APPG
    # fallback when neither can fill.
    platoon_by_team: Dict[str, List[str]] = {}
    for pid in platoon_order:
        sp = by_id.get(pid)
        if sp is not None and not is_pitcher(sp) and sp.team not in excluded_teams:
            platoon_by_team.setdefault(sp.team, []).append(pid)
    # R60: which teams the platoon projection ACTUALLY supplied, which is no
    # longer the same question as which teams it covers. Posted seeds can take
    # every seat, and a team whose projection supplied nothing must not drag the
    # staleness gate down with it — the same reasoning CLAUDE.md item 2 already
    # applies to a fully pasted slate.
    platoon_used_teams: List[str] = []
    for team in tbd_teams:
        posted = [pid for pid in posted_partial_by_team.get(team, [])
                  if pid not in keep][:9]
        got = [pid for pid in platoon_by_team.get(team, [])
               if pid not in keep and pid not in posted][: max(0, 9 - len(posted))]
        seeded = posted + got
        for pid in seeded:
            keep[pid] = _pool_row(by_id[pid], batting_order=None)
        if got:
            platoon_used_teams.append(team)
        n = len(seeded)
        if n >= 9:
            teams_report[team] = {
                "status": "posted_partial_plus_platoon" if posted and got
                else "posted_partial" if posted else "platoon",
                "hitters": n,
            }
            if posted:
                warnings.append(
                    f"{team}: {len(posted)} posted starter(s) seeded from the "
                    f"partial lineup ahead of projected order"
                )
            continue
        if tbd_fallback == "exclude":
            # R60(b): "team excluded" has to mean excluded. The seeded rows used
            # to survive in the pool while the blocker said the team was out, so
            # the report and the pool disagreed at the moment the operator reads
            # the blocker to decide.
            for pid in seeded:
                keep.pop(pid, None)
            if got:
                platoon_used_teams.remove(team)
            teams_report[team] = {"status": "excluded_no_order_data", "hitters": 0}
            blockers.append(
                f"{team}: TBD lineup and platoon data filled only {n}/9; "
                f"team excluded (tbd_fallback='exclude'), "
                f"{n} row(s) dropped from the pool"
            )
            continue
        candidates = sorted(
            (p for p in players
             if p.team == team and not is_pitcher(p) and p.player_id not in keep),
            key=appg_of, reverse=True,
        )
        for sp in candidates[: 9 - n]:
            keep[sp.player_id] = _pool_row(sp, batting_order=None)
        filled = min(9, n + len(candidates[: 9 - n]))
        teams_report[team] = {
            "status": "posted_partial_plus_appg_fallback" if posted
            else "platoon_plus_appg_fallback" if got
            else "fallback_top9_appg",
            "hitters": filled,
        }
        detail = ""
        if posted:
            detail += f"{len(posted)} posted starter(s) seeded, "
        if got:
            detail += f"platoon filled {len(got)}/9, "
        warnings.append(
            f"{team}: {'partial' if posted else 'TBD'} lineup; {detail}"
            f"top-AvgPointsPerGame fallback supplied {filled - n} hitters"
        )

    # R60: the safety net behind the seeding. A posted starter that did not
    # reach the pool is named with the reason available, because the failure
    # this item was filed for was silent, not wrong-by-a-lot.
    for team in sorted(posted_partial_by_team):
        missed = [pid for pid in posted_partial_by_team[team] if pid not in keep]
        if not missed:
            continue
        named = ", ".join(
            f"{by_id[pid].name} ({pid})" for pid in missed if pid in by_id
        )
        warnings.append(
            f"{team}: posted starter(s) left out of the pool: {named}"
        )
    # F17: the platoon file's age against THIS slate, escalated only when the
    # build actually leans on it. A stale reference on an all-confirmed slate
    # costs nothing and says nothing; a stale reference supplying the projected
    # nine for a team that may be stacked is the mechanism behind the whole F1
    # class of defect and it was unobservable.
    platoon_dependent_teams = sorted(set(platoon_used_teams))
    if platoon_age_days is not None and platoon_dependent_teams:
        collected_text = (platoon_report or {}).get("collected_date")
        detail = (
            f"platoon reference collected {collected_text} is "
            f"{platoon_age_days} days old against slate {slate_date.isoformat()} "
            f"and supplies the projected order for "
            f"{', '.join(platoon_dependent_teams)}"
        )
        if platoon_age_days > PLATOON_AGE_BLOCK_DAYS and stale_platoon_policy == "block":
            blockers.append(
                detail + "; refresh it from FanGraphs RosterResource "
                "(python tools/fetch_rotowire_lineups.py writes the same schema) "
                "or pass stale_platoon_policy='warn' to accept the age on the record"
            )
        elif platoon_age_days > PLATOON_AGE_WARN_DAYS:
            warnings.append(detail)
    elif platoon_report is not None and platoon_dependent_teams:
        # R69(b): a reference the build IS leaning on, whose collected_date is
        # absent or will not parse, used to reach neither branch above -- the
        # age came out None and None compares against no threshold, so the
        # policy that exists to stop a stale reference was silent at its
        # strictest setting. Age unknown is not age zero. It is the one state
        # where the gate cannot answer its own question, so it reports at the
        # POLICY's severity rather than assuming the reference is fresh.
        collected_text = (platoon_report or {}).get("collected_date")
        detail = (
            f"platoon reference supplies the projected order for "
            f"{', '.join(platoon_dependent_teams)} but carries no parseable "
            f"collected_date (found {collected_text!r}); its age against slate "
            f"{slate_date.isoformat()} is UNKNOWN and cannot be checked"
        )
        if stale_platoon_policy == "block":
            blockers.append(
                detail + "; refresh it from FanGraphs RosterResource "
                "(python tools/fetch_rotowire_lineups.py writes the same schema) "
                "or pass stale_platoon_policy='warn' to accept the unknown age "
                "on the record"
            )
        else:
            warnings.append(detail)

    for team in sorted(excluded_teams):
        teams_report[team] = {"status": "excluded_postponed", "hitters": 0}
        # R26: name the signal that fired, so a salary-only exclusion (feed
        # not yet aware) reads differently from a feed-status one.
        reasons: List[str] = []
        if team in salary_unparsed_game:
            reasons.append(
                f"salary Game Info reads '{salary_unparsed_game[team]}', not a matchup"
            )
        if team in feed_excluded_team_status:
            reasons.append(
                f"lineups feed marks the game {feed_excluded_team_status[team]}"
            )
        if not reasons:
            reasons.append(
                f"game {team_game.get(team)} postponed/cancelled/suspended in the feed"
            )
        warnings.append(
            f"{team}: game postponed/cancelled/suspended "
            f"({'; '.join(reasons)}); team excluded"
        )

    # Backstop for the crosswalk. Since R143 a complete DK 1-9 is SOURCED above
    # rather than merely checked here, so this should now be unreachable for a
    # posted side; it stays because it fires on the remaining way a DK-posted
    # team can arrive thin (status drops, exclusions), and a check that has
    # become hard to trip is not a check worth deleting.
    starting_by_team: Dict[str, int] = {}
    for p in players:
        if p.team and str(p.starting).isdigit() and 1 <= int(p.starting) <= 9:
            starting_by_team[p.team] = starting_by_team.get(p.team, 0) + 1
    for team, dk_slots in sorted(starting_by_team.items()):
        if team in excluded_teams or dk_slots < 9:
            continue
        matched = sum(1 for r in keep.values() if r["Team"] == team)
        if matched < 5:
            blockers.append(
                f"{team}: DK marks 9 confirmed batting slots in the salary file "
                f"but the pool holds {matched}; crosswalk failure, the "
                f"authoritative order went unused"
            )

    # R133(3). This loop used to fire a BLOCKER at any count under nine, with
    # the message "the team cannot fill a stack". Three things were wrong with
    # it and they compound.
    #
    # The bar. A DK Classic lineup admits at most MAX_HITTERS_PER_TEAM hitters
    # from one team, so a team with that many CAN fill a maximum stack and the
    # sentence was false everywhere from 5 to 8. The bar now comes off the
    # solver constant rather than a number typed here, so if DK's rule moves the
    # check moves with it. It lands on the same 5 the contract already names for
    # a crosswalk failure (CLAUDE.md, SKILL.md), which is a coincidence of
    # arithmetic and not a copy: five is what fills a stack, and five is also
    # where a posted lineup that matched almost nothing stops being thin data.
    #
    # The contradiction. The confirmed path above ALREADY decides this exact
    # question and decides it differently -- `n < 5` blocks as a crosswalk
    # failure, 5 through 8 warns -- so a confirmed team at 8 got a warning there
    # and a blocker here, from one fact. This loop no longer re-decides a
    # confirmed team; it covers the statuses that path does not reach.
    #
    # The attribution. `status_out_rows` is built from every salary row, so the
    # list named PITCHERS as reasons a team was short of HITTERS. Worse, it is
    # not the cause at all when the shortfall is a posted starter DK never
    # listed: on 2026-08-12 DET read "8/9 hitters after dropping [15 IL
    # arms/bats]" when the actual ninth was Corey Julks, who has no salary row
    # and appears in no dropped list. The list is now hitters only, and it is
    # only offered as an explanation when it can be one.
    from mlb_engine.optimize.optimizer_v3 import MAX_HITTERS_PER_TEAM

    unstackable: List[str] = []
    short_of_nine: List[str] = []
    for team, rec in sorted(teams_report.items()):
        if rec.get("status") in ("excluded_postponed", "excluded_no_order_data"):
            continue
        n = int(rec.get("hitters") or 0)
        if n >= 9:
            continue
        hitters_dropped = [r for r in status_out_rows
                           if r["team"] == team and not r.get("is_pitcher")]
        detail = f"{team}: {n}/9 hitters in the pool"
        if hitters_dropped:
            detail += (" after dropping "
                       + ", ".join(f"{r['name']} ({r['status']})"
                                   for r in hitters_dropped))
        if n < MAX_HITTERS_PER_TEAM:
            unstackable.append(team)
            # The confirmed path owns this decision for a confirmed team and
            # says it better (it names the crosswalk). Two blockers on one fact
            # is what this loop was already doing wrong.
            if rec.get("status") != "confirmed":
                blockers.append(
                    detail + f"; under {MAX_HITTERS_PER_TEAM}, so the team "
                    f"cannot fill a stack of any legal size"
                )
        else:
            short_of_nine.append(team)
            if rec.get("status") != "confirmed":
                warnings.append(
                    detail + f"; enough for a full {MAX_HITTERS_PER_TEAM}-hitter "
                    f"stack, short of a full lineup"
                )

    # Pitchers: probables plus explicit declarations. Nothing else exists.
    pitcher_roles: Dict[str, str] = {}
    # R104. Arms DK named that this build refuses to roster, carried as a
    # reported fact rather than a silent absence. Never merged into
    # pitcher_roles; see BARRED_OPENER_ROLE for why that separation matters.
    non_rosterable_arms: List[Dict[str, str]] = []
    barred_opener_teams: Dict[str, List[str]] = {}
    for pid in probable_ids:
        sp = by_id.get(str(pid))
        if sp is None or sp.team in excluded_teams:
            continue
        # F17 established that DK's own Starting token decides the role and
        # routed PO to viable_bulk_or_alt_sp, which took the opener out of
        # REQUIRED_SP_AUDIT_STATUSES. R104 finishes the job, because that role is
        # still ROSTERABLE -- ALLOWED_PITCHER_ROLES, OPTIONAL_SP_AUDIT_STATUSES
        # and ALLOWED_PITCHER_ROLES_FOR_GATE all hold it -- so the optimizer could
        # put a one-or-two-inning arm in a P slot priced on a starter's workload
        # and the build certified with nothing downstream flagging it. The
        # asymmetry decides it: excluding an opener costs an option, rostering
        # one costs a P slot on a certified build. He is barred and absent from
        # the frame, which is the pool contract's "absent, not excluded".
        if str(sp.starting).strip().upper() in DK_STARTING_OPENER_TOKENS:
            non_rosterable_arms.append({
                "player_id": str(pid), "name": sp.name, "team": sp.team,
                "dk_starting": str(sp.starting).strip().upper(),
                "role": BARRED_OPENER_ROLE,
                "reason": "DK declares a probable opener: one or two innings by "
                          "design, and a P slot is priced on a starter's workload",
            })
            barred_opener_teams.setdefault(sp.team, []).append(sp.name)
            warnings.append(
                f"{sp.team} {sp.name} ({pid}): DK Starting={sp.starting} "
                f"(probable opener); BARRED from pitcher slots, role "
                f"{BARRED_OPENER_ROLE}, absent from the frame. If DK is wrong, "
                f"declare him via declared_pitchers ({pid}=declared_probable_sp), "
                f"and declare the bulk arm behind him the same way."
            )
            continue
        pitcher_roles[str(pid)] = "declared_probable_sp"
        keep[str(pid)] = _pool_row(sp, batting_order=None)
    for pid, role in (declared_pitchers or {}).items():
        sp = by_id.get(str(pid))
        if sp is None:
            warnings.append(f"declared pitcher id {pid} not on the salary file; skipped")
            continue
        if sp.team in excluded_teams:
            # R26: probables already skip excluded teams; an explicit
            # declaration must not be the back door into a postponed game.
            warnings.append(
                f"{sp.team} {sp.name} ({pid}): declared, but the game is "
                f"postponed/cancelled/suspended; excluded"
            )
            continue
        pitcher_roles[str(pid)] = str(role or "declared_probable_sp")
        keep.setdefault(str(pid), _pool_row(sp, batting_order=None))
    # R104. An explicit declaration is the documented way past the PO bar, so an
    # arm the operator declared is no longer a barred arm. Reconciled here rather
    # than guarded above, because declared_pitchers is read after the probables.
    if non_rosterable_arms:
        non_rosterable_arms = [a for a in non_rosterable_arms
                               if a["player_id"] not in pitcher_roles]
        barred_now = {a["team"] for a in non_rosterable_arms}
        barred_opener_teams = {t: n for t, n in barred_opener_teams.items()
                               if t in barred_now}

    # R104. PLR is a projected long reliever, a role claim DK is making, and this
    # module used to document it as meaningless -- so a PLR arm who was not also
    # the feed probable never entered the pool at all. Live case: DET Ty Madden
    # (Starting=PLR, $5,800, DK 43755567) sat outside the 2026-08-05 pool while
    # DK's own ID allocation put him inside the declared-starter block.
    # Confirming what a long reliever will actually throw is a web search, which
    # is non-deterministic and must not live inside a replayable build, so this
    # SURFACES one named blocker per arm and stops. It is tiered SOFT by
    # build_slate.py: it is a decision the operator owes, not a statement that
    # the pool is of the wrong slate.
    for pid_str in sorted(by_id):
        sp = by_id[pid_str]
        if str(getattr(sp, "starting", "") or "").strip().upper() \
                not in DK_STARTING_LONG_RELIEVER_TOKENS:
            continue
        if "P" not in set(getattr(sp, "positions", ()) or ()):
            continue
        if sp.team in excluded_teams or str(pid_str) in pitcher_roles:
            continue
        blockers.append(
            f"{sp.team} {sp.name} ({pid_str}): DK Starting=PLR, a projected long "
            f"reliever, and he is not in the pool. Confirm the role, then either "
            f"leave him out or add him with --declare-pitcher {pid_str}[=<role>]. "
            f"Surfaced, never auto-resolved: the confirm step is a web search and "
            f"a replayable build must not contain one."
        )

    teams_with_arm = {by_id[pid].team for pid in pitcher_roles if pid in by_id}
    for team in slate_teams:
        if team in excluded_teams or team in teams_with_arm:
            continue
        if team in barred_opener_teams:
            # R104. Naming the cause, because "no probable" reads as a feed gap
            # and this is not one: DK named an arm and the build refused him.
            blockers.append(
                f"{team}: no ROSTERABLE starter. DK's only declared arm is "
                f"{', '.join(sorted(barred_opener_teams[team]))}, a probable "
                f"opener barred from pitcher slots; declare the bulk arm behind "
                f"him via declared_pitchers, or that side has no rosterable arm"
            )
            continue
        blockers.append(
            f"{team}: no probable or declared starter; declare one via "
            f"declared_pitchers or that side has no rosterable arm"
        )

    rows = sorted(keep.values(), key=lambda r: (r["Team"], r["Player_ID"]))
    missing_appg = [r["Player_ID"] for r in rows if r.get("AvgPointsPerGame") in (None, "")]
    if missing_appg:
        warnings.append(
            f"{len(missing_appg)} kept rows missing AvgPointsPerGame; supply Base "
            f"before run_slate or those rows will fail assembly"
        )

    clock = slate_clock(
        players=players,
        lock_time_by_game_id=status.get("lock_time_by_game_id") or None,
        now=now,
        buffer_minutes=lock_buffer_minutes,
    )

    team_by_player_id = {
        r["Player_ID"]: r["Team"] for r in rows if r["Player_ID"] not in pitcher_roles
    }

    # R117(b). A probable that reaches the pool NAMED but with no MLBAM id or no
    # hand is a dead F4 wearing a live probable's clothes: the empty id fails the
    # join to the Savant pitching table so the quality term is 1.0, and the empty
    # hand misses every key in F4_PLATOON_PRIOR so the platoon term is 1.0 too.
    # `teams_without_opposing_probable` cannot see it, because DK's `Starting`
    # column supplied a NAME and that list only holds sides with no probable at
    # all. On 1910_10g every one of twenty probables arrived this way and the
    # build certified with `f4_non_neutral: 0` of 180 hitters.
    # ONE warning naming the sides, not one info line per side: twenty per-side
    # lines is what read as routine, and the fact is about the slate.
    opposing_probables = extract_opposing_probables(
        lineups_feed, _salary_game_times(salary_map))
    probables_no_id = sorted(
        team for team, rec in opposing_probables.items()
        if not str((rec or {}).get("id") or "").strip())
    probables_no_hand = sorted(
        team for team, rec in opposing_probables.items()
        if str((rec or {}).get("hand") or "").strip().upper() not in ("R", "L"))
    if probables_no_id or probables_no_hand:
        detail = []
        if probables_no_id:
            detail.append(
                f"no MLBAM id for the opposing probable of "
                f"{', '.join(probables_no_id)} (the Savant join key, so F4's "
                f"SP-quality term stays 1.0 for those bats)")
        if probables_no_hand:
            detail.append(
                f"no handedness for the opposing probable of "
                f"{', '.join(probables_no_hand)} (so F4's platoon term stays "
                f"1.0 for those bats)")
        warnings.append(
            "opposing probables reached the pool named but incomplete: "
            + "; ".join(detail)
            + ". A DK `Starting` fallback carries a name and neither field; "
            "supply a lineups feed or a paste with the RHP/LHP line to restore "
            "F4")
    kept_confirmed_hitters = sorted(
        pid for pid in confirmed_hitter_ids if str(pid) in keep
    )

    return {
        "projection_rows": rows,
        "run_slate_kwargs": {
            "projection_rows": rows,
            "confirmed_hitter_ids": kept_confirmed_hitters,
            "confirmed_teams": sorted(confirmed_teams - excluded_teams),
            "pitcher_roles": pitcher_roles,
            "platoon_order_by_player_id": platoon_order or None,
        },
        "pitcher_roles": pitcher_roles,
        "platoon_order_by_player_id": platoon_order,
        "platoon_report": platoon_report,
        "platoon_source": platoon_source,
        "team_by_player_id": team_by_player_id,
        # R58(b): one leg per matchup, the same selection the status map above
        # already applies. Without it these two are last-write-wins on a
        # doubleheader and a matinee build takes the night starter's F4 quality
        # and the night side's bat hands.
        "opposing_probables": opposing_probables,
        "batter_hands": extract_batter_hands(
            lineups_feed, salary_map, _salary_game_times(salary_map)),
        "clock": clock,
        "lock_time_by_game_id": status.get("lock_time_by_game_id"),
        "pool_report": {
            "salary_rows_total": len(all_players),
            "kept": len(rows),
            "dropped": len(all_players) - len(rows),
            "status_dropped": status_out_rows,
            "status_watch": [
                {"player_id": pid, "name": by_id[pid].name, "team": by_id[pid].team,
                 "status": by_id[pid].status}
                for pid in sorted(status_watch_ids)
                if pid in by_id and pid in keep
            ],
            "hitters_kept": len(team_by_player_id),
            "pitchers_kept": len(pitcher_roles),
            "teams": teams_report,
            # R143: which sides came from DK's own file, which the caller's
            # feed still had to cover, and where DK and the feed disagreed.
            # A session reads this to know whether a fetch was needed at all.
            "dk_batting_order": dk_order_report,
            # R26: the bucket that stayed empty on 2026-07-28. One key, so a
            # caller checks postponement exclusions without walking teams.
            "excluded_postponed_teams": sorted(excluded_teams),
            "pitchers": [
                {"player_id": pid, "name": by_id[pid].name, "team": by_id[pid].team,
                 "role": role}
                for pid, role in sorted(pitcher_roles.items()) if pid in by_id
            ],
            # R104. Arms DK named and this build refused. Separate from
            # 'pitchers' on purpose: that key is the rosterable set and feeds
            # the pitcher-audit gate, this one is the audit trail for the bar.
            "non_rosterable_arms": sorted(non_rosterable_arms,
                                          key=lambda a: (a["team"], a["player_id"])),
            "unmatched_feed_players": status.get("unmatched_feed_players"),
            "partial_lineup_teams": status.get("partial_lineup_teams") or [],
            "platoon_age_days": platoon_age_days,
            "platoon_dependent_teams": platoon_dependent_teams,
            # R69(a). Whether DK's Status/Starting read was armed for this file.
            "salary_status_coverage": status_coverage,
            # R117(b). The machine-readable half of the warning above: which
            # sides hold a NAMED opposing probable that cannot feed F4. Two
            # lists rather than one, because a missing id and a missing hand
            # kill different terms and are fixed by different inputs.
            "opposing_probables_incomplete": {
                "no_mlbam_id": probables_no_id,
                "no_hand": probables_no_hand,
            },
            # R133(3). Which teams are short of nine hitters, split at the bar
            # that decides what being short MEANS. Two lists rather than one
            # because the remedies differ and only one of them is fatal: under
            # MAX_HITTERS_PER_TEAM the team cannot fill a stack of any legal
            # size and the build is of a different slate, at or above it the
            # team stacks normally and the shortfall costs options. This is the
            # one definition of thin; `_derive_workflow_gates` reads it rather
            # than recomputing a third bar of its own.
            "thin_teams": {
                "cannot_fill_a_stack": unstackable,
                "short_of_nine": short_of_nine,
                "stack_bar": MAX_HITTERS_PER_TEAM,
            },
            "slate_date": slate_date.isoformat(),
            "warnings": warnings,
            "blockers": blockers,
        },
    }



# ---------------------------------------------------------------------------
# the-odds-api.com v4: game totals -> odds packet entries
# ---------------------------------------------------------------------------

def _et_day_utc_bounds(date_et: Optional[str]) -> Tuple[str, str]:
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    if date_et:
        day = datetime.strptime(date_et, "%Y-%m-%d").replace(tzinfo=eastern)
    else:
        day = datetime.now(eastern).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def fetch_the_odds_api_totals(
    api_key: str,
    date_et: Optional[str] = None,
    bookmakers: str = "draftkings,fanduel",
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Fetch full-game MLB totals. Cost: 1 credit per ~10 bookmakers (DK+FD = 1).

    Returns {"raw": <api response>, "quota": {"remaining", "used"}}.
    """
    start, end = _et_day_utc_bounds(date_et)
    params = {
        "apiKey": api_key, "markets": "totals", "oddsFormat": "american",
        "dateFormat": "iso", "bookmakers": bookmakers,
        "commenceTimeFrom": start, "commenceTimeTo": end,
    }
    url = f"{THE_ODDS_API_BASE}/sports/baseball_mlb/odds?{urllib.parse.urlencode(params)}"
    raw, headers = _http_get_json(url, timeout=timeout, secret=api_key)
    return {"raw": raw, "quota": {
        "remaining": headers.get("x-requests-remaining"),
        "used": headers.get("x-requests-used"),
    }}


# Top-level keys under which this project's tools wrap a raw the-odds-api
# events list. Ordered; the first list found wins.
_ODDS_WRAPPER_KEYS = ("odds_raw_totals", "raw", "events", "odds")

# The mlb-game-odds skill's DEFAULT output is not a raw events list: it is
# already flattened per book. Reversing that flattening is exact for the three
# markets the skill records, so both shapes can feed one parser rather than the
# default output being a documented footgun.
_SKILL_BOOK_MARKETS = ("h2h", "spreads", "totals")


def _skill_game_to_raw_event(game: Mapping[str, Any]) -> Dict[str, Any]:
    """One mlb-game-odds ``games`` entry -> one raw the-odds-api event.

    The skill's ``parse_event`` flattens ``bookmakers[].markets[].outcomes[]``
    into ``books[<book>].{moneyline,spread,total}``; this rebuilds the outcome
    lists it was built from. Team names are carried through unchanged, because
    the skill preserves the API's own ``home_team``/``away_team`` strings and
    those are what ``team_name_to_dk_abbrev`` expects.
    """
    home = game.get("home_team")
    away = game.get("away_team")
    books_raw = game.get("books")
    if books_raw is None:
        books_raw = {}
    if not isinstance(books_raw, Mapping):
        # Every guard here exists because the caller catches ValueError only, and
        # a hand-edited or half-written odds file must degrade to a stated shape
        # error rather than an AttributeError traceback out of a live build.
        raise ValueError(
            f"a 'games' entry's 'books' is {type(books_raw).__name__}, expected an "
            f"object keyed by bookmaker")
    bookmakers: List[Dict[str, Any]] = []
    for book_key, book in sorted(books_raw.items(), key=lambda kv: str(kv[0])):
        if not isinstance(book, Mapping):
            continue
        markets: List[Dict[str, Any]] = []
        moneyline = book.get("moneyline") or {}
        if not isinstance(moneyline, Mapping):
            raise ValueError(
                f"book {str(book_key)!r} has a 'moneyline' of "
                f"{type(moneyline).__name__}, expected an object with home/away "
                f"prices")
        if moneyline:
            outcomes = [{"name": name, "price": moneyline.get(side)}
                        for side, name in (("home", home), ("away", away))
                        if moneyline.get(side) is not None and name]
            if outcomes:
                markets.append({"key": "h2h", "outcomes": outcomes})
        spread = book.get("spread") or {}
        if not isinstance(spread, Mapping):
            raise ValueError(
                f"book {str(book_key)!r} has a 'spread' of "
                f"{type(spread).__name__}, expected an object with "
                f"home_line/home_price/away_line/away_price")
        if spread:
            outcomes = [{"name": name, "price": spread.get(f"{side}_price"),
                         "point": spread.get(f"{side}_line")}
                        for side, name in (("home", home), ("away", away))
                        if spread.get(f"{side}_price") is not None and name]
            if outcomes:
                markets.append({"key": "spreads", "outcomes": outcomes})
        total = book.get("total") or {}
        if not isinstance(total, Mapping):
            raise ValueError(
                f"book {str(book_key)!r} has a 'total' of "
                f"{type(total).__name__}, expected an object with "
                f"line/over/under")
        if total:
            outcomes = [{"name": label, "price": total.get(field),
                         "point": total.get("line")}
                        for label, field in (("Over", "over"), ("Under", "under"))
                        if total.get(field) is not None]
            if outcomes:
                markets.append({"key": "totals", "outcomes": outcomes})
        if markets:
            bookmakers.append({"key": str(book_key).lower(),
                               "last_update": book.get("last_update"),
                               "markets": markets})
    return {
        "id": game.get("event_id"),
        "commence_time": game.get("commence_time_utc"),
        "home_team": home,
        "away_team": away,
        "bookmakers": bookmakers,
    }


def normalize_odds_payload(payload: Any) -> Tuple[List[Mapping[str, Any]], str]:
    """Any odds payload this project produces -> (raw events list, shape name).

    R29(5b). ``load_odds_packet`` recognised a bare list and four wrapper keys,
    none of which is ``games``, which is what the mlb-game-odds skill emits
    without ``--raw``. The default output therefore fell through to "no
    recognizable events list", and the caller reported the same generic "no
    moneyline matched this game's teams" it reports when a game genuinely has no
    odds posted. A silent fall-through to a neutral 50/50 allocation is a
    correctness gap wearing a missing-data costume.

    Raises ValueError naming the shape it actually found. That error is the
    point: an unrecognised payload must never be indistinguishable from an
    absent market.
    """
    if isinstance(payload, list):
        return list(payload), "raw_events_list"
    if isinstance(payload, Mapping):
        for key in _ODDS_WRAPPER_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return list(value), f"wrapped:{key}"
        games = payload.get("games")
        if isinstance(games, list):
            try:
                events = [_skill_game_to_raw_event(g) for g in games
                          if isinstance(g, Mapping)]
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001
                # The contract of this function is that it raises ValueError and
                # nothing else, because build_slate's Classic path catches only
                # that and an escaping AttributeError is a traceback out of a
                # live build. Anything unforeseen becomes a shape error naming
                # what happened.
                raise ValueError(
                    f"a 'games' entry could not be converted "
                    f"({type(exc).__name__}: {exc})") from exc
            return events, "mlb_game_odds_games"
        raise ValueError(
            "odds payload is a dict with keys "
            f"{sorted(str(k) for k in payload)} and none of them holds an "
            f"events list. Expected a bare the-odds-api events list, one of "
            f"{list(_ODDS_WRAPPER_KEYS)}, or mlb-game-odds' 'games' schema")
    raise ValueError(
        f"odds payload is {type(payload).__name__}, not a list or a dict")


def parse_the_odds_api_totals(
    raw: Sequence[Mapping[str, Any]],
    fetched_at: Optional[str] = None,
    slate_game_times: Optional[Mapping[str, datetime]] = None,
    tolerance_minutes: int = 10,
) -> Dict[str, Any]:
    """Parse a v4 odds response (markets=totals) into odds-gate packet entries.

    Output ``odds_by_game_id`` maps ``AWAY@HOME`` (DK abbreviations) to
    ``{"total", "source", "fetched_at", "books", "commence_time_utc"}``. The
    consensus total is the median across books. Merge each entry under the
    matching game's ``odds`` key in the slate context packet.

    F18. A doubleheader ships two events under one ``AWAY@HOME`` key and this
    dict assignment used to be last-write-wins, so the matinee draftgroup could
    be priced off the night game's total with nothing saying so. The lineups
    feed got leg resolution and the odds packet did not. Both now go through
    ``select_one_leg_per_matchup``: pass ``slate_game_times`` (from
    ``salary_game_times``) and the leg matching the salary file's start wins.
    Without it the earliest leg wins, which is first-wins rather than the
    silent last-wins this replaces. Every other leg is reported in
    ``doubleheader_legs_dropped`` with its own total, and ``legs_by_game_id``
    carries all legs so the second total is visible rather than erased.
    """
    odds_by_game_id: Dict[str, Dict[str, Any]] = {}
    parsed_events: List[Dict[str, Any]] = []
    unmapped: List[str] = []
    for event in raw or []:
        home = team_name_to_dk_abbrev(event.get("home_team"))
        away = team_name_to_dk_abbrev(event.get("away_team"))
        if not home or not away:
            unmapped.append(f"{event.get('away_team')} @ {event.get('home_team')}")
            continue
        game_id = f"{away}@{home}"
        books: Dict[str, float] = {}
        latest_update: Optional[str] = None
        for bookmaker in event.get("bookmakers") or []:
            key = str(bookmaker.get("key") or "").lower()
            for market in bookmaker.get("markets") or []:
                if str(market.get("key")) != "totals":
                    continue
                update = market.get("last_update") or bookmaker.get("last_update")
                if update and (latest_update is None or str(update) > latest_update):
                    latest_update = str(update)
                for outcome in market.get("outcomes") or []:
                    point = outcome.get("point")
                    if point is not None:
                        books[key] = float(point)
                        break
        # Moneylines ride along when the response carries the h2h market. They
        # are what splits a game total into per-team implied totals, which is
        # the whole input to F1. Absent, F1 falls back to an even split, which
        # still prices the game environment and simply does not pick a side.
        moneyline_books: Dict[str, Dict[str, float]] = {"away": {}, "home": {}}
        for bookmaker in event.get("bookmakers") or []:
            key = str(bookmaker.get("key") or "").lower()
            for market in bookmaker.get("markets") or []:
                if str(market.get("key")) != "h2h":
                    continue
                for outcome in market.get("outcomes") or []:
                    side = team_name_to_dk_abbrev(outcome.get("name"))
                    price = outcome.get("price")
                    if price is None or side is None:
                        continue
                    if side == away:
                        moneyline_books["away"][key] = float(price)
                    elif side == home:
                        moneyline_books["home"][key] = float(price)
        moneyline: Dict[str, float] = {}
        for side_key, team_code in (("away", away), ("home", home)):
            prices = moneyline_books[side_key]
            if prices:
                moneyline[team_code] = float(statistics.median(sorted(prices.values())))

        if not books:
            continue
        stamp = fetched_at or latest_update or datetime.now(timezone.utc).isoformat()
        parsed_events.append({
            "game_id": game_id,
            "moneyline": moneyline,
            "total": float(statistics.median(sorted(books.values()))),
            "source": "the-odds-api:" + ",".join(sorted(books)),
            "fetched_at": stamp,
            "books": books,
            "commence_time_utc": event.get("commence_time"),
            "event_id": event.get("id"),
        })

    def _start(entry: Mapping[str, Any]) -> Optional[datetime]:
        try:
            return _parse_utc(entry.get("commence_time_utc"))
        except (TypeError, ValueError):
            return None

    kept, dropped_raw = select_one_leg_per_matchup(
        parsed_events, lambda entry: entry.get("game_id"), _start,
        slate_game_times or {}, tolerance_minutes)

    legs_by_game_id: Dict[str, List[Dict[str, Any]]] = {}
    for entry in parsed_events:
        legs_by_game_id.setdefault(entry["game_id"], []).append(
            {k: v for k, v in entry.items() if k != "game_id"})
    for entry in kept:
        odds_by_game_id[entry["game_id"]] = {
            k: v for k, v in entry.items() if k != "game_id"}
    dropped = [{
        "game_id": record["game_id"],
        "event_id": (record["entry"] or {}).get("event_id"),
        "total": (record["entry"] or {}).get("total"),
        "start_utc": record["start_utc"],
        "reason": record["reason"],
    } for record in dropped_raw]
    return {
        "odds_by_game_id": odds_by_game_id,
        "unmapped_teams": unmapped,
        "doubleheader_legs_dropped": dropped,
        "legs_by_game_id": {k: v for k, v in sorted(legs_by_game_id.items())
                            if len(v) > 1},
    }


# ---------------------------------------------------------------------------
# the-odds-api.com v4: per-event player props -> implied probabilities
# ---------------------------------------------------------------------------

def fetch_the_odds_api_events(api_key: str, date_et: Optional[str] = None, timeout: float = 20.0) -> Dict[str, Any]:
    """List MLB event ids for the ET day (needed for per-event props calls)."""
    start, end = _et_day_utc_bounds(date_et)
    params = {"apiKey": api_key, "dateFormat": "iso", "commenceTimeFrom": start, "commenceTimeTo": end}
    url = f"{THE_ODDS_API_BASE}/sports/baseball_mlb/events?{urllib.parse.urlencode(params)}"
    raw, headers = _http_get_json(url, timeout=timeout, secret=api_key)
    return {"raw": raw, "quota": {
        "remaining": headers.get("x-requests-remaining"),
        "used": headers.get("x-requests-used"),
    }}


def fetch_the_odds_api_event_props(
    api_key: str,
    event_id: str,
    markets: str = "batter_home_runs",
    regions: str = "us",
    bookmakers: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Fetch player props for one event. Cost: markets x regions PER EVENT.

    A 12-game slate with one market and one region costs ~12 credits, so on
    the free 500/month plan treat props as an occasional research pull, not a
    daily default. Use estimate_the_odds_api_props_cost() before fetching.
    """
    params: Dict[str, str] = {
        "apiKey": api_key, "markets": markets, "oddsFormat": "american", "dateFormat": "iso",
    }
    if bookmakers:
        params["bookmakers"] = bookmakers
    else:
        params["regions"] = regions
    url = f"{THE_ODDS_API_BASE}/sports/baseball_mlb/events/{urllib.parse.quote(str(event_id))}/odds?{urllib.parse.urlencode(params)}"
    raw, headers = _http_get_json(url, timeout=timeout, secret=api_key)
    return {"raw": raw, "quota": {
        "remaining": headers.get("x-requests-remaining"),
        "used": headers.get("x-requests-used"),
    }}


def estimate_the_odds_api_props_cost(n_events: int, n_markets: int = 1, n_regions: int = 1) -> int:
    return max(0, int(n_events)) * max(1, int(n_markets)) * max(1, int(n_regions))


def american_to_implied_prob(price: float) -> float:
    value = float(price)
    if value > 0:
        return 100.0 / (value + 100.0)
    if value < 0:
        return -value / (-value + 100.0)
    raise ValueError("american odds of 0 are undefined")


def vig_free_probabilities(prob_a: float, prob_b: float) -> Tuple[float, float]:
    total = float(prob_a) + float(prob_b)
    if total <= 0:
        raise ValueError("probabilities must be positive")
    return float(prob_a) / total, float(prob_b) / total


def parse_the_odds_api_event_props(raw_event: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Flatten one event-odds response into prop rows with implied probabilities."""
    rows: List[Dict[str, Any]] = []
    home = team_name_to_dk_abbrev(raw_event.get("home_team"))
    away = team_name_to_dk_abbrev(raw_event.get("away_team"))
    game_id = f"{away}@{home}" if home and away else ""
    for bookmaker in raw_event.get("bookmakers") or []:
        book = str(bookmaker.get("key") or "").lower()
        for market in bookmaker.get("markets") or []:
            market_key = str(market.get("key") or "")
            for outcome in market.get("outcomes") or []:
                price = outcome.get("price")
                if price is None:
                    continue
                rows.append({
                    "event_id": raw_event.get("id"),
                    "game_id": game_id,
                    "market": market_key,
                    "player": str(outcome.get("description") or outcome.get("name") or ""),
                    "book": book,
                    "side": str(outcome.get("name") or ""),
                    "point": outcome.get("point"),
                    "price_american": float(price),
                    "implied_prob": round(american_to_implied_prob(float(price)), 6),
                })
    return rows


def build_props_implied_table(
    rows: Sequence[Mapping[str, Any]],
    salary_players: Any = None,
) -> List[Dict[str, Any]]:
    """Per (player, market): best Over/Yes implied probability, vig-free when paired.

    The vig-free probability normalizes the SAME book's Over/Under pair at the
    same point. Output is a deterministic research table for F3/F4/right-tail
    tags; it is not an ownership model and not a win-rate claim.
    """
    players = _load_salary_players(salary_players) if salary_players is not None else {}
    salary_by_name: Dict[str, List[str]] = {}
    for pid, record in players.items():
        salary_by_name.setdefault(normalize_name(_record_get(record, "name")), []).append(str(pid))

    over_sides = {"over", "yes"}
    under_sides = {"under", "no"}
    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for row in rows:
        key = (normalize_name(row.get("player")), str(row.get("market") or ""))
        grouped.setdefault(key, []).append(row)

    table: List[Dict[str, Any]] = []
    for (player_norm, market), group in sorted(grouped.items()):
        best: Optional[Mapping[str, Any]] = None
        for row in group:
            if str(row.get("side") or "").lower() in over_sides:
                if best is None or float(row["implied_prob"]) < float(best["implied_prob"]):
                    best = row  # lowest implied = best price on the Over
        if best is None:
            continue
        vig_free = None
        for row in group:
            same_book = row.get("book") == best.get("book")
            same_point = row.get("point") == best.get("point")
            if same_book and same_point and str(row.get("side") or "").lower() in under_sides:
                vig_free = round(vig_free_probabilities(float(best["implied_prob"]), float(row["implied_prob"]))[0], 6)
                break
        matches = salary_by_name.get(player_norm, [])
        table.append({
            "player": best.get("player"), "market": market, "game_id": best.get("game_id"),
            "best_over_book": best.get("book"), "point": best.get("point"),
            "best_over_price_american": best.get("price_american"),
            "implied_prob": best.get("implied_prob"),
            "vig_free_prob": vig_free,
            "dk_player_id": matches[0] if len(matches) == 1 else None,
        })
    return table


# ---------------------------------------------------------------------------
# odds-api.io v3: HR props (decimal odds), tolerant parser
# ---------------------------------------------------------------------------

def decimal_to_implied_prob(price_decimal: float) -> float:
    value = float(price_decimal)
    if value <= 1.0:
        raise ValueError("decimal odds must exceed 1.0")
    return 1.0 / value


def parse_odds_api_io_hr_props(payload: Any) -> List[Dict[str, Any]]:
    """Flatten odds-api.io event odds into HR prop rows.

    odds-api.io's docs do not publish baseball prop response examples, so this
    parser is deliberately tolerant about where the player name and prices
    live (mirrors the discovery-first approach in the mlb-hr-prop-arb skill).
    Run that skill's ``--discover`` mode once per account to confirm shapes;
    if a field moves, the row simply carries what was found.
    Bookmaker names on odds-api.io are case-sensitive (Bet365, DraftKings,
    Fanatics). Rate limit: 5,000 requests/hour on all plans.
    """
    events = payload.get("events") if isinstance(payload, Mapping) else payload
    if isinstance(events, Mapping):
        events = list(events.values())
    rows: List[Dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        event_id = event.get("id") or event.get("eventId") or event.get("event_id")
        bookmakers = event.get("bookmakers") or event.get("books") or []
        if isinstance(bookmakers, Mapping):
            bookmakers = [{"name": name, **(value if isinstance(value, Mapping) else {"markets": value})}
                          for name, value in bookmakers.items()]
        for bookmaker in bookmakers:
            book = str(bookmaker.get("name") or bookmaker.get("bookmaker") or bookmaker.get("key") or "")
            markets = bookmaker.get("markets") or bookmaker.get("odds") or []
            for market in markets if isinstance(markets, list) else []:
                if not isinstance(market, Mapping):
                    continue
                market_name = str(market.get("name") or market.get("market") or market.get("key") or "")
                if "home run" not in market_name.lower():
                    continue
                market_player = str(market.get("label") or market.get("player") or "").strip()
                outcomes = market.get("odds") or market.get("outcomes") or market.get("selections") or []
                for outcome in outcomes if isinstance(outcomes, list) else []:
                    if not isinstance(outcome, Mapping):
                        continue
                    price = outcome.get("price") or outcome.get("odds") or outcome.get("decimal")
                    if price is None:
                        continue
                    side = str(outcome.get("label") or outcome.get("name") or outcome.get("selection") or "")
                    player = market_player or str(outcome.get("player") or outcome.get("participant") or "").strip()
                    point = outcome.get("point", outcome.get("line", outcome.get("handicap", 0.5)))
                    try:
                        implied = round(decimal_to_implied_prob(float(price)), 6)
                    except (TypeError, ValueError):
                        continue
                    rows.append({
                        "event_id": event_id, "market": market_name, "player": player,
                        "book": book, "side": side, "point": point,
                        "price_decimal": float(price), "implied_prob": implied,
                    })
    return rows
