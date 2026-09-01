#!/usr/bin/env python3
"""R267(a). Single-slot repair: replace a player who will not play, one slot at
a time, by enumerating the salary file directly instead of matching whole
lineups out of the bank.

WHY THIS EXISTS, and why it is not a search-effort fix. `late_swap` matches
whole-lineup candidates out of the bank against an entry's pins. Late in a
slate an entry has 3 to 9 slots frozen in locked games and no generic bank
lineup reproduces that exact prefix, so the refusal
(`contest_allocator.py:2394`, "no compatible candidate for Entry ID ...") is
STRUCTURAL. Growing the bank cannot touch it: on `1305_12g` the bank went
566 -> 1425 candidates across six invocations and the message never changed,
because more whole lineups do not make a 9-pin prefix more likely. Entry
5234627043 had 9 of 10 slots locked, only P2 open and $5,300 of cap -- a
one-slot search over ~1100 salary rows, which the engine spent ~13 minutes
failing to find because it was searching the wrong object. This tool searches
the right one.

WHAT IT IS. A deterministic filter, well under a second, over the DK salary
file. Six constraints, all mechanical:

  1. slot eligibility -- `Roster Position` admits the DK column the dead
     player occupies;
  2. salary -- the entry's total after removing the dead player leaves room;
  3. the candidate's game has NOT locked, from the feed clock, through
     `verify_export.derive_locked_teams_from_feed` (the same derivation the
     verifier uses, so the tool that repairs and the tool that checks read one
     fact rather than two);
  4. confirmed starter -- the OBSERVED tier (R270(b)) once the candidate's
     game is underway, the feed's confirmed set before that;
  5. not already in the entry, by `person_key` (a person, not a draftable id);
  6. NOT on a team opposing any SP rostered in that entry -- `verify_export`
     caught exactly this bug in the hand-built `1305_12g` repair, so the
     constraint is load-bearing rather than decorative.

Survivors rank by projection (`AvgPointsPerGame` where no Base exists), best
wins, and the diff is recorded.

R267(b): THE TOOL PICKS THE MODE, NOT THE CALLER. An entry with more open
slots than pins still belongs to the whole-lineup solve, which optimises
jointly; this mode is for the tail, where the solve is structurally refused.
`--mode` overrides, and the chosen mode and its pin count are always reported.

R267(c): IT TOUCHES NO PORTFOLIO CONTROL. No exposure cap, no stack plan, no
overlap bound is read or written. That is what makes it safe to run unattended
under CLAUDE.md's repair clause, and it is the reason it is built as a filter
rather than as a relaxation of the existing solve. If a future change makes
this tool read a portfolio control, the autonomy argument built on top of it
has evaporated and both have to be revisited together.

NOT CERTIFIED. This tool edits a delivered file; it does not run the three
gates. Its output is review-grade and the preflight is still mandatory:

    python tools/preflight_upload.py --entries <out.csv> --salary <salary.csv>

Usage:
    python tools/repair_entry.py --entries runs/<id>/final/DKEntries.csv \\
        --salary data/slates/<date>/DKSalaries.csv \\
        [--feed data/slates/<date>/lineups_feed.json] \\
        [--boxscores data/slates/<date>/boxscores.json] \\
        [--dead "Feltner" --dead 12345678] \\
        [--entry-ids 5234627043,5234627044] \\
        [--as-of 2026-08-29T19:40:00Z] \\
        [--mode auto|repair|defer] [--out <path>] [--json]

Exit codes: 0 a repair was found for every dead slot (or there was nothing to
repair); 2 at least one dead slot has NO legal replacement; 3 IO/parse error;
4 clean and nothing written because --dry-run. A refusal outranks the dry-run
code -- 4 never means "there was a problem but I did not write."
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
# `tools/` FIRST and the repo root second, which is `verify_export.py`'s own
# convention and is not cosmetic: importing a sibling tool as `tools.X` while
# the tests import it bare loads the same file twice under two module names,
# and then `preflight_upload.SALARY_CAP` and `tools.preflight_upload.
# SALARY_CAP` are different objects that can be patched apart. One name, one
# module -- which is the same rule as one rule, one owner, applied to imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT))

# Shared, never reimplemented. Every one of these already has exactly one
# definition in this repo and a second copy is how the R248 crosswalk went
# wrong; `preflight_upload` owns the DK file geometry and the slot-eligibility
# rule, and `verify_export` owns the lock derivation.
from preflight_upload import (  # noqa: E402
    CLASSIC_SLOTS, SALARY_CAP, EntryRow, load_entries, load_salary,
    person_key, slot_admits, _digits, _int_or_none, _norm_name,
)
from verify_export import derive_locked_teams_from_feed  # noqa: E402

PITCHER_SLOTS = {"P", "SP", "RP"}


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def projection_of(row: Mapping[str, Any]) -> float:
    """The build's own projection where it exists, APPG otherwise.

    R267(a) names the fallback: "rank survivors by projection (APPG where no
    Base exists)". A DK salary export carries only AvgPointsPerGame; a staged
    projection file may carry Base. Both are read here so the caller does not
    have to know which file it handed over.
    """
    for key in ("Base", "base", "Projection", "AvgPointsPerGame"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            continue
    return 0.0


# --------------------------------------------------------------------------- #
# who is dead
# --------------------------------------------------------------------------- #
def resolve_dead_players(tokens: Sequence[str],
                         salary: Mapping[str, Mapping[str, str]]) -> Tuple[List[str], List[str]]:
    """Operator tokens (a DK id or a name) -> (player_ids, unresolved).

    A name that matches more than one salary row is UNRESOLVED, never guessed.
    Under a lock clock the wrong guess is a second dead slot, not a saved
    round trip.
    """
    resolved: List[str] = []
    unresolved: List[str] = []
    by_norm: Dict[str, List[str]] = {}
    for pid, row in salary.items():
        by_norm.setdefault(_norm_name(row.get("Name")), []).append(pid)
    for token in tokens:
        text = str(token).strip()
        if not text:
            continue
        digits = _digits(text)
        if digits and digits in salary:
            resolved.append(digits)
            continue
        hits = by_norm.get(_norm_name(text), [])
        if len(hits) == 1:
            resolved.append(hits[0])
        else:
            unresolved.append(
                f"{text} ({'no salary row' if not hits else f'{len(hits)} salary rows'})")
    return sorted(set(resolved)), unresolved


def derive_dead_from_observed(entries: Sequence[EntryRow],
                              salary: Mapping[str, Mapping[str, str]],
                              observed: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Rostered players the OBSERVED tier says did not start (R270(b)).

    Only `did_not_start` counts. `unobserved` is a game that has not begun and
    is not evidence of anything -- treating it as a scratch here would scratch
    the whole slate before first pitch, which is why the tier returns three
    values instead of a bool.
    """
    from mlb_engine.intake.live_data_adapters import observed_starter_state

    dead: Dict[str, Dict[str, str]] = {}
    for entry in entries:
        for pid in entry.cells:
            if not pid or pid in dead:
                continue
            row = salary.get(pid)
            if row is None:
                continue
            team = str(row.get("TeamAbbrev") or "").strip().upper()
            if observed_starter_state(observed, pid, team) == "did_not_start":
                dead[pid] = {"player_id": pid, "name": str(row.get("Name") or ""),
                             "team": team, "source": "observed_did_not_start"}
    return [dead[k] for k in sorted(dead)]


