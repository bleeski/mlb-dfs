#!/usr/bin/env python3
"""outcome_review.py -- grade a delivery against the standings that already exist (R370).

THE DEFECT THIS CLOSES. Nothing in this tree joins a run, or a delivered
sha256, to a contest result. The archive knows what the FIELD did -- 584
contests in `ledger/own_results.json`, every one of them mined -- and not one
of those records carries a `run_id`, a delivered file, or a portfolio. The
miner's `summarize_own_entries` does the grading and has exactly one production
caller (`field_miner.py:2203`), driven by entry IDs a human types in. So "how
did the thing we built actually do" has been a hand reconstruction every time,
and on the host that now runs most sessions it was not reconstructible at all.

R369 supplied the missing half: `data/deliveries/<date>/<tag>_<run_id>.json` is
tracked, survives the container, and carries the delivered sha256 together with
every Entry ID parsed out of the delivered bytes. That is the join. This tool
walks it.

WHAT IT EMITS, per contest: rank span, points, whether any entry finished in a
paid position, how many of our own lineups the field duplicated, and planned
exposures against realized ones. Then one portfolio line: washout, defined as
NO entry of ours in a paid position anywhere.

WASHOUT IS THREE-VALUED AND THAT IS THE POINT. `false` means "we cashed
somewhere" and it is only sayable when every contest has a payout curve. A
contest whose curve is unknown makes the portfolio answer UNKNOWN, with the
contests named -- never `false`, which would read as a result. CLAUDE.md's dual
objective binds washout at the PORTFOLIO level, so a per-contest answer is not
a substitute.

TRUTHFUL LABELS. Everything here is an observed outcome read off a completed
contest: a rank, a point total, a paid-place count somebody wrote down. It is
never ROI, a win rate, a cash rate, an edge, or a probability, and the renderer
carries none of those words. `tests.test_core.OutcomeReviewTests` greps the
emitted text for them.

NEVER RAISES on a per-contest problem. A missing standings export, an
unreadable one, a contest the payout files do not cover: each resolves to a
named absence in the output and the rest of the portfolio still grades. Only a
bad invocation exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA_VERSION = 1

#: Ranked payout sources. The money export is first because it is the one that
#: covers satellites, and a satellite's `paid_places` IS its ticket count --
#: which is what makes a rank-1 finish gradeable as a seat (R30a). A GPP the
#: export does not cover stays UNKNOWN rather than being inferred from breadth.
PAID_PLACES_FILES = (
    "data/reference/dk_contest_money_2026-09-15.json",
    "data/reference/dk_contest_paid_places.json",
)

LABEL = ("observed outcomes read off completed contests, and a deterministic "
         "review proxy for the portfolio; never a graded prediction")


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------

def standings_candidates(root: Path, slate_date: str, contest_id: str) -> List[Path]:
    """Where one contest's standings export could be, most authoritative first.

    `data/archive/<slate_date>/` is where the miner MOVES a mined inbox CSV
    (`field_miner.archive_mined_standings`), so it is the durable home. The
    inbox is second because a pull that has not been mined yet is still a real
    export. The repo-wide archive sweep is last and exists because a contest
    that starts after midnight ET is filed under a date the delivery does not
    name, and a standings file found under the wrong date is still that
    contest's standings -- the contest id is in the filename.
    """
    cid = str(contest_id or "").strip()
    if not cid:
        return []
    out: List[Path] = []
    seen: set = set()

    def _add(path: Path) -> None:
        resolved = str(path)
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            out.append(path)

    _add(root / "data" / "archive" / str(slate_date) / f"contest-standings-{cid}.csv")
    for pattern in (f"*{cid}*.csv",):
        inbox = root / "data" / "standings" / "inbox"
        if inbox.is_dir():
            for path in sorted(inbox.glob(pattern)):
                _add(path)
        archive = root / "data" / "archive"
        if archive.is_dir():
            for path in sorted(archive.glob(f"*/contest-standings-{cid}.csv")):
                _add(path)
    return out


def resolve_paid_places(root: Path, contest_id: str) -> Tuple[Optional[int], str, str]:
    """``(paid_places, source_file, note)``; ``(None, "", why)`` when uncovered.

    Delegates to `field_miner.paid_places_from_file`, which already refuses to
    guess and already returns a sentence saying why. Both files are tried and
    the FIRST hit wins, so a contest in both reads one number rather than two.
    """
    from mlb_engine.field.field_miner import paid_places_from_file

    notes: List[str] = []
    for rel in PAID_PLACES_FILES:
        places, note = paid_places_from_file(str(root / rel), contest_id)
        if places is not None:
            return places, rel, note
        notes.append(note)
    return None, "", "; ".join(notes)


def money_row(root: Path, contest_id: str) -> Dict[str, Any]:
    """The observed fee/winnings row for a contest, or {}.

    Read off Ben's own DraftKings entry-history export. Observed history and
    nothing else: no figure here is derived, projected, or annualized.
    """
    try:
        payload = json.loads((root / PAID_PLACES_FILES[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    table = payload.get("contests") if isinstance(payload, Mapping) else None
    row = (table or {}).get(str(contest_id)) if isinstance(table, Mapping) else None
    return dict(row) if isinstance(row, Mapping) else {}


def id_to_name(root: Path, slate_date: str, contest_id: str) -> Tuple[Dict[str, str], str]:
    """``{DK player id: normalized name}``, or ``({}, why)``.

    The record holds PLAYER IDS (that is what a DKEntries cell carries) and a
    standings export holds NAMES, so planned and realized exposures are stated
    in two different alphabets. The crosswalk is the slate's salary file, found
    by CONTENT through R369's `record_salary_candidates` -- by the input sha256
    the record itself names, never by filename, because a bare `DKSalaries.csv`
    from one draftgroup silently answers for another.

    `data/slates/<date>/` is gitignored, so in a fresh container this resolves
    only once the salary export has been archived. That is an ordinary miss and
    it is REPORTED: the two exposure tables are still emitted, side by side and
    unjoined, rather than the whole section disappearing.
    """
    try:
        from mlb_engine.field.field_miner import load_salary_map, record_salary_candidates
        candidates = record_salary_candidates(root, str(slate_date), str(contest_id))
    except Exception as exc:  # noqa: BLE001
        return {}, f"salary crosswalk unavailable ({type(exc).__name__}: {exc})"
    if not candidates:
        return {}, ("no salary export matches the sha256 this record names, in "
                    "data/archive/<date>/ or data/slates/<date>/; planned and "
                    "realized exposures are reported unjoined")
    try:
        salary_map = load_salary_map(candidates[0])
    except (OSError, ValueError) as exc:
        return {}, f"{Path(candidates[0]).name} is unreadable ({exc})"
    out: Dict[str, str] = {}
    for key, rec in salary_map.items():
        if key.startswith("__") or "|" in key or not isinstance(rec, Mapping):
            continue
        pid = str(rec.get("player_id") or "").strip()
        if pid:
            out[pid] = key
    return out, f"joined through {Path(candidates[0]).name}"


# ---------------------------------------------------------------------------
# exposures
# ---------------------------------------------------------------------------

def _exposure(counter: Mapping[str, int], lineups: int) -> Dict[str, float]:
    if not lineups:
        return {}
    return {k: round(v / lineups, 4) for k, v in
            sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))}


def exposure_diff(planned: Mapping[str, int], realized: Mapping[str, int],
                  planned_lineups: int, realized_lineups: int,
                  crosswalk: Mapping[str, str], join_note: str) -> Dict[str, Any]:
    """Planned exposure against realized, joined when the crosswalk resolved.

    PLANNED is what the delivered file held. REALIZED is what DK's standings
    show under those same Entry IDs. They diverge for real reasons -- a late
    swap, an upload that took only some rows, a row DK voided -- and every one
    of those is a fact about the delivery that no other artifact records.

    Unjoined, both sides are still emitted: an id-keyed table and a name-keyed
    one, with the reason the join did not happen. A section that vanishes when
    a file is missing teaches a reader that nothing diverged.
    """
    out: Dict[str, Any] = {
        "planned_lineups": planned_lineups,
        "realized_lineups": realized_lineups,
        "join": join_note,
        "joined": bool(crosswalk),
    }
    if not crosswalk:
        out["planned_by_player_id"] = _exposure(planned, planned_lineups)
        out["realized_by_player_name"] = _exposure(realized, realized_lineups)
        return out
    planned_named: Counter = Counter()
    unmapped = 0
    for pid, count in planned.items():
        name = crosswalk.get(str(pid))
        if name is None:
            unmapped += count
            continue
        planned_named[name] += count
    planned_pct = _exposure(planned_named, planned_lineups)
    realized_pct = _exposure(realized, realized_lineups)
    moved = []
    for name in sorted(set(planned_pct) | set(realized_pct)):
        before = planned_pct.get(name, 0.0)
        after = realized_pct.get(name, 0.0)
        if abs(after - before) > 1e-9:
            moved.append({"player": name, "planned": before, "realized": after,
                          "delta": round(after - before, 4)})
    out["planned"] = planned_pct
    out["realized"] = realized_pct
    out["moved"] = moved
    out["unmapped_planned_slots"] = unmapped
    return out


# ---------------------------------------------------------------------------
# the review
# ---------------------------------------------------------------------------

def review_contest(root: Path, slate_date: str, contest_id: str,
                   rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Grade one contest. Returns a block; never raises."""
    from mlb_engine.field import field_miner as fm

    entry_ids = sorted({str(r.get("entry_id")) for r in rows if r.get("entry_id")})
    fees = {r.get("entry_fee") for r in rows if r.get("entry_fee") is not None}
    block: Dict[str, Any] = {
        "contest_id": str(contest_id),
        "contest_name": next((str(r.get("contest_name") or "") for r in rows
                              if r.get("contest_name")), ""),
        "entries_delivered": len(entry_ids),
        "entry_ids": entry_ids,
    }
    places, places_source, places_note = resolve_paid_places(root, contest_id)
    block["paid_places"] = places
    block["paid_places_source"] = places_source
    block["paid_places_note"] = places_note

    candidates = standings_candidates(root, slate_date, contest_id)
    if not candidates:
        block["status"] = "standings_absent"
        block["in_the_money"] = "UNKNOWN"
        block["note"] = (
            f"no standings export for {contest_id} under data/archive/ or "
            f"data/standings/inbox/; pull it (tools/awaiting_standings.py scan "
            f"lists what is outstanding) and run this again")
        return block
    path = candidates[0]
    block["standings_path"] = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    try:
        standings = fm.parse_standings_export(str(path))
        mined = fm.mine_contest(standings, None, contest_id=str(contest_id),
                                slate_date=str(slate_date))
    except (OSError, ValueError) as exc:
        block["status"] = "standings_unreadable"
        block["in_the_money"] = "UNKNOWN"
        block["note"] = f"{path.name} could not be parsed ({exc})"
        return block

    row = money_row(root, contest_id)
    entry_fee = (sorted(fees)[0] if fees else row.get("entry_fee"))
    summary = fm.summarize_own_entries(
        mined, entry_ids, entry_fee=entry_fee,
        winnings=row.get("winnings_total"), paid_places=places)
    block["status"] = "graded" if summary.get("matched") else "entries_unmatched"
    for key in ("matched", "requested", "field_size", "best_rank", "worst_rank",
                "best_points", "winning_points", "best_finish_percentile",
                "median_finish_percentile", "own_lineups_duplicated_by_field",
                "max_copies_of_an_own_lineup", "entry_fee", "fees_total",
                "winnings_total", "cashed_entries", "net", "note"):
        if key in summary:
            block[key] = summary[key]
    # Three-valued, and the UNKNOWN branch is the one that matters: a contest
    # whose curve nobody wrote down cannot say a rank-4 finish missed.
    if places is None:
        block["in_the_money"] = "UNKNOWN"
    elif not summary.get("matched"):
        block["in_the_money"] = "UNKNOWN"
    else:
        block["in_the_money"] = bool(summary.get("cashed_entries"))

    planned: Counter = Counter()
    planned_lineups = 0
    for entry in rows:
        ids = [str(p) for p in (entry.get("roster_ids") or []) if str(p).strip()]
        if not ids:
            continue
        planned_lineups += 1
        planned.update(ids)
    realized: Counter = Counter()
    realized_lineups = 0
    wanted = set(entry_ids)
    for entry in mined.get("entries") or []:
        if str(entry.get("entry_id")) not in wanted:
            continue
        realized_lineups += 1
        realized.update(entry.get("players_norm") or ())
    crosswalk, join_note = id_to_name(root, slate_date, contest_id)
    block["exposures"] = exposure_diff(planned, realized, planned_lineups,
                                       realized_lineups, crosswalk, join_note)
    return block


