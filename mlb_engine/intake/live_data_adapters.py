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

import collections
import json
import math
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
from mlb_engine.intake.slate_intake_manager import (
    DK_ORDER_SLOTS, normalize_name)
# R289: the ONE reading of the Excluded column, imported rather than restated.
# The front door decides pool MEMBERSHIP, so a second token rule here would be
# the F21 defect in the one place it costs the most.
from mlb_engine.optimize.optimizer_v3 import read_excluded_cell

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
#
# R323, third limit and the one this module got wrong for a month: a DK
# draftable id is a ROLE, not a person. A Showdown export prices everybody
# twice, so a complete nine arrives as EIGHTEEN order tokens and the
# two-people-on-one-slot guard below -- correct on a Classic file -- discarded
# both sides of a fully posted single game. The rows are collapsed to PERSONS
# before the completeness test now, through the one collapse
# (`slate_intake_manager.collapse_showdown_roles`) and the one predicate
# (`posted_order_completeness`) the Showdown pool also calls. `DK_ORDER_SLOTS`
# moved to that module for the same reason and is imported above.


def dk_side_readings(salary_players: Any) -> Dict[str, Dict[str, Any]]:
    """DK team -> ONE reading of what the ``Starting`` column posted for it.

    ``{"order": [slot rows 1-9], "shelved": [the rows DK marks OUT],
    "state": "confirmed" | "degraded"}``. A team appears only when the column
    supplies every slot 1 through 9 exactly once; anything short of that is a
    partial posting and is not a reading of a posted side at all.

    R159(a). ``state`` is the distinction that did not exist. ``dk_order_coverage``
    read the RAW salary rows and the pool's merge read the status-FILTERED map,
    so a single ``Status=IL`` flip inside a posted nine left the team "covered"
    (fetch skipped, empty feed) while the merge saw eight slots, refused the side
    outright, and dropped the whole posted lineup to ``fallback_top9_appg`` — plus
    the team's ``Starting=SP`` arm, which only ever got attached to a side the
    merge accepted. Repro'd 2026-08-22 and again at this head: coverage
    ``(['BOS','NYY'], [])`` against a pool reporting ``NYY: fallback_top9_appg 9``.
    A shelved player inside an otherwise-complete side is now DEGRADED, which is
    neither "confirmed" nor "never posted": the surviving eight are observed fact
    and R60's partial path already knows how to seed them.

    Reads status off the row, so passing a map a caller already status-filtered
    yields exactly the previous behaviour (the shelved row is simply absent and
    the side is incomplete). Passing the RAW rows is what earns the degraded
    reading, which is why the front door now passes them.
    """
    readings = dk_posted_order_readings(salary_players)
    out: Dict[str, Dict[str, Any]] = {}
    for team, reading in readings.items():
        if reading["state"] not in ("confirmed", "degraded"):
            continue
        out[team] = {"order": reading["order"], "shelved": reading["shelved"],
                     "state": reading["state"], "event": reading["event"]}
    return out


def dk_posted_order_readings(salary_players: Any) -> Dict[str, Dict[str, Any]]:
    """DK team -> the full per-side reading, malformed and partial sides included.

    R323. The reading itself, before ``dk_side_readings`` throws away the two
    states it does not use. Three things happen here and nowhere else:

    * roles are collapsed to PERSONS through ``collapse_showdown_roles``, the
      collapse R235 already shipped -- whose own docstring names this defect --
      so a Showdown side's eighteen order tokens are nine claims. It no-ops on a
      Classic file (``applied`` False) and it is idempotent, so a caller that
      collapsed first pays nothing;
    * a person whose CPT and UTIL rows DISAGREE about team, position or
      ``Starting``, and a person whose name is ambiguous on his own team (R75),
      poisons his side: ``malformed``, never confirmed. He is only counted
      against the side he actually claims a batting slot on, so a duplicate-named
      bench bat cannot invalidate a nine that is otherwise clean;
    * the completeness test itself is ``posted_order_completeness``, the one
      predicate the Showdown pool's participation reading also calls.

    Keyed by TEAM, because every caller is, and every DK draftgroup ships one leg
    of a doubleheader (CLAUDE.md's build contract). A team that somehow appears
    under two DK game ids is therefore not a lineup either, and reads
    ``malformed`` rather than having one of its two events silently win.
    """
    from mlb_engine.intake.slate_intake_manager import (
        collapse_showdown_roles, posted_order_completeness, salary_status_tier,
        showdown_person_key)

    players = _load_salary_players(salary_players)
    records = list(players.values())
    collapsed, collapse_report = collapse_showdown_roles(records)
    ids_by_person: Dict[str, set] = {}
    for pid, record in players.items():
        key = showdown_person_key(_record_get(record, "name"),
                                  _record_get(record, "team"))
        ids_by_person.setdefault(key, set()).add(str(pid))
    poisoned = {str(entry.get("person_key") or "")
                for entry in (collapse_report.get("unpaired") or [])}

    slots: List[Dict[str, Any]] = []
    for record in collapsed:
        team = str(_record_get(record, "team") or "").strip().upper()
        if not team:
            continue
        person = showdown_person_key(_record_get(record, "name"), team)
        status = str(_record_get(record, "status") or "").strip().upper()
        pid = str(_record_get(record, "player_id") or "")
        slots.append({
            "event": str(_record_get(record, "game_id") or "").strip().upper(),
            "team": team, "person_key": person,
            "order": str(_record_get(record, "starting") or "").strip(),
            "name": str(_record_get(record, "name") or ""),
            "dk_id": pid,
            "dk_ids": tuple(sorted(ids_by_person.get(person) or {pid})),
            "status": status, "shelved": salary_status_tier(status) == "out",
            "ambiguous": person in poisoned,
        })
    per_side = posted_order_completeness(slots)
    events_by_team: Dict[str, set] = {}
    for event, team in per_side:
        events_by_team.setdefault(team, set()).add(event)
    out: Dict[str, Dict[str, Any]] = {}
    for (event, team), reading in sorted(per_side.items()):
        if len(events_by_team.get(team) or ()) > 1:
            reading = dict(reading)
            reading.update({"state": "malformed", "complete": False,
                            "order": [], "shelved": []})
        if team in out and out[team]["state"] in ("confirmed", "degraded"):
            continue
        out[team] = reading
    return out


def dk_confirmed_sides(salary_players: Any) -> Dict[str, List[Dict[str, Any]]]:
    """DK team -> its batting order from the salary file, complete sides only.

    A side is returned only when the ``Starting`` column supplies every slot 1
    through 9 exactly once AND no slot holds a player DK marks OUT. Anything
    short of that is a partial posting and is not a confirmed lineup, so it is
    not returned at all. See ``dk_side_readings`` for the degraded case.
    """
    return {team: reading["order"]
            for team, reading in dk_side_readings(salary_players).items()
            if reading["state"] == "confirmed"}


