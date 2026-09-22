"""Replay a lineup set against an archived contest's OBSERVED field, and settle
it at that contest's own payout curve.

R118 (roadmap CC-6). Exact accounting over archived outcomes. Nothing here
simulates anything, estimates a distribution, or predicts. A replay is an
observed-outcome counterfactual conditioned on ONE archived field: it is never
ROI, a win rate, a cash rate, or a probability, and a construction that wins a
replay is "supported in the shapes replayed", never proven -- the field it beat
is that slate's field and no other.

Scope, and every limit here is measured rather than assumed (see CHANGELOG R384):

* CLASSIC ONLY. Showdown is REFUSED by name. An archived Showdown record cannot
  be replayed exactly: DK's captain takes 1.5x, and 89 of 249 archived Showdown
  records carry no ``CPT`` row at all while ``captain_norm`` is absent on 31.2%
  of Showdown entries, so for those the captain is not recoverable. Where a
  ``CPT`` row does exist its ``fpts`` is the 1.5x ALREADY APPLIED and rounded to
  2dp, while DK's own ``points`` column carries the unrounded value -- so
  reading it is wrong twice over. Refusing is the rule this repo already has for
  a player DK's table omits: report it, never approximate it.
* Scores are summed in INTEGER HUNDREDTHS, never floats. The tie group decides
  the payout, and float addition is not associative: 1,408 of 4,409 real
  archived lineups (31.9%) sum to a different float depending on term order, so
  two IDENTICAL lineups would sometimes fail to tie and split the wrong prize.
* A contest with no parseable payout curve settles UNKNOWN. It is never
  approximated and never silently treated as zero.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "archive"
MONEY_FILE = ROOT / "data" / "reference" / "dk_contest_money_2026-09-15.json"

LABEL = (
    "observed-outcome counterfactual against ONE archived field; exact accounting, "
    "no simulation. Never ROI, a win rate, a cash rate, or a probability"
)

#: Where the tie oracle below came from, and what pins it. COPIED rather than
#: imported on purpose: `tests/test_greenfield_regressions.py`'s
#: `test_no_legacy_module_imports_the_production_package_or_pydantic` forbids any
#: module under `tools/` (outside a four-name exemption list) from importing
#: `mlb_engine.production.*`. That wall is why R302's package can sit beside a
#: live build path at all, so the right move is a copy that names its origin.
SETTLE_ORACLE_ORIGIN = "mlb_engine/production/simulation.py:95 (settle_scores)"


def settle_scores(scores: Sequence[int], payouts_cents: Sequence[int]) -> List[Fraction]:
    """Exact tie oracle: every duplicated entry occupies and shares a paid rank.

    A copy of ``settle_scores`` from %s, with one deliberate difference: scores
    are INTEGER hundredths here, not floats, so the ``==`` that forms a tie group
    is exact. Pinned against that function's own hand example.

    A tie group of size d spanning ranks a..a+d-1 takes Fraction(sum(prize over
    those ranks), d) each. Returns GROSS cents; the entry fee is the caller's.
    """ % SETTLE_ORACLE_ORIGIN
    if len(scores) != len(payouts_cents) or not scores:
        raise ValueError("finite scores and one payout per field entry required")
    if any(type(s) is not int for s in scores):
        raise ValueError("scores must be integer hundredths, so ties are exact")
    if any(type(p) is not int or p < 0 for p in payouts_cents):
        raise ValueError("payouts must be nonnegative integer cents")
    if any(a < b for a, b in zip(payouts_cents, payouts_cents[1:])):
        raise ValueError("payout curve must be nonincreasing")
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    output = [Fraction(0) for _ in scores]
    rank = 0
    while rank < len(order):
        end = rank + 1
        while end < len(order) and scores[order[end]] == scores[order[rank]]:
            end += 1
        prize = Fraction(sum(payouts_cents[rank:end]), end - rank)
        for index in order[rank:end]:
            output[index] = prize
        rank = end
    return output


def to_cents(value: Any) -> Optional[int]:
    """DK fantasy points -> integer hundredths. None when unusable."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return int(round(f * 100))