def portfolio_washout(contests: Sequence[Mapping[str, Any]]) -> Tuple[Any, str]:
    """``(True | False | "UNKNOWN", reason)``, and never ``False`` on a guess.

    One cash anywhere disproves a washout outright, whatever the other contests
    say, so that branch is checked first and is the only one that can return
    False. Otherwise any contest without a payout curve, or without standings,
    leaves the portfolio question open and it is returned open, with the
    contests named. Reporting `false` there would read as "we cashed" from an
    absence of evidence, which is the failure this project calls a fail-open.
    """
    if not contests:
        return "UNKNOWN", "this delivery names no contest, so there is nothing to grade"
    if any(c.get("in_the_money") is True for c in contests):
        cashed = [c["contest_id"] for c in contests if c.get("in_the_money") is True]
        return False, ("at least one entry finished in a paid position in "
                       + ", ".join(cashed))
    unknown = [c for c in contests if c.get("in_the_money") == "UNKNOWN"]
    if unknown:
        why = "; ".join(
            f"{c['contest_id']} ({c.get('note') or c.get('paid_places_note') or 'no payout curve'})"
            for c in unknown)
        return "UNKNOWN", ("no entry is known to have finished in a paid position, "
                           "and these contests cannot say either way: " + why)
    return True, ("every contest has a payout curve and no entry of ours "
                  "finished in a paid position")