# SP/P only. PO is an opener and R104 settled that he is not a declared
# starter; PLR is a projected long reliever and CLAUDE.md makes rostering one an
# explicit call, not something a merge decides on a team's behalf. Neither
# belongs in an automatic probable.
DK_STARTING_PROBABLE_TOKENS = frozenset({"SP", "P"})


def dk_declared_probables(salary_players: Any) -> Dict[str, str]:
    """DK team -> Player_ID of the arm DK's ``Starting`` column marks SP/P.

    A shelved arm is never a probable, whatever the ``Starting`` column says.
    The status read lives here rather than in the caller because since R159(a)
    the front door hands this function the RAW salary rows, and a rule that
    depends on which map a caller happened to pass is the defect R159(a) is.
    """
    from mlb_engine.intake.slate_intake_manager import (
        collapse_showdown_roles, salary_status_tier)

    players = _load_salary_players(salary_players)
    # R323, N+1 of the entry's own enumeration. This loop takes the FIRST id by
    # sort order, and on a Showdown export the declared arm owns two -- so the
    # probable it wrote into the feed was whichever ROLE happened to sort first,
    # usually the CPT row, a draftable nobody else in the pipeline keys on. The
    # collapse keeps the UTIL row, which is the person's base price and the id
    # every other reader means. No-op on a Classic file.
    collapsed, collapse_report = collapse_showdown_roles(list(players.values()))
    if collapse_report.get("applied"):
        players = {str(_record_get(r, "player_id")): r for r in collapsed}
    out: Dict[str, str] = {}
    for pid, record in sorted(players.items(), key=lambda kv: str(kv[0])):
        team = str(_record_get(record, "team") or "").strip().upper()
        token = str(_record_get(record, "starting") or "").strip().upper()
        if salary_status_tier(_record_get(record, "status")) == "out":
            continue
        if team and token in DK_STARTING_PROBABLE_TOKENS and team not in out:
            out[team] = str(pid)
    return out


