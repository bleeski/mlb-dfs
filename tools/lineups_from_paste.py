#!/usr/bin/env python3
"""lineups_from_paste.py -- your mlb.com paste becomes the slate's lineups feed.

R32. Ben pastes https://www.mlb.com/starting-lineups into the prompt. That paste
is ground truth for every team in it, and this turns it into an ordinary
``lineups_feed.json`` that ``build_slate.py --lineups`` and ``late_swap.py
--lineups`` already read. Nothing about the downstream path changes, which is the
point: the status map, the lock times, the confirmation contracts and
verify_export all keep working on a feed they cannot tell was typed rather than
fetched, except that every team carries ``source: operator_paste``.

The fallback rule, and it is the whole reason this exists: a team in the paste is
NEVER fetched. ``--merge-feed`` takes an API feed and uses it only for what the
paste does not cover -- a game you did not paste, a side still TBD. Paste a full
slate and the build makes zero network calls for lineups.

Usage:
    python tools/lineups_from_paste.py --salary <DKSalaries.csv> \
        --paste <pasted.txt|->                 # '-' reads stdin
        [--out data/slates/<date>/lineups_feed.json]
        [--merge-feed <api_feed.json>]         # fallback for uncovered teams only
        [--resolve "W Wilson=Weston Wilson"]   # settle an ambiguous name
        [--json]

Exit 0 clean, 2 on any blocker, 3 on IO. A blocker never writes the feed: a
half-resolved lineup is the pool reduction CLAUDE.md forbids, and it would
arrive looking like a posted partial. Three things block. A name that is
AMBIGUOUS or UNMATCHED, always. A side or a slate where too much of the paste is
ABSENT FROM THE DK POOL, because in bulk that is one wrong-pairing fact rather
than N call-ups; one absent name on its own is reported and shipped, since DK
owns eligibility. Nothing else.

Nothing here fetches anything, and nothing here corrects the paste against a
real-world roster. If the paste and the salary file disagree about a player's
team, that is reported and left alone; the CSV is authoritative for eligibility.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mlb_engine.intake.paste_lineups import resolve_paste_to_feed  # noqa: E402


def _parse_resolves(values: Optional[Sequence[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise ValueError(f"--resolve {item!r} is not '<pasted name>=<DK name>'")
        pasted, _, dk = item.partition("=")
        pasted, dk = pasted.strip(), dk.strip()
        if not pasted or not dk:
            raise ValueError(f"--resolve {item!r} has an empty side")
        out[pasted] = dk
    return out


def merge_feeds(pasted: Dict[str, Any], api: Dict[str, Any]) -> Dict[str, Any]:
    """Paste wins per SIDE; the API feed fills only what the paste left uncovered.

    Per side rather than per game, because a paste routinely covers one side of a
    game while the other is still TBD, and refetching the covered side to get the
    uncovered one would reintroduce exactly the disagreement this avoids.

    A side is 'covered' when the paste posted hitters for it. A pasted side with
    no hitters (tbd) yields to the API feed, which is the fallback working.
    """
    merged = dict(pasted)
    by_id: Dict[str, Dict[str, Any]] = {}
    for game in pasted.get("games") or []:
        key = f"{game['away']['team_abbrev']}@{game['home']['team_abbrev']}"
        by_id[key] = game

    added_games: List[str] = []
    filled_sides: List[str] = []
    for game in api.get("games") or []:
        away = (game.get("away") or {}).get("team_abbrev")
        home = (game.get("home") or {}).get("team_abbrev")
        if not away or not home:
            continue
        key = f"{away}@{home}"
        existing = by_id.get(key)
        if existing is None:
            enriched = dict(game)
            enriched["source"] = "api_feed_fallback"
            # Provenance is per SIDE everywhere, because that is the grain the
            # paste-wins rule works at and the grain the report is keyed on. A
            # side with no source is a side nobody can attribute later.
            for side in ("away", "home"):
                if isinstance(enriched.get(side), dict):
                    enriched[side] = {**enriched[side], "source": "api_feed_fallback"}
            merged.setdefault("games", []).append(enriched)
            added_games.append(key)
            continue
        for side in ("away", "home"):
            if (existing.get(side) or {}).get("lineup"):
                continue  # the paste covered it; never refetch, never overwrite
            replacement = dict(game.get(side) or {})
            if not replacement.get("lineup") and not replacement.get("probable_pitcher"):
                continue
            replacement["source"] = "api_feed_fallback"
            existing[side] = replacement
            filled_sides.append(f"{key} {side}")

    merged["merge_report"] = {
        "games_added_from_api": sorted(added_games),
        "sides_filled_from_api": sorted(filled_sides),
        "paste_is_complete": not added_games and not filled_sides,
    }
    return merged


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salary", required=True,
                    help="the slate's DKSalaries.csv; authoritative for identity, "
                         "eligibility and lock times")
    ap.add_argument("--paste", required=True,
                    help="file holding the mlb.com paste, or '-' for stdin")
    ap.add_argument("--out", help="where to write the feed; defaults to stdout")
    ap.add_argument("--merge-feed",
                    help="an API lineups feed used ONLY for teams the paste does "
                         "not cover")
    ap.add_argument("--resolve", action="append", default=[],
                    help="'<pasted name>=<full DK name>', repeatable; settles an "
                         "ambiguous match such as two same-initial teammates")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    try:
        overrides = _parse_resolves(args.resolve)
        text = (sys.stdin.read() if args.paste == "-"
                else Path(args.paste).read_text(encoding="utf-8"))
        result = resolve_paste_to_feed(text, args.salary, resolve_overrides=overrides)
    except (OSError, ValueError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3

    feed, report = result["feed"], result["report"]
    if args.merge_feed:
        try:
            api = json.loads(Path(args.merge_feed).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"ERROR  --merge-feed unreadable: {exc}", file=sys.stderr)
            return 3
        feed = merge_feeds(feed, api)
        report["merge"] = feed.get("merge_report")

    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"paste: {report['games_parsed']} game(s) parsed, "
              f"{report['games_used']} on this slate, {report['resolved']} "
              f"name(s) resolved to DK rows")
        print("confirmed from the paste (never fetched): "
              + (", ".join(report["confirmed_teams"]) or "none"))
        for row in report["partial_teams"]:
            print(f"PARTIAL  {row['team']} {row['hitters_posted']}/9 "
                  f"({row['reason']}) -- projected, not confirmed")
        for row in report.get("dk_declared_probables") or []:
            print(f"DK STARTING  {row['team']}: {row['name']} -- the paste left "
                  f"this side's probable unnamed and DK's Starting column names "
                  f"him; no handedness, so the platoon view falls back")
        for row in report["unrostered_starters"]:
            print(f"NOT IN DK POOL  {row['team']} slot {row['order']}: "
                  f"{row['pasted_name']} -- {row['note']}")
        for text_line in report["warnings"]:
            print(f"WARN  {text_line}")
        if report.get("merge"):
            merge = report["merge"]
            if merge["paste_is_complete"]:
                print("fallback: not needed, the paste covered every game and "
                      "side on this slate. Zero lineup fetches.")
            else:
                print(f"fallback from the API feed: games "
                      f"{merge['games_added_from_api'] or 'none'}, sides "
                      f"{merge['sides_filled_from_api'] or 'none'}")
        for text_line in report["blockers"]:
            print(f"BLOCKER  {text_line}", file=sys.stderr)

    if report["blockers"]:
        print(f"\nrefused: {len(report['blockers'])} blocker(s); no feed written. "
              f"A half-resolved lineup would arrive downstream looking like a "
              f"posted partial, which is the pool reduction the contract "
              f"forbids.", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(feed, indent=1, default=str), encoding="utf-8")
        tmp.replace(out)
        print(f"wrote {out}")
    elif not args.json:
        print(json.dumps(feed, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