def review_record(record: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    """The whole review for one delivery record."""
    manifest_row = record.get("manifest_row") or {}
    slate_date = str(record.get("date") or "")
    by_contest: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for entry in record.get("entries") or []:
        cid = str(entry.get("contest_id") or "").strip()
        if cid:
            by_contest[cid].append(entry)
    contests = [review_contest(root, slate_date, cid, rows)
                for cid, rows in sorted(by_contest.items())]
    washout, reason = portfolio_washout(contests)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "outcome_review",
        "date": slate_date,
        "slate_tag": str(manifest_row.get("slate_tag") or ""),
        "contest_type": str(manifest_row.get("contest_type") or ""),
        "run_id": manifest_row.get("run_id"),
        "delivered_file": manifest_row.get("delivered_file"),
        "delivered_sha256": manifest_row.get("sha256"),
        "certification": manifest_row.get("certification"),
        # R389(b). A baseline row's lineage, only when it has one, so its
        # review files beside the enhanced file's rather than over it.
        **({"lineage": str(manifest_row["lineage"])}
           if manifest_row.get("lineage") else {}),
        "record_path": str(record.get("_path") or ""),
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "contests": contests,
        "portfolio_washout": washout,
        "portfolio_washout_reason": reason,
        "labels": LABEL,
    }


