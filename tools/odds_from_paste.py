#!/usr/bin/env python3
"""odds_from_paste.py -- your odds paste becomes the slate's odds packet.

R236. ``api.the-odds-api.com`` is proxy-gated in cloud sessions exactly as
``statsapi.mlb.com`` is, and a build that cannot reach it prices no game: on
2026-08-24's 1940_7g a certified file shipped with ``f1_games_priced: 0`` while
``enrichment.signal_applied`` read true, because five other factors had moved
rows. The rebuild with F1 live moved the apex mean 144.0 -> 149.48 and cut CIN
from three stacks to one on the slate's second-weakest environment. This is
R32's paste path on that second source: what you paste is what the packet says,
and ``build_slate.py --odds`` reads the result unchanged.

One row per game PER BOOK, and the book column is required. The workaround this
replaces was averaging seven book columns by eye, which is R205's bug executed
by hand and unauditable afterwards -- no per-book record survives a collapsed
"consensus". R205 has landed, so the packet parser de-vigs each book and
averages in probability space; more books is now strictly better input.

Usage:
    python tools/odds_from_paste.py --salary <DKSalaries.csv> \
        --paste <pasted.txt|->                        # '-' reads stdin
        [--out data/slates/<date>/odds_from_paste.json]
        [--book draftkings]     # names the book for a paste with no book column
        [--fetched-at <iso>]    # defaults to now, UTC
        [--exclude-game AWAY@HOME ...]   # a salary game not being played
        [--feed <lineups_feed.json>]     # its postponed/cancelled/suspended games
        [--json]

The paste, delimiter-tolerant (tab, comma, pipe, or two-plus spaces), with '#'
comments ignored::

    book        away  home  away_ml  home_ml  total
    draftkings  TEX   CWS   +110     -130     9.5
    fanduel     TEX   CWS   +116     -136     9.5

Teams may be codes (DK's or another book's), full names, or nicknames.
``game`` ("TEX@CWS") substitutes for ``away``/``home``.

Exit 0 clean, 2 on any blocker, 3 on IO. A blocker never writes the file: a
half-priced slate reaches F1 looking like a slate where some teams genuinely
have no market. Before writing, the emitted payload is READ BACK through
``normalize_odds_payload`` -> ``parse_the_odds_api_totals`` and compared to the
paste, so a file the engine cannot parse is never left on disk.

Nothing here fetches anything. The salary file is authoritative for which games
are on the slate and for their start times; a priced row for a game it does not
carry is dropped and reported, because the source table covers the whole day.

R397. A salary game that is not being played is owed no price. On 1840_5g the
salary file predated TOR@BAL's postponement and this tool refused "no priced row
for TOR@BAL" with every live game priced. ``--feed`` exempts what a lineups feed
marks postponed, cancelled or suspended (the pool's own reading); ``--exclude-game``
exempts a game the operator names. Both are reported as ``excluded_postponed``.
A feed that cannot be read, or a name that matches no salary game, is a warning
and exempts nothing, so the game it meant still blocks.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mlb_engine.intake.paste_odds import (  # noqa: E402
    payload_matches_paste, resolve_paste_to_odds_payload,
)


def _read_back(events, report) -> list:
    """Parse the payload the way a build will, and complain about differences.

    Imported here rather than at module scope: ``live_data_adapters`` pulls
    ``urllib.request``, and the tool's own import graph stays network-free for
    the same reason ``lineups_from_paste`` keeps its.
    """
    from mlb_engine.intake.live_data_adapters import (
        normalize_odds_payload, parse_the_odds_api_totals,
    )
    raw, _shape = normalize_odds_payload(events)
    return payload_matches_paste(parse_the_odds_api_totals(raw), report)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salary", required=True,
                    help="the slate's DKSalaries.csv; authoritative for which "
                         "games are on the slate and when they start")
    ap.add_argument("--paste", required=True,
                    help="file holding the pasted odds table, or '-' for stdin")
    ap.add_argument("--out", help="where to write the payload; defaults to stdout")
    ap.add_argument("--book",
                    help="the book name for a paste with no book column; a row "
                         "that names its own book still wins")
    ap.add_argument("--fetched-at",
                    help="ISO stamp recorded as each book's last_update; "
                         "defaults to now in UTC")
    ap.add_argument("--exclude-game", dest="exclude_games", action="append",
                    default=[], metavar="AWAY@HOME",
                    help="a salary-file game that is not being played "
                         "(postponed, cancelled, suspended); repeatable. It is "
                         "owed no price, any priced row for it is dropped, and "
                         "the report names it as excluded_postponed")
    ap.add_argument("--feed",
                    help="a lineups_feed.json; games it marks postponed, "
                         "cancelled or suspended are exempt the same way. A "
                         "feed fetched before the postponement says Scheduled, "
                         "and a pasted feed never says Postponed")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    try:
        text = (sys.stdin.read() if args.paste == "-"
                else Path(args.paste).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3

    feed, feed_warning = None, None
    if args.feed:
        try:
            feed = json.loads(Path(args.feed).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            feed_warning = (f"--feed {args.feed} not read ({exc}); no game "
                            "exempted on it")

    result = resolve_paste_to_odds_payload(
        text, args.salary, default_book=args.book, fetched_at=args.fetched_at,
        exclude_games=args.exclude_games, lineups_feed=feed)
    events, report = result["events"], result["report"]
    if feed_warning:
        report["exclusion_warnings"].insert(0, feed_warning)

    if events and not report["blockers"]:
        try:
            complaints = _read_back(events, report)
        except ValueError as exc:
            complaints = [f"the emitted payload did not normalize: {exc}"]
        report["round_trip"] = complaints or "parsed back to the same games and books"
        report["blockers"].extend(complaints)

    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"paste: {report['rows_parsed']} row(s), {report['games_priced']} "
              f"of {report['slate_games']} slate game(s) priced, book(s): "
              + (", ".join(report["books"]) or "none"))
        for game_id, books in report["books_by_game"].items():
            print(f"  {game_id}: {', '.join(books)}")
        if report["games_off_slate_dropped"]:
            print("off slate, dropped: "
                  + ", ".join(report["games_off_slate_dropped"]))
        if report["duplicate_rows_ignored"]:
            print("identical duplicate row(s) ignored: "
                  + ", ".join(report["duplicate_rows_ignored"]))
        for row in report["excluded_postponed"]:
            print(f"excluded_postponed: {row['game'] or '/'.join(row['teams'])} "
                  f"({'; '.join(row['signals'])})"
                  + (f", priced row(s) dropped: {', '.join(row['priced_books_dropped'])}"
                     if row["priced_books_dropped"] else ""))
        for line in report["exclusion_warnings"]:
            print(f"WARN  {line}", file=sys.stderr)
        if report["games_without_a_salary_start"]:
            print("no salary start time (leg resolution falls back to earliest): "
                  + ", ".join(report["games_without_a_salary_start"]))
        if isinstance(report.get("round_trip"), str):
            print(f"round trip: {report['round_trip']}")
        for line in report["blockers"]:
            print(f"BLOCKER  {line}", file=sys.stderr)

    if report["blockers"]:
        print(f"\nrefused: {len(report['blockers'])} blocker(s); nothing written. "
              f"A half-priced slate reaches F1 looking like a slate where those "
              f"teams have no market.", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(events, indent=1, default=str), encoding="utf-8")
        tmp.replace(out)
        print(f"wrote {out}  ->  build_slate.py --odds {out}")
    elif not args.json:
        print(json.dumps(events, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
