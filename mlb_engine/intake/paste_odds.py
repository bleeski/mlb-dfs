"""paste_odds.py -- a pasted odds table becomes an ordinary the-odds-api payload.

R236, and it is R32's pattern on a second source. ``api.the-odds-api.com`` is
proxy-gated in the cloud Cowork container exactly as ``statsapi.mlb.com`` is, so
a build that runs there prices no game at all: on 2026-08-24's 1940_7g a
certified file shipped with ``f1_games_priced: 0`` while
``enrichment.signal_applied`` read true, because five other factors had moved
rows. The F1-live rebuild moved the apex mean 144.0 -> 149.48 and cut CIN from
three stacks to one on the slate's second-weakest environment. F1 is not
cosmetic, and a source that cannot be reached needs a path that does not reach.

The output is a v4 events list, which is what ``normalize_odds_payload`` and
``parse_the_odds_api_totals`` already consume. Nothing downstream changes and
nothing downstream can tell the payload was typed.

**Per book, never averaged.** The operator workaround this replaces was reading
seven book columns across and averaging the moneylines BY EYE, which is R205's
arithmetic executed by hand: American odds are discontinuous at +/-100, and the
collapsed number cannot be audited back to any book afterwards. So the table is
LONG -- one row per game per book -- the book column is required, and every
posted price reaches the packet as that book's own price. R205 landed first, so
the parser de-vigs each book before averaging in probability space and multiple
books are now the better input rather than a new door onto the same bug.

The paste format, delimiter-tolerant (tab, comma, pipe, or two-plus spaces),
header-driven, with ``#`` comments and blank lines ignored::

    book        away  home  away_ml  home_ml  total
    draftkings  TEX   CWS   +110     -130     9.5
    fanduel     TEX   CWS   +116     -136     9.5
    draftkings  BAL   NYY   -155     +130     8.5

Teams may be DK codes, other books' codes (AZ, TBR, CHW...), full names, or
nicknames; everything normalizes through ``mlb_engine.team_codes``. ``game``
("TEX@CWS") substitutes for the ``away``/``home`` pair. ``over``/``under``
juice columns are optional and carried when present. A single-book paste may
omit the book column and name it once via ``default_book``.

What blocks, because a half-priced slate reaches F1 looking like a slate where
some teams genuinely have no market:

* a team that does not resolve,
* a slate game with no priced row,
* a row with no book name,
* a moneyline missing a side, or a price that is not a finite American number,
* a missing or unreadable total, since the packet's contract is keyed on it,
* two rows for the same game and book that disagree.

Rows for games the salary file does not carry are DROPPED and reported, never
blocked: the source table covers the whole day, including in-progress games,
and filtering that is this module's job.

A game that is not being played is owed no price (R397). It is exempt from the
"no priced row" block on an OBSERVED signal and named ``excluded_postponed``, the
word the pool uses for the same fact: a lineups feed that marks it postponed,
cancelled or suspended (the pool's own classifier), or the operator naming it.
DK's own ``Postponed`` Game Info literal never reaches the game set at all, and
is named too. An absent signal exempts nothing.

Nothing here reaches the network. The salary file is authoritative for which
games are on the slate and for their start times, so the emitted
``commence_time`` is the salary file's, and the packet's doubleheader leg
selection agrees with the lineups feed's by construction.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.team_codes import (
    dk_abbrev_to_team_name, is_dk_abbrev, team_name_to_dk_abbrev, to_dk_abbrev,
)

VERSION = "v1.0"

# Column synonyms. One canonical name per fact; every spelling a real paste is
# likely to carry maps onto it here rather than in the row loop.
_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "book": ("book", "sportsbook", "bookmaker", "site"),
    "game": ("game", "matchup", "game_id"),
    "away": ("away", "away_team", "road", "road_team", "visitor"),
    "home": ("home", "home_team"),
    "away_ml": ("away_ml", "away_moneyline", "away_price", "ml_away", "away_line"),
    "home_ml": ("home_ml", "home_moneyline", "home_price", "ml_home", "home_line"),
    "total": ("total", "game_total", "ou", "o_u", "over_under", "line"),
    "over": ("over", "over_price", "over_juice"),
    "under": ("under", "under_price", "under_juice"),
}
_HEADER_BY_SYNONYM = {syn: canonical
                      for canonical, syns in _COLUMNS.items() for syn in syns}

_SPLIT = re.compile(r"\t|\s*\|\s*|,|\s{2,}")


def _normalize_header(cell: str) -> str:
    text = str(cell or "").strip().lower().replace("/", "_").replace("-", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    return _HEADER_BY_SYNONYM.get(text, text)


def _split_row(line: str) -> List[str]:
    return [cell.strip() for cell in _SPLIT.split(line.strip()) if cell.strip() != ""]


def _resolve_team(value: str) -> Optional[str]:
    """A team as any source spells it -> its DK code, or None.

    Full names and nicknames first, then codes. ``to_dk_abbrev`` passes an
    unknown code through unchanged, so the code branch is gated on
    ``is_dk_abbrev``; without that gate a typo would resolve to itself and
    match nothing downstream in silence.
    """
    text = str(value or "").strip()
    if not text:
        return None
    named = team_name_to_dk_abbrev(text)
    if named:
        return named
    return to_dk_abbrev(text) if is_dk_abbrev(text) else None


def _american(value: Any) -> float:
    """A pasted American price -> float. ``+110``, ``110``, ``-130``, ``−130``."""
    text = str(value or "").strip().replace("−", "-").replace(",", "")
    text = text.lstrip("+")
    if text.lower() in ("even", "ev", "pk", "pick"):
        return 100.0
    if text in ("", "-"):
        raise ValueError("no price")
    price = float(text)
    if not math.isfinite(price):
        raise ValueError(f"{value!r} is not a finite American price")
    if price == 0 or abs(price) < 100:
        # Every well-formed American price is at least 100 away from zero.
        # R205's fabricated -2.0 lived in exactly this gap, and a paste that
        # carries one is a transcription error, not a market.
        raise ValueError(f"{value!r} is not a well-formed American price "
                         f"(|price| < 100)")
    return price


def _total(value: Any) -> float:
    text = str(value or "").strip().lstrip("ouOU").strip()
    line = float(text)
    if not math.isfinite(line) or line <= 0:
        raise ValueError(f"{value!r} is not a game total")
    return line


def parse_odds_paste(
    text: str,
    default_book: Optional[str] = None,
) -> Dict[str, Any]:
    """Pasted table -> ({game_id: {book: row}}, blockers, notes). No filtering yet.

    Slate membership is not this function's question; it needs the salary file
    and is settled in ``resolve_paste_to_odds_payload``.
    """
    blockers: List[str] = []
    rows_by_game: Dict[str, Dict[str, Dict[str, Any]]] = {}
    duplicates: List[str] = []
    header: Optional[List[str]] = None
    header_line = 0
    parsed_rows = 0

    def _refused() -> Dict[str, Any]:
        # Every return carries the same note keys. A caller formatting the
        # report should not have to know which failure it is looking at.
        return {"rows_by_game": {}, "blockers": blockers,
                "notes": {"header_line": 0, "header": [], "rows_parsed": 0,
                          "duplicate_rows_ignored": []}}

    lines = [line for line in str(text or "").splitlines()]
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = _split_row(stripped)
        if header is None:
            candidate = [_normalize_header(cell) for cell in cells]
            known = {c for c in candidate if c in _COLUMNS}
            if not ({"away", "home"} <= known or "game" in known) or not (
                    {"away_ml", "home_ml"} <= known):
                blockers.append(
                    f"line {number}: expected a header naming the columns; found "
                    f"{cells}. Required: away+home (or game), away_ml, home_ml, "
                    f"total; book unless a single book is named for the whole "
                    f"paste")
                return _refused()
            if "total" not in known:
                blockers.append(
                    f"line {number}: the header has no total column, and the odds "
                    f"packet is keyed on the game total: an event with no totals "
                    f"market is dropped by the parser, moneyline included")
                return _refused()
            header, header_line = candidate, number
            continue

        row = dict(zip(header, cells))
        where = f"line {number}"
        if len(cells) != len(header):
            blockers.append(
                f"{where}: {len(cells)} cell(s) against {len(header)} header "
                f"column(s) ({cells})")
            continue

        book = str(row.get("book") or default_book or "").strip().lower()
        if not book:
            blockers.append(
                f"{where}: no book named. Every price reaches the packet as some "
                f"book's price or not at all -- an unattributed column is the "
                f"hand-averaged consensus R236 exists to end")
            continue

        if row.get("game") and not (row.get("away") and row.get("home")):
            parts = re.split(r"\s*(?:@|vs\.?|at)\s*", str(row["game"]), maxsplit=1)
            if len(parts) != 2:
                blockers.append(f"{where}: cannot read {row['game']!r} as AWAY@HOME")
                continue
            row["away"], row["home"] = parts[0], parts[1]

        away = _resolve_team(row.get("away"))
        home = _resolve_team(row.get("home"))
        for label, raw in (("away", row.get("away")), ("home", row.get("home"))):
            if _resolve_team(raw) is None:
                blockers.append(
                    f"{where}: {label} team {str(raw or '').strip()!r} does not "
                    f"resolve to a DK team code")
        if away is None or home is None:
            continue
        game_id = f"{away}@{home}"

        try:
            prices = {away: _american(row.get("away_ml")),
                      home: _american(row.get("home_ml"))}
        except (TypeError, ValueError) as exc:
            blockers.append(f"{where}: {game_id} {book} moneyline unusable ({exc})")
            continue
        try:
            total = _total(row.get("total"))
        except (TypeError, ValueError) as exc:
            blockers.append(f"{where}: {game_id} {book} total unusable ({exc})")
            continue

        record: Dict[str, Any] = {"book": book, "away": away, "home": home,
                                  "moneyline": prices, "total": total,
                                  "source_line": number}
        for juice in ("over", "under"):
            if row.get(juice):
                try:
                    record[juice] = _american(row[juice])
                except (TypeError, ValueError):
                    record[juice] = None
        existing = rows_by_game.setdefault(game_id, {}).get(book)
        if existing is not None:
            same = (existing["moneyline"] == record["moneyline"]
                    and existing["total"] == record["total"])
            if not same:
                blockers.append(
                    f"{where}: {game_id} appears twice for {book} with different "
                    f"prices (line {existing['source_line']}: "
                    f"{existing['moneyline']} total {existing['total']}; here: "
                    f"{record['moneyline']} total {record['total']}). Two answers "
                    f"to one question is not a market")
                continue
            duplicates.append(f"{game_id} {book} (lines "
                              f"{existing['source_line']} and {number})")
            continue
        rows_by_game[game_id][book] = record
        parsed_rows += 1

    if header is None and not blockers:
        blockers.append("the paste carried no rows")
    return {
        "rows_by_game": rows_by_game,
        "blockers": blockers,
        "notes": {"header_line": header_line, "header": header or [],
                  "rows_parsed": parsed_rows,
                  "duplicate_rows_ignored": sorted(duplicates)},
    }


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_events(
    rows_by_game: Mapping[str, Mapping[str, Mapping[str, Any]]],
    game_times: Optional[Mapping[str, datetime]] = None,
    fetched_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """The parsed rows -> a the-odds-api v4 events list, one event per game.

    ``commence_time`` is the SALARY file's start for the matchup, not anything
    the paste claimed, so ``parse_the_odds_api_totals``' leg selection resolves
    to the leg on the slate by construction.
    """
    stamp = fetched_at or _iso(datetime.now(timezone.utc))
    events: List[Dict[str, Any]] = []
    for game_id in sorted(rows_by_game):
        away, _, home = game_id.partition("@")
        away_name = dk_abbrev_to_team_name(away)
        home_name = dk_abbrev_to_team_name(home)
        bookmakers: List[Dict[str, Any]] = []
        for book in sorted(rows_by_game[game_id]):
            record = rows_by_game[game_id][book]
            h2h = {"key": "h2h", "outcomes": [
                {"name": away_name, "price": record["moneyline"][away]},
                {"name": home_name, "price": record["moneyline"][home]}]}
            totals = {"key": "totals", "outcomes": [
                {"name": "Over", "point": record["total"],
                 "price": record.get("over")},
                {"name": "Under", "point": record["total"],
                 "price": record.get("under")}]}
            bookmakers.append({"key": book, "last_update": stamp,
                               "markets": [h2h, totals]})
        event: Dict[str, Any] = {
            "id": f"paste:{game_id}",
            "home_team": home_name,
            "away_team": away_name,
            "bookmakers": bookmakers,
        }
        start = (game_times or {}).get(game_id)
        if start is not None:
            event["commence_time"] = _iso(start)
        events.append(event)
    return events


def resolve_paste_to_odds_payload(
    text: str,
    salary_csv: Any,
    default_book: Optional[str] = None,
    fetched_at: Optional[str] = None,
    exclude_games: Optional[Sequence[str]] = None,
    lineups_feed: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Paste + salary file -> ({"events": [...], "report": {...}}).

    The salary file is authoritative for the slate's game set, exactly as it is
    for identity and eligibility everywhere else in this engine. A game it
    carries with no priced row BLOCKS; a priced row for a game it does not carry
    is dropped and named.

    R397. A salary game that is not being played is exempt from that block:
    ``lineups_feed`` marks it postponed, cancelled or suspended, or
    ``exclude_games`` names it (``AWAY@HOME``, any spelling the paste accepts).
    Each exempt game is named in ``excluded_postponed`` with the signal that
    exempted it, and any priced row for it is dropped rather than written: a
    price for a game nobody plays would move F1 for teams a stale salary file
    still carries. A name matching no salary game is a warning, never a block,
    because the unexempted game still blocks on its own.
    """
    parsed = parse_odds_paste(text, default_book=default_book)
    rows_by_game = parsed["rows_by_game"]
    blockers = list(parsed["blockers"])

    slate_games, game_times, salary_note, salary_literal = _slate_games(salary_csv)
    if salary_note:
        blockers.append(salary_note)
        slate_games = set()

    exempt, exclusion_warnings = _postponed_exemptions(
        slate_games, salary_csv, exclude_games, lineups_feed)
    required = slate_games - set(exempt)
    off_slate = sorted(set(rows_by_game) - slate_games) if slate_games else []
    kept = {gid: books for gid, books in rows_by_game.items()
            if not slate_games or gid in required}
    missing = sorted(required - set(kept)) if slate_games else []
    excluded_postponed = [
        {"game": gid, "teams": gid.split("@"), "signals": signals,
         "priced_books_dropped": sorted(rows_by_game.get(gid) or {})}
        for gid, signals in sorted(exempt.items())]
    for literal, teams in sorted(salary_literal.items()):
        excluded_postponed.append(
            {"game": None, "teams": teams,
             "signals": [f"salary Game Info {literal!r}"],
             "priced_books_dropped": []})
    if missing:
        blockers.append(
            "no priced row for " + ", ".join(missing) + ". A partial packet "
            "reaches F1 looking like a slate where those teams have no market, "
            "and an even split on a game the book did price is a fabrication "
            "the report cannot see. A game that is not being played is exempt "
            "on `--feed <lineups_feed.json>` or `--exclude-game AWAY@HOME`")

    events = build_events(kept, game_times, fetched_at) if not blockers else []
    report = {
        "games_priced": len(kept),
        # The games owed a price: the salary file's set less the exempt ones.
        "slate_games": len(required),
        "books_by_game": {gid: sorted(books) for gid, books in sorted(kept.items())},
        "books": sorted({book for books in kept.values() for book in books}),
        "games_off_slate_dropped": off_slate,
        "slate_games_unpriced": missing,
        "excluded_postponed": excluded_postponed,
        "exclusion_warnings": exclusion_warnings,
        "games_without_a_salary_start": sorted(
            gid for gid in kept if gid not in (game_times or {})),
        "blockers": blockers,
        "note": (
            "Every price is one named book's posted price. Nothing here is "
            "averaged across books: the packet parser de-vigs each book and "
            "averages in probability space (R205), which is the arithmetic a "
            "hand-read consensus gets wrong at the +/-100 boundary."
        ),
        **parsed["notes"],
    }
    return {"events": events, "report": report}