# ---------------------------------------------------------------------------
# rendering and filing
# ---------------------------------------------------------------------------

def render(review: Mapping[str, Any]) -> str:
    """The human-readable review. Carries no forbidden label word, by test."""
    out: List[str] = []
    tag = review.get("slate_tag") or "untagged"
    out.append(f"# Outcome review -- {review.get('date')} {tag} "
               f"({review.get('contest_type') or 'classic'})")
    sha = str(review.get("delivered_sha256") or "")
    out.append(f"delivered file: {review.get('delivered_file') or 'unknown'}")
    out.append(f"delivered sha256: {sha or 'unrecorded'}")
    out.append(f"run: {review.get('run_id') or 'none'}   "
               f"certification: {review.get('certification') or 'unknown'}")
    out.append(f"record: {review.get('record_path') or 'unknown'}")
    out.append("")
    washout = review.get("portfolio_washout")
    shown = "UNKNOWN" if washout == "UNKNOWN" else ("YES" if washout else "NO")
    out.append(f"PORTFOLIO WASHOUT (no entry in a paid position): {shown}")
    out.append(f"  {review.get('portfolio_washout_reason')}")
    out.append("")
    for block in review.get("contests") or []:
        out.append(f"## {block.get('contest_id')} {block.get('contest_name') or ''}".rstrip())
        status = block.get("status")
        if status in ("standings_absent", "standings_unreadable"):
            out.append(f"  {status}: {block.get('note')}")
            out.append("")
            continue
        out.append(f"  standings: {block.get('standings_path')}")
        out.append(f"  entries delivered {block.get('entries_delivered')}, "
                   f"matched {block.get('matched')} of {block.get('requested')} "
                   f"in a field of {block.get('field_size')}")
        if block.get("note"):
            out.append(f"  {block['note']}")
        out.append(f"  rank {block.get('best_rank')} to {block.get('worst_rank')}"
                   f"   points best {block.get('best_points')}"
                   f"   contest best {block.get('winning_points')}")
        places = block.get("paid_places")
        itm = block.get("in_the_money")
        itm_shown = "UNKNOWN" if itm == "UNKNOWN" else ("yes" if itm else "no")
        out.append(f"  paid places: {places if places is not None else 'UNKNOWN'}"
                   f"{(' from ' + block['paid_places_source']) if block.get('paid_places_source') else ''}"
                   f"   entries in a paid position: "
                   f"{block.get('cashed_entries') if places is not None else 'UNKNOWN'}"
                   f"   any: {itm_shown}")
        if places is None and block.get("paid_places_note"):
            out.append(f"    {block['paid_places_note']}")
        out.append(f"  own lineups the field also had: "
                   f"{block.get('own_lineups_duplicated_by_field')}"
                   f"   most copies of one of ours: "
                   f"{block.get('max_copies_of_an_own_lineup')}")
        exposures = block.get("exposures") or {}
        out.append(f"  exposures: {exposures.get('planned_lineups')} lineup(s) "
                   f"delivered, {exposures.get('realized_lineups')} found in the "
                   f"standings -- {exposures.get('join')}")
        if exposures.get("joined"):
            moved = exposures.get("moved") or []
            if not moved:
                out.append("    planned and realized exposures agree on every player")
            for item in moved[:20]:
                out.append(f"    {item['player']}: planned {item['planned']} -> "
                           f"realized {item['realized']} ({item['delta']:+})")
            if len(moved) > 20:
                out.append(f"    ... and {len(moved) - 20} more")
        else:
            planned = exposures.get("planned_by_player_id") or {}
            realized = exposures.get("realized_by_player_name") or {}
            out.append(f"    planned, by player id: {len(planned)} player(s)")
            out.append(f"    realized, by name: {len(realized)} player(s)")
        out.append("")
    out.append(review.get("labels") or LABEL)
    return "\n".join(out)