# --------------------------------------------------------------------------- #
# the filter
# --------------------------------------------------------------------------- #
def opposing_teams_of_rostered_pitchers(entry: EntryRow,
                                        slots: Sequence[str],
                                        salary: Mapping[str, Mapping[str, str]],
                                        game_ids: Mapping[str, str],
                                        exclude_index: Optional[int] = None) -> Dict[str, str]:
    """team -> the rostered SP it would be hitting against.

    A hitter opposing your own starting pitcher is a bet against your own
    lineup. `verify_export` caught this exact bug in the hand-built `1305_12g`
    repair; a repair that reintroduces it has not repaired anything.

    ``exclude_index`` is the slot being repaired, and passing it is not an
    optimisation. The dead player is LEAVING the entry, so the game he was in
    stops being a conflict the moment he is replaced; counting him bars every
    replacement from the team he was facing -- which on a two-game slate is
    most of the legal pool, and it bars them on the strength of a constraint
    that will not exist once the write lands. Measured on the first cut: the
    dead COL arm barred every ARI candidate from his own replacement search.
    """
    out: Dict[str, str] = {}
    for i, pid in enumerate(entry.cells):
        if not pid or i >= len(slots) or slots[i].upper() not in PITCHER_SLOTS:
            continue
        if exclude_index is not None and i == exclude_index:
            continue
        row = salary.get(pid)
        if row is None:
            continue
        team = str(row.get("TeamAbbrev") or "").strip().upper()
        game_id = game_ids.get(pid) or str(row.get("Game Info") or "")
        for other in {t for t in game_id.replace("@", " ").split() if t.isalpha()}:
            other = other.upper()
            if other and other != team:
                out[other] = str(row.get("Name") or pid)
    return out


