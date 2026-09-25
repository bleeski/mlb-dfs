"""R406: Classic scenario sleeves. One owner for sleeve definitions, the
salary-only transform, the environment-game rule, and apportionment.

Every Classic candidate was an argmax of ONE projection under a different (SP
pair, stack team) constraint, so a systematic projection error was shared by
every entry: the caps spread persons, not beliefs. A sleeve is a WORLD in which
a share of the bank's jobs is generated, and each entry is confined to one
sleeve's candidates through the allocator's own compatibility mask, so the joint
MILP and every cap stay in force across the whole entered set (R405's cluster
cap still binds at the portfolio level).

Ben's decisions (2026-09-23):

* weights projection 40%, salary-only 20%, chalk-fails 20%, environment 20%;
* ``wta_satellite`` and WTA contests shift 10 points from projection to
  chalk-fails (30/20/30/20);
* the environment sleeve takes the top 2 games by implied total, or by park run
  factor when no odds are priced;
* sleeves are on by default.

Truthful labels: every sleeve is a deterministic construction over labeled
priors. Nothing here is a probability or an edge, and a sleeve that does well in
a replay is "supported in the shapes replayed", never more.

R422 (Ben, 2026-09-24): tail seats scale with coverage. The slate's teams are
ranked by the MARKET's implied totals and its bottom third is the tail. Once
the portfolio holds enough entries to give every comfortable team one stack,
each further entry opens one tail seat, highest-implied tail team first, until
every tail team has one (``tail_seat_count``). A tail seat is pinned to its
team and seated on a projection-world lineup whose PRIMARY stack is that team:
a membership through the allocator's mask, like environment, because the
bank's job grid already stacks every team. Seats go only to top-heavy shapes
with two or more entries, at most half of a contest. A coverage rule over a
labeled prior; it says nothing about how often a tail wins.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.contest_shapes import WTA_CONSTRUCTION_SHAPES, validate_shape

VERSION = "1.1"

SLEEVE_PROJECTION = "projection"
SLEEVE_SALARY_ONLY = "salary_only"
SLEEVE_CHALK_FAILS = "chalk_fails"
SLEEVE_ENVIRONMENT = "environment"
#: Apportionment order, and the order a tie in largest remainder resolves in.
SLEEVES: Tuple[str, ...] = (SLEEVE_PROJECTION, SLEEVE_SALARY_ONLY,
                            SLEEVE_CHALK_FAILS, SLEEVE_ENVIRONMENT)

DEFAULT_WEIGHTS: Dict[str, float] = {
    SLEEVE_PROJECTION: 0.40, SLEEVE_SALARY_ONLY: 0.20,
    SLEEVE_CHALK_FAILS: 0.20, SLEEVE_ENVIRONMENT: 0.20,
}
#: Ben: WTA and `wta_satellite` lean on the contrarian sleeves.
WTA_WEIGHTS: Dict[str, float] = {
    SLEEVE_PROJECTION: 0.30, SLEEVE_SALARY_ONLY: 0.20,
    SLEEVE_CHALK_FAILS: 0.30, SLEEVE_ENVIRONMENT: 0.20,
}
ENVIRONMENT_GAME_COUNT = 2
#: The `bank_job_class` each non-projection sleeve's candidates carry. The
#: allocator derives R405's consensus cluster from candidates WITHOUT a class,
#: so no sleeve's world can dilute the definition of the projection's consensus.
SLEEVE_JOB_CLASS: Dict[str, str] = {
    SLEEVE_SALARY_ONLY: "sleeve_salary_only",
    SLEEVE_CHALK_FAILS: "sleeve_chalk_fails",
    SLEEVE_ENVIRONMENT: "sleeve_environment",
}

#: R422. The tail sleeve. Not in ``SLEEVES``: its seats are not apportioned by
#: weight but counted off coverage and pinned to a team before the weights
#: apportion the rest of each contest.
SLEEVE_TAIL = "tail"
SLEEVE_JOB_CLASS[SLEEVE_TAIL] = "sleeve_tail"
#: The order the bank builds sleeves in: the weighted four, then the tail.
BANK_SLEEVES: Tuple[str, ...] = SLEEVES + (SLEEVE_TAIL,)
#: The entry-requirement key a tail seat's team is stamped under.
TAIL_TEAM_KEY = "tail_team"
#: The membership token a projection-world lineup stacking ``team`` carries.
TAIL_TOKEN_PREFIX = "tail:"
#: Top-heavy shapes, the only ones a tail seat goes to. Cash, satellites and
#: single entry seat none, whatever N is.
TAIL_SHAPES = frozenset({"large_field_gpp", "large_wta", "mme_gpp"})
for _shape in sorted(TAIL_SHAPES):
    validate_shape(_shape, "classic_sleeves.TAIL_SHAPES")
del _shape
#: The tail is the bottom 1/TAIL_DENOMINATOR of the slate's teams by implied total.
TAIL_DENOMINATOR = 3
#: R405's cluster limit for chalk-fails: at most one consensus bat per lineup.
CHALK_FAILS_MAX_MEMBERS = 1
#: The candidate key a sleeve tags its lineups with.
SLEEVE_TAG_KEY = "bank_sleeve"
SINGLE_ENTRY_POSTURES = frozenset({"single_entry"})
CASH_POSTURES = frozenset({"cash"})
WTA_POSTURES = frozenset({"wta_satellite"})


def weights_for_contest(posture: Optional[str], contest_shape: Optional[str]) -> Dict[str, float]:
    """The declared weights for one contest: WTA-tilted for `wta_satellite` and
    every WTA-construction shape, the default otherwise."""
    shape = str(contest_shape or "").strip().lower()
    if str(posture or "") in WTA_POSTURES or (
            shape in WTA_CONSTRUCTION_SHAPES and shape != "single_entry_gpp"):
        return dict(WTA_WEIGHTS)
    return dict(DEFAULT_WEIGHTS)


def largest_remainder(n: int, weights: Mapping[str, float],
                      order: Sequence[str] = SLEEVES) -> Dict[str, int]:
    """Apportion ``n`` seats over ``weights`` by largest remainder.

    Deterministic: quotas floor first, then the leftover seats go to the largest
    fractional remainders, ties broken by ``order``. Weights are normalized, so
    they need not sum to exactly 1.
    """
    n = max(0, int(n))
    names = [s for s in order if float(weights.get(s) or 0.0) > 0.0]
    total = sum(float(weights[s]) for s in names)
    if not n or not names or total <= 0:
        return {s: 0 for s in order}
    quotas = {s: n * float(weights[s]) / total for s in names}
    seats = {s: int(math.floor(q + 1e-9)) for s, q in quotas.items()}
    left = n - sum(seats.values())
    ranked = sorted(names, key=lambda s: (-(quotas[s] - seats[s]), order.index(s)))
    for s in ranked[:left]:
        seats[s] += 1
    return {s: seats.get(s, 0) for s in order}


def contest_sleeve_weights(posture: Optional[str], contest_shape: Optional[str]) -> Dict[str, float]:
    """One contest's declared weights. Single-entry and cash contests go to
    ``projection`` alone (Ben, 2026-09-23); WTA leans contrarian."""
    shape = str(contest_shape or "").strip().lower()
    if str(posture or "") in SINGLE_ENTRY_POSTURES | CASH_POSTURES or shape in (
            "cash", "single_entry_gpp"):
        return {SLEEVE_PROJECTION: 1.0}
    return weights_for_contest(posture, shape)


def weights_by_contest(posture_by_contest: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, float]]:
    """The merged control: every contest's declared weights, sorted by id."""
    return {str(cid): contest_sleeve_weights(info.get("posture"), info.get("contest_shape"))
            for cid, info in sorted(posture_by_contest.items())}


