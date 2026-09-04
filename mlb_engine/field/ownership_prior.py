"""ownership_prior.py — structural ownership prior for MLB Classic.

STATUS: review-only, and WIRED as of R135 (2026-08-17): `tools/ownership_pred.py`
calls both halves, and this module's VERSION is pinned in the audit's
`EXPECTED_VERSION_TEXT` beside the boundary modules. Two claims that used to
head this file were false and are corrected rather than deleted, because three
other documents copied them. It was never UNTRACKED: `git log --follow` puts it
in the v3.0.0-pre restructure commit, the repo's first, so "untracked and
unwired" was half right and the tracked half sent R135 looking for a `git add`
that was not needed. And it is not outside the audit's module count, which is
taken off the filesystem: it has always been one of the 26.

R154 (2026-08-19) narrowed that further, and the sentence that used to sit here
("nothing here is applied to projections, `Ownership_Tier`, or the optimizer")
is now true of only two of those three. `attach_projected_ownership` writes ONE
column, `Projected_Ownership_Pct`, which `optimizer_v3._ownership_pct_for_row`
already read and defaulted to a flat 12.0. `Ownership_Tier` is still never
written, because `_ownership_priority` reads it in one-off selection and an
uncalibrated prior must not reach lineups through a side door.

What made that safe to do on an uncalibrated prior is the first grade, from
contest 194022265 (7,833 entries) on 2026-08-19: Spearman +0.581 against
realized %Drafted on `large_field_gpp`, +0.66 on `cash`, with the LEVEL
under-predicted by about a third and not fixable by rescaling. Ordering is
usable; magnitude is not. So R154 spends the ordering (constraints that rank
lineups by cumulative predicted ownership) and spends none of the magnitude
(no objective coefficient, no per-player value claim). Both open project slots
stay reserved for the fitted model this replaces, which lands once 8-15
archetype-conditioned slates of archived DK standings exist.

Nothing here is a calibrated value: every output
is an UNCALIBRATED STRUCTURAL PRIOR, labeled as such, never a win-rate, ROI,
or probability claim, and never auto-applied to projections, Ownership_Tier,
or the optimizer.

Purpose: start the predict-then-grade loop on slate one instead of waiting to
accumulate data. Each slate this emits a per-player predicted ownership share
per contest archetype from structural features that are public before lock
(salary, position scarcity, implied team total, batting order, probable-SP
status, and optionally a Base projection for value). After the slate, the
archived DK standings' actual %Drafted grades the prediction
(grade_against_actuals), and the graded errors accumulate in the calibration
ledger. The 20-31 percentage-point ownership swings observed for the same
player across contest archetypes on the same slate are encoded as
archetype-conditioned concentration (temperature): cash and single-entry
fields chase value hard (concentrated), large-field GPPs flatten, MME flattens
further. Those temperatures are the primary thing the graded errors should
eventually correct.

Accounting: a DK Classic roster is 2 P + 8 hitters, so across any contest the
pitcher pool's ownership sums to 200% and the hitter pool's to 800%. The prior
allocates those budgets with a softmax over a structural score.

Typical session flow:
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    players = parse_dk_salary_csv("DKSalaries.csv")
    pred = predict_ownership(players,
                             archetype="large_field_gpp",
                             implied_total_by_team={"NYY": 5.4, ...},
                             batting_order_by_player_id=order_map,
                             probable_sp_ids=sp_ids,
                             base_projection_by_player_id=base_map)  # optional
    # after the slate, with actuals joined from the archived standings:
    report = grade_against_actuals(pred["own_pct_by_player_id"], actual_pct)
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

VERSION = "v0.1-prior"

# Archetype-conditioned concentration and feature weights. LABELED PRIORS.
# temperature: lower = more concentrated on the top structural scores (cash
# fields pile onto value); higher = flatter (MME spreads). sp_weight scales the
# probable-SP boost; value_weight scales pts/$ when a Base map is supplied.
ARCHETYPE_PARAMS: Dict[str, Dict[str, float]] = {
    "cash":              {"temperature": 0.55, "sp_weight": 1.20, "value_weight": 1.30},
    "single_entry_gpp":  {"temperature": 0.70, "sp_weight": 1.10, "value_weight": 1.15},
    "wta_satellite":     {"temperature": 0.75, "sp_weight": 1.10, "value_weight": 1.10},
    "small_gpp":         {"temperature": 0.85, "sp_weight": 1.00, "value_weight": 1.00},
    "large_field_gpp":   {"temperature": 1.00, "sp_weight": 1.00, "value_weight": 0.90},
    "mme":               {"temperature": 1.20, "sp_weight": 0.95, "value_weight": 0.80},
}
DEFAULT_ARCHETYPE = "large_field_gpp"

# R136. The engine speaks twelve CONTEST SHAPES and this prior speaks six
# ARCHETYPES, so anything reading a prediction for a real contest has to
# project one vocabulary onto the other. That projection lives here, once,
# rather than in whichever report tool needed it first: a private copy in
# qa_portfolio would have been a second answer to "which archetype is this
# contest", and ownership is CONDITIONED on archetype, so a second answer is a
# pooling bug waiting to happen.
#
# Every value carries how much the projection LOSES, because two of these are
# not the same kind of statement. EXACT means the shape and the archetype name
# the same thing. COLLAPSED means several shapes share one archetype, so the
# projection has thrown away a distinction the engine makes -- five WTA and
# satellite shapes land on one `wta_satellite`, and `mid_field_gpp` has no
# counterpart at all and is read as the flatter neighbour. A caller printing a
# number off a COLLAPSED projection is printing it for a coarser contest than
# the one in hand, and the label is how a reader knows that.
ARCHETYPE_BY_CONTEST_SHAPE: Dict[str, Tuple[str, str]] = {
    "cash":                 ("cash", "EXACT"),
    "single_entry_gpp":     ("single_entry_gpp", "EXACT"),
    "small_field_gpp":      ("small_gpp", "EXACT"),
    "large_field_gpp":      ("large_field_gpp", "EXACT"),
    "mme_gpp":              ("mme", "EXACT"),
    "mid_field_gpp":        ("large_field_gpp", "COLLAPSED"),
    "portfolio_gpp":        ("mme", "COLLAPSED"),
    "small_wta":            ("wta_satellite", "COLLAPSED"),
    "mid_wta":              ("wta_satellite", "COLLAPSED"),
    "large_wta":            ("wta_satellite", "COLLAPSED"),
    "wta_ticket_satellite": ("wta_satellite", "COLLAPSED"),
    "satellite":            ("wta_satellite", "COLLAPSED"),
}


def archetype_for_contest_shape(shape: object) -> Optional[Tuple[str, str]]:
    """(archetype, EXACT|COLLAPSED) for a contest shape, or None if unknown.

    None rather than DEFAULT_ARCHETYPE on purpose. A shape this map does not
    carry is a shape somebody added to ``contest_shapes`` without deciding what
    the field does in it, and answering that with the default would price the
    contest against a large-field GPP crowd while saying nothing. The import
    check below is what makes that case unreachable in a released tree; the
    None is for a caller holding a shape string from a file rather than from
    the vocabulary.
    """
    return ARCHETYPE_BY_CONTEST_SHAPE.get(str(shape or "").strip().lower())


def _check_shape_projection() -> None:
    """The map covers the closed shape set exactly, checked at import.

    ``contest_shapes`` is the vocabulary and every producer of a shape
    validates against it at import (CLAUDE.md). This is the consumer side of
    the same rule: adding a thirteenth shape and forgetting the field it
    implies fails here, loudly, at import, instead of silently defaulting a
    live contest to the wrong crowd.
    """
    from mlb_engine.contest_shapes import CONTEST_SHAPES

    missing = sorted(set(CONTEST_SHAPES) - set(ARCHETYPE_BY_CONTEST_SHAPE))
    extra = sorted(set(ARCHETYPE_BY_CONTEST_SHAPE) - set(CONTEST_SHAPES))
    if missing or extra:
        raise ImportError(
            "ARCHETYPE_BY_CONTEST_SHAPE must cover contest_shapes.CONTEST_SHAPES "
            f"exactly; missing {missing}, not a shape {extra}")
    unknown = sorted({a for a, _ in ARCHETYPE_BY_CONTEST_SHAPE.values()}
                     - set(ARCHETYPE_PARAMS))
    if unknown:
        raise ImportError(
            f"ARCHETYPE_BY_CONTEST_SHAPE maps to unknown archetype(s) {unknown}")
    bad = sorted({e for _, e in ARCHETYPE_BY_CONTEST_SHAPE.values()}
                 - {"EXACT", "COLLAPSED"})
    if bad:
        raise ImportError(f"unknown projection exactness {bad}")


_check_shape_projection()

def archetype_for_contest_facts(
    contest_type: object,
    field_size: object,
    max_entries: object,
) -> Optional[Tuple[str, str]]:
    """(archetype, EXACT|COLLAPSED) from the facts an ARCHIVED contest carries.

    R306 step 1. Grading the archive means answering "which archetype was this
    contest" for a contest that is over, and the only facts on disk for one are
    its DK name (which the name-archetype layer turns into a ``contest_type``),
    its field size, and an inferred max-entries. There is no prize pool and no
    payout schedule, so there is no ``ContestCard`` to hand
    ``contest_shape_for_card``.

    The temptation is a second classifier here. That is the exact bug
    ``ARCHETYPE_BY_CONTEST_SHAPE``'s own comment was written against: ownership
    is CONDITIONED on archetype, so a second answer to "which archetype is this
    contest" is a pooling bug waiting to happen. So this does not decide a
    shape. It CALLS ``contest_shape_for_card`` on a card carrying the three
    facts, and the import check below proves the fields it had to invent to
    build that card (buy-in, prize pool, payout rows, ticket count) cannot
    reach the answer: for every contest type and every field-size band, the
    archetype is invariant under all of them. If a future edit makes one of
    them matter, the check fails at import rather than silently pricing an
    archived contest against the wrong crowd.

    None, never a default, for a contest type this cannot resolve -- same
    reasoning as ``archetype_for_contest_shape`` above.
    """
    from mlb_engine.allocate.contest_allocator import (
        CONTEST_TYPES, ContestCard, contest_shape_for_card,
    )

    ctype = str(contest_type or "").strip().lower()
    if ctype not in CONTEST_TYPES:
        return None
    try:
        size = int(field_size)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    try:
        entries = int(max_entries)
    except (TypeError, ValueError):
        entries = 1
    card = ContestCard(contest_id="", name="", contest_type=ctype,
                       field_size=size, max_entries=max(1, entries),
                       buy_in=0.0, prize_pool=0.0)
    return archetype_for_contest_shape(contest_shape_for_card(card))


# The bands ``contest_shape_for_card`` splits field size on, plus one value
# either side of each boundary. Used only by the import check below; a band
# table that drifts from the allocator's thresholds makes the check weaker,
# never wrong, because the check calls the allocator rather than these numbers.
_FIELD_SIZE_PROBES: Tuple[int, ...] = (1, 20, 500, 501, 5000, 5001, 100000)


def _check_contest_fact_projection() -> None:
    """The invented card fields cannot reach the archetype. Checked at import.

    ``archetype_for_contest_facts`` builds a ``ContestCard`` with a zero buy-in,
    a zero prize pool, no payout rows and no ticket count, because an archived
    contest carries none of them. That is only safe while the archetype does
    not depend on them. This asserts it by construction rather than by reading
    the allocator's branches: for every contest type and field-size probe, vary
    each invented field and require one distinct archetype.
    """
    from mlb_engine.allocate.contest_allocator import (
        CONTEST_TYPES, ContestCard, PayoutRow, contest_shape_for_card,
    )

    variants = (
        {},
        {"buy_in": 25.0, "prize_pool": 100000.0},
        {"satellite_tickets": 1},
        {"satellite_tickets": 40},
        {"payout_rows": [PayoutRow(1, 1, 100.0)]},
        {"payout_rows": [PayoutRow(1, 50, 5.0)]},
    )
    for ctype in sorted(CONTEST_TYPES):
        for size in _FIELD_SIZE_PROBES:
            for entries in (1, 20, 150):
                seen = set()
                for extra in variants:
                    kwargs = {"contest_id": "", "name": "",
                              "contest_type": ctype, "field_size": size,
                              "max_entries": entries, "buy_in": 0.0,
                              "prize_pool": 0.0}
                    kwargs.update(extra)
                    seen.add(archetype_for_contest_shape(
                        contest_shape_for_card(ContestCard(**kwargs))))
                if len(seen) != 1:
                    raise ImportError(
                        "archetype_for_contest_facts invents buy-in, prize pool, "
                        "payout rows and ticket count, and one of them now "
                        f"reaches the archetype: contest_type={ctype!r} "
                        f"field_size={size} max_entries={entries} yields "
                        f"{sorted(str(s) for s in seen)}. Resolve the archived "
                        "contest's real value or refuse; do not default it.")


HITTER_BUDGET_PCT = 800.0   # 8 hitter slots per roster
PITCHER_BUDGET_PCT = 200.0  # 2 P slots per roster

# R306. A DK SHOWDOWN roster is one CPT plus five UTIL, so across a contest the
# captain slot's shares sum to 100% and the six-slot person market's to 600%.
# Measured at exactly those two values in all 41 of 41 archived Showdown
# contests carrying at least 10 complete entries with a captain -- one distinct
# value each, which is an accounting identity and not an estimate. The Classic
# 800/200 pair above has no Showdown analogue and this module carried only it.
CAPTAIN_BUDGET_PCT = 100.0          # 1 CPT slot per Showdown roster
SHOWDOWN_ROSTER_BUDGET_PCT = 600.0  # 6 roster slots per Showdown roster

# R306. The captain slot's own concentration and pitcher tilt, per archetype.
# LABELED PRIORS, exactly like ARCHETYPE_PARAMS above, and read only by
# ``predict_captain_ownership``.
#
# HOW THESE WERE SET, because "fit per archetype" would overstate it. The
# archive's usable Showdown contests are 37 of 41 `wta_satellite` and the
# remaining four resolve to no archetype at all, so ONE archetype has evidence
# and five do not. Pretending to six fits would be six numbers with one
# measurement behind them. Instead: `wta_satellite` carries values jointly fit
# against the 41 archived contests, and every other archetype carries its
# ROSTER temperature scaled by CAPTAIN_TEMPERATURE_RATIO -- one relationship,
# stated once, that says the captain market is more concentrated than the
# roster market by the factor the fitted archetype shows. A five-archetype
# table of independently invented numbers would read as five measurements.
#
# THE FIT, and what it can and cannot claim. Two parameters against two
# measured medians over the 41 contests: realized top-captain share 32.7% and
# realized arm share of the captain slot 52.2%. A joint grid settles at
# temperature 0.13 and pitcher weight 0.10, reproducing 32.5% and 51.9%, both
# gaps under half a point. Three properties of that fit are worth stating
# because each one bounds what the number means.
#
#   Temperature buys NO ordering, and that is analytic rather than lucky. A
#   softmax is monotone in the score and Spearman is computed on ranks, so
#   every temperature yields the identical ordering: median Spearman sits at
#   0.746-0.750 across the whole swept range. Temperature is therefore fit to
#   CONCENTRATION only, and no setting of it can spend magnitude the project
#   does not have.
#
#   The pitcher tilt is small but it is NOT decoration. Pinned at zero,
#   temperature alone cannot reach both targets: the best achievable worst-gap
#   is 7.3 points, with the arm share stuck at 44.9% against a realized 52.2%.
#   It is also nearly ordering-neutral (median Spearman 0.747 at zero against
#   0.746-0.750 fitted, and the WORST contest gets slightly worse, 0.311 ->
#   0.286), which corrects the naive reading of the archive's arm skew: arms
#   are the most expensive players on a Showdown slate, so a salary percentile
#   over one pool already ranks them at the top and the tilt is doing
#   concentration work, not ranking work.
#
#   The fit was made with the implied-total and value tilts INERT, because an
#   archived slate carries no odds packet joined to the contest and no Base
#   map. A live emit supplies both, so a live captain distribution is shaped by
#   inputs the fit never saw. Treat the fitted concentration as a floor on how
#   sharp this market is, not as a setting validated end to end.
#
# THE ZERO TAIL BELONGS IN THE GRADE, and leaving it out is not conservative.
# On a Showdown slate the salary file IS the contest's player pool, so a player
# nobody captained has an OBSERVED captain share of 0.0 -- an observed count,
# not a missing value, and a different fact from the Classic case
# ``own_by_player_norm`` is careful about, where DK simply lists no share.
# Grading only the players who WERE captained truncates the sample at the end
# the prior is most likely to get wrong, and it does not bias in a predictable
# direction: on the same 41 contests, dropping the tail moves median Spearman
# from 0.547 to 0.746 on the captain market and from 0.618 to 0.499 on the
# roster market. Up on one, down on the other. Both grade paths zero-fill the
# pool.
#
# Neither parameter is calibrated and neither may reach the optimizer. R154's
# ruling holds here and is if anything sharper: spend the ORDERING, spend none
# of the magnitude.
CAPTAIN_TEMPERATURE_RATIO = 0.1733
CAPTAIN_PITCHER_WEIGHT = 0.10

CAPTAIN_ARCHETYPE_PARAMS: Dict[str, Dict[str, float]] = {
    name: {
        "temperature": round(params["temperature"] * CAPTAIN_TEMPERATURE_RATIO, 4),
        "captain_pitcher_weight": CAPTAIN_PITCHER_WEIGHT,
        "value_weight": params["value_weight"],
        "fitted": 0.0,
    }
    for name, params in ARCHETYPE_PARAMS.items()
}
CAPTAIN_ARCHETYPE_PARAMS["wta_satellite"].update(
    {"temperature": 0.13, "captain_pitcher_weight": 0.10, "fitted": 1.0})

# R306. The six-slot Showdown ROSTER market's own parameters. Same structure,
# same one fitted archetype, same joint grid, against its own two measured
# medians over the same 41 contests: realized top-PERSON share 69.8% and
# realized arm share of the six-slot market 114.3%. Settles at temperature 0.17
# and pitcher weight -0.10, reproducing 69.4% and 115.1%.
#
# THE PITCHER WEIGHT IS NEGATIVE HERE AND POSITIVE ON THE CAPTAIN SLOT, and
# that sign flip is the R306 finding stated in one parameter each. Relative to
# where salary rank alone puts them, the field UP-weights arms for the captain
# slot and DOWN-weights them across the six roster slots: a zero weight
# predicts 156.5% arm share against a realized 114.3%, because two arms sit at
# the top of a Showdown salary file and a lineup can only usefully hold so many
# of them. A single ownership number cannot carry both signs, which is the
# mechanism behind a 60%-rostered player landing at 6% captain.
#
# This table exists because the Classic 800/200 split is not the Showdown
# geometry, not because the roster market needed re-modelling.
SHOWDOWN_ROSTER_TEMPERATURE_RATIO = 0.2267
SHOWDOWN_ROSTER_PITCHER_WEIGHT = -0.10

SHOWDOWN_ROSTER_ARCHETYPE_PARAMS: Dict[str, Dict[str, float]] = {
    name: {
        "temperature": round(params["temperature"]
                             * SHOWDOWN_ROSTER_TEMPERATURE_RATIO, 4),
        "roster_pitcher_weight": SHOWDOWN_ROSTER_PITCHER_WEIGHT,
        "value_weight": params["value_weight"],
        "fitted": 0.0,
    }
    for name, params in ARCHETYPE_PARAMS.items()
}
SHOWDOWN_ROSTER_ARCHETYPE_PARAMS["wta_satellite"].update(
    {"temperature": 0.17, "roster_pitcher_weight": -0.10, "fitted": 1.0})

SHOWDOWN_ROSTER_NOTE = (
    "UNCALIBRATED STRUCTURAL PRIOR over the six-slot SHOWDOWN ROSTER market, "
    "budget 600%. `predict_ownership`'s 800/200 split is the CLASSIC roster "
    "and sums to 1000% on a Showdown file, which is no contest's accounting. "
    "Fit only on `wta_satellite`, the one archetype the archive covers. Never "
    "a win rate, an ROI figure, a cash rate, or a probability claim; never fed "
    "to the optimizer, to projections, or to Ownership_Tier."
)

CAPTAIN_NOTE = (
    "UNCALIBRATED STRUCTURAL PRIOR over the SHOWDOWN CAPTAIN SLOT, a separate "
    "100% budget from the 600% six-slot roster prior beside it. Fit only on "
    "`wta_satellite`, the one archetype the archive covers; every other "
    "archetype carries its roster temperature scaled by one stated ratio. "
    "Never a win rate, an ROI figure, a cash rate, or a probability claim; "
    "never fed to the optimizer, to projections, or to Ownership_Tier. The "
    "archive it was swept against is small-field satellites in which Ben's own "
    "entries sit in the denominator, so the concentration it reproduces "
    "carries a self-inclusion bias that a larger sample dilutes and does not "
    "remove."
)


def _check_captain_params() -> None:
    """Every params table covers the same archetypes. Checked at import.

    An archetype in one table and not another is a caller getting a captain
    distribution for a contest whose roster distribution came from a different
    archetype, or a KeyError at emit time on a live slate. Cheap to assert
    here, expensive to find there.
    """
    for label, table, weight_key in (
        ("CAPTAIN_ARCHETYPE_PARAMS", CAPTAIN_ARCHETYPE_PARAMS,
         "captain_pitcher_weight"),
        ("SHOWDOWN_ROSTER_ARCHETYPE_PARAMS", SHOWDOWN_ROSTER_ARCHETYPE_PARAMS,
         "roster_pitcher_weight"),
    ):
        missing = sorted(set(ARCHETYPE_PARAMS) - set(table))
        extra = sorted(set(table) - set(ARCHETYPE_PARAMS))
        if missing or extra:
            raise ImportError(
                f"{label} must cover ARCHETYPE_PARAMS exactly; "
                f"missing {missing}, unknown {extra}")
        for name, params in sorted(table.items()):
            for key in ("temperature", weight_key, "value_weight"):
                if key not in params:
                    raise ImportError(f"{label}[{name!r}] is missing {key!r}")
            if float(params["temperature"]) <= 0.0:
                raise ImportError(
                    f"{label}[{name!r}] temperature must be positive; a "
                    "non-positive temperature makes the softmax a point mass "
                    "and the whole budget lands on one player")
    # The two Showdown budgets are the DK roster: one captain plus five UTIL.
    # A drift in either constant silently rebases every share this module
    # emits for a Showdown slate, and the 100/600 pair is an accounting
    # identity measured at exactly those values in 41 of 41 archived contests.
    if CAPTAIN_BUDGET_PCT <= 0 or SHOWDOWN_ROSTER_BUDGET_PCT <= 0:
        raise ImportError("Showdown budgets must be positive")
    if round(SHOWDOWN_ROSTER_BUDGET_PCT / CAPTAIN_BUDGET_PCT, 6) != 6.0:
        raise ImportError(
            "the Showdown roster budget must be six times the captain budget: "
            "a DK Showdown roster is one CPT plus five UTIL, so the person "
            f"market sums to 600% and the captain slot to 100%, not "
            f"{SHOWDOWN_ROSTER_BUDGET_PCT}/{CAPTAIN_BUDGET_PCT}")


_check_contest_fact_projection()
_check_captain_params()

# Batting-order attention prior: earlier slots draw more ownership. Distinct
# from the engine's F2 (a scoring factor); this is a field-behavior prior.
ORDER_ATTENTION = {1: 1.15, 2: 1.12, 3: 1.12, 4: 1.10, 5: 1.02,
                   6: 0.95, 7: 0.88, 8: 0.82, 9: 0.78}
LEAGUE_MEAN_IMPLIED = 4.5   # runs; used when a team's implied total is absent


def _is_pitcher(positions: Iterable[str]) -> bool:
    return "P" in {str(p).strip().upper() for p in positions}


def _player_record(p: Any) -> Dict[str, Any]:
    """Accept slate_intake_manager player objects or plain dicts."""
    if isinstance(p, Mapping):
        return {"id": str(p.get("player_id") or p.get("Player_ID") or p.get("id")),
                "name": str(p.get("name") or p.get("Name") or ""),
                "team": str(p.get("team") or p.get("Team") or "").strip().upper(),
                "salary": float(p.get("salary") or p.get("Salary") or 0.0),
                "positions": [t for t in str(p.get("positions") or p.get("Position") or "").replace("/", ",").split(",") if t]
                             if not isinstance(p.get("positions"), (list, tuple)) else list(p.get("positions"))}
    return {"id": str(getattr(p, "player_id")), "name": str(getattr(p, "name", "")),
            "team": str(getattr(p, "team", "")).strip().upper(),
            "salary": float(getattr(p, "salary", 0.0)),
            "positions": list(getattr(p, "positions", []))}


def _softmax_shares(scores: Dict[str, float], temperature: float) -> Dict[str, float]:
    if not scores:
        return {}
    t = max(float(temperature), 1e-6)
    peak = max(scores.values())
    exps = {k: math.exp((v - peak) / t) for k, v in scores.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}


def predict_ownership(
    salary_players: Iterable[Any],
    archetype: str = DEFAULT_ARCHETYPE,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
    batting_order_by_player_id: Optional[Mapping[str, int]] = None,
    probable_sp_ids: Optional[Iterable[str]] = None,
    base_projection_by_player_id: Optional[Mapping[str, float]] = None,
    archetype_params: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[str, Any]:
    """Return the structural ownership prior for one contest archetype.

    Output dict:
      own_pct_by_player_id  — predicted %Drafted per player (hitters sum ~800,
                              pitchers ~200)
      tier_by_player_id     — High / Mid / Low by within-pool percentile
                              (top 15% High, bottom 40% Low), the ONLY field
                              ever eligible to feed Ownership_Tier, and only on
                              explicit operator opt-in
      archetype, params, note — provenance and the truthful label

    Structural score per player (before the softmax):
      salary percentile within the P/hitter pool
      + implied-total tilt (hitters; team implied over league mean)
      + batting-order attention prior (hitters with a known/projected slot)
      + probable-SP boost (pitchers; the field concentrates on named starters)
      + optional value tilt (pts/$ percentile when a Base map is supplied)
    """
    params_table = dict(ARCHETYPE_PARAMS)
    if archetype_params:
        params_table.update({k: dict(v) for k, v in archetype_params.items()})
    params = params_table.get(str(archetype), params_table[DEFAULT_ARCHETYPE])

    implied = {str(k).strip().upper(): float(v) for k, v in (implied_total_by_team or {}).items()}
    orders = {str(k): int(v) for k, v in (batting_order_by_player_id or {}).items()}
    sp_set = {str(x) for x in (probable_sp_ids or [])}
    bases = {str(k): float(v) for k, v in (base_projection_by_player_id or {}).items()}

    records = [_player_record(p) for p in salary_players]
    pitchers = [r for r in records if _is_pitcher(r["positions"])]
    hitters = [r for r in records if not _is_pitcher(r["positions"])]

    def _pool_scores(pool: List[Dict[str, Any]], is_pitcher_pool: bool) -> Dict[str, float]:
        if not pool:
            return {}
        salaries = sorted(r["salary"] for r in pool)
        n = len(salaries)

        def pct_of(value: float, ordered: List[float]) -> float:
            below = sum(1 for s in ordered if s < value)
            equal = sum(1 for s in ordered if s == value)
            return (below + 0.5 * equal) / max(len(ordered), 1)

        value_pool: List[Tuple[str, float]] = []
        for r in pool:
            base = bases.get(r["id"])
            if base is not None and r["salary"] > 0:
                value_pool.append((r["id"], base / (r["salary"] / 1000.0)))
        value_sorted = sorted(v for _, v in value_pool)
        value_pct = {pid: pct_of(v, value_sorted) for pid, v in value_pool}

        scores: Dict[str, float] = {}
        for r in pool:
            score = pct_of(r["salary"], salaries)  # salary as the baseline attention proxy
            if is_pitcher_pool:
                if r["id"] in sp_set:
                    score += 0.60 * params["sp_weight"]
                else:
                    score -= 0.80  # non-probable arms draw near-zero classic ownership
            else:
                team_implied = implied.get(r["team"], LEAGUE_MEAN_IMPLIED)
                score += 0.35 * (team_implied - LEAGUE_MEAN_IMPLIED)
                slot = orders.get(r["id"])
                if slot is not None:
                    score += ORDER_ATTENTION.get(int(slot), 0.90) - 1.0
                else:
                    score -= 0.15  # no known slot: the field discounts TBD bats
            if r["id"] in value_pct:
                score += params["value_weight"] * (value_pct[r["id"]] - 0.5)
            scores[r["id"]] = score
        return scores

    hitter_shares = _softmax_shares(_pool_scores(hitters, False), params["temperature"])
    pitcher_shares = _softmax_shares(_pool_scores(pitchers, True), params["temperature"])

    own: Dict[str, float] = {}
    own.update({pid: round(share * HITTER_BUDGET_PCT, 2) for pid, share in hitter_shares.items()})
    own.update({pid: round(share * PITCHER_BUDGET_PCT, 2) for pid, share in pitcher_shares.items()})

    def _tiers(shares: Mapping[str, float]) -> Dict[str, str]:
        if not shares:
            return {}
        ordered = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)
        n = len(ordered)
        out: Dict[str, str] = {}
        for rank, (pid, _) in enumerate(ordered):
            frac = rank / max(n - 1, 1)
            out[pid] = "High" if frac <= 0.15 else ("Low" if frac >= 0.60 else "Mid")
        return out

    tiers = {**_tiers(hitter_shares), **_tiers(pitcher_shares)}
    return {
        "own_pct_by_player_id": own,
        "tier_by_player_id": tiers,
        "archetype": str(archetype),
        "params": dict(params),
        "prior_version": VERSION,
        "note": (
            "UNCALIBRATED STRUCTURAL PRIOR. Predicted %Drafted from salary, implied "
            "totals, batting order, probable-SP status, and optional value; archetype-"
            "conditioned concentration encodes the observed cross-archetype ownership "
            "swings. Never a win-rate, ROI, or probability claim; never auto-applied "
            "to projections, Ownership_Tier, or the optimizer. Grade every slate "
            "against archived DK standings and reconcile errors into the calibration "
            "ledger; the fitted replacement takes a tracked project slot."
        ),
    }


def _single_pool_shares(
    records: List[Dict[str, Any]],
    temperature: float,
    pitcher_weight: float,
    value_weight: float,
    implied: Mapping[str, float],
    orders: Mapping[str, int],
    sp_set: Iterable[str],
    bases: Mapping[str, float],
) -> Dict[str, float]:
    """Softmax shares (summing to 1.0) over ONE pool of PEOPLE.

    The Showdown core, shared by both distributions below. The roster prior
    above scores hitters and pitchers in separate pools because a Classic
    roster fills 8 and 2 slots from separate menus; a Showdown roster fills six
    interchangeable slots and a captain fills one, both from the whole field,
    so the salary percentile is taken over every player rather than within a
    position pool.

    One function rather than two near-copies: the two Showdown distributions
    differ only in their temperature, their pitcher weight and their budget,
    and a second copy of this scoring is how the captain and roster halves
    would end up disagreeing about what a player's structural score is.
    """
    if not records:
        return {}
    sp = {str(x) for x in sp_set}
    salaries = sorted(r["salary"] for r in records)

    def pct_of(value: float, ordered: List[float]) -> float:
        below = sum(1 for s in ordered if s < value)
        equal = sum(1 for s in ordered if s == value)
        return (below + 0.5 * equal) / max(len(ordered), 1)

    value_pool: List[Tuple[str, float]] = []
    for r in records:
        base = bases.get(r["id"])
        if base is not None and r["salary"] > 0:
            value_pool.append((r["id"], base / (r["salary"] / 1000.0)))
    value_sorted = sorted(v for _, v in value_pool)
    value_pct = {pid: pct_of(v, value_sorted) for pid, v in value_pool}

    scores: Dict[str, float] = {}
    for r in records:
        score = pct_of(r["salary"], salaries)
        if _is_pitcher(r["positions"]):
            if r["id"] in sp:
                score += float(pitcher_weight)
            else:
                # A Showdown salary file lists the day's relievers too and the
                # field does not roster them. Same discount the Classic prior
                # applies to a non-probable arm.
                score -= 0.80
        else:
            team_implied = implied.get(r["team"], LEAGUE_MEAN_IMPLIED)
            score += 0.35 * (team_implied - LEAGUE_MEAN_IMPLIED)
            slot = orders.get(r["id"])
            if slot is not None:
                score += ORDER_ATTENTION.get(int(slot), 0.90) - 1.0
            else:
                score -= 0.15
        if r["id"] in value_pct:
            score += float(value_weight) * (value_pct[r["id"]] - 0.5)
        scores[r["id"]] = score
    return _softmax_shares(scores, temperature)


def _showdown_prediction(
    salary_players: Iterable[Any],
    archetype: str,
    params_table: Mapping[str, Mapping[str, float]],
    budget_pct: float,
    pitcher_weight_key: str,
    note: str,
    implied_total_by_team: Optional[Mapping[str, float]],
    batting_order_by_player_id: Optional[Mapping[str, int]],
    probable_sp_ids: Optional[Iterable[str]],
    base_projection_by_player_id: Optional[Mapping[str, float]],
    archetype_params: Optional[Mapping[str, Mapping[str, float]]],
) -> Dict[str, Any]:
    """One Showdown distribution: shares over one pool, scaled to one budget."""
    table = {k: dict(v) for k, v in params_table.items()}
    if archetype_params:
        table.update({k: dict(v) for k, v in archetype_params.items()})
    params = table.get(str(archetype), table[DEFAULT_ARCHETYPE])

    implied = {str(k).strip().upper(): float(v)
               for k, v in (implied_total_by_team or {}).items()}
    orders = {str(k): int(v) for k, v in (batting_order_by_player_id or {}).items()}
    bases = {str(k): float(v)
             for k, v in (base_projection_by_player_id or {}).items()}

    records = [_player_record(p) for p in salary_players]
    shares = _single_pool_shares(
        records,
        temperature=float(params["temperature"]),
        pitcher_weight=float(params[pitcher_weight_key]),
        value_weight=float(params["value_weight"]),
        implied=implied, orders=orders,
        sp_set=probable_sp_ids or [], bases=bases,
    )
    own = {pid: round(share * float(budget_pct), 2)
           for pid, share in shares.items()}

    ordered = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))
    tiers: Dict[str, str] = {}
    for rank, (pid, _) in enumerate(ordered):
        frac = rank / max(len(ordered) - 1, 1)
        tiers[pid] = "High" if frac <= 0.15 else ("Low" if frac >= 0.60 else "Mid")

    return {
        "own_pct_by_player_id": own,
        "tier_by_player_id": tiers,
        "archetype": str(archetype),
        "params": dict(params),
        "prior_version": VERSION,
        "budget_pct": float(budget_pct),
        "note": note,
    }


def predict_showdown_roster_ownership(
    salary_players: Iterable[Any],
    archetype: str = DEFAULT_ARCHETYPE,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
    batting_order_by_player_id: Optional[Mapping[str, int]] = None,
    probable_sp_ids: Optional[Iterable[str]] = None,
    base_projection_by_player_id: Optional[Mapping[str, float]] = None,
    archetype_params: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[str, Any]:
    """The six-slot SHOWDOWN ROSTER prior, budget 600%. R306 step 2.

    ``predict_ownership`` above allocates 800% to hitters and 200% to pitchers
    because that is the Classic roster. Handed a Showdown salary file it does
    the same thing and the shares sum to 1000%, which is not any contest's
    accounting: a Showdown roster is six people, so the person market sums to
    600% -- measured at exactly 600.0 in all 41 of 41 archived Showdown
    contests. The Classic function is left alone rather than taught a second
    geometry, because every one of its callers is a Classic caller and a
    geometry flag on it is the shape of defect this project keeps paying for.

    This does NOT undo R235's CPT/UTIL person collapse. The collapse produces
    one row per PERSON, which is exactly the grain a 600% person market wants;
    this allocates the six-slot budget over those people, and
    ``predict_captain_ownership`` allocates the one-slot budget over the same
    people. Two allocations, one collapsed pool.
    """
    return _showdown_prediction(
        salary_players, archetype, SHOWDOWN_ROSTER_ARCHETYPE_PARAMS,
        SHOWDOWN_ROSTER_BUDGET_PCT, "roster_pitcher_weight",
        SHOWDOWN_ROSTER_NOTE, implied_total_by_team,
        batting_order_by_player_id, probable_sp_ids,
        base_projection_by_player_id, archetype_params)


def predict_captain_ownership(
    salary_players: Iterable[Any],
    archetype: str = DEFAULT_ARCHETYPE,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
    batting_order_by_player_id: Optional[Mapping[str, int]] = None,
    probable_sp_ids: Optional[Iterable[str]] = None,
    base_projection_by_player_id: Optional[Mapping[str, float]] = None,
    archetype_params: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[str, Any]:
    """The structural prior for the SHOWDOWN CAPTAIN SLOT. R306 step 2.

    A second distribution over the same people, with its own 100% budget and
    its own temperature, to sit BESIDE ``predict_ownership``'s 600% roster
    prior rather than replace it. It is not a re-expansion of R235's CPT/UTIL
    person collapse: the collapse gives one row per PERSON, which is what both
    distributions want, and this allocates a different slot over those same
    people.

    Why it is a separate distribution and not a rescaling of the roster one:
    on 41 archived Showdown contests the captain market is measurably a
    different market. Person-level and captain-level ownership correlate
    between 0.33 and 0.85, a 60%-rostered player has landed at 6% captain, and
    the captain slot is held by an ARM in a median 52.2% of entries against
    arms taking a median 19.0% of all six roster slots. So the captain slot
    gets its own concentration and its own pitcher tilt, both LABELED PRIORS.

    Three ways this differs from the roster prior, each deliberate:

      ONE POOL. The roster prior scores hitters and pitchers separately
      because a Classic roster fills 8 and 2 slots from separate menus. A
      captain is chosen across the whole field for one slot, so the salary
      percentile is taken over every player rather than within a pool.

      ITS OWN TEMPERATURE. Concentration is the parameter the module already
      models per archetype, and Showdown CPT is a different temperature from
      Showdown UTIL inside the same contest: 6 to 21 distinct captains appear
      per contest against roughly 20 rostered people, with the top captain
      taking a median 32.7%.

      AN EXPLICIT PITCHER TILT. In one pool a hitter collects the implied-total
      and batting-order tilts and an arm collects neither, so without a tilt
      the arm skew the archive shows could only appear through salary. The
      measured skew is not a constant -- it ranges 21.5% to 73.9% across the
      41 -- so the tilt is applied to PROBABLE starters only and the rest of
      the shape is left to the structural score, rather than pinning a rate.

    Output mirrors ``predict_ownership``: ``own_pct_by_player_id`` (summing to
    CAPTAIN_BUDGET_PCT), ``tier_by_player_id``, provenance and the label.
    UNCALIBRATED, like everything else here; nothing auto-applies.
    """
    return _showdown_prediction(
        salary_players, archetype, CAPTAIN_ARCHETYPE_PARAMS,
        CAPTAIN_BUDGET_PCT, "captain_pitcher_weight", CAPTAIN_NOTE,
        implied_total_by_team, batting_order_by_player_id, probable_sp_ids,
        base_projection_by_player_id, archetype_params)


PROJECTED_OWNERSHIP_COLUMN = "Projected_Ownership_Pct"


def attach_predicted_ownership(
    projections_df: Any,
    own_pct_by_player_id: Mapping[str, float],
    source: Optional[str] = None,
    overwrite: bool = False,
) -> Tuple[Any, Dict[str, Any]]:
    """Write ``Projected_Ownership_Pct`` onto a COPY of a frame from an EMITTED
    prediction file, rather than recomputing the prior here.

    R246. ``attach_projected_ownership`` above derives the column from the
    frame's own features; this writes the numbers a slate's
    ``ownership_pred_<tag>.json`` already carries, which is the artifact R209
    actually graded (Spearman +0.581 over 112 graded players) and the artifact
    whose sha256 a brief can name. Two functions rather than one because they
    answer different questions -- "what would this prior say" and "what did that
    file say" -- and collapsing them would make the recorded sha describe an
    input that was then recomputed.

    Same three limits as its sibling, restated because they are the reason this
    is safe: it writes ONE column, that column has exactly one reader in the
    engine (``optimizer_v3._ownership_pct_for_row``), and it does NOT touch
    ``Ownership_Tier``, which is behaviour-bearing in one-off selection. So
    attaching changes no lineup by itself; the two R154 controls are off unless
    a caller passes a number.

    **This is an UNCALIBRATED, UNGRADED PRIOR.** Its ORDERING is what R209
    measured as usable and its LEVEL is explicitly not; one slate cannot size a
    coefficient. Nothing here is an ROI, win-rate, cash-rate or probability
    claim, and a caller that reports it must say so.

    Players absent from the map are left to ``_ownership_pct_for_row``'s own
    fallback rather than being written a number this file never predicted, and
    they are COUNTED, because a prediction file that covers half the pool makes
    a cumulative cap mean half of what the operator asked for.
    """
    frame = projections_df.copy()
    report: Dict[str, Any] = {
        "applied": False, "reason": None, "source": source,
        "prior_version": VERSION, "players_scored": 0, "players_unscored": 0,
        "unscored_player_ids": [], "column": PROJECTED_OWNERSHIP_COLUMN,
        "label": ("UNCALIBRATED, UNGRADED PRIOR read from an emitted prediction "
                  "file; its ORDERING is what has been measured and its LEVEL "
                  "has not. A predicted share, never a measured one, and never "
                  "an ROI, win-rate, cash-rate or probability claim."),
    }
    if PROJECTED_OWNERSHIP_COLUMN in getattr(frame, "columns", []) and not overwrite:
        report["reason"] = "column_present_and_overwrite_false"
        return frame, report
    supplied = {str(k).strip(): v for k, v in dict(own_pct_by_player_id or {}).items()}
    if not supplied:
        report["reason"] = "no_predicted_ownership_supplied"
        return frame, report
    if not len(getattr(frame, "index", [])):
        report["reason"] = "empty_frame"
        return frame, report

    values, unscored = [], []
    for pid in frame["Player_ID"]:
        key = str(pid).strip()
        raw = supplied.get(key)
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            values.append(float("nan"))
            unscored.append(key)
    frame[PROJECTED_OWNERSHIP_COLUMN] = values
    report.update({
        "applied": True,
        "players_scored": len(values) - len(unscored),
        "players_unscored": len(unscored),
        "unscored_player_ids": sorted(unscored),
    })
    return frame, report


def attach_projected_ownership(
    projections_df: Any,
    contest_shape: object = None,
    archetype: Optional[str] = None,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
    overwrite: bool = False,
) -> Tuple[Any, Dict[str, Any]]:
    """Write ``Projected_Ownership_Pct`` onto a COPY of a projections frame.

    R154, and the one place this module's old "never applied to projections"
    sentence stops being true. Two things bound how far it goes.

    It writes ONE column, and that column has exactly one reader in the engine
    (``optimizer_v3._ownership_pct_for_row``), which until R154 fell back to a
    flat 12.0 for every player. So attaching this changes no lineup by itself:
    the two R154 controls are off unless a caller passes a number, and until
    one does, the only visible effect is that the ownership diagnostics stop
    being a constant.

    It does NOT touch ``Ownership_Tier``. That field is behaviour-bearing --
    ``_ownership_priority`` reads it in one-off selection -- and this prior is
    uncalibrated, so writing it would change lineups through a side door with
    no gate and no record. ``tier_by_player_id`` is returned in the report for
    a caller that opts in explicitly, and nothing here applies it.

    Everything written is an UNCALIBRATED STRUCTURAL PRIOR. It is a predicted
    share, never a measured one, and never a win-rate or probability claim.

    Feature inputs are read off the frame itself (``Salary``, ``Position``,
    ``Team``, ``Batting_Order``, ``Base_Projection``) so the prediction cannot
    drift from the projections it is attached to. ``implied_total_by_team`` is
    the caller's, because it comes from the odds leg and is not on the frame.

    Returns ``(frame_copy, report)``. ``report['applied']`` is False with a
    ``reason`` whenever the column was not written, which includes an unknown
    contest shape: ``archetype_for_contest_shape`` answers None for a shape
    nobody has decided the field's behaviour for, and defaulting that to a
    large-field crowd would price the contest against the wrong field while
    saying nothing.
    """
    frame = projections_df.copy()
    report: Dict[str, Any] = {
        "applied": False, "reason": None, "archetype": None,
        "shape_match": None, "prior_version": VERSION,
        "players_scored": 0, "column": PROJECTED_OWNERSHIP_COLUMN,
        "label": "UNCALIBRATED STRUCTURAL PRIOR; predicted share, never measured",
    }
    if PROJECTED_OWNERSHIP_COLUMN in getattr(frame, "columns", []) and not overwrite:
        report["reason"] = "column_present_and_overwrite_false"
        return frame, report

    resolved, match = (archetype, "EXPLICIT") if archetype else (
        archetype_for_contest_shape(contest_shape) or (None, None))
    if not resolved:
        report["reason"] = f"unknown_contest_shape:{contest_shape!r}"
        return frame, report
    if resolved not in ARCHETYPE_PARAMS:
        report["reason"] = f"unknown_archetype:{resolved}"
        return frame, report
    report["archetype"], report["shape_match"] = resolved, match

    records = frame.to_dict("records")
    if not records:
        report["reason"] = "empty_frame"
        return frame, report

    def _num(value):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return None if out != out else out  # NaN

    orders, bases, sps = {}, {}, []
    for row in records:
        pid = str(row.get("Player_ID") or "").strip()
        if not pid:
            continue
        order = _num(row.get("Batting_Order"))
        if order and 1 <= order <= 9:
            orders[pid] = int(order)
        base = _num(row.get("Base_Projection"))
        if base is None:
            base = _num(row.get("Base"))
        if base is not None:
            bases[pid] = base
        if _is_pitcher(str(row.get("Position") or "").replace("/", ",").split(",")):
            sps.append(pid)

    prediction = predict_ownership(
        records, archetype=resolved,
        implied_total_by_team=implied_total_by_team,
        batting_order_by_player_id=orders,
        probable_sp_ids=sps,
        base_projection_by_player_id=bases or None,
    )
    own = prediction["own_pct_by_player_id"]
    frame[PROJECTED_OWNERSHIP_COLUMN] = [
        own.get(str(row.get("Player_ID") or "").strip()) for row in records
    ]
    report.update(
        applied=True,
        players_scored=sum(1 for row in records
                           if str(row.get("Player_ID") or "").strip() in own),
        tier_by_player_id=prediction["tier_by_player_id"],
        note=prediction["note"],
    )
    return frame, report


def grade_against_actuals(
    predicted_pct: Mapping[str, float],
    actual_pct: Mapping[str, float],
) -> Dict[str, Any]:
    """Grade one archetype's prediction against archived actual %Drafted.

    Joins on DK Player_ID over the intersection (players absent from the
    standings export are excluded and counted). Reports MAE, mean signed error
    (positive = prior over-predicts), Spearman rank correlation (computed
    directly, no scipy dependency), and the ten largest misses both ways. The
    grade is bookkeeping for the ledger, not a model-quality claim on its own;
    per the ledger discipline a single slate never moves a prior.
    """
    keys = sorted(set(map(str, predicted_pct)) & set(map(str, actual_pct)))
    if not keys:
        return {"joined": 0, "note": "no overlapping Player_IDs; check the standings join"}
    pred = [float(predicted_pct[k]) for k in keys]
    act = [float(actual_pct[k]) for k in keys]
    errors = [p - a for p, a in zip(pred, act)]
    mae = sum(abs(e) for e in errors) / len(errors)
    signed = sum(errors) / len(errors)

    def _ranks(values: List[float]) -> List[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rp, ra = _ranks(pred), _ranks(act)
    mean_rp = sum(rp) / len(rp)
    mean_ra = sum(ra) / len(ra)
    cov = sum((x - mean_rp) * (y - mean_ra) for x, y in zip(rp, ra))
    var_p = math.sqrt(sum((x - mean_rp) ** 2 for x in rp))
    var_a = math.sqrt(sum((y - mean_ra) ** 2 for y in ra))
    spearman = cov / (var_p * var_a) if var_p and var_a else None

    ranked = sorted(zip(keys, errors), key=lambda kv: kv[1])
    return {
        "joined": len(keys),
        "unjoined_predicted": len(set(map(str, predicted_pct)) - set(keys)),
        "mae_pct_points": round(mae, 2),
        "mean_signed_error_pct_points": round(signed, 2),
        "spearman_rank_corr": round(spearman, 3) if spearman is not None else None,
        "largest_under_predictions": [{"Player_ID": k, "error": round(e, 2)} for k, e in ranked[:10]],
        "largest_over_predictions": [{"Player_ID": k, "error": round(e, 2)} for k, e in ranked[-10:][::-1]],
        "note": "Grade is ledger bookkeeping; one slate never moves a prior. Condition on contest archetype and field size, never pooled.",
    }