def ambiguous_norms(player_table: Sequence[Mapping[str, Any]]) -> Dict[str, List[float]]:
    """Normalized names this contest's table maps to MORE THAN ONE realized score.

    Two different major-league players can normalize to one name. Measured over
    the archive, this is what actually breaks Classic replay: all 1,827
    irreproducible Classic entries live in 8 contests, and in every one the
    cause is a collision -- two Max Muncys, both listed `3B`, both
    `max muncy`, with different realized scores (one contest also carries two
    Jose Fermins, one of them a pitcher). It is NOT the DK multi-position
    row-splitting the backlog entry attributes it to: a player split across
    roster positions holds the SAME score on each row.

    That distinction decides the remedy. Row-splitting is collapsible, so
    first-wins is right for it. A collision is not: `player_norm -> fpts` is
    not a function when two people share a name, and any collapse rule silently
    attributes one player's score to the other. So a lineup naming a colliding
    player is reported non-replayable, the same rule this repo already applies
    to a player DK's table omits.
    """
    seen: Dict[str, List[float]] = {}
    for row in player_table:
        if str(row.get("roster_position") or "").strip().upper() == "CPT":
            continue
        norm = row.get("player_norm")
        cents = to_cents(row.get("fpts"))
        if not norm or cents is None:
            continue
        bucket = seen.setdefault(norm, [])
        if cents not in bucket:
            bucket.append(cents)
    return {k: [c / 100.0 for c in v] for k, v in seen.items() if len(v) > 1}