def candidate_sleeve(candidate: Mapping[str, Any]) -> str:
    """The world a candidate was built in; untagged is the projection's."""
    return str(candidate.get(SLEEVE_TAG_KEY) or SLEEVE_PROJECTION)


def apportion_entries(
    entry_requirements: Sequence[Mapping[str, Any]],
    weights: Mapping[str, Mapping[str, float]],
    *,
    available: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Assign each entry a sleeve, per contest, by largest remainder.

    A contest with one entry goes to ``projection`` whatever its weights.
    Entries are taken in entry-id order within a contest and sleeves in
    ``SLEEVES`` order, so the mapping is deterministic. ``available`` names the
    sleeves whose bank holds candidates; a sleeve outside it gets no seats and
    its share falls back to ``projection``, counted in ``fallbacks`` -- a
    relaxation, never a silent reshuffle.

    R422. An entry stamped with a tail team (``TAIL_TEAM_KEY``, by
    ``tail_seat_plan``) seats ``tail:<team>`` and the weights apportion the
    rest of its contest.
    """
    have = set(available) if available is not None else set(SLEEVES)
    have.add(SLEEVE_PROJECTION)
    by_contest: Dict[str, List[Mapping[str, Any]]] = {}
    for req in entry_requirements:
        by_contest.setdefault(str(req.get("contest_id") or ""), []).append(req)
    sleeve_by_entry: Dict[str, str] = {}
    contests: List[Dict[str, Any]] = []
    fallbacks: List[Dict[str, Any]] = []
    for cid in sorted(by_contest):
        every = sorted(by_contest[cid], key=lambda r: str(r.get("entry_id")))
        tail_reqs = [r for r in every if r.get(TAIL_TEAM_KEY)]
        reqs = [r for r in every if not r.get(TAIL_TEAM_KEY)]
        declared = dict(weights.get(cid) or {SLEEVE_PROJECTION: 1.0})
        if len(every) <= 1:
            declared, rule = {SLEEVE_PROJECTION: 1.0}, "single entry"
        else:
            rule = "weights" if len(declared) > 1 else "projection only"
        for req in tail_reqs:
            sleeve_by_entry[str(req.get("entry_id"))] = tail_token(req[TAIL_TEAM_KEY])
        seats = largest_remainder(len(reqs), declared)
        for s in SLEEVES:
            if s != SLEEVE_PROJECTION and seats.get(s) and s not in have:
                fallbacks.append({"contest_id": cid, "sleeve": s, "entries": seats[s],
                                  "reason": "the sleeve's bank holds no candidates"})
                seats[SLEEVE_PROJECTION] += seats[s]
                seats[s] = 0
        cursor = 0
        for s in SLEEVES:
            for req in reqs[cursor:cursor + seats.get(s, 0)]:
                sleeve_by_entry[str(req.get("entry_id"))] = s
            cursor += seats.get(s, 0)
        if tail_reqs:
            seats = {**seats, SLEEVE_TAIL: len(tail_reqs)}
        contests.append({"contest_id": cid, "entries": len(every), "weights": declared,
                         "entries_by_sleeve": seats, "rule": rule})
    return {"sleeve_by_entry": sleeve_by_entry, "contests": contests,
            "fallbacks": fallbacks, "relaxations": len(fallbacks)}


def expected_entries_by_sleeve(
    weights: Mapping[str, Mapping[str, float]],
    entries_by_contest: Mapping[str, int],
    tail_seats_by_contest: Optional[Mapping[str, int]] = None,
) -> Dict[str, int]:
    """How many entries each sleeve will seat, before any fallback: what the
    bank has to be asked to supply. R422: a contest's tail seats come off its
    count before the weights apportion the rest, as ``apportion_entries``
    does, and ``tail`` appears only when a seat was placed."""
    tail = {str(k): int(v) for k, v in (tail_seats_by_contest or {}).items() if int(v) > 0}
    totals = {s: 0 for s in SLEEVES}
    for cid, n in sorted(entries_by_contest.items()):
        declared = dict(weights.get(str(cid)) or {SLEEVE_PROJECTION: 1.0})
        if int(n) <= 1:
            declared = {SLEEVE_PROJECTION: 1.0}
        for s, seats in largest_remainder(int(n) - tail.get(str(cid), 0), declared).items():
            totals[s] += seats
    if tail:
        totals[SLEEVE_TAIL] = sum(tail.values())
    return totals


def static_park_run_factor_by_game(
    game_ids: Iterable[str],
    reference_dir: Optional[Any] = None,
) -> Dict[str, float]:
    """The environment sleeve's fallback when no odds are priced and no F5
    report was handed in: the home venue's applied run factor, from the static
    reference tables F5 itself reads. Game ids are ``AWAY@HOME``."""
    from pathlib import Path
    from mlb_engine.intake.slate_intake_manager import (
        load_f5_park_factors, load_team_venue_map)
    root = Path(reference_dir) if reference_dir else (
        Path(__file__).resolve().parents[2] / "data" / "reference")
    try:
        venues = load_team_venue_map(str(root / "team_to_venue.csv"))
        parks = load_f5_park_factors(str(root / "f5_park_factors.csv"))
    except Exception:  # noqa: BLE001 - a missing table degrades to no ranking
        return {}
    out: Dict[str, float] = {}
    for gid in sorted({str(g) for g in game_ids}):
        home = gid.split("@")[-1].strip().upper() if "@" in gid else ""
        venue = (venues.get(home) or {}).get("venue") or (venues.get(home) or {}).get("Venue")
        park = parks.get(str(venue)) if venue else None
        if park:
            factor = park.get("run_factor_applied", park.get("Run_Factor_Applied"))
            try:
                out[gid] = float(factor)
            except (TypeError, ValueError):
                continue
    return out


def salary_only_frame(projections: Any) -> Tuple[Any, Dict[str, Any]]:
    """DK salary as the only prior. A COPY of the frame, never an edit of it.

    Base is rebuilt from salary through a position-group points-per-dollar ratio
    measured on the slate's own frame (hitters and pitchers separately), Ceiling
    is Base x the group's median Ceiling/Base, and Floor is Base x the group's
    median Floor/Base, so no player-level factor survives in any of the three.
    """
    frame = projections.copy()
    report: Dict[str, Any] = {"groups": {}}
    is_p = frame["Position"].astype(str) == "P"
    for label, mask in (("pitchers", is_p), ("hitters", ~is_p)):
        group = frame.loc[mask]
        if not len(group):
            continue
        salary = group["Salary"].astype(float)
        base = group["Base"].astype(float) if "Base" in group.columns else None
        if base is None or float(salary.sum()) <= 0:
            continue
        per_dollar = float(base.sum()) / float(salary.sum())
        positive = base > 0
        ceil_ratio = float((group.loc[positive, "Ceiling"].astype(float)
                            / base[positive]).median()) if positive.any() else 1.0
        floor_ratio = (float((group.loc[positive, "Floor"].astype(float)
                              / base[positive]).median())
                       if positive.any() and "Floor" in group.columns else 0.5)
        new_base = salary * per_dollar
        frame.loc[mask, "Base"] = new_base.round(4)
        frame.loc[mask, "Ceiling"] = (new_base * ceil_ratio).round(4)
        if "Floor" in frame.columns:
            frame.loc[mask, "Floor"] = (new_base * floor_ratio).round(4)
        report["groups"][label] = {
            "points_per_dollar": round(per_dollar, 8),
            "median_ceiling_over_base": round(ceil_ratio, 4),
            "median_floor_over_base": round(floor_ratio, 4),
            "players": int(mask.sum()),
        }
    report["note"] = ("salary is the only prior: group points-per-dollar and "
                      "group median ratios, no player-level factor; a labeled "
                      "prior, never a projection claim")
    return frame, report


def rank_environment_games(
    games: Iterable[str],
    *,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
    park_run_factor_by_game: Optional[Mapping[str, float]] = None,
    teams_by_game: Optional[Mapping[str, Sequence[str]]] = None,
    count: int = ENVIRONMENT_GAME_COUNT,
) -> Dict[str, Any]:
    """The environment sleeve's games: top ``count`` by implied game total when
    F1 priced them, else by park run factor, ties by game id."""
    game_list = sorted({str(g) for g in games if str(g)})
    implied = {str(k).upper(): float(v) for k, v in (implied_total_by_team or {}).items()}
    teams = {str(g): [str(t).upper() for t in (teams_by_game or {}).get(g, [])]
             for g in game_list}
    totals = {}
    if implied:
        for g in game_list:
            vals = [implied[t] for t in teams[g] if t in implied]
            if teams[g] and len(vals) == len(teams[g]):
                totals[g] = round(sum(vals), 3)
    if totals:
        basis = "implied_total"
        ranked = sorted(totals, key=lambda g: (-totals[g], g))
        scores = totals
    else:
        parks = {str(k): float(v) for k, v in (park_run_factor_by_game or {}).items()}
        scored = {g: parks[g] for g in game_list if g in parks}
        basis = "park_run_factor" if scored else "none"
        ranked = sorted(scored, key=lambda g: (-scored[g], g))
        scores = scored
    chosen = ranked[:max(0, int(count))]
    return {"basis": basis, "games": chosen,
            "scores": {g: scores[g] for g in chosen},
            "teams": sorted({t for g in chosen for t in teams.get(g, [])}),
            "note": ("games ranked by the implied total F1 priced, else the park "
                     "run factor, ties by game id; a deterministic rule, never a "
                     "probability")}


#: `bank_job_class` -> sleeve, the inverse of SLEEVE_JOB_CLASS.
SLEEVE_BY_JOB_CLASS: Dict[str, str] = {v: k for k, v in SLEEVE_JOB_CLASS.items()}


#: The candidate key listing EVERY sleeve a lineup may seat.
SLEEVE_MEMBERSHIP_KEY = "bank_sleeves"


def tag_sleeves(candidates: Sequence[Mapping[str, Any]],
                environment_teams: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Stamp each candidate's world and the sleeves it may seat.

    ``bank_sleeve`` is the world a lineup was BUILT in, read off its
    ``bank_job_class`` (salary-only, chalk-fails; untagged is the projection's).
    ``bank_sleeves`` is where it may be SEATED: the environment sleeve is the
    projection world's lineups whose primary stack is a chosen game's team. That
    is a membership and not a separate build, because a job grid restricted to
    teams the ordinary bank already covered solves the same MILP and returns the
    same lineup -- restriction alone is not a different world, the chosen
    environment is. The environment jobs add depth there when the ordinary bank
    stopped short of those teams.
    """
    env = {str(t).upper() for t in (environment_teams or [])}
    out = []
    for c in candidates:
        c = dict(c)
        built = SLEEVE_BY_JOB_CLASS.get(str(c.get("bank_job_class") or ""))
        if built in (SLEEVE_ENVIRONMENT, SLEEVE_TAIL):
            built = SLEEVE_PROJECTION  # a projection-world solve, a narrower grid
        world = built or SLEEVE_PROJECTION
        if world != SLEEVE_PROJECTION:
            c[SLEEVE_TAG_KEY] = world
        members = [world]
        stack = str(c.get("primary_stack") or "").upper()
        if world == SLEEVE_PROJECTION and env and stack in env:
            members.append(SLEEVE_ENVIRONMENT)
        c[SLEEVE_MEMBERSHIP_KEY] = members
        out.append(c)
    return out


def candidate_sleeves(candidate: Mapping[str, Any]) -> List[str]:
    """Every sleeve a candidate may seat (its world, plus environment when it
    stacks a chosen game)."""
    members = candidate.get(SLEEVE_MEMBERSHIP_KEY)
    if members:
        return [str(m) for m in members]
    return [candidate_sleeve(candidate)]


def environment_teams_of(request: Optional[Mapping[str, Any]]) -> Optional[List[str]]:
    """The teams the environment sleeve seats on, or None when the request did
    not keep it (off, dropped, or no game ranked)."""
    req = dict(request or {})
    if not req.get("active") or SLEEVE_ENVIRONMENT not in (req.get("sleeves") or {}):
        return None
    return list((req.get("environment") or {}).get("teams") or []) or None


# --------------------------------------------------------------------------- #
# R422. Tail seats scale with coverage.
# --------------------------------------------------------------------------- #
def tail_token(team: str) -> str:
    """The membership a projection-world lineup whose primary stack is ``team``
    carries, and the sleeve a tail seat pinned to ``team`` asks for."""
    return f"{TAIL_TOKEN_PREFIX}{str(team).strip().upper()}"


def sleeve_family(sleeve: str) -> str:
    """``tail:MIA`` -> ``tail``; every other sleeve is its own family."""
    text = str(sleeve or SLEEVE_PROJECTION)
    return SLEEVE_TAIL if text.startswith(TAIL_TOKEN_PREFIX) else text


def tail_seat_count(n_entries: int, teams_on_slate: int) -> int:
    """Portfolio tail seats: ``clamp(N - C, 0, t)``.

    ``t = S // 3`` tail teams and ``C = S - t`` comfortable ones. No seat opens
    until N could give every comfortable team one stack; then each entry opens
    one, until every tail team holds one at ``N >= S``. More than one per tail
    team waits for the archive measurement (R422(c)).
    """
    s = max(0, int(teams_on_slate))
    t = s // TAIL_DENOMINATOR
    return max(0, min(t, int(n_entries) - (s - t)))


def normalize_implied_totals(
        implied_total_by_team: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """Team code (stripped, upper-case) -> float, skipping values that do not
    parse. The one reader the tail ranking and the market record share, so the
    two cannot key or drop a feed's totals differently."""
    out: Dict[str, float] = {}
    for k, v in (implied_total_by_team or {}).items():
        try:
            out[str(k).strip().upper()] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def rank_tail_teams(
    teams: Iterable[str],
    implied_total_by_team: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """The slate's teams by the MARKET's implied total, and its bottom third.

    Descending, ties by team. The market only: no park-factor or ownership
    fallback, and a team without a total drops the tail by name, because the
    market cannot rank a bottom third it did not price. ``tail_teams`` runs
    highest-implied first, the order seats open in.
    """
    team_list = sorted({str(t).strip().upper() for t in teams if str(t).strip()})
    implied = normalize_implied_totals(implied_total_by_team)
    s = len(team_list)
    t = s // TAIL_DENOMINATOR
    out: Dict[str, Any] = {
        "teams_on_slate": s, "tail_count": t, "comfortable_count": s - t,
        "basis": "none", "tail_teams": [], "implied_total_by_team": {},
        "dropped": None,
        "note": ("the bottom third of the slate's teams by the market's implied "
                 "total; a labeled prior, never a probability"),
    }
    if not implied:
        out["dropped"] = ("no market implied totals were priced; the tail is "
                          "defined by the market only")
        return out
    unpriced = [x for x in team_list if x not in implied]
    if unpriced:
        out["dropped"] = (f"no implied total for {', '.join(unpriced)}; the market "
                          f"cannot rank a bottom third it did not price")
        return out
    if t < 1:
        out["dropped"] = f"{s} team(s) on the slate leave no bottom third"
        return out
    ranked = sorted(team_list, key=lambda x: (-implied[x], x))
    out.update({
        "basis": "implied_total",
        "ranked": ranked,
        "implied_total_by_team": {x: round(implied[x], 3) for x in ranked},
        "tail_teams": ranked[s - t:],
    })
    return out


def tail_seat_plan(
    entry_requirements: Sequence[Mapping[str, Any]],
    rank: Mapping[str, Any],
) -> Dict[str, Any]:
    """Place the portfolio's tail seats and pin each to one team.

    ``T = tail_seat_count(N, S)`` over every entry in the portfolio. Seats go
    only to contests whose shape is in ``TAIL_SHAPES`` with two or more
    entries, at most ``N_c // 2`` per contest (tail never outnumbers
    comfortable inside one; a cash or single-entry POSTURE seats none whatever
    shape it resolved to, as in ``contest_sleeve_weights``), largest ``N_c``
    first and then by contest id -- the build path carries no field size, so
    "largest field first" waits on R422(d). Teams open highest-implied first. Inside a contest the tail seats
    are the LAST entry ids, the end R406 seats its sleeves toward. A seat with
    no room is counted in ``unplaced``, never silently dropped.
    """
    reqs = list(entry_requirements or [])
    n = len(reqs)
    s = int(rank.get("teams_on_slate") or 0)
    plan: Dict[str, Any] = {
        "active": False, "entries": n, "teams_on_slate": s,
        "tail_count": int(rank.get("tail_count") or 0),
        "comfortable_count": int(rank.get("comfortable_count") or 0),
        "basis": rank.get("basis"), "seats": 0, "tail_teams": [],
        "seats_by_contest": {}, "unplaced": [], "placed_teams": [], "team_by_entry": {},
        "dropped": rank.get("dropped"),
        "note": ("a deterministic coverage rule over the market's implied totals; "
                 "it says nothing about how often a tail wins"),
    }
    if rank.get("dropped"):
        return plan
    seats = tail_seat_count(n, s)
    teams = list(rank.get("tail_teams") or [])[:seats]
    plan.update({"seats": seats, "tail_teams": teams,
                 "implied_total_by_team": {t: (rank.get("implied_total_by_team") or {}).get(t)
                                           for t in teams}})
    if not teams:
        return plan
    by_contest: Dict[str, List[Mapping[str, Any]]] = {}
    for req in reqs:
        by_contest.setdefault(str(req.get("contest_id") or ""), []).append(req)
    eligible = [cid for cid, rows in by_contest.items() if len(rows) >= 2 and str(
        rows[0].get("contest_shape") or "").strip().lower() in TAIL_SHAPES
        and str(rows[0].get("posture") or "") not in SINGLE_ENTRY_POSTURES | CASH_POSTURES]
    order = sorted(eligible, key=lambda cid: (-len(by_contest[cid]), cid))
    queue = list(teams)
    for cid in order:
        room = len(by_contest[cid]) // 2
        placed = queue[:room]
        queue = queue[room:]
        if not placed:
            continue
        ids = sorted(str(r.get("entry_id")) for r in by_contest[cid])
        for eid, team in zip(ids[len(ids) - len(placed):], placed):
            plan["team_by_entry"][eid] = team
        plan["seats_by_contest"][cid] = placed
    plan["unplaced"] = queue
    plan["placed_teams"] = [t for t in teams if t not in queue]
    plan["active"] = bool(plan["team_by_entry"])
    if queue:
        plan["unplaced_reason"] = (
            "no top-heavy contest with two or more entries had room "
            "(at most half of a contest's entries seat the tail)")
    return plan


def stamp_tail_seats(entry_requirements: Sequence[Dict[str, Any]],
                     plan: Mapping[str, Any]) -> int:
    """Write each tail seat's team onto its entry requirement, in place, and
    return how many were stamped. A stale stamp from an earlier call is cleared
    first, so the requirements always say what THIS plan placed."""
    team_by_entry = dict(plan.get("team_by_entry") or {})
    stamped = 0
    for req in entry_requirements:
        req.pop(TAIL_TEAM_KEY, None)
        team = team_by_entry.get(str(req.get("entry_id")))
        if team:
            req[TAIL_TEAM_KEY] = team
            stamped += 1
    return stamped