def dk_order_coverage_report(salary_csv: str | Path) -> Dict[str, Any]:
    """The full coverage reading: covered, degraded, uncovered, from ONE input.

    R159(a). ``covered`` is a side this build can source from DK and skip the
    fetch for. ``degraded`` is a side DK posted a complete nine for with a
    shelved player in it: covered-but-degraded, which counts as NOT covered for
    the fetch decision (the ninth slot has to come from somewhere) and is named
    rather than folded into "DK has not posted this team". ``uncovered`` is the
    rest. The three lists partition the slate's teams.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    rows = parse_dk_salary_csv(str(salary_csv))
    readings = dk_posted_order_readings({p.player_id: p for p in rows})
    covered = {t for t, r in readings.items() if r["state"] == "confirmed"}
    degraded = {t for t, r in readings.items() if r["state"] == "degraded"}
    malformed = {t for t, r in readings.items() if r["state"] == "malformed"}
    teams = {str(p.team).strip().upper() for p in rows if p.team}
    return {
        "covered": sorted(covered),
        "degraded": sorted(degraded),
        "uncovered": sorted(teams - covered - degraded),
        # R323. A side whose rows contradict each other is NOT the same fact as
        # a side DK has not posted, and reporting only the second is how a
        # malformed Showdown file read as "no lineups feed resolved". It stays
        # inside `uncovered` so the three lists still partition the slate.
        "malformed": sorted(malformed),
        "malformed_detail": [
            {"team": t, "reason": readings[t]["state"],
             "duplicate_slots": readings[t]["duplicate_slots"],
             "ambiguous": readings[t]["ambiguous"],
             "missing": readings[t]["missing"]}
            for t in sorted(malformed)
        ],
        "degraded_detail": [
            {"team": t,
             "shelved": [{"order": s["order"], "name": s["name"],
                          "dk_id": s["dk_id"], "status": s["status"]}
                         for s in readings[t]["shelved"]]}
            for t in sorted(degraded)
        ],
    }


def dk_order_coverage(salary_csv: str | Path) -> Tuple[List[str], List[str]]:
    """(teams DK has posted a usable full 1-9 for, teams it has not).

    One definition of "covered", shared by the pool and by any caller deciding
    whether a fetch is worth making, so the build cannot skip a fetch on one
    rule and then find the pool applying another. A DEGRADED side (nine slots
    posted, one of them shelved) is reported as NOT covered here, because the
    fetch it would otherwise skip is the only thing that can fill the ninth
    slot. ``dk_order_coverage_report`` separates the two.
    """
    report = dk_order_coverage_report(salary_csv)
    return report["covered"], sorted(report["degraded"] + report["uncovered"])


def _note_hands(report: Dict[str, Any], team: str,
                merged: Sequence[Mapping[str, Any]]) -> None:
    """R159(d). How many of this side's hitters kept a bat side, per side.

    ``f4_handedness_unavailable`` fires only when a side loses ALL of its hands,
    so three-of-nine lost was invisible -- and R151's post-mortem records ten
    hitters losing both F4 terms on one slate with that list still empty. A side
    that is missing SOME hands is a different fact from a side missing all of
    them and is now named as one, with the count.
    """
    present = sum(1 for h in merged if h.get("bat_side"))
    if present == 0:
        report["f4_handedness_unavailable"].append(team)
    elif present < len(merged):
        report["f4_handedness_partial"].append(
            {"team": team, "hands_present": present, "of": len(merged)})


def _side_is_complete(side: Mapping[str, Any]) -> bool:
    """R219. Does this feed side already hold a lineup that outranks DK's eight?

    R143's rule is "only a COMPLETE 1-9 counts", and R159(a) applies it to the
    degraded case: a source holding a complete nine outranks eight-of-nine. The
    guard that shipped asked ``if side.get("lineup")`` -- ANY nonempty list --
    so a one-to-three-hitter mid-repost API partial won, DK's eight observed,
    ``Player_ID``-keyed slots were discarded, and five seats filled from priors
    while both routes ended labelled "partial". Completeness is the order SET
    equalling ``range(1, 10)`` (the outside spec's predicate, D07), not a row
    count: nine rows numbered 1,1,2,... is not a lineup. A side the feed itself
    calls ``confirmed`` also counts, because that label is the feed asserting the
    side is posted and the confirmed path elsewhere already trusts it.

    And an OPERATOR PASTE side counts at any length, which is the one place this
    predicate is deliberately looser than "complete". R32 ranks a lineup Ben
    pastes above any API pull and R143 narrowed that to "behind a COMPLETE DK
    1-9" -- neither says what happens when DK's side is degraded and the paste is
    short, and a paste is short for its own reasons (a `1. TBD` positional hold,
    or R133's starter DK never listed, both of which leave the side ``partial``).
    Ranking DK's eight over a paste's eight would extend a rule Ben wrote,
    silently, in a fix aimed at a mid-repost API partial. It stays where he put
    it; the DK-vs-paste question for two incomplete sides is his.
    """
    rows = side.get("lineup") or []
    if not rows:
        return False
    if str(side.get("lineup_status") or "").strip().lower() == "confirmed":
        return True
    if str(side.get("source") or "").strip().lower() == "operator_paste":
        return True
    orders = {row.get("order") for row in rows if isinstance(row, dict)}
    return orders == set(range(1, DK_ORDER_SLOTS + 1))


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
    resolved), ``degraded_sides`` (R159(a): a posted nine holding a shelved
    player, seeded as a PARTIAL rather than discarded, each record carrying the
    R219 ``resolution``: ``seeded`` | ``deferred_to_feed`` | ``all_shelved`` |
    ``no_game``),
    ``f4_handedness_unavailable``, ``f4_handedness_partial`` (R159(d)) and
    ``sides_left_to_feed``.
    """
    players = _load_salary_players(salary_players)
    readings = dk_side_readings(players)
    sides = {t: r["order"] for t, r in readings.items()
             if r["state"] == "confirmed"}
    # R159(a). A posted nine with a shelved player in it: the surviving eight
    # are observed fact, so they are seeded as a partial and routed through
    # R60's path instead of the whole side being thrown away.
    degraded = {t: [row for row in r["order"] if not row["shelved"]]
                for t, r in readings.items() if r["state"] == "degraded"}
    probables = dk_declared_probables(players)
    out_feed: Dict[str, Any] = dict(feed or {})
    games = [dict(g) for g in (out_feed.get("games") or [])]
    report: Dict[str, Any] = {
        "dk_sides": sorted(sides), "upgraded": [], "disagreements": [],
        "f4_handedness_unavailable": [], "f4_handedness_partial": [],
        "sides_left_to_feed": [], "degraded_sides": [
            # R219. `resolution` is filled in below, once the loops have run: it
            # is what the merge DID with this side, and without it every consumer
            # had to assume "seeded" -- which the pool report duly asserted on
            # sides that were deferred, or that had nothing left to seed.
            {"team": t, "posted": len(degraded[t]),
             "shelved": [{"order": s["order"], "name": s["name"],
                          "dk_id": s["dk_id"], "status": s["status"]}
                         for s in readings[t]["shelved"]],
             "resolution": "no_game"}
            for t in sorted(degraded)
        ],
        "probables_attached": [], "games_synthesized": [],
        "games_unsynthesizable": [], "source": "dk_salary_starting",
    }
    if not sides and not degraded and not probables:
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

    def _probable_payload(team: str) -> Dict[str, Any]:
        """R159(b). A DK-declared probable needs a NAME, not only a DK id.

        The merge used to write ``{"dk_id": ...}`` and nothing else. The status
        map reads either (R143), but ``extract_opposing_probables`` requires
        ``.get("name")``, so on the no-fetch path every DK-declared arm was
        invisible to it, ``opposing_probables`` came back EMPTY, and the F4
        quality term went neutral for every hitter on the slate while the only
        warning blamed a missing probable. DK ships no MLBAM id, so ``id`` stays
        absent and ``compute_f4_factors`` resolves the Savant join by name
        (R189(2)) instead of silently scoring 1.0.
        """
        dk_id = probables[team]
        record = players.get(dk_id) or players.get(str(dk_id)) or {}
        return {"dk_id": str(dk_id),
                "name": str(_record_get(record, "name") or ""),
                "source": "dk_salary_starting"}

    def _attach_probable(side: Dict[str, Any], team: str) -> None:
        if probables.get(team) and not side.get("probable_pitcher"):
            side["probable_pitcher"] = _probable_payload(team)
            report["probables_attached"].append(team)

    covered: set = set()
    # R219. Teams whose degraded side lost to a source already holding a complete
    # nine. It is the one resolution that cannot be derived from `covered` after
    # the fact, so the loop records it and the rest is derived below.
    deferred_to_feed: set = set()
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
            _note_hands(report, team, merged)
            side["lineup"] = merged
            side["lineup_status"] = "confirmed"
            side["lineup_source"] = "dk_salary_starting"
            _attach_probable(side, team)
            game[key] = side

        # R159(a). The degraded side, in the feed. DK's eight are seeded ONLY
        # where nothing else has the side: a source holding a complete nine
        # outranks eight-of-nine, which is R143's own rule ("only a COMPLETE 1-9
        # counts") applied to the case that rule did not anticipate.
        #
        # R219. "Nothing else has the side" was written as `if side.get("lineup")`,
        # which is any nonempty list -- so a one-to-three-hitter mid-repost API
        # partial outranked DK's eight OBSERVED, Player_ID-keyed slots and five
        # seats filled from priors instead. `_side_is_complete` is the same
        # predicate R143 states, applied here: a COMPLETE 1-9, or a side the feed
        # itself calls confirmed. Anything short of that is a projection and loses
        # to eight observed slots, exactly as R159(a)'s comment intends.
        for team, order in degraded.items():
            key = _side_of(game, team)
            if key is None:
                continue
            side = dict(game.get(key) or {})
            if _side_is_complete(side):
                _attach_probable(side, team)
                game[key] = side
                deferred_to_feed.add(team)
                continue
            # R220(c). An all-nine-shelved side leaves NOTHING to seed. It used
            # to seed `lineup=[]`, count as covered, and fire
            # `f4_handedness_unavailable` through `_note_hands` on a side that
            # holds no hitters -- a report about a lineup that does not exist.
            if not order:
                continue
            covered.add(team)
            side["lineup"] = [{"order": h["order"], "name": h["name"],
                               "dk_id": h["dk_id"], "bat_side": ""}
                              for h in order]
            side["lineup_status"] = "partial"
            side["lineup_source"] = "dk_salary_starting_degraded"
            _attach_probable(side, team)
            _note_hands(report, team, side["lineup"])
            game[key] = side

    # Games DK posted that the feed never mentioned: build them from salary.
    # Every team DK says something about gets a pass here, not only the teams
    # with a confirmed side -- R159(c): a team with `Starting=SP` and no
    # complete 1-9 used to get its probable merged NOWHERE, because the only
    # code that attached one ran inside the confirmed-side loop.
    for team in sorted(set(sides) | set(degraded) | set(probables)):
        if team in covered:
            continue
        order = sides.get(team) or degraded.get(team) or []
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
            if start is None:
                # R160. A game whose salary Game Info parses as a matchup but
                # not a time (real on DH game 2s: "BOS@NYY 08/17/2026 TBD") used
                # to be synthesized with an empty `game_date_utc`, and the very
                # next read -- the status map's unguarded `_parse_utc("")` --
                # took the front door down with `ValueError: Invalid isoformat
                # string: ''`, a traceback where a blocker belonged. A game with
                # no start time has no lock time, so it is not synthesized at
                # all: the side is left to the feed and NAMED here.
                #
                # R220(b). This loop walks TEAMS, and the fact is about a GAME,
                # so a DH game 2 with DK data on both sides emitted the record
                # twice and the pool blocked twice on one game. Keyed by gid,
                # carrying every team that reached it: one record per game, and
                # the teams are what the operator needs named.
                existing = next((r for r in report["games_unsynthesizable"]
                                 if r["game_id"] == gid), None)
                if existing is None:
                    report["games_unsynthesizable"].append(
                        {"game_id": gid, "teams": [team],
                         "reason": "no parseable start time in the salary Game Info"})
                elif team not in existing["teams"]:
                    existing["teams"] = sorted(existing["teams"] + [team])
                continue
            game = {"game_pk": None, "venue": None, "status": "Scheduled",
                    "game_date_utc": start.astimezone(timezone.utc).isoformat(),
                    "away": {"team_abbrev": away}, "home": {"team_abbrev": home}}
            games.append(game)
            report["games_synthesized"].append(gid)
        key = "away" if team == away else "home"
        side = dict(game.get(key) or {})
        side["team_abbrev"] = team
        if order and not side.get("lineup"):
            side["lineup"] = [{"order": h["order"], "name": h["name"],
                               "dk_id": h["dk_id"], "bat_side": ""} for h in order]
            side["lineup_status"] = ("confirmed" if team in sides else "partial")
            side["lineup_source"] = ("dk_salary_starting" if team in sides
                                     else "dk_salary_starting_degraded")
            _note_hands(report, team, side["lineup"])
            covered.add(team)
        _attach_probable(side, team)
        game[key] = side

    report["upgraded"] = sorted(set(report["upgraded"]))
    report["probables_attached"] = sorted(set(report["probables_attached"]))
    report["f4_handedness_unavailable"] = sorted(
        set(report["f4_handedness_unavailable"]))
    report["f4_handedness_partial"] = sorted(
        report["f4_handedness_partial"], key=lambda r: r["team"])
    report["sides_left_to_feed"] = sorted(set(team_game) - covered)
    # R219. What the merge actually DID with each degraded side, in one place and
    # derived from what happened rather than tracked at four sites. Precedence:
    # nothing survived to seed outranks everything (neither claim applies);
    # `covered` is the merge's own record that it seeded the surviving rows, on
    # whichever of the two loops did it; a deferral is the loop's explicit note;
    # and a side that reached neither had no game to attach to.
    for rec in report["degraded_sides"]:
        team = rec["team"]
        if not degraded.get(team):
            rec["resolution"] = "all_shelved"
        elif team in covered:
            rec["resolution"] = "seeded"
        elif team in deferred_to_feed:
            rec["resolution"] = "deferred_to_feed"
        else:
            rec["resolution"] = "no_game"
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
    games_without_lock_time: List[Dict[str, str]] = []
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
        # R220(a). The postponed/cancelled/suspended read used to sit BELOW the
        # lock-time parse, past the `continue` that skips a game with no parseable
        # time -- so a postponed game with a malformed `game_date_utc` was named
        # as a game needing "a real start time" instead of being excluded as
        # postponed, and the operator got a blocker that nothing they can do to
        # the slate makes go away. A postponed game has no lock time because it
        # is not being played; that is the fact, and it is read first.
        state = str(game_entry.get("status") or "").strip().lower()
        excluded = ("postpon" in state or "cancel" in state or "suspend" in state)
        if excluded:
            excluded_game_ids.append(game_id)
        # R160. `_parse_utc` was called unguarded here, so any feed carrying a
        # game with a missing or malformed `game_date_utc` took the front door
        # down with `ValueError: Invalid isoformat string: ''` instead of
        # producing a blocker. The merge no longer synthesizes such a game, but
        # the guard belongs at the READ as well: the merge is one of several
        # feed sources and a crash here is a lost build window whichever one
        # supplied it. A game with no lock time cannot be late-swap-checked, so
        # it is named and skipped rather than admitted with a guessed time.
        try:
            lock_time = _parse_utc(game_entry.get("game_date_utc"))
        except (TypeError, ValueError):
            if not excluded:
                games_without_lock_time.append(
                    {"game_id": game_id,
                     "game_date_utc": str(game_entry.get("game_date_utc") or ""),
                     "reason": "unparseable game_date_utc; no lock time can be derived"})
            continue
        lock_time_by_game_id[game_id] = lock_time
        game_meta[game_id] = {
            "game_pk": game_entry.get("game_pk"),
            "venue": game_entry.get("venue"),
            "status": game_entry.get("status"),
            "lock_time_utc": lock_time.isoformat(),
        }

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
        "games_without_lock_time": sorted(games_without_lock_time,
                                          key=lambda r: r["game_id"]),
        "doubleheader_legs_dropped": doubleheader_legs_dropped,
        "feed_date": feed.get("date"),
        "feed_fetched_at": feed.get("fetched_at"),
    }


# ---------------------------------------------------------------------------
# R270(b): the OBSERVED-FACT tier, which outranks all three sources above
# ---------------------------------------------------------------------------
# The schedule hydrate stops carrying a game's lineup once that game is in
# progress, so every "confirmed" test against the feed SILENTLY DEGRADES to
# "not posted" for exactly the games whose answer is now certain. On
# `1305_12g` that is how a dead bat (Nootbaar) survived a preflight that was
# reading his side as unposted.
#
# The ranking this adds to R143's line, and the reason it sits at the top:
# DK's `Starting` column, an operator paste and the schedule API are all
# PREDICTIONS of who will play. A boxscore is a RECORD of who did. Once a game
# is underway the prediction cannot improve and the record cannot be wrong, so
# the record wins for that game and only for that game -- a Preview game has no
# boxscore and this tier says nothing about it, which is the whole point of
# `observed_starter_state` returning a third value rather than a bool.
#
# Name normalisation is SHARED, not reimplemented: `normalize_name` is the
# same function `build_player_lineup_status` uses for this identical DK-salary
# join (see `match_dk_id` above), so the observed tier and the feed tier cannot
# disagree about who "Acuna" is. R270(b) named `preflight_upload._norm_name`
# as the thing to share; that copy is equivalent on the accented cases but it
# lives in a TOOL, and an engine module importing a tool inverts the dependency
# -- so the share is the engine's own, which the join it has to agree with
# already uses. Reimplementing either is how the R248 crosswalk got two copies.
BOXSCORE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# `abstractGameState` values that mean first pitch has happened. Preview is the
# only state that means it has not; anything unrecognised is treated as NOT
# started, because a boxscore read out of an unknown state is a guess wearing
# an observation's label.
BOXSCORE_STARTED_STATES = ("Live", "Final")


def boxscore_url(game_pk: Any) -> str:
    """The `/feed/live` URL for one game. One place, so a caller that fetches
    and a test that fixtures cannot drift on the path."""
    return BOXSCORE_FEED_URL.format(game_pk=str(game_pk).strip())


def boxscore_urls_for_feed(
    feed: Mapping[str, Any],
    salary_game_times: Optional[Mapping[str, datetime]] = None,
) -> Dict[str, str]:
    """DK ``game_id -> boxscore URL`` for the games on this slate.

    Goes through ``_legs_for_extraction``, so a doubleheader contributes the
    SLATE's leg and not the other one -- the same leg filter every other reader
    of the hydrated schedule uses (R58/R270(a)). A game with no ``game_pk`` is
    omitted rather than given a guessed one.
    """
    out: Dict[str, str] = {}
    for game_entry in _legs_for_extraction(feed, salary_game_times):
        away = to_dk_abbrev((game_entry.get("away") or {}).get("team_abbrev"))
        home = to_dk_abbrev((game_entry.get("home") or {}).get("team_abbrev"))
        game_pk = game_entry.get("game_pk")
        if not (away and home) or game_pk in (None, ""):
            continue
        out[f"{away}@{home}"] = boxscore_url(game_pk)
    return out


def _boxscore_person_names(side: Mapping[str, Any],
                           game_data: Mapping[str, Any]) -> Dict[str, str]:
    """MLBAM id (as str) -> full name, from the boxscore's own player block,
    falling back to ``gameData.players``. Both are keyed ``ID<mlbam>``."""
    names: Dict[str, str] = {}
    for block in ((game_data.get("players") or {}), (side.get("players") or {})):
        if not isinstance(block, Mapping):
            continue
        for key, entry in block.items():
            if not isinstance(entry, Mapping):
                continue
            person = entry.get("person") or entry
            mlbam = str(person.get("id") or str(key).replace("ID", "")).strip()
            full = str(person.get("fullName") or "").strip()
            if mlbam and full:
                names[mlbam] = full
    return names


def parse_boxscore_feed(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """One game's ``/feed/live`` -> who ACTUALLY batted and who ACTUALLY started.

    ``liveData.boxscore.teams.<side>.battingOrder`` is the observed 1-9 and
    ``.pitchers[0]`` is the arm that threw the first pitch. Returns::

        {"game_pk", "game_id", "abstract_state", "detailed_state", "started",
         "sides": {"away"|"home": {"team": DK abbrev,
                                   "batting_order": [{"mlbam", "name", "order"}],
                                   "starting_pitcher": {"mlbam", "name"} | None}}}

    ``started`` is False for a Preview game and for any payload whose state is
    unreadable, and a not-started game returns EMPTY sides even when the
    boxscore block is present -- a pre-game boxscore carries an empty or
    provisional order, and reading it would put a prediction into the tier
    whose entire claim is that it holds observations.
    """
    game_data = payload.get("gameData") or {}
    live_data = payload.get("liveData") or {}
    status = game_data.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").strip()
    detailed = str(status.get("detailedState") or "").strip()
    game_pk = (game_data.get("game") or {}).get("pk", payload.get("gamePk"))

    teams_meta = game_data.get("teams") or {}
    box_teams = (live_data.get("boxscore") or {}).get("teams") or {}
    started = abstract in BOXSCORE_STARTED_STATES

    sides: Dict[str, Dict[str, Any]] = {}
    abbrevs: Dict[str, str] = {}
    for side_key in ("away", "home"):
        meta = teams_meta.get(side_key) or {}
        dk_team = to_dk_abbrev(meta.get("abbreviation") or "") or team_name_to_dk_abbrev(
            str(meta.get("name") or ""))
        abbrevs[side_key] = dk_team
        side = box_teams.get(side_key) or {}
        entry: Dict[str, Any] = {"team": dk_team, "batting_order": [],
                                 "starting_pitcher": None}
        if started:
            names = _boxscore_person_names(side, game_data)
            order_ids = [str(x).replace("ID", "").strip()
                         for x in (side.get("battingOrder") or [])]
            for slot, mlbam in enumerate(order_ids[:9], start=1):
                if not mlbam:
                    continue
                entry["batting_order"].append(
                    {"mlbam": mlbam, "name": names.get(mlbam, ""), "order": slot})
            pitchers = [str(x).replace("ID", "").strip()
                        for x in (side.get("pitchers") or []) if str(x).strip()]
            if pitchers:
                entry["starting_pitcher"] = {
                    "mlbam": pitchers[0], "name": names.get(pitchers[0], "")}
        sides[side_key] = entry

    game_id = (f"{abbrevs['away']}@{abbrevs['home']}"
               if abbrevs["away"] and abbrevs["home"] else "")
    return {
        "game_pk": game_pk,
        "game_id": game_id,
        "abstract_state": abstract,
        "detailed_state": detailed,
        "started": started,
        "sides": sides,
    }


def fetch_boxscore(game_pk: Any, timeout: float = 20.0) -> Dict[str, Any]:  # pragma: no cover - network path
    """Fetch and parse one game's boxscore. Network; the parse is what is tested."""
    payload, _headers = _http_get_json(boxscore_url(game_pk), timeout=timeout)
    return parse_boxscore_feed(payload)


def build_observed_starters(boxscores: Iterable[Mapping[str, Any]],
                            salary_players: Any) -> Dict[str, Any]:
    """Parsed boxscores + the DK salary file -> the observed-fact tier.

    Takes the output of ``parse_boxscore_feed`` (one per game) and joins it to
    DK Player_IDs on ``normalize_name`` + team, the same crosswalk the status
    map uses. Returns::

        {"observed_teams": [DK teams whose game is underway and was read],
         "observed_game_ids", "not_started_game_ids",
         "observed_hitter_ids", "observed_order_by_player_id",
         "observed_pitcher_ids", "observed_pitcher_by_team",
         "unmatched", "unrostered_observed"}

    ``unrostered_observed`` is an observed starter with no DK salary row. That
    is NOT an error -- DK owns eligibility and a player it never listed is
    unrosterable anyway -- so it is named and carried, the same reading R32
    settled for a pasted starter absent from the pool.

    A side enters ``observed_teams`` ONLY when it carries an actual observation
    (a non-empty batting order, or a starting pitcher). A game that is underway
    whose side block came back empty is an INCOMPLETE READ, not evidence that
    nobody started, and admitting it would make every player on that side read
    ``did_not_start`` -- one empty block condemning nine bats, which is the
    false-positive class this tier was built to remove rather than relocate.
    Those sides are named in ``sides_unread``.
    """
    players = _load_salary_players(salary_players)
    by_name_team: Dict[Tuple[str, str], List[str]] = {}
    for pid, record in players.items():
        key = (normalize_name(_record_get(record, "name")),
               str(_record_get(record, "team")).strip().upper())
        by_name_team.setdefault(key, []).append(str(pid))

    observed_teams: List[str] = []
    observed_game_ids: List[str] = []
    not_started: List[str] = []
    hitter_ids: List[str] = []
    order_by_pid: Dict[str, int] = {}
    pitcher_ids: List[str] = []
    pitcher_by_team: Dict[str, str] = {}
    unmatched: List[Dict[str, str]] = []
    unrostered: List[Dict[str, str]] = []
    sides_unread: List[Dict[str, str]] = []

    def resolve(name: str, dk_team: str, role: str) -> Optional[str]:
        hits = by_name_team.get((normalize_name(name), dk_team), [])
        if len(hits) == 1:
            return hits[0]
        if not hits:
            unrostered.append({"name": str(name), "team": dk_team, "role": role,
                               "reason": "observed starter absent from the DK pool"})
        else:
            unmatched.append({"name": str(name), "team": dk_team, "role": role,
                              "reason": "ambiguous salary match"})
        return None

    for box in boxscores:
        game_id = str(box.get("game_id") or "")
        if not box.get("started"):
            if game_id:
                not_started.append(game_id)
            continue
        if game_id:
            observed_game_ids.append(game_id)
        for side in (box.get("sides") or {}).values():
            dk_team = str(side.get("team") or "").strip().upper()
            if not dk_team:
                continue
            if not (side.get("batting_order") or side.get("starting_pitcher")):
                sides_unread.append({
                    "team": dk_team, "game_id": game_id,
                    "reason": "game is underway but the boxscore carried no "
                              "batting order and no starting pitcher for this "
                              "side; absence here is an unread block, not an "
                              "observation"})
                continue
            observed_teams.append(dk_team)
            for row in side.get("batting_order") or []:
                dk_id = resolve(row.get("name") or "", dk_team, "hitter")
                if dk_id is None:
                    continue
                hitter_ids.append(dk_id)
                order_by_pid[dk_id] = int(row.get("order") or 0)
            starter = side.get("starting_pitcher") or None
            if starter:
                dk_id = resolve(starter.get("name") or "", dk_team, "pitcher")
                if dk_id is not None:
                    pitcher_ids.append(dk_id)
                    pitcher_by_team[dk_team] = dk_id

    return {
        "observed_teams": sorted(set(observed_teams)),
        "observed_game_ids": sorted(set(observed_game_ids)),
        "not_started_game_ids": sorted(set(not_started)),
        "observed_hitter_ids": sorted(set(hitter_ids)),
        "observed_order_by_player_id": order_by_pid,
        "observed_pitcher_ids": sorted(set(pitcher_ids)),
        "observed_pitcher_by_team": dict(sorted(pitcher_by_team.items())),
        "unmatched": unmatched,
        "unrostered_observed": unrostered,
        "sides_unread": sorted(sides_unread, key=lambda r: (r["team"], r["game_id"])),
    }


def observed_starter_state(observed: Mapping[str, Any],
                           player_id: Any,
                           team: Any) -> str:
    """``"started"`` | ``"did_not_start"`` | ``"unobserved"`` for one DK player.

    THREE values, not a bool, and that is the whole contract. ``unobserved``
    means this player's game has not begun, so the observed tier has nothing to
    say and the caller must fall through to the feed; collapsing it into
    ``did_not_start`` is the same conflation R237 is filed on and the exact
    failure this tier exists to end. A player on a team whose game IS underway
    and who is in neither observed set did not start -- that is an observation,
    and it is the one that finds a dead bat.
    """
    pid = str(player_id).strip()
    dk_team = str(team or "").strip().upper()
    if dk_team not in set(observed.get("observed_teams") or []):
        return "unobserved"
    if pid in set(observed.get("observed_hitter_ids") or []):
        return "started"
    if pid in set(observed.get("observed_pitcher_ids") or []):
        return "started"
    return "did_not_start"


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
    # R289, 2026-09-01. The salary file's own Excluded column, CARRIED rather
    # than overwritten with False.
    #
    # What the hardcode cost, on 1940_9g: an operator built
    # data/slates/2026-09-01/DKSalaries_excl_locked.csv with Excluded=TRUE on all
    # 288 players from games that had locked, to restrict the pool to the six
    # open games. The build read the column, threw it away, CERTIFIED, and
    # delivered a file holding 151 of those players. `optimizer_v3.excluded_flags`
    # is careful and correct about which tokens exclude, and it never received an
    # operator exclusion because this line and its sibling in
    # slate_intake_manager stamped the field before the frame ever existed.
    #
    # Note which direction the failure runs. CLAUDE.md forbids trimming the legal
    # pool because a trim is invisible in the certified output; here the operator
    # asked for an explicit, visible, instructed restriction and it was silently
    # ignored while the output certified. Both failures are the same shape --
    # pool membership not represented in the artifact -- and this is the one the
    # guardrail's wording does not cover.
    #
    # The token rule is `read_excluded_cell`'s, imported rather than restated:
    # only an affirmative token excludes, blank and unrecognized keep the player.
    excluded, excluded_kind = read_excluded_cell(raw.get("Excluded"))
    row: Dict[str, Any] = {
        "Player_ID": str(sp.player_id),
        "Name": sp.name,
        "Team": sp.team,
        "Opponent": sp.opponent,
        "Position": "/".join(sp.positions),
        "Salary": float(sp.salary),
        "Game_ID": sp.game_id or sp.game_info,
        "AvgPointsPerGame": appg,
        "Excluded": excluded,
        "Excluded_Source": ("salary_file" if excluded_kind != 'blank'
                            else "absent_or_blank"),
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
    #
    # R159(a): the merge reads the RAW rows, shelved players included, because
    # it is the thing that has to TELL a posted nine holding an IL bat from a
    # side DK never posted. Feeding it the status-filtered map made those two
    # cases identical here while `dk_order_coverage` -- reading the raw file --
    # called the first one covered and skipped the fetch that was the only way
    # to fill the ninth slot. One input, one reading; the merge applies the
    # status rule itself and never seats a shelved player.
    raw_salary_map = {p.player_id: p for p in all_players}
    lineups_feed, dk_order_report = merge_dk_starting_into_feed(
        lineups_feed, raw_salary_map)
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

    # R159(a): a DK side that lost a player to the Status column is not the same
    # fact as a side DK never posted, and the operator's next move differs --
    # one needs a ninth bat, the other needs a lineup. Named with the shelved
    # player, because that name is what the operator is about to go look up.
    # R219: and what the merge DID with the surviving rows is a fourth fact,
    # which this warning used to assert rather than read. It said "the surviving
    # N are seeded as a partial" unconditionally -- including on a side the merge
    # deferred to a source holding a complete nine, where nothing was seeded, and
    # on an all-nine-shelved side where there was nothing to seed. Each
    # resolution gets the sentence that is true of it, because the operator's
    # next move differs by resolution and only the first two lines share one.
    for rec in dk_order_report.get("degraded_sides") or []:
        if rec["team"] not in slate_team_set or rec["team"] in excluded_teams:
            continue
        shelved = ", ".join(f"{s['name']} (slot {s['order']}, {s['status'] or 'OUT'})"
                            for s in rec["shelved"])
        head = (f"{rec['team']}: DK posted a full 1-9 but {len(rec['shelved'])} of "
                f"them are shelved [{shelved}]")
        resolution = rec.get("resolution") or "seeded"
        if resolution == "deferred_to_feed":
            warnings.append(
                f"{head}; another source holds a complete nine for this side and "
                f"it is used instead, so DK's surviving {rec['posted']} were not "
                f"seeded -- check the shelved names against that lineup"
            )
        elif resolution == "all_shelved":
            warnings.append(
                f"{head}; nothing survived to seed, so the whole side comes from "
                f"the projection"
            )
        elif resolution == "no_game":
            warnings.append(
                f"{head}; the merge found no game to attach the side to, so the "
                f"surviving {rec['posted']} were NOT seeded and the whole side "
                f"comes from the projection"
            )
        else:
            warnings.append(
                f"{head}; the surviving {rec['posted']} are seeded as a partial "
                f"and the rest of the side comes from the projection"
            )

    # R160: named FIRST, because without it the symptom the operator reads is
    # "no probable or declared starter" for both sides of the game -- true, and
    # about the wrong thing. The side has no probable because the game was never
    # built, and the game was never built because DK shipped no start time for
    # it. A blocker that names a consequence and not the cause is the class this
    # whole batch is about.
    #
    # R220(b): one record per GAME now, carrying every team that reached it, so
    # this emits one blocker for one fact instead of one per side.
    for rec in dk_order_report.get("games_unsynthesizable") or []:
        teams = [t for t in (rec.get("teams") or []) if t in slate_team_set]
        if teams:
            blockers.append(
                f"{rec['game_id']}: {rec['reason']}, so the game was not built "
                f"from the salary file and {', '.join(teams)} "
                f"{'has' if len(teams) == 1 else 'have'} no lock time "
                f"(DH game 2s ship 'TBD' here); supply a feed covering this game"
            )

    # R160: a game whose lock time could not be derived is skipped by the status
    # map, so nothing on it can be late-swap-checked. That is a blocker, not a
    # warning -- the swap rails are the reason lock times exist.
    #
    # R220(a): scoped to the slate, which the sibling loop above always was and
    # this one was not. The status map reads whatever feed it is handed, and a
    # day-wide feed carries games no draftgroup on this slate can touch, so one
    # malformed `game_date_utc` on an off-slate game blocked a build whose pool
    # cannot reach it -- a refusal the operator has no move against. The record
    # carries the game, not a team, so the slate filter is on its two sides.
    for rec in status.get("games_without_lock_time") or []:
        if not (set(str(rec["game_id"]).split("@")) & slate_team_set):
            continue
        blockers.append(
            f"{rec['game_id']}: {rec['reason']} "
            f"(game_date_utc={rec['game_date_utc']!r}); supply a feed with a real "
            f"start time for this game before building it"
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
    # R289. The operator exclusion, counted where the brief can print it. The
    # 1940_9g failure was not that the exclusion was refused, it was that it was
    # accepted, discarded, and NOTHING SAID SO -- the build certified and the
    # locked-game players were in the delivered file. A count that reaches the
    # brief is what makes the instruction auditable at T-5; the rows themselves
    # are still carried and the optimizer still owns the removal, because a drop
    # here would put a second pool-reduction site in the intake path.
    excluded_rows = [r for r in rows if r.get("Excluded")]
    excluded_report = {
        "column_present": any(r.get("Excluded_Source") == "salary_file" for r in rows),
        "applied": len(excluded_rows),
        "by_team": dict(sorted(collections.Counter(
            str(r.get("Team") or "?") for r in excluded_rows).items())),
        "player_ids": sorted(str(r["Player_ID"]) for r in excluded_rows)[:50],
        "note": ("salary-file Excluded column carried through the front door; "
                 "only an affirmative token excludes (optimizer_v3."
                 "read_excluded_cell), and the optimizer is what removes the row"),
    }
    if excluded_rows:
        warnings.append(
            f"salary file excludes {len(excluded_rows)} of {len(rows)} kept "
            f"rows via its Excluded column "
            f"({', '.join(f'{t}={n}' for t, n in excluded_report['by_team'].items())}); "
            f"those players are carried into the frame and removed by the "
            f"optimizer, and this build's legal pool is {len(rows) - len(excluded_rows)}"
        )
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
            # R289. The OPERATOR's exclusion, distinct from the postponement one
            # above: that key is the engine excluding a game, this one is the
            # operator excluding players. Conflating them would hide the
            # instruction inside a fact about the schedule.
            "excluded_column": excluded_report,
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

    R205. The MONEYLINE consensus is not a median and is not computed in
    American-odds space at all: each book that posts a complete two-way is
    de-vigged first, the normalized probabilities are averaged, and the pair is
    carried back into ``moneyline`` as the vig-free price implying it. That
    price is derived, so the entry states its ``moneyline_basis``, the
    probabilities themselves, every book's raw posted pair in
    ``moneyline_books``, and which books were excluded and why. See
    ``consensus_two_way_probabilities`` for the arithmetic and the ATL@MIN
    case that paid for it.

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
        # R205. The consensus is computed in probability space, per book, and
        # only from books that posted a COMPLETE two-way. What lands in
        # ``moneyline`` is the vig-free price implying that consensus -- a
        # derived number, never a posted one, which is why the entry carries
        # its basis and every book's raw pair beside it.
        consensus = consensus_two_way_probabilities(moneyline_books)
        probabilities = consensus["probabilities"]
        moneyline: Dict[str, float] = {}
        moneyline_probabilities: Dict[str, float] = {}
        if probabilities:
            for side_key, team_code in (("away", away), ("home", home)):
                prob = probabilities[side_key]
                moneyline[team_code] = round(implied_prob_to_american(prob), 6)
                moneyline_probabilities[team_code] = round(prob, 6)
        raw_by_book: Dict[str, Dict[str, float]] = {}
        for side_key, team_code in (("away", away), ("home", home)):
            for book_key, price in moneyline_books[side_key].items():
                raw_by_book.setdefault(book_key, {})[team_code] = price

        if not books:
            continue
        stamp = fetched_at or latest_update or datetime.now(timezone.utc).isoformat()
        parsed_events.append({
            "game_id": game_id,
            "moneyline": moneyline,
            "moneyline_basis": (consensus["basis"] if probabilities
                                else "unpriced: no book posted a complete two-way"),
            "moneyline_probabilities": moneyline_probabilities,
            "moneyline_books": {b: raw_by_book[b] for b in sorted(raw_by_book)},
            "moneyline_books_used": consensus["books_used"],
            "moneyline_books_incomplete": consensus["books_incomplete"],
            # A game total is a linear quantity with no discontinuity anywhere
            # in its range, so a cross-book median is sound here in a way it is
            # not one field above. It is still a derived line rather than a
            # posted one; ``books`` carries what each book actually posted.
            "total": float(statistics.median(sorted(books.values()))),
            "total_basis": "median_across_books",
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
    # R205. A game where some book posted a price and none posted a complete
    # two-way is a DIFFERENT fact from a game with no h2h market at all, and
    # the packet says which. Downstream the moneyline is simply absent and the
    # split is even, which is honest; what would not be honest is that outcome
    # arriving with nothing naming the one-sided market it came from.
    moneyline_incomplete = [
        {"game_id": game_id,
         "books_incomplete": entry["moneyline_books_incomplete"],
         "reason": "no book posted a complete two-way"}
        for game_id, entry in sorted(odds_by_game_id.items())
        if not entry.get("moneyline") and entry.get("moneyline_books_incomplete")
    ]
    return {
        "odds_by_game_id": odds_by_game_id,
        "unmapped_teams": unmapped,
        "doubleheader_legs_dropped": dropped,
        "legs_by_game_id": {k: v for k, v in sorted(legs_by_game_id.items())
                            if len(v) > 1},
        "moneyline_incomplete": moneyline_incomplete,
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


def implied_prob_to_american(prob: float) -> float:
    """A probability -> the American price that implies exactly it.

    The inverse of ``american_to_implied_prob``, exact for every price the
    books post. Used to carry a consensus BACK into the packet's American-price
    field so no consumer has to change shape; the price it returns is vig-free
    and is labeled as such where it is stored, because no book posted it.

    p == 0.5 returns +100 rather than -100. Both imply a half and the two are
    the same price; picking one keeps the function deterministic.
    """
    value = float(prob)
    if not (value > 0.0) or not (value < 1.0) or value != value:
        raise ValueError(
            f"probability must be strictly between 0 and 1, got {prob!r}")
    if value > 0.5:
        return -100.0 * value / (1.0 - value)
    return 100.0 * (1.0 - value) / value


CONSENSUS_TWO_WAY_BASIS = "devig_per_book_then_average_probability"


def consensus_two_way_probabilities(
    prices_by_side: Mapping[str, Mapping[str, Any]],
    side_keys: Tuple[str, str] = ("away", "home"),
) -> Dict[str, Any]:
    """Cross-book consensus for a two-way market, computed in PROBABILITY space.

    R205. American odds are discontinuous at +/-100 -- -104 and +100 are
    adjacent prices, both about half -- so their arithmetic mean is -2.0, which
    reads as a 98% favorite. Averaging (or taking a median of an even count,
    which is the same operation) ACROSS BOOKS in American space therefore
    fabricates prices no book posted, and it is worst on exactly the games
    closest to a coin flip, where two books routinely straddle the boundary.
    ATL@MIN on 2026-08-19: DK ATL -104 / MIN -104, FD ATL -108 / MIN +100
    produced ``{'ATL': -106.0, 'MIN': -2.0}`` and an implied split of 5.36/3.14
    on an 8.5 total, against 4.26/4.24 here.

    The order is the fix. De-vig EACH COMPLETE BOOK to a two-way pair first,
    THEN average the normalized probabilities: correct at any book count,
    where average-then-de-vig reintroduces the same boundary problem in a
    smaller way. Averaging normalized pairs yields a normalized pair, so the
    result is itself vig-free and a consumer that de-vigs again gets identity.

    A book contributes only when it posts BOTH sides. That is not fastidiousness:
    the old code took a median per SIDE independently, so the away price could
    come from one set of books and the home price from another, and the vig
    relationship that makes a pair mean anything was broken before the median
    ever ran. A book missing a side, or quoting a price this scale cannot read
    (0, NaN, inf), is NAMED in ``books_incomplete`` and excluded.

    When no book posts a complete two-way, ``probabilities`` is None. The caller
    omits the moneyline and names the game, which is what the downstream F1
    already handles honestly (an even split says "this is a run environment and
    we do not know which side is favored"). Inventing a one-sided price from a
    one-sided market would be R205 with a different arithmetic.
    """
    away_key, home_key = side_keys
    raw_by_book: Dict[str, Dict[str, Any]] = {}
    for side in (away_key, home_key):
        for book, price in (prices_by_side.get(side) or {}).items():
            raw_by_book.setdefault(str(book), {})[side] = price

    per_book: Dict[str, Dict[str, float]] = {}
    incomplete: Dict[str, str] = {}
    for book in sorted(raw_by_book):
        posted = raw_by_book[book]
        if away_key not in posted or home_key not in posted:
            side_posted = away_key if away_key in posted else home_key
            incomplete[book] = f"{side_posted}_only"
            continue
        try:
            probs = [_finite_american_to_prob(posted[side])
                     for side in (away_key, home_key)]
        except (TypeError, ValueError) as exc:
            incomplete[book] = f"unusable_price: {exc}"
            continue
        p_away, p_home = vig_free_probabilities(probs[0], probs[1])
        per_book[book] = {away_key: p_away, home_key: p_home}

    if not per_book:
        return {
            "probabilities": None,
            "basis": CONSENSUS_TWO_WAY_BASIS,
            "books_used": [],
            "books_incomplete": incomplete,
            "per_book_probabilities": {},
        }

    books_used = sorted(per_book)
    n = float(len(books_used))
    averaged = {side: sum(per_book[b][side] for b in books_used) / n
                for side in (away_key, home_key)}
    # Averaging normalized pairs is already normalized; the renormalization is
    # float hygiene, not a second de-vig.
    p_away, p_home = vig_free_probabilities(averaged[away_key], averaged[home_key])
    return {
        "probabilities": {away_key: p_away, home_key: p_home},
        "basis": CONSENSUS_TWO_WAY_BASIS,
        "books_used": books_used,
        "books_incomplete": incomplete,
        "per_book_probabilities": {b: {k: round(v, 6) for k, v in pair.items()}
                                   for b, pair in per_book.items()},
    }


def _finite_american_to_prob(price: Any) -> float:
    """``american_to_implied_prob`` with the non-numbers rejected by name.

    R215's discipline on a second surface: a NaN price propagates through every
    comparison as False and would leave a book in the consensus contributing a
    NaN probability, which poisons the average without failing anything.
    """
    value = float(price)
    if not math.isfinite(value):
        raise ValueError(f"{price!r} is not a finite American price")
    return american_to_implied_prob(value)


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