def fpts_cents_by_norm(player_table: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """{player_norm -> realized DK points in integer hundredths}, first-wins.

    ``CPT`` rows are EXCLUDED before the collapse, not after. On a Showdown
    table a player holds both a ``UTIL`` row (base) and a ``CPT`` row (1.5x
    already applied, 2dp-rounded); ``player_table`` is ordered by pct_drafted
    descending, so the CPT row comes first for 85 of 2,648 such players and a
    naive first-wins would record the inflated number as that player's realized
    score. Classic tables carry no CPT row, so this filter is a no-op there.

    First-wins among the remaining rows is the miner's own collapse and it is
    the right one: measured over all 442,001 archived Classic field entries it
    reproduces DK's recorded points on 99.587%, against 96.610% for last-wins.
    """
    out: Dict[str, int] = {}
    for row in player_table:
        if str(row.get("roster_position") or "").strip().upper() == "CPT":
            continue
        norm = row.get("player_norm")
        if not norm or norm in out:
            continue
        cents = to_cents(row.get("fpts"))
        if cents is not None:
            out[norm] = cents
    return out


def find_mined_record(contest_id: str) -> Optional[Path]:
    hits = sorted(ARCHIVE.glob(f"*/mined_{contest_id}.json"))
    return hits[0] if hits else None


def load_money() -> Dict[str, Mapping[str, Any]]:
    if not MONEY_FILE.exists():
        return {}
    return json.loads(MONEY_FILE.read_text(encoding="utf-8")).get("contests") or {}


_DOLLARS = re.compile(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)")


def ticket_face_value(record: Mapping[str, Any]) -> Tuple[Optional[float], str]:
    """The value of one paid seat, and how it was obtained.

    Two provenances, and they are NOT the same kind of fact:

    ``observed``    -- this contest records a ``winnings_ticket`` we actually
                       won, so the face value is a recorded observation.
    ``contest_name`` -- parsed from the contest title. A labeled INFERENCE, not
                       an observation. It is corroborated, not assumed: across
                       the money file every contest that both pays places and
                       recorded a won ticket (21 of them) has a title whose one
                       dollar figure equals the recorded value exactly, 21 of 21
                       with no disagreement. The only titles carrying more than
                       one dollar figure are the 11 Best Ball GPPs, which pay no
                       places and so never reach this function.
    """
    won = record.get("winnings_ticket") or 0
    if won and (record.get("my_entries") or 0):
        return float(won), "observed"
    figures = _DOLLARS.findall(record.get("name") or "")
    if len(figures) == 1:
        return float(figures[0].replace(",", "")), "contest_name"
    return None, "unavailable"


def payout_curve_cents(
    record: Optional[Mapping[str, Any]], field_size: int
) -> Tuple[Optional[List[int]], Dict[str, Any]]:
    """A nonincreasing per-rank curve in cents, right-padded to the field size.

    A satellite's curve is flat by construction: ``paid_places`` identical seats.
    Returns (None, why) when the contest has no curve on disk -- the caller then
    settles UNKNOWN. Never guesses.
    """
    if record is None:
        return None, {"settled": False, "reason": "contest not in the payout reference"}
    paid = record.get("paid_places") or 0
    if not paid:
        return None, {"settled": False, "reason": "reference records no paid places"}
    value, provenance = ticket_face_value(record)
    if value is None:
        return None, {"settled": False, "reason": "no ticket face value available"}
    paid = min(int(paid), field_size)
    cents = int(round(value * 100))
    curve = [cents] * paid + [0] * (field_size - paid)
    return curve, {
        "settled": True,
        "paid_places": paid,
        "seat_value_usd": value,
        "seat_value_provenance": provenance,
        "award_kind": "tournament_ticket",
        "note": ("a seat is a TICKET at face value, not cash; it is never counted "
                 "twice against a later redemption"),
    }


class ShowdownRefused(Exception):
    """Raised by name, per CLAUDE.md's rule against silent approximation."""


def load_contest(contest_id: str) -> Dict[str, Any]:
    path = find_mined_record(contest_id)
    if path is None:
        raise FileNotFoundError(
            f"no archived record for contest {contest_id}: expected "
            f"data/archive/<date>/mined_{contest_id}.json"
        )
    record = json.loads(path.read_text(encoding="utf-8"))
    contest_type = str(record.get("contest_type") or "").strip().lower()
    if contest_type == "showdown":
        raise ShowdownRefused(
            f"contest {contest_id} is Showdown and is not exactly replayable from "
            "the archive: the captain takes 1.5x, 89 of 249 archived Showdown "
            "records carry no CPT row, and captain_norm is absent on 31.2% of "
            "Showdown entries. Replaying it would approximate a score, which this "
            "tool does not do. Classic only."
        )
    if contest_type != "classic":
        raise ShowdownRefused(
            f"contest {contest_id} records contest_type={contest_type!r}; this tool "
            "replays Classic only and will not guess a scoring convention"
        )
    record["_path"] = str(path)
    return record


def score_lineup_cents(
    names: Sequence[str],
    fmap: Mapping[str, int],
    ambiguous: Optional[Mapping[str, Any]] = None,
) -> Tuple[Optional[int], List[str], List[str]]:
    """(score in integer hundredths, missing players, colliding players).

    Either list non-empty means the lineup is NOT replayable from this table,
    and the caller reports that rather than scoring it.
    """
    missing = [n for n in names if n not in fmap]
    collides = [n for n in names if ambiguous and n in ambiguous]
    if missing or collides:
        return None, missing, collides
    return sum(fmap[n] for n in names), [], []


def replay(
    contest_id: str, lineups: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Score each supplied lineup against the archived field and settle it.

    Each supplied lineup ENTERS the field as an additional entry: it takes its
    own rank, and a duplicate of an archived lineup ties with it and splits the
    tied ranks, which is DK's own rule and the whole reason the tie oracle is
    exact. The archived field is not replaced, resized, or resampled.
    """
    record = load_contest(contest_id)
    table = record.get("player_table") or []
    fmap = fpts_cents_by_norm(table)
    collisions = ambiguous_norms(table)
    field = [e for e in (record.get("entries") or []) if e.get("players_norm")]

    field_scores: List[int] = []
    field_unscorable = 0
    for entry in field:
        cents, _missing, _coll = score_lineup_cents(entry["players_norm"], fmap, collisions)
        if cents is None:
            # The FIELD is DK's own record, so fall back to the points DK
            # published for it. That keeps the field intact and the ranks
            # honest; it is only OUR supplied lineups that must refuse.
            field_unscorable += 1
            cents = to_cents(entry.get("points")) or 0
        field_scores.append(cents)

    field_rosters = [frozenset(e["players_norm"]) for e in field]
    roster_counts: Dict[frozenset, int] = {}
    for roster in field_rosters:
        roster_counts[roster] = roster_counts.get(roster, 0) + 1

    replayed: List[Dict[str, Any]] = []
    entered_scores: List[int] = []
    for lineup in lineups:
        names = [str(n) for n in (lineup.get("players_norm") or [])]
        cents, missing, collides = score_lineup_cents(names, fmap, collisions)
        row: Dict[str, Any] = {
            "lineup_id": lineup.get("lineup_id"),
            "players_norm": names,
            "replayable": cents is not None,
        }
        if cents is None:
            if missing:
                row["unresolved_players"] = missing
                row["note"] = ("not replayable from this contest's table: DK's export "
                               "carries no realized score for the named players")
            if collides:
                row["ambiguous_players"] = {n: collisions[n] for n in collides}
                row["note"] = ("not replayable: this contest's table maps one "
                               "normalized name to two different realized scores, "
                               "so the name identifies two different players")
        else:
            row["points"] = cents / 100.0
            row["duplicates_in_field"] = roster_counts.get(frozenset(names), 0)
            entered_scores.append(cents)
        replayed.append(row)

    money = load_money().get(str(contest_id))
    field_size = len(field_scores) + len(entered_scores)
    curve, settlement = payout_curve_cents(money, field_size)

    combined = field_scores + entered_scores
    if curve is not None:
        payouts = settle_scores(combined, curve)
    else:
        payouts = None

    entry_fee = float((money or {}).get("entry_fee") or 0.0)
    idx = len(field_scores)
    for row in replayed:
        if not row["replayable"]:
            continue
        cents = to_cents(row["points"])
        better = sum(1 for s in combined if s > cents)
        tied = sum(1 for s in combined if s == cents)
        row["rank"] = better + 1
        row["tied_with"] = tied - 1
        row["percentile"] = round(100.0 * (1.0 - better / max(len(combined), 1)), 3)
        if curve is not None:
            gross = payouts[idx]
            row["seat_cleared"] = gross > 0
            row["gross_award_usd"] = float(gross) / 100.0
            row["net_usd"] = float(gross) / 100.0 - entry_fee
            row["award_is_ticket_face_value"] = True
        else:
            row["settlement"] = "UNKNOWN"
        idx += 1

    return {
        "label": LABEL,
        "contest_id": str(contest_id),
        "slate_date": record.get("slate_date"),
        "contest_type": record.get("contest_type"),
        "archived_field_entries": len(field_scores),
        "field_entries_not_scorable_from_table": field_unscorable,
        "colliding_player_names": collisions or None,
        "entry_fee_usd": entry_fee or None,
        "settlement": settlement,
        "lineups": replayed,
        "source_record": record["_path"],
    }


def self_validate(contest_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The closed loop: re-score every archived Classic entry from the table and
    compare against DK's own recorded points and rank.

    This is the tool's acceptance test and it uses no input of ours: the field,
    its points and its ranks are all DK's, so a disagreement is this tool's.
    """
    paths = ([find_mined_record(c) for c in contest_ids] if contest_ids
             else sorted(ARCHIVE.glob("*/mined_*.json")))
    totals = {"contests": 0, "entries": 0, "points_exact": 0, "points_mismatch": 0,
              "unresolvable": 0, "ambiguous": 0, "rank_exact": 0, "rank_checked": 0,
              "contests_with_colliding_names": 0, "contests_points_perfect": 0,
              "contests_rank_perfect": 0}
    worst: List[Tuple[float, str, int, int]] = []
    for path in paths:
        if path is None or not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if str(record.get("contest_type") or "").strip().lower() != "classic":
            continue
        table = record.get("player_table") or []
        fmap = fpts_cents_by_norm(table)
        collisions = ambiguous_norms(table)
        entries = [e for e in (record.get("entries") or []) if e.get("players_norm")]
        if not entries:
            continue
        totals["contests"] += 1
        if collisions:
            totals["contests_with_colliding_names"] += 1
        scored: List[Tuple[int, Any]] = []
        c_ok = c_tot = 0
        for entry in entries:
            recorded = to_cents(entry.get("points"))
            cents, missing, collides = score_lineup_cents(
                entry["players_norm"], fmap, collisions)
            totals["entries"] += 1
            c_tot += 1
            if cents is None:
                totals["ambiguous" if collides else "unresolvable"] += 1
                continue
            if recorded is not None and cents == recorded:
                totals["points_exact"] += 1
                c_ok += 1
            else:
                totals["points_mismatch"] += 1
            scored.append((cents, entry.get("rank")))
        # Rank agreement. DK ranks by competition convention -- a tie group
        # shares the best rank and the next group resumes after it (2,2,4 and
        # 4,4,4,7 in the archive) -- which is exactly `better + 1`.
        r_ok = r_tot = 0
        for cents, recorded_rank in scored:
            if recorded_rank in (None, ""):
                continue
            totals["rank_checked"] += 1
            r_tot += 1
            better = sum(1 for s, _ in scored if s > cents)
            if better + 1 == int(recorded_rank):
                totals["rank_exact"] += 1
                r_ok += 1
        if c_tot:
            worst.append((c_ok / c_tot, path.name, c_ok, c_tot))
            if c_ok == c_tot:
                totals["contests_points_perfect"] += 1
            if r_tot and r_ok == r_tot:
                totals["contests_rank_perfect"] += 1
    worst.sort()
    totals["points_exact_pct"] = round(
        100.0 * totals["points_exact"] / max(totals["entries"], 1), 3)
    totals["rank_exact_pct"] = round(
        100.0 * totals["rank_exact"] / max(totals["rank_checked"], 1), 3)
    # PER CONTEST is the headline, and the entry-pooled figure beside it is
    # there to be read as the thing it is. CLAUDE.md conditions outcome counts
    # on contest and field size and never pools them, and this is why: every
    # irreproducible Classic entry in the archive sits in 8 contests, and 5 of
    # those are the largest fields in it, so the entry-weighted rank figure
    # reads ~75% while 353 of 361 contests reproduce every rank exactly.
    totals["contests_points_perfect_pct"] = round(
        100.0 * totals["contests_points_perfect"] / max(totals["contests"], 1), 3)
    totals["contests_rank_perfect_pct"] = round(
        100.0 * totals["contests_rank_perfect"] / max(totals["contests"], 1), 3)
    totals["worst_contests"] = [
        {"record": n, "exact": a, "entries": b, "pct": round(100.0 * r, 2)}
        for r, n, a, b in worst[:10]
    ]
    totals["reading"] = (
        "contests_*_perfect_pct is the headline; the entry-pooled *_exact_pct "
        "beside it is dominated by a few very large contests and is not a "
        "per-contest accuracy"
    )
    totals["label"] = LABEL
    return totals


def lineups_from_csv(path: Path) -> List[Dict[str, Any]]:
    """Read a lineup set from a CSV carrying a `players_norm` column.

    Deliberately narrow. A DKEntries export names players as `Name (ID)` and
    resolving those to the miner's normalized names is a separate join this tool
    does not own; feeding it a normalized column keeps the replay's subject the
    settlement rather than a name crosswalk.
    """
    rows: List[Dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for i, row in enumerate(csv.DictReader(handle)):
            raw = row.get("players_norm") or ""
            names = [n.strip() for n in raw.split("/") if n.strip()]
            rows.append({"lineup_id": row.get("lineup_id") or f"row{i+1}",
                         "players_norm": names})
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--contest", help="archived contest id to replay against")
    p.add_argument("--lineups", type=Path,
                   help="CSV with a players_norm column (slash-separated)")
    p.add_argument("--self-validate", action="store_true",
                   help="re-score every archived Classic entry against DK's own "
                        "recorded points and rank; the acceptance test")
    p.add_argument("--json", type=Path, help="write the full result here")
    args = p.parse_args(argv)

    if args.self_validate:
        result = self_validate([args.contest] if args.contest else None)
    elif args.contest:
        if not args.lineups:
            p.error("--contest needs --lineups (or use --self-validate)")
        try:
            result = replay(args.contest, lineups_from_csv(args.lineups))
        except ShowdownRefused as exc:
            print(json.dumps({"refused": str(exc)}, indent=2))
            return 3
    else:
        p.error("one of --contest or --self-validate is required")

    text = json.dumps(result, indent=2, default=str)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