def candidates_for_slot(
    entry: EntryRow,
    slot_index: int,
    slots: Sequence[str],
    salary: Mapping[str, Mapping[str, str]],
    locked_teams: Iterable[str],
    confirmed_ids: Iterable[str],
    observed: Optional[Mapping[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Every legal replacement for ONE slot, ranked, plus a rejection census.

    The census is returned rather than logged because "no legal replacement"
    is a verdict an operator has to be able to argue with under a clock, and
    "0 candidates" is not an argument. R267(d)'s price-band count is the same
    fact measured at build time and is deliberately NOT computed here.

    The census is FIRST-MATCH, not full attribution: a row barred by three
    constraints is counted once, under the first one to reject it, in the
    order below. That is stated because the alternative reading is available
    and wrong -- `opposes_rostered_sp: 1` does not mean one row opposed a
    rostered arm, it means one row survived everything else and then opposed
    one. Evaluating all six per row would cost nothing here; it is not done
    because a census where the counts sum to more than the pool is a worse
    thing to hand someone under a clock than one that is merely partial.
    """
    from mlb_engine.intake.live_data_adapters import observed_starter_state

    slot = slots[slot_index]
    locked = {str(t).strip().upper() for t in locked_teams}
    confirmed = {str(p) for p in confirmed_ids}
    dead_pid = entry.cells[slot_index]

    other_ids = [pid for i, pid in enumerate(entry.cells)
                 if pid and i != slot_index]
    incumbent_people = {person_key(salary[pid]) for pid in other_ids if pid in salary}
    spent = sum(_int_or_none(salary[pid].get("Salary")) or 0
                for pid in other_ids if pid in salary)
    headroom = SALARY_CAP - spent

    game_ids = {pid: str(salary[pid].get("Game Info") or "")
                for pid in entry.cells if pid in salary}
    opposed = opposing_teams_of_rostered_pitchers(
        entry, slots, salary, game_ids, exclude_index=slot_index)

    census = {"slot_ineligible": 0, "over_headroom": 0, "team_locked": 0,
              "not_confirmed": 0, "did_not_start": 0, "already_in_entry": 0,
              "opposes_rostered_sp": 0, "eligible": 0}
    out: List[Dict[str, Any]] = []
    for pid, row in salary.items():
        if pid == dead_pid:
            continue
        if not slot_admits(row, slot):
            census["slot_ineligible"] += 1
            continue
        cost = _int_or_none(row.get("Salary"))
        if cost is None or cost > headroom:
            census["over_headroom"] += 1
            continue
        team = str(row.get("TeamAbbrev") or "").strip().upper()
        if team in locked:
            census["team_locked"] += 1
            continue
        state = (observed_starter_state(observed, pid, team)
                 if observed is not None else "unobserved")
        if state == "did_not_start":
            # The observed tier outranks the feed: a player who has already not
            # started cannot be repaired INTO an entry, whatever the feed says.
            census["did_not_start"] += 1
            continue
        if state != "started" and pid not in confirmed:
            # `unobserved` falls through to the feed, which is the ranking
            # CLAUDE.md's build contract item 1 states. `started` needs no feed
            # corroboration -- it is the record.
            census["not_confirmed"] += 1
            continue
        if person_key(row) in incumbent_people:
            census["already_in_entry"] += 1
            continue
        if team in opposed:
            census["opposes_rostered_sp"] += 1
            continue
        census["eligible"] += 1
        out.append({
            "player_id": pid, "name": str(row.get("Name") or ""), "team": team,
            "salary": cost, "projection": round(projection_of(row), 4),
            "roster_position": str(row.get("Roster Position") or ""),
            "confirmed_source": "observed" if state == "started" else "feed",
        })
    # Deterministic: projection desc, then salary desc, then player_id, so two
    # runs over one file can never disagree (CLAUDE.md's determinism rule).
    out.sort(key=lambda c: (-c["projection"], -(c["salary"] or 0), c["player_id"]))
    return out, census


def open_slot_count(entry: EntryRow, slots: Sequence[str],
                    salary: Mapping[str, Mapping[str, str]],
                    locked_teams: Iterable[str]) -> Tuple[int, int]:
    """(open, pinned) for one entry, by the lock clock."""
    locked = {str(t).strip().upper() for t in locked_teams}
    open_n = pinned = 0
    for pid in entry.cells:
        row = salary.get(pid)
        team = str((row or {}).get("TeamAbbrev") or "").strip().upper()
        if team and team in locked:
            pinned += 1
        else:
            open_n += 1
    return open_n, pinned


def choose_mode(open_n: int, pinned: int) -> str:
    """R267(b). The whole-lineup solve owns any entry with meaningful freedom;
    this mode owns the tail. The boundary is open <= pinned -- an entry with
    more frozen rows than free ones cannot have its exact prefix reproduced by
    a generic bank lineup, which is the refusal this tool answers."""
    return "repair" if open_n <= pinned else "defer"


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def repair_entries(
    entries: Sequence[EntryRow],
    slots: Sequence[str],
    salary: Mapping[str, Mapping[str, str]],
    dead_ids: Iterable[str],
    locked_teams: Iterable[str],
    confirmed_ids: Iterable[str],
    observed: Optional[Mapping[str, Any]] = None,
    authorized: Optional[Iterable[str]] = None,
    mode: str = "auto",
) -> Dict[str, Any]:
    dead = {str(p) for p in dead_ids}
    allow = {str(e) for e in authorized} if authorized else None
    repairs: List[Dict[str, Any]] = []
    refusals: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    untouched = 0

    for entry in entries:
        if entry.is_blank:
            continue
        if allow is not None and entry.entry_id not in allow:
            continue
        hits = [i for i, pid in enumerate(entry.cells) if pid in dead]
        if not hits:
            untouched += 1
            continue
        open_n, pinned = open_slot_count(entry, slots, salary, locked_teams)
        chosen = mode if mode in ("repair", "defer") else choose_mode(open_n, pinned)
        if chosen == "defer":
            deferred.append({"entry_id": entry.entry_id, "open_slots": open_n,
                             "pinned_slots": pinned, "dead_slots": len(hits),
                             "reason": "more open slots than pins: the whole-lineup "
                                       "solve optimises jointly and owns this entry"})
            continue
        for slot_index in hits:
            dead_pid = entry.cells[slot_index]
            dead_row = salary.get(dead_pid) or {}
            ranked, census = candidates_for_slot(
                entry, slot_index, slots, salary, locked_teams, confirmed_ids, observed)
            record = {
                "entry_id": entry.entry_id, "slot": slots[slot_index],
                "slot_index": slot_index, "open_slots": open_n,
                "pinned_slots": pinned, "mode": chosen,
                "out_player_id": dead_pid,
                "out_name": str(dead_row.get("Name") or ""),
                "out_salary": _int_or_none(dead_row.get("Salary")),
                "out_projection": round(projection_of(dead_row), 4),
                "candidates_considered": len(salary),
                "rejection_census": census,
            }
            if not ranked:
                record["reason"] = ("no legal replacement for this slot; the census "
                                    "names which constraint removed each row")
                refusals.append(record)
                continue
            best = ranked[0]
            entry.cells[slot_index] = best["player_id"]
            entry.raw[4 + slot_index] = f"{best['name']} ({best['player_id']})"
            record.update({
                "in_player_id": best["player_id"], "in_name": best["name"],
                "in_team": best["team"], "in_salary": best["salary"],
                "in_projection": best["projection"],
                "confirmed_source": best["confirmed_source"],
                "projection_delta": round(
                    best["projection"] - projection_of(dead_row), 4),
                "runner_up": (ranked[1]["name"] if len(ranked) > 1 else None),
                "eligible_count": len(ranked),
            })
            repairs.append(record)

    return {
        "repairs": repairs, "refusals": refusals, "deferred": deferred,
        "entries_untouched": untouched,
        "portfolio_controls_touched": [],  # R267(c): structurally empty, and asserted.
    }


def write_entries(path: Path, header: Sequence[str], entries: Sequence[EntryRow],
                  trailing: Sequence[Sequence[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for entry in entries:
            writer.writerow(entry.raw)
        for row in trailing:
            writer.writerow(row)


def _load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entries", required=True, type=Path)
    ap.add_argument("--salary", required=True, type=Path)
    ap.add_argument("--feed", type=Path)
    ap.add_argument("--boxscores", type=Path,
                    help="parsed boxscores (R270(b)); a list, or {'games': [...]}")
    ap.add_argument("--dead", action="append", default=[],
                    help="a DK player id or a name; repeatable. Omit to derive "
                         "from the observed tier, which needs --boxscores.")
    ap.add_argument("--entry-ids", default="",
                    help="comma-separated authorized Entry IDs; default all")
    ap.add_argument("--as-of", default="")
    ap.add_argument("--mode", choices=("auto", "repair", "defer"), default="auto")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        contest, slots, entries, trailing, _ = load_entries(args.entries)
        with args.entries.open(encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh))
        salary = load_salary(args.salary)
    except (OSError, ValueError) as exc:
        print(f"repair_entry: {exc}", file=sys.stderr)
        return 3

    now = (datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
           if args.as_of else datetime.now(timezone.utc))

    locked: set[str] = set()
    confirmed: List[str] = []
    lock_note = "no feed supplied; no team treated as locked"
    if args.feed:
        derived = derive_locked_teams_from_feed(args.feed, args.salary, now)
        if derived is not None:
            locked, lock_note, _not_locked = derived
        try:
            from mlb_engine.intake.live_data_adapters import (
                build_status_map_from_lineups_feed)
            status = build_status_map_from_lineups_feed(
                _load_json(args.feed), str(args.salary))
            confirmed = list(status.get("confirmed_hitter_ids") or []) + list(
                status.get("probable_pitcher_ids") or [])
        except Exception as exc:  # noqa: BLE001
            print(f"repair_entry: feed unreadable for confirmation ({exc}); "
                  f"no player will pass the confirmed test on feed evidence",
                  file=sys.stderr)

    observed = None
    if args.boxscores:
        from mlb_engine.intake.live_data_adapters import (
            build_observed_starters, parse_boxscore_feed)
        payload = _load_json(args.boxscores)
        raw = payload.get("games") if isinstance(payload, Mapping) else payload
        boxes = [b if "sides" in b else parse_boxscore_feed(b) for b in (raw or [])]
        observed = build_observed_starters(boxes, salary)

    dead_ids, unresolved = resolve_dead_players(args.dead, salary)
    derived_dead: List[Dict[str, str]] = []
    if not args.dead and observed is not None:
        derived_dead = derive_dead_from_observed(entries, salary, observed)
        dead_ids = [d["player_id"] for d in derived_dead]
    if unresolved:
        print(f"repair_entry: REFUSING, unresolved --dead token(s): {unresolved}",
              file=sys.stderr)
        return 3

    result = repair_entries(entries, slots, salary, dead_ids, locked, confirmed,
                            observed, [e for e in args.entry_ids.split(",") if e],
                            args.mode)
    result.update({"contest": contest, "as_of": now.isoformat(),
                   "lock_note": lock_note, "locked_teams": sorted(locked),
                   "dead_player_ids": dead_ids,
                   "dead_derived_from_observed": derived_dead,
                   "observed_supplied": observed is not None})

    out_path = args.out or args.entries.with_name(
        args.entries.stem + "_repaired.csv")
    if args.dry_run:
        result["written"] = None
    else:
        write_entries(out_path, header, entries, trailing)
        result["written"] = str(out_path)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for r in result["repairs"]:
            print(f"{r['entry_id']} {r['slot']}: OUT {r['out_name']} "
                  f"(${r['out_salary']}) -> IN {r['in_name']} (${r['in_salary']}, "
                  f"{r['confirmed_source']}), proj {r['projection_delta']:+.2f}, "
                  f"{r['eligible_count']} legal")
        for r in result["refusals"]:
            print(f"{r['entry_id']} {r['slot']}: NO LEGAL REPLACEMENT for "
                  f"{r['out_name']} -- {r['rejection_census']}")
        for d in result["deferred"]:
            print(f"{d['entry_id']}: DEFERRED to the whole-lineup solve "
                  f"({d['open_slots']} open / {d['pinned_slots']} pinned)")
        print(f"lock: {result['lock_note']}")
        if result["written"]:
            print(f"wrote {result['written']}")
            print("REVIEW-GRADE, not certified. Run the preflight before upload:")
            print(f"  python tools/preflight_upload.py --entries {result['written']} "
                  f"--salary {args.salary}")

    # A refusal outranks the dry-run code. Returning 4 for "nothing written"
    # over a run that found a dead slot with NO legal replacement would hide
    # the finding behind the mode, which is R176's rider (the preflight
    # computing its exit code before the fact that makes it durable) arriving
    # in a new tool. 4 means clean-and-unwritten, never merely unwritten.
    if result["refusals"]:
        return 2
    return 4 if args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