def sidecar_path(record_path: Path) -> Path:
    """`<record>.outcome.json`, beside the record it grades.

    A sibling rather than a new tree: the record is the thing being graded and
    a reader who has one wants the other. It carries `kind: outcome_review`, and
    every reader of `delivery_record.read_records` already filters on
    `kind != "delivery"`, so a sidecar can never be mistaken for a delivery.
    """
    return record_path.with_suffix(".outcome.json")


def write_sidecar(review: Mapping[str, Any], record_path: Path) -> Optional[Path]:
    target = sidecar_path(record_path)
    text = json.dumps(review, indent=1, sort_keys=True, default=str)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(target))
        return target
    except OSError as exc:
        print(f"outcome review: sidecar not written ({exc})", file=sys.stderr)
        return None


def write_fragment(review: Mapping[str, Any], root: Path) -> Optional[Path]:
    """Drop the review in `ledger/inbox/` for ARCHIVE to merge.

    Only ARCHIVE edits the ledger (CLAUDE.md), and this tool runs wherever the
    delivery was. A fragment is the documented hand-off, and it is REPLACED on
    a re-run of the same delivery rather than appended -- the same rule
    `field_miner.write_ledger_fragment` follows, so a review run twice is one
    fragment rather than a double count in the one file the R10 gate reads.
    """
    tag = str(review.get("slate_tag") or "untagged") or "untagged"
    # R389(b). The baseline and the enhanced file are both live deliveries of
    # one slate; one fragment each, so neither review overwrites the other.
    if review.get("lineage"):
        tag = f"{tag}_{review['lineage']}"
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in tag)
    dest = root / "ledger" / "inbox" / f"{review.get('date')}_outcome_{safe}.md"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
        tmp.write_text(render(review).rstrip() + "\n", encoding="utf-8")
        os.replace(str(tmp), str(dest))
        return dest
    except OSError as exc:
        print(f"outcome review: fragment not written ({exc})", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# what is outstanding
# ---------------------------------------------------------------------------

def pending(root: Optional[Path] = None) -> List[Dict[str, str]]:
    """Delivery records with no review beside them. Never raises.

    This is the startup reconciliation line: a delivery nobody graded is the
    state R370 exists to end, and it is invisible unless something counts it.
    A refusal record is not pending -- there is no portfolio to grade.
    """
    base = Path(root) if root is not None else REPO
    try:
        from mlb_engine.entries.delivery_record import read_records
        out: List[Dict[str, str]] = []
        for record in read_records(root=base):
            if record.get("kind") != "delivery":
                continue
            raw = str(record.get("_path") or "")
            if not raw:
                continue
            path = base / raw
            if sidecar_path(path).exists():
                continue
            out.append({"record": raw, "date": str(record.get("date") or ""),
                        "slate_tag": str((record.get("manifest_row") or {}).get("slate_tag") or "")})
        return sorted(out, key=lambda r: (r["date"], r["record"]))
    except Exception:  # noqa: BLE001 - a hook calls this; it never fails a session
        return []


def pending_line(root: Optional[Path] = None) -> str:
    """One line for the session-start hook."""
    try:
        rows = pending(root)
    except Exception:  # noqa: BLE001
        return "outcome review due: not measured"
    if not rows:
        return "outcome review due: 0"
    names = ", ".join(f"{r['date']} {r['slate_tag'] or 'untagged'}" for r in rows[:4])
    more = f" (+{len(rows) - 4} more)" if len(rows) > 4 else ""
    return (f"outcome review due: {len(rows)} ({names}{more}); "
            f"python tools/outcome_review.py --date <date>")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _records_for(args, root: Path) -> List[Mapping[str, Any]]:
    from mlb_engine.entries.delivery_record import read_records

    if args.record:
        out = []
        for raw in args.record:
            path = Path(raw)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["_path"] = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
            out.append(payload)
        return out
    return [r for r in read_records(root=root, date=args.date)
            if r.get("kind") == "delivery"]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record", nargs="*",
                    help="delivery record JSON path(s); omit and use --date")
    ap.add_argument("--date", help="grade every delivery record for this slate date")
    ap.add_argument("--root", default=str(REPO), help="repo root (tests point this at a temp tree)")
    ap.add_argument("--json", action="store_true", help="emit the review as JSON")
    ap.add_argument("--no-sidecar", action="store_true", help="do not write <record>.outcome.json")
    ap.add_argument("--no-fragment", action="store_true", help="do not write the ledger/inbox fragment")
    ap.add_argument("--pending", action="store_true",
                    help="list delivery records with no review beside them, and exit")
    args = ap.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve()

    if args.pending:
        rows = pending(root)
        print(pending_line(root))
        for row in rows:
            print(f"  {row['record']}")
        return 0
    if not args.record and not args.date:
        ap.error("pass a record path or --date")

    try:
        records = _records_for(args, root)
    except (OSError, ValueError) as exc:
        print(f"ERROR  could not read the delivery record(s): {exc}", file=sys.stderr)
        return 3
    if not records:
        where = f"for {args.date}" if args.date else ""
        print(f"no delivery record {where} under {root / 'data' / 'deliveries'}; "
              f"nothing to grade. A build records itself; see R369.")
        return 0

    reviews = []
    for record in records:
        review = review_record(record, root)
        reviews.append(review)
        if args.json:
            print(json.dumps(review, indent=1, sort_keys=True, default=str))
        else:
            print(render(review))
            print()
        raw = str(record.get("_path") or "")
        record_path = (root / raw) if raw else None
        if record_path is not None and not args.no_sidecar:
            written = write_sidecar(review, record_path)
            if written:
                print(f"review written to {written}", file=sys.stderr)
        if not args.no_fragment:
            fragment = write_fragment(review, root)
            if fragment:
                print(f"ledger fragment for ARCHIVE at {fragment}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