def _slate_games(salary_csv: Any) -> Tuple[set, Dict[str, datetime], Optional[str],
                                           Dict[str, List[str]]]:
    """The salary file's game set and start times, without importing the fetchers.

    ``live_data_adapters.salary_game_times`` is the one owner of the start-time
    rule and this defers to it, lazily: that module imports ``urllib.request``
    at module scope, and a paste path exists precisely because the network is
    not there. Same deferral ``paste_lineups`` makes, for the same reason.

    The fourth value is R397's naming of a case that was already exempt and
    silent: teams whose Game Info is a non-blank literal with no ``AWY@HOM``
    first token (DK's ``Postponed``), keyed by the literal. That is the pool's
    Signal 1 predicate (``build_slate_pool``, R26), including its stand-down: a
    file where EVERY team fails to parse is a format change, not a slate of
    postponements, and names nothing.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    from mlb_engine.intake.live_data_adapters import salary_game_times

    try:
        players = parse_dk_salary_csv(str(salary_csv))
    except Exception as exc:  # noqa: BLE001 - surfaced as a blocker, never a traceback
        return set(), {}, f"salary file unreadable: {exc}", {}
    games = {str(getattr(player, "game_id", "") or "").strip().upper()
             for player in players}
    games.discard("")
    team_game = {str(p.team): str(p.game_id or p.game_info or "")
                 for p in players if getattr(p, "team", "")}
    unparsed = {team: game for team, game in team_game.items()
                if game.strip() and "@" not in game.strip().split()[0]}
    literal: Dict[str, List[str]] = {}
    if unparsed and set(unparsed) != set(team_game):
        for team, game in sorted(unparsed.items()):
            literal.setdefault(game.strip(), []).append(team)
    try:
        times = salary_game_times(str(salary_csv))
    except Exception:  # noqa: BLE001 - times are a refinement; the game set is not
        times = {}
    return games, times, None, literal


def _postponed_exemptions(
    slate_games: set,
    salary_csv: Any,
    exclude_games: Optional[Sequence[str]],
    lineups_feed: Optional[Mapping[str, Any]],
) -> Tuple[Dict[str, List[str]], List[str]]:
    """R397. Salary games owed no price, each with the signals that say so.

    Two signals, both observations. The feed reading is the pool's own
    classifier (``build_status_map_from_lineups_feed``: a status containing
    "postpon", "cancel" or "suspend"), imported lazily for the reason
    ``_slate_games`` gives. The operator's name resolves through the paste's
    own team rule. A feed that cannot be read, and a name that matches no
    salary game, exempt nothing and are returned as warnings: the game they
    meant still blocks unless something else exempts it.
    """
    exempt: Dict[str, List[str]] = {}
    warnings: List[str] = []
    for raw in exclude_games or []:
        # `@` only: the paste's `vs`/`at` alternatives would split a lowercase
        # "atl@wsh" at its first two letters.
        parts = str(raw).strip().split("@")
        teams = [_resolve_team(part) for part in parts] if len(parts) == 2 else []
        gid = "@".join(teams) if len(teams) == 2 and all(teams) else None
        if gid and gid in slate_games:
            exempt.setdefault(gid, []).append("operator --exclude-game")
        else:
            warnings.append(
                f"--exclude-game {str(raw)!r} names no game on this salary "
                f"file's slate ({', '.join(sorted(slate_games)) or 'none'}); "
                "nothing exempted on it")
    if lineups_feed is not None:
        try:
            from mlb_engine.intake.live_data_adapters import (
                build_status_map_from_lineups_feed,
            )
            status = build_status_map_from_lineups_feed(lineups_feed, str(salary_csv))
        except Exception as exc:  # noqa: BLE001 - an unread feed exempts nothing
            warnings.append(f"lineups feed not read for postponements ({exc}); "
                            "no game exempted on it")
        else:
            meta = status.get("game_meta") or {}
            for gid in sorted(set(status.get("excluded_game_ids") or [])):
                if gid not in slate_games:
                    continue
                state = str((meta.get(gid) or {}).get("status")
                            or "postponed/cancelled/suspended")
                exempt.setdefault(gid, []).append(f"lineups feed status {state!r}")
    return exempt, warnings


def payload_matches_paste(
    parsed_packet: Mapping[str, Any],
    report: Mapping[str, Any],
) -> List[str]:
    """Differences between what was written and what the engine read back.

    The round trip is a property of every run, not of a test: the emitted file
    is only useful if ``parse_the_odds_api_totals`` returns every game it names,
    with the books it names. Returns a list of complaints; empty is agreement.
    """
    complaints: List[str] = []
    odds = parsed_packet.get("odds_by_game_id") or {}
    for game_id, books in (report.get("books_by_game") or {}).items():
        entry = odds.get(game_id)
        if entry is None:
            complaints.append(f"{game_id} was written and did not parse back")
            continue
        read_back = sorted(entry.get("moneyline_books") or {})
        if read_back != sorted(books):
            complaints.append(
                f"{game_id} parsed back with books {read_back} against the "
                f"paste's {sorted(books)}")
        if not entry.get("moneyline"):
            complaints.append(
                f"{game_id} parsed back with no moneyline consensus "
                f"({entry.get('moneyline_basis')})")
    for game_id in sorted(set(odds) - set(report.get("books_by_game") or {})):
        complaints.append(f"{game_id} parsed back and was never in the paste")
    return complaints
