#!/usr/bin/env python3
"""build_slate.py -- one command from uploaded DK files to a certified upload file.

Detects Classic vs Showdown from the files themselves, stages inputs, builds the
pool, decides a solve strategy that fits the execution budget, builds, certifies,
verifies, and writes a short brief.

Resumability is the point of --max-seconds. Bash calls in Cowork are killed the
moment the call returns, so an unbounded build produces no output and no
diagnostic and you cannot tell a hard slate from a hung one. This script does as
much as fits, persists the candidate bank, and exits 10 to mean "run me again".
Each rerun picks up where the last one stopped.

Exit codes:
    0   certified file written
    10  partial progress saved, run the same command again
    3   build ran but did not certify (errors printed)
    4   inputs missing or unreadable

Every number this prints is a deterministic review proxy or a labeled prior.
Nothing here is ROI, win rate, cash rate, or a probability claim. Nothing here
touches DraftKings: lineups and money move only at Ben's manual upload.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# F19: pinned before anything else runs, because the interpreter reads
# PYTHONHASHSEED at startup and setting it later does nothing. This is the
# build that writes the file Ben uploads, so "same inputs, same file" has to be
# true here or it is not true anywhere. Solver-facing collections are sorted
# regardless; this closes the gap for anything the sorting misses.
#
# Only when run as a script. The test suite imports this module to drive its
# functions directly, and a module-level execve would replace the test runner's
# process on import.
if (__name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0"
        and sys.executable):
    try:
        os.execve(sys.executable, [sys.executable, *sys.argv],
                  {**os.environ, "PYTHONHASHSEED": "0"})
    except OSError:
        pass  # a slate that builds on an unpinned seed beats one that does not


def _find_repo() -> Path:
    """Locate the mlb-dfs engine root.

    An installed skill lives outside the repo, so the root cannot be derived from
    __file__ alone. Order: explicit env var, then a walk up from this file (works
    when the skill is versioned inside the repo), then the usual workspace mount
    paths. Failing loudly here beats importing a half-present package later.
    """
    import os

    env = os.environ.get("MLB_DFS_ROOT")
    if env and (Path(env) / "mlb_engine").is_dir():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "mlb_engine").is_dir() and (parent / "CLAUDE.md").exists():
            return parent
    for guess in (
        Path.home() / "Documents" / "Claude" / "mlb-dfs",
        Path("/sessions") / "mnt" / "mlb-dfs",
    ):
        if (guess / "mlb_engine").is_dir():
            return guess
    for mount in Path("/sessions").glob("*/mnt/mlb-dfs"):
        if (mount / "mlb_engine").is_dir():
            return mount
    raise SystemExit(
        "cannot locate the mlb-dfs engine. Set MLB_DFS_ROOT to the repo root."
    )


REPO = _find_repo()
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SALARY_CAP = 50000
CLASSIC_SLOTS = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")
MAX_HITTERS_PER_TEAM = 5
MIN_GAMES_PER_LINEUP = 2


# --------------------------------------------------------------------------- #
# Contest-type detection: the files already answer this, so never ask.
# --------------------------------------------------------------------------- #
def detect_contest_type(salary_csv: Path, entries_csv: Path) -> str:
    """Return 'showdown' or 'classic'.

    DK declares the roster geometry in both files: a Showdown salary file lists
    Roster Position CPT/UTIL and its entries header is CPT,UTIL x5, while Classic
    lists P/C/1B/... and P,P,C,1B,2B,3B,SS,OF,OF,OF. Reading it beats asking.
    """
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh), [])
    if "CPT" in header:
        return "showdown"
    with salary_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("Roster Position", "")).strip().upper() in ("CPT", "UTIL"):
                return "showdown"
            break
    return "classic"


def slate_date_from_salary(salary_csv: Path) -> str:
    from mlb_engine.intake.slate_intake_manager import (
        parse_dk_salary_csv, parse_game_info_datetime,
    )
    for sp in parse_dk_salary_csv(str(salary_csv)):
        parsed = parse_game_info_datetime(sp.game_info)
        if parsed is not None:
            return parsed.date().isoformat()
    return dt.date.today().isoformat()


def feed_age_minutes(feed: dict) -> float | None:
    """Minutes since the feed was fetched, or None when it does not say.

    The feed has always carried `fetched_at` and nothing ever read it, so a
    morning file on disk beat a fresh fetch silently.
    """
    stamp = (feed or {}).get("fetched_at")
    if not stamp:
        return None
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - when
    return round(delta.total_seconds() / 60.0, 1)


def manifest_repo_relative(path) -> str | None:
    if not path:
        return None
    from mlb_engine.entries.upload_manifest import repo_relative
    return repo_relative(path)


def manifest_sha256(path) -> str | None:
    if not path or not Path(path).exists():
        return None
    from mlb_engine.entries.upload_manifest import sha256_file
    return sha256_file(path)


def slate_tag_suffix(salary_csv: Path) -> str:
    """'_1610_1g' for the delivered filename, so same-date builds cannot collide.

    Three Showdown slates on 2026-07-25 each recorded a delivered_path of
    .../DKEntries_showdown.csv, so two briefs ended up citing a file holding
    another slate's lineups. The delivered name always carries the slate tag.
    """
    try:
        tag = str(slate_signature(Path(salary_csv)).get("tag") or "").strip()
    except Exception:
        tag = ""
    return f"_{tag}" if tag else ""


def slate_signature(salary_csv: Path) -> dict:
    """Identify the draftgroup, not just the date.

    DK runs more than one Classic draftgroup on most dates: a main slate and a
    night slate, sometimes an early one. Keying staged inputs and delivered
    artifacts by date alone means the second build of the day overwrites the
    first one's staged CSVs and its delivered DKEntries.csv. On 2026-07-24 a
    night-slate build destroyed a certified main-slate file that survived only
    because it had been copied aside by hand.

    Returns the game set and a short human-readable tag (first lock in ET plus
    game count, e.g. "1905_10g"), so a caller can both name a slate and tell two
    slates apart without trusting filenames.
    """
    from mlb_engine.intake.slate_intake_manager import (
        parse_dk_salary_csv, parse_game_info_datetime,
    )
    games, starts = set(), []
    for sp in parse_dk_salary_csv(str(salary_csv)):
        info = getattr(sp, "game_info", "") or ""
        gid = str(getattr(sp, "game_id", "") or info.split(" ", 1)[0] or "").strip()
        if gid:
            games.add(gid)
        parsed = parse_game_info_datetime(info)
        if parsed is not None:
            starts.append(parsed)
    first = min(starts) if starts else None
    tag = f"{first.strftime('%H%M')}_{len(games)}g" if first else f"{len(games)}g"
    # The contract goes in the tag. A Showdown slate is one game, so its tag
    # renders as "1915_1g", which is indistinguishable from a one-game Classic
    # draftgroup. preserve_prior_slate used that tag to rename a Showdown pair
    # aside on 2026-07-25 and the result read as Classic on disk, which is
    # exactly the confusion the tag exists to prevent.
    from mlb_engine.entries.dk_entries_manager import detect_salary_contract
    contract = detect_salary_contract(salary_csv)
    if contract == "SHOWDOWN":
        tag = f"{tag}_sd"
    return {"games": frozenset(games), "tag": tag, "contract": contract,
            "first_lock": first.isoformat() if first else None}


def _self_declared_tag(path: Path) -> str:
    """A brief names its own slate; a delivered file's sibling brief names its.

    The tag used to come from whatever was staged at the moment of the rename,
    not from the file being renamed. On 2026-07-25 that filed the certified
    10-game Classic export away as ``DKEntries_1915_1g.csv``, borrowing the tag
    of a one-game Showdown slate it had nothing to do with, and wrote the same
    brief under two names. A file that can state its own slate should be asked.
    """
    try:
        if path.suffix == ".json" and path.name.startswith("build_brief"):
            return str((json.loads(path.read_text(encoding="utf-8"))
                        .get("slate") or {}).get("tag") or "")
        if path.suffix == ".csv" and path.name.startswith("DKEntries"):
            sibling = path.with_name(
                path.name.replace("DKEntries", "build_brief").replace(".csv", ".json"))
            if sibling.exists():
                return str((json.loads(sibling.read_text(encoding="utf-8"))
                            .get("slate") or {}).get("tag") or "")
    except (OSError, ValueError):
        return ""
    return ""


def preserve_prior_slate(paths, tag: str) -> list:
    """Move artifacts from a different draftgroup aside instead of overwriting.

    Silent overwriting is the failure; a renamed file that is still on disk is
    recoverable, and the rename is printed so it is never a surprise.
    """
    moved = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        own = _self_declared_tag(path)
        if own and own != tag:
            print(f"preserve: {path.name} declares slate {own}, not {tag}; "
                  f"filing it under its own tag", file=sys.stderr)
        dest = path.with_name(f"{path.stem}_{own or tag}{path.suffix}")
        if dest.exists() and dest.read_bytes() == path.read_bytes():
            # The tag-copy already exists with identical content, which is what
            # happens when the delivery path also writes the tagged name. Minting
            # a _1 here produced three duplicate briefs in outputs/2026-07-25/ and
            # made the directory unreadable.
            continue
        n = 1
        while dest.exists():
            dest = path.with_name(f"{path.stem}_{tag}_{n}{path.suffix}")
            n += 1
        path.rename(dest)
        moved.append(str(dest))
        print(f"preserved prior slate artifact: {path.name} -> {dest.name}",
              file=sys.stderr)
    return moved


def fetch_handedness(player_ids) -> dict:
    """Map MLBAM id -> {"bat": code, "pitch": code} for the supplied players.

    The schedule hydrate returns lineup players and probable pitchers as id +
    fullName only, with no handedness on either. That left ``bat_side`` absent on
    every hitter and ``hand`` None on every probable, so BOTH inputs to the F4
    platoon prior were missing and the component was structurally dead no matter
    how well the rest of the enrichment was wired. One batched /people call
    supplies both. Failure is non-fatal: F4's team-level opposing-SP quality
    component still applies and only the platoon multiplier goes neutral.
    """
    ids = sorted({str(p) for p in player_ids if p})
    if not ids:
        return {}
    out: dict = {}
    base = "https://statsapi.mlb.com/api/v1"
    for start in range(0, len(ids), 250):  # keep the query string sane
        chunk = ",".join(ids[start:start + 250])
        url = (f"{base}/people?personIds={chunk}"
               "&fields=people,id,batSide,pitchHand,code")
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"handedness hydrate failed ({exc}); F4 platoon component will "
                  "be neutral for this build", file=sys.stderr)
            continue
        for person in payload.get("people") or []:
            entry = {}
            for key, field in (("bat", "batSide"), ("pitch", "pitchHand")):
                code = str(((person.get(field) or {}).get("code") or "")).strip().upper()
                if code in ("L", "R", "S"):
                    entry[key] = code
            if entry:
                out[str(person.get("id"))] = entry
    return out


def fetch_lineups(date: str, dest: Path) -> dict:
    """Minimal MLB Stats API pull, used only when no feed was supplied.

    The mlb-lineups skill is the canonical fetcher and handles more edge cases;
    this exists so a missing feed degrades to a slower path instead of a dead end.
    """
    base = "https://statsapi.mlb.com/api/v1"
    url = (f"{base}/schedule?sportId=1&date={date}"
           "&hydrate=lineups,probablePitcher,team")
    with urllib.request.urlopen(url, timeout=25) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    games = []
    for day in raw.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            lineups = game.get("lineups") or {}

            def side(key, lineup_key):
                info = teams.get(key, {}) or {}
                team = (info.get("team") or {})
                pitcher = info.get("probablePitcher") or {}
                players = lineups.get(lineup_key) or []
                return {
                    "team_abbrev": team.get("abbreviation", ""),
                    "lineup_status": "confirmed" if len(players) >= 9 else "tbd",
                    "lineup": [
                        {"order": i + 1, "id": p.get("id"), "name": p.get("fullName")}
                        for i, p in enumerate(players)
                    ],
                    "probable_pitcher": ({
                        "id": pitcher.get("id"), "name": pitcher.get("fullName"),
                        "hand": ((pitcher.get("pitchHand") or {}).get("code")),
                    } if pitcher else None),
                }

            games.append({
                "game_pk": game.get("gamePk"),
                "game_date_utc": game.get("gameDate", "").replace("+00:00", "Z"),
                "status": (game.get("status") or {}).get("detailedState", ""),
                "away": side("away", "awayPlayers"),
                "home": side("home", "homePlayers"),
            })

    # Attach handedness so extract_batter_hands and extract_opposing_probables
    # have something to read. Both are inputs to the F4 platoon prior.
    wanted = []
    for game_entry in games:
        for team_side in (game_entry["away"], game_entry["home"]):
            wanted += [h.get("id") for h in team_side["lineup"]]
            probable = team_side.get("probable_pitcher") or {}
            if probable.get("id"):
                wanted.append(probable["id"])
    hand_by_id = fetch_handedness(wanted)
    for game_entry in games:
        for team_side in (game_entry["away"], game_entry["home"]):
            for hitter in team_side["lineup"]:
                code = (hand_by_id.get(str(hitter.get("id"))) or {}).get("bat")
                if code:
                    hitter["bat_side"] = code
            probable = team_side.get("probable_pitcher") or {}
            if probable and not probable.get("hand"):
                code = (hand_by_id.get(str(probable.get("id"))) or {}).get("pitch")
                if code:
                    probable["hand"] = code

    feed = {"date": date, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "games": games}
    dest.write_text(json.dumps(feed), encoding="utf-8")
    return feed


def resolve_platoon_json(args):
    """RotoWire projected orders overlaid on the FanGraphs reference, for TBD teams.

    The MLB Stats API (and mlb.com, which renders it) only shows a lineup once the
    team officially posts it; until then the team reads TBD. RotoWire publishes a
    beat-projected order for those teams and refreshes it through the day. This
    fetches RotoWire and merges it over the manually-refreshed FanGraphs platoon
    reference, so a TBD team gets the freshest projected order available: RotoWire
    where it covers the team, FanGraphs otherwise, and top-9 AvgPointsPerGame only
    when neither does.

    The merged dict is handed to build_slate_pool as platoon_json, so
    build_projected_order applies it strictly to TBD teams (only_teams) and always
    as a projected order, never a confirmed one. A confirmed lineup posted later
    still supersedes it. Any failure returns None, which restores the engine's
    default FanGraphs-only behavior. RotoWire is a public HTTP page; this never
    touches DraftKings.
    """
    if not getattr(args, "rotowire", True):
        return None
    today = dt.date.today().isoformat()
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    rw_when = "today" if args.date == today else "tomorrow" if args.date == tomorrow else None
    if rw_when is None:
        # RotoWire only serves today and tomorrow; a backfill keeps the default.
        return None
    try:
        from tools.fetch_rotowire_lineups import fetch_rotowire_platoon
        from mlb_engine.intake.live_data_adapters import to_dk_abbrev
        from mlb_engine.intake.platoon_order_adapter import (
            DEFAULT_PLATOON_REFERENCE, load_platoon_lineups,
        )
        rw = fetch_rotowire_platoon(rw_when, collected_date=args.date)
        # Key on the DK code, not the raw abbrev: FanGraphs ships TBR/SDP/SFG where
        # RotoWire ships TB/SD/SF, so a raw-code merge would leave two entries for
        # one club and let a stale FanGraphs-only hitter survive next to RotoWire's
        # nine. Normalizing both sides lets RotoWire replace FanGraphs outright.
        by_team: dict = {}
        ref = DEFAULT_PLATOON_REFERENCE
        if not ref.is_absolute():
            ref = REPO / ref
        if ref.exists():
            for t in load_platoon_lineups(ref).get("teams") or []:
                by_team[to_dk_abbrev(t.get("abbrev", ""))] = t
        rw_n = 0
        for t in rw.get("teams") or []:
            by_team[to_dk_abbrev(t.get("abbrev", ""))] = t  # RotoWire wins
            rw_n += 1
        print(f"rotowire: merged {rw_n} projected lineups over the FanGraphs "
              "reference", file=sys.stderr)
        return {
            "source": "merged: RotoWire (fresh) over FanGraphs reference",
            "collected_date": args.date,
            "teams": list(by_team.values()),
        }
    except Exception as exc:  # never let a fallback source break the build
        print(f"rotowire fetch unavailable ({exc}); using FanGraphs reference only",
              file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Shared verification. The upload file is the only thing that matters, so check
# it directly rather than trusting the build report.
# --------------------------------------------------------------------------- #
def verify_classic(salary_csv: Path, entries_csv: Path) -> dict:
    with salary_csv.open(encoding="utf-8-sig", newline="") as fh:
        salary = {r["ID"]: r for r in csv.DictReader(fh)}
    failures, lineups = [], []
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 14 or not row[0].strip().isdigit():
                continue
            eid, ids = row[0].strip(), [c.strip() for c in row[4:14]]
            if any(not p for p in ids):
                failures.append(f"{eid}: blank slot")
                continue
            if any(p not in salary for p in ids):
                failures.append(f"{eid}: unknown player id")
                continue
            players = [salary[p] for p in ids]
            total = sum(int(p["Salary"]) for p in players)
            if total > SALARY_CAP:
                failures.append(f"{eid}: salary {total} over cap")
            if len(set(ids)) != 10:
                failures.append(f"{eid}: duplicate player")
            bad = [i for i in range(10)
                   if CLASSIC_SLOTS[i] not in str(players[i]["Roster Position"]).split("/")]
            if bad:
                failures.append(f"{eid}: slot ineligibility at {bad}")
            teams = {}
            for p in players[2:]:
                teams[p["TeamAbbrev"]] = teams.get(p["TeamAbbrev"], 0) + 1
            # DK Classic legality, checked here because this is the last
            # independent look at the file before Ben uploads it: at most 5
            # hitters from one team, and players from at least 2 games.
            over = [f"{t} {n}" for t, n in teams.items() if n > MAX_HITTERS_PER_TEAM]
            if over:
                failures.append(f"{eid}: more than {MAX_HITTERS_PER_TEAM} hitters "
                                f"from one team ({', '.join(sorted(over))})")
            games = {str(p.get("Game Info", "")).split(" ", 1)[0] for p in players}
            games.discard("")
            if len(games) < MIN_GAMES_PER_LINEUP:
                failures.append(f"{eid}: players from {len(games)} game(s), "
                                f"DK requires {MIN_GAMES_PER_LINEUP}")
            top = sorted(teams.items(), key=lambda kv: -kv[1])[:2]
            lineups.append({"entry_id": eid, "salary": total, "stack": top})
    return {"passed": not failures, "failures": failures, "lineups": lineups}


# --------------------------------------------------------------------------- #
# Projection enrichment. Everything below exists because a build that skips it
# certifies exactly as cleanly as one that does not: with no reference data the
# engine ranks players on AvgPointsPerGame times a batting-order factor and
# nothing else, and no gate anywhere in the pipeline can tell the difference.
# The enrichments themselves already exist and are tested; the only thing that
# was ever missing on this path was the wiring.
# --------------------------------------------------------------------------- #
def resolve_reference_data(args) -> dict:
    """Locate the enrichment inputs and report how fresh they are.

    Returns a dict with the three CSV paths (None when absent or when
    enrichment is disabled) plus the status block that rides into the brief.
    Missing or stale files never block a build: degraded signal beats no
    lineups at T-10. They are loud instead, in the brief and on stderr.
    """
    status: dict = {"enabled": bool(getattr(args, "enrichment", True))}
    if not status["enabled"]:
        status["note"] = ("enrichment disabled with --no-enrichment; this build "
                          "ranks on AvgPointsPerGame x batting-order factor only")
        print(f"enrichment: {status['note']}", file=sys.stderr)
        return {"savant_batting": None, "savant_pitching": None,
                "fangraphs_pitching": None, "status": status}

    try:
        from tools.refresh_reference_data import reference_status
        report = reference_status(
            Path(getattr(args, "reference_dir", None) or (REPO / "data" / "reference")),
            max_age_days=getattr(args, "reference_max_age_days", 14.0),
        )
    except Exception as exc:  # a reporting failure must never kill a build
        status["note"] = f"reference-data status unavailable ({exc}); enrichment OFF"
        print(f"enrichment: {status['note']}", file=sys.stderr)
        return {"savant_batting": None, "savant_pitching": None,
                "fangraphs_pitching": None, "status": status}

    files = report["files"]
    status.update({
        "files": {name: {"age_days": info["age_days"], "stale": info["stale"],
                         "exists": info["exists"]}
                  for name, info in files.items()},
        "warnings": list(report["warnings"]),
        "any_stale": report["any_stale"],
    })
    for warning in status["warnings"]:
        print(f"enrichment warning: {warning}", file=sys.stderr)

    def usable(name: str):
        info = files.get(name) or {}
        return info["path"] if info.get("exists") else None

    return {
        "savant_batting": usable("expected_stats_batting.csv"),
        "savant_pitching": usable("expected_stats_pitching.csv"),
        "fangraphs_pitching": usable("fangraphs_season_pitching.csv"),
        "status": status,
    }


def load_odds_packet(args) -> tuple[dict, dict]:
    """Return ({game_id: odds entry}, note) for the slate, or ({}, note).

    Accepts an --odds file in either shape the project produces: a raw
    the-odds-api events list, an mlb-game-odds payload wrapping one, or a
    slate_bundle carrying ``odds_raw_totals``. Falls back to fetching when
    THE_ODDS_API_KEY is set. The key is read from the environment, never
    printed, and scrubbed from any error text.
    """
    import os

    from mlb_engine.intake.live_data_adapters import parse_the_odds_api_totals

    raw = None
    source = None
    path = getattr(args, "odds", None)
    if path and Path(path).exists():
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            return {}, {"source": str(path), "warning": f"unreadable odds file: {exc}"}
        if isinstance(payload, list):
            raw = payload
        elif isinstance(payload, dict):
            for key in ("odds_raw_totals", "raw", "events", "odds"):
                if isinstance(payload.get(key), list):
                    raw = payload[key]
                    break
        source = str(path)
        if raw is None:
            return {}, {"source": source,
                        "warning": "odds file carried no recognizable events list"}

    if raw is None:
        key = os.environ.get("THE_ODDS_API_KEY")
        if not key:
            return {}, {"source": None,
                        "warning": "no --odds file and THE_ODDS_API_KEY unset; "
                                   "F1 stays neutral for this build"}
        import urllib.parse
        query = urllib.parse.urlencode({
            "apiKey": key, "regions": "us", "markets": "totals,h2h",
            "oddsFormat": "american",
        })
        url = ("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?" + query)
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # Never let the key reach a log line or the brief.
            scrubbed = str(exc).replace(key, "<redacted>")
            return {}, {"source": "the-odds-api",
                        "warning": f"odds fetch failed ({scrubbed}); F1 stays neutral"}
        source = "the-odds-api"

    parsed = parse_the_odds_api_totals(raw)
    odds = parsed.get("odds_by_game_id") or {}
    with_ml = sum(1 for v in odds.values() if (v or {}).get("moneyline"))
    return odds, {"source": source, "games": len(odds), "games_with_moneyline": with_ml}


def build_f1_map(pool: dict, odds_by_game_id: dict) -> tuple[dict, dict]:
    """Return ({Player_ID: F1}, report) from the slate's posted game lines.

    Game environment is the strongest exogenous signal in MLB DFS and the market
    prices it for free. Pitchers are held at 1.0 in v1 so the opposing-team
    total is not counted twice. Labeled prior, never a run projection.
    """
    from mlb_engine.projections.projection_builder import build_f1_factors

    team_by_player_id = dict(pool.get("team_by_player_id") or {})
    pitcher_ids = list((pool.get("pitcher_roles") or {}).keys())
    # Pitchers are absent from team_by_player_id (it is hitters only), so add
    # them explicitly to keep the F1 map total and its report honest.
    salary_team = pool.get("team_by_player_id") or {}
    for pid in pitcher_ids:
        team_by_player_id.setdefault(str(pid), salary_team.get(str(pid), ""))
    if not odds_by_game_id:
        return {}, {"skipped": "no odds packet available", "non_neutral_f1": 0}
    return build_f1_factors(odds_by_game_id, team_by_player_id, pitcher_ids=pitcher_ids)


def build_f5_map(pool: dict, args) -> tuple[dict, dict]:
    """Return ({Player_ID: F5}, report) from park factors and tonight's weather.

    F5 is the only enrichment with a HUMAN step that cannot be automated away.
    A retractable roof's open/closed state is not in any forecast, and guessing
    it is worse than leaving it neutral: a closed roof cancels the wind
    adjustment entirely, so a wrong guess moves every hitter in that game the
    wrong way. Unresolved retractables therefore take the park factor only, and
    the game is named in a checkpoint warning for Ben to resolve by hand.

    Park factors apply on their own even with no forecast at all, which is most
    of the available signal: Coors is Coors in any weather.
    """
    from mlb_engine.intake.slate_intake_manager import (
        compute_f5_factor, load_f5_park_factors, load_f5_weather_adjustments,
    )
    from mlb_engine.optimize.optimizer_v3 import wind_bearing_to_f5_label

    report: dict = {"games_scored": 0, "retractable_unresolved": [],
                    "venues_without_park_factor": [], "non_neutral_f5": 0}

    bundle_path = getattr(args, "bundle", None)
    weather_by_venue: dict = {}
    if bundle_path and Path(bundle_path).exists():
        try:
            bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
            weather_by_venue = bundle.get("weather") or {}
            report["weather_source"] = str(bundle_path)
        except Exception as exc:
            report["warning"] = f"bundle unreadable ({exc}); park factors only"
    else:
        report["weather_source"] = None

    try:
        park_factors = load_f5_park_factors(str(REPO / "data/reference/f5_park_factors.csv"))
        adjustments = load_f5_weather_adjustments(
            str(REPO / "data/reference/f5_weather_adjustments.csv"))
        venue_rows = {}
        with (REPO / "data/reference/team_to_venue.csv").open(encoding="utf-8-sig",
                                                             newline="") as fh:
            for row in csv.DictReader(fh):
                venue_rows[str(row.get("Home_Team", "")).strip().upper()] = row
    except Exception as exc:
        report["skipped"] = f"F5 reference data unreadable: {exc}"
        return {}, report

    # Game_ID is AWAY@HOME, so the home team names the venue.
    team_by_player_id = dict(pool.get("team_by_player_id") or {})
    pitcher_roles = pool.get("pitcher_roles") or {}
    home_by_team: dict = {}
    for row in (pool.get("projection_rows") or []):
        game_id = str(row.get("Game_ID") or "")
        if "@" in game_id:
            home_by_team[str(row.get("Team") or "").strip().upper()] = \
                game_id.split("@", 1)[1].strip().upper()
        if str(row.get("Player_ID")) in pitcher_roles:
            team_by_player_id.setdefault(str(row.get("Player_ID")),
                                         str(row.get("Team") or ""))

    f5_by_team: dict = {}
    for team in sorted({str(t).strip().upper() for t in team_by_player_id.values() if t}):
        home = home_by_team.get(team)
        venue_row = venue_rows.get(home or "")
        if not venue_row:
            continue
        venue = str(venue_row.get("Venue", "")).strip()
        if venue not in park_factors:
            report["venues_without_park_factor"].append(venue or home or team)
        roof_type = str(venue_row.get("Roof_Type", "")).strip().lower()
        forecast = (weather_by_venue.get(venue) or {})
        hours = forecast.get("hourly_window") or []
        mid = hours[len(hours) // 2] if hours else {}

        roof_closed = roof_type == "dome"
        if roof_type == "retractable" and venue not in report["retractable_unresolved"]:
            # Never guessed. Neutral wind plus the park factor is the honest read.
            report["retractable_unresolved"].append(venue)

        wind_status = "cross"
        if hours and roof_type == "outdoor":
            wind_status = wind_bearing_to_f5_label(
                mid.get("wind_direction_deg"),
                venue_row.get("CF_Azimuth_Degrees"))
        weather = {
            "wind_status": wind_status,
            "wind_speed_mph": mid.get("wind_speed_mph"),
            "delay_risk": "none",
            "postponement_risk": "none",
        }
        threshold = venue_row.get("Wind_Min_Speed_MPH")
        try:
            threshold = float(threshold) if threshold not in (None, "") else None
        except (TypeError, ValueError):
            threshold = None
        result = compute_f5_factor(venue, weather, park_factors, adjustments,
                                   wind_threshold_mph=threshold,
                                   roof_closed=roof_closed or roof_type == "retractable")
        f5_by_team[team] = result
        report["games_scored"] += 1

    f5_by_player: dict = {}
    for pid, team in team_by_player_id.items():
        result = f5_by_team.get(str(team).strip().upper())
        if not result:
            f5_by_player[str(pid)] = 1.0
            continue
        f5_by_player[str(pid)] = float(
            result["pitcher_f5"] if str(pid) in pitcher_roles else result["hitter_f5"])

    report["non_neutral_f5"] = sum(
        1 for v in f5_by_player.values() if abs(float(v) - 1.0) > 1e-9)
    report["f5_by_team"] = {
        t: {"venue": r["components"]["venue"],
            "hitter_f5": r["hitter_f5"], "pitcher_f5": r["pitcher_f5"],
            "wind": r["components"].get("wind_row")}
        for t, r in sorted(f5_by_team.items())}
    report["note"] = (
        "Deterministic F5 prior: park run factor times a wind adjustment that "
        "applies only when the roof is open, direction is out/in, and speed "
        "meets the venue threshold. Retractable roofs are never guessed. "
        "Labeled prior, never a run projection or probability claim.")
    return f5_by_player, report


def build_f4_map(pool: dict, savant_pitching_csv) -> tuple[dict, dict]:
    """Return ({Player_ID: F4}, report) for the pool's hitters, or ({}, report).

    F4 is the deterministic matchup prior: opposing-SP xwOBA-against quality
    times a platoon hand factor, PA-shrunk and clipped. The SP-quality component
    applies team-wide even when batter hands are missing, so a TBD lineup still
    receives it. It is a labeled prior, never a win-rate or probability claim.
    """
    from mlb_engine.projections.projection_builder import (
        compute_f4_factors, load_savant_expected_stats,
    )

    team_by_player_id = pool.get("team_by_player_id") or {}
    opposing = pool.get("opposing_probables") or {}
    if not team_by_player_id:
        return {}, {"skipped": "no hitters in the pool"}

    table = None
    if savant_pitching_csv:
        try:
            table = load_savant_expected_stats(savant_pitching_csv)
        except Exception as exc:
            return {}, {"skipped": f"savant pitching table unreadable: {exc}"}

    f4, report = compute_f4_factors(
        team_by_player_id, opposing, table, pool.get("batter_hands") or {},
    )
    non_neutral = sum(1 for v in f4.values() if abs(float(v) - 1.0) > 1e-9)
    report["non_neutral_f4"] = non_neutral
    if f4 and non_neutral == 0:
        # Not fatal, but it means every hitter got the neutral factor, which is
        # indistinguishable from not computing F4 at all. Say so.
        report["warning"] = (
            "F4 computed for "
            f"{len(f4)} hitters but every value is neutral 1.0; the opposing-SP "
            "quality and platoon components both found nothing to apply"
        )
    return f4, report


def summarize_enrichment(reference_status: dict, enrichment: dict,
                         f4_report: dict, degraded_reason,
                         f1_report: dict | None = None,
                         f5_report: dict | None = None) -> dict:
    """Condense the enrichment record into the block the brief carries.

    The one question this has to answer at a glance is whether this build had
    signal or was APPG in a ceiling costume. ``signal_applied`` is that answer:
    it is True only when at least one factor moved at least one player off
    neutral.
    """
    enrichment = enrichment or {}
    xwoba = enrichment.get("xwoba") or {}
    ceiling = enrichment.get("ceiling") or {}
    pitcher_ceiling = enrichment.get("pitcher_ceiling") or {}
    non_neutral_f4 = int(f4_report.get("non_neutral_f4") or 0)
    f1_report = f1_report or {}
    f5_report = f5_report or {}

    counts = {
        "xwoba_non_neutral": int(xwoba.get("non_neutral_applied") or 0),
        "xwoba_match_rate": xwoba.get("match_rate"),
        "hitter_ceiling_differentiated": int(ceiling.get("differentiated_rows") or 0),
        "pitcher_ceiling_differentiated": int(
            pitcher_ceiling.get("differentiated_rows")
            or pitcher_ceiling.get("matched") or 0),
        "f4_non_neutral": non_neutral_f4,
        "f4_hitters_scored": int(f4_report.get("hitters_scored") or 0),
        "f4_platoon_applied": int(f4_report.get("platoon_component_applied") or 0),
        "f1_non_neutral": int(f1_report.get("non_neutral_f1") or 0),
        "f1_games_priced": int(f1_report.get("games_priced") or 0),
        "f5_non_neutral": int(f5_report.get("non_neutral_f5") or 0),
        "f5_games_scored": int(f5_report.get("games_scored") or 0),
    }
    warnings = list(reference_status.get("warnings") or [])
    warnings += list(enrichment.get("warnings") or [])
    for key in ("warning", "skipped"):
        if f4_report.get(key):
            warnings.append(f"f4: {f4_report[key]}")
        if f1_report.get(key):
            warnings.append(f"f1: {f1_report[key]}")
        if f5_report.get(key):
            warnings.append(f"f5: {f5_report[key]}")
    if (f1_report.get("odds") or {}).get("warning"):
        warnings.append(f"f1: {f1_report['odds']['warning']}")
    no_ml = f1_report.get("games_without_moneyline") or []
    if no_ml:
        warnings.append(
            "f1: no moneyline for " + ", ".join(no_ml)
            + "; those totals split evenly rather than by side")
    teams_no_odds = f1_report.get("teams_without_odds") or []
    if teams_no_odds:
        warnings.append(
            "f1: no game line for " + ", ".join(teams_no_odds)
            + "; those hitters stay neutral")
    teams_without = f4_report.get("teams_without_opposing_probable") or []
    if teams_without:
        warnings.append(
            "f4: no opposing probable for " + ", ".join(sorted(teams_without))
            + "; those hitters stay neutral")
    if degraded_reason:
        warnings.append(f"DEGRADED to unenriched build: {degraded_reason}")

    # Derived from what the engine actually applied per row, not from the size of
    # the input maps. A stale-ID map is requested-but-unapplied, and the brief
    # used to report that as enrichment; an honest-looking enrichment block that
    # misreports is worse than none.
    engine_applied = {
        key: int((enrichment.get(key) or {}).get("applied_count") or 0)
        for key in ("f1", "f4", "f5")
        if isinstance(enrichment.get(key), dict)
    }
    counts.update({f"{k}_engine_applied": v for k, v in engine_applied.items()})
    requested_but_unapplied = sorted(
        key for key in ("f1", "f4", "f5")
        if isinstance(enrichment.get(key), dict)
        and int((enrichment[key] or {}).get("requested") or 0) > 0
        and int((enrichment[key] or {}).get("applied_count") or 0) == 0
    )
    for key in requested_but_unapplied:
        warnings.append(
            f"{key}: a map was supplied but reached zero rows; the ids in it do "
            f"not match this slate's pool. That factor is OFF for this build.")
    signal = any(counts[k] for k in (
        "xwoba_non_neutral", "hitter_ceiling_differentiated",
        "pitcher_ceiling_differentiated", "f4_non_neutral", "f1_non_neutral",
        "f5_non_neutral")) and not (
        # If every factor that was requested applied to nothing, and nothing else
        # differentiated a row, there is no signal to claim.
        requested_but_unapplied and not counts["xwoba_non_neutral"]
        and not counts["hitter_ceiling_differentiated"]
        and not counts["pitcher_ceiling_differentiated"])
    return {
        "signal_applied": bool(signal),
        "requested_but_unapplied": requested_but_unapplied,
        "degraded": bool(degraded_reason),
        "degraded_reason": degraded_reason,
        "reference_data": reference_status,
        "counts": counts,
        "f4_league_mean_est_woba": f4_report.get("league_mean_est_woba"),
        "f1_odds": f1_report.get("odds"),
        "f1_league_mean_implied_total": f1_report.get("league_mean_implied_total"),
        "f1_implied_total_by_team": f1_report.get("implied_total_by_team"),
        "f5_by_team": f5_report.get("f5_by_team"),
        "f5_retractable_unresolved": f5_report.get("retractable_unresolved") or [],
        "warnings": warnings,
        "note": "Enrichment counts are deterministic labeled priors applied to the "
                "projection frame: xwOBA Base correction, xISO hitter ceilings, "
                "K-rate pitcher ceilings, the F4 opposing-SP/platoon matchup "
                "factor, F1 from Vegas implied team totals, and F5 park/weather. "
                "Implied totals are derived from the posted total and moneyline, "
                "not published by the book. signal_applied and the *_engine_applied "
                "counts come from the engine's per-row application, not from the "
                "size of the input maps. Never ROI, win rate, or a probability "
                "claim.",
    }


# --------------------------------------------------------------------------- #
# Classic
# --------------------------------------------------------------------------- #
def run_classic(args, slate_dir: Path, salary: Path, entries: Path,
                feed: dict, deadline: float) -> tuple[int, dict]:
    from mlb_engine.intake.live_data_adapters import build_slate_pool
    from mlb_engine.optimize.bank_cache import BankCache, extend_bank, pool_signature
    from mlb_engine.pipeline.execution_pipeline import (
        _assemble_projection_frame, run_slate,
    )

    pool = build_slate_pool(str(salary), feed, platoon_json=resolve_platoon_json(args))
    report = pool["pool_report"]
    clock = pool.get("clock") or {}
    kwargs = pool["run_slate_kwargs"]

    # F8: the intake blockers landed, and then were read once, to be printed into
    # the brief. Nothing exited on them, so the 2026-07-22 failure (23 teams
    # matched 0/9, headline read certified) replayed with prettier logging.
    #
    # Tiering per the anti-paralysis doctrine: a blocker that says the pool is
    # structurally wrong for this slate is HARD, because a build on it is not a
    # worse build, it is a build of something else. A blocker about the freshness
    # of a reference file is SOFT: it degrades the build, it does not invalidate
    # it, and stopping the slate over it is the failure mode the doctrine exists
    # to prevent.
    blockers = list(report.get("blockers") or [])
    soft = [b for b in blockers if SOFT_POOL_BLOCKER_RE.search(b)]
    hard = [b for b in blockers if b not in soft]
    for b in soft:
        print(f"pool (soft): {b}", file=sys.stderr)
    if hard and not args.ignore_pool_blockers:
        for b in hard:
            print(f"POOL BLOCKER: {b}", file=sys.stderr)
        print(json.dumps({
            "status": "pool_blocked",
            "blockers": hard,
            "soft_blockers": soft,
            "note": "the pool this build would use is structurally wrong for this "
                    "slate; building on it produces a certified file for a "
                    "different slate than the one being entered. Fix the input, "
                    "or pass --ignore-pool-blockers to build anyway and have the "
                    "override recorded in the brief.",
        }, indent=1))
        return 3, {}
    if hard:
        for b in hard:
            print(f"POOL BLOCKER OVERRIDDEN by --ignore-pool-blockers: {b}",
                  file=sys.stderr)

    # A salary/feed clock disagreement means two sources describe different
    # slates, so say which one this build adopted rather than picking silently.
    if report.get("salary_cross_check") is False:
        print(f"clock: salary file says {clock.get('first_lock_local')}, the "
              f"lineups feed says {clock.get('feed_first_lock_local')}; adopted "
              f"{clock.get('source', 'salary')}", file=sys.stderr)

    n_entries = args.entries or count_reserved(entries)

    reference = resolve_reference_data(args)
    f4_by_player_id, f4_report = build_f4_map(pool, reference["savant_pitching"])
    if f4_report.get("warning"):
        print(f"enrichment warning: {f4_report['warning']}", file=sys.stderr)

    odds_by_game_id, odds_note = load_odds_packet(args)
    if odds_note.get("warning"):
        print(f"odds: {odds_note['warning']}", file=sys.stderr)
    f1_by_player_id, f1_report = build_f1_map(pool, odds_by_game_id)
    f1_report["odds"] = odds_note
    if f1_report.get("warning"):
        print(f"enrichment warning: {f1_report['warning']}", file=sys.stderr)

    f5_by_player_id, f5_report = build_f5_map(pool, args)
    for venue in f5_report.get("retractable_unresolved") or []:
        print(f"F5 ROOF: {venue} is retractable and its open/closed state is "
              "unresolved; wind is NOT applied there. Confirm by hand if it "
              "matters to this slate.", file=sys.stderr)

    # Assemble the frame WITH the enrichments. This frame is not just the timing
    # probe: on the sliced-bank path it is the frame every cached candidate is
    # built from, so enriching it here is what puts the signal in the portfolio.
    enrich_kwargs = dict(
        savant_batting_csv=reference["savant_batting"],
        savant_pitching_csv=reference["savant_pitching"],
        fangraphs_pitching_csv=reference["fangraphs_pitching"],
        f4_by_player_id=f4_by_player_id or None,
        f1_by_player_id=f1_by_player_id or None,
        f5_by_player_id=f5_by_player_id or None,
    )
    degraded_reason = None
    try:
        projections, enrichment = _assemble_projection_frame(
            str(salary), kwargs["projection_rows"], "emergency_proxy",
            enrich_kwargs["savant_batting_csv"], enrich_kwargs["savant_pitching_csv"],
            None,
            projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
            f4_by_player_id=enrich_kwargs["f4_by_player_id"],
            f1_by_player_id=enrich_kwargs["f1_by_player_id"],
            f5_by_player_id=enrich_kwargs["f5_by_player_id"],
            fangraphs_pitching_csv=enrich_kwargs["fangraphs_pitching_csv"],
        )
    except ValueError as exc:
        # The engine's zero-match guards raise rather than build a silent no-op.
        # That is the right call at the library layer and the wrong outcome at
        # T-10, so degrade to the unenriched frame and make the reason impossible
        # to miss. A shipped build on bare APPG that SAYS it is on bare APPG is
        # honest; a killed slate is not a better answer.
        degraded_reason = str(exc)
        print(f"ENRICHMENT FAILED, building unenriched: {degraded_reason}",
              file=sys.stderr)
        enrich_kwargs = dict(savant_batting_csv=None, savant_pitching_csv=None,
                             fangraphs_pitching_csv=None, f4_by_player_id=None,
                             f1_by_player_id=None, f5_by_player_id=None)
        f4_by_player_id = {}
        f1_by_player_id = {}
        f5_by_player_id = {}
        projections, enrichment = _assemble_projection_frame(
            str(salary), kwargs["projection_rows"], "emergency_proxy", None, None, None,
            projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
        )

    # Decide the strategy from a measurement, never from a guess. The rule that
    # matters: an infrastructure limit may reduce search effort, never the legal
    # player set, because trimming the pool is a strategy change that is invisible
    # in the certified output.
    t0 = time.monotonic()
    from mlb_engine.optimize.optimizer_v3 import (
        build_single_lineup, resolve_candidate_bank_size,
    )
    build_single_lineup(projections, target="ceiling")
    single_s = time.monotonic() - t0
    remaining = deadline - time.monotonic()

    # Model the real cost, which is base bank plus SP-pair augmentation. A naive
    # per-lineup estimate ignores the augmentation and understates the total by
    # roughly the pair count, which is exactly how a build gets started that
    # cannot finish. Same model as tools/solver_probe.py.
    bank_size = resolve_candidate_bank_size(n_entries)
    game_of = {str(r.Player_ID): str(r.Game_ID) for r in projections.itertuples()}
    sps = [str(p) for p in projections[projections["Position"] == "P"]["Player_ID"]]
    cross_pairs = sum(
        1 for i in range(len(sps)) for j in range(i + 1, len(sps))
        if game_of.get(sps[i]) != game_of.get(sps[j])
    )
    growth = max(bank_size / 5.0, 1.0)
    projected_direct = (single_s * bank_size * (1 + (growth - 1) / 2)
                        + cross_pairs * single_s)

    bank_path = REPO / "runs" / f"bank_cache_{args.date}_{pool_signature(salary)}.json"
    strategy = "direct"
    bank_report = None
    candidates = None

    if projected_direct > remaining:
        strategy = "sliced_bank"
        cache = BankCache(bank_path)
        bank_report = extend_bank(
            cache, projections,
            time_budget_s=max(remaining - 8.0, 5.0),
            max_candidates=max(n_entries * 12, 60),
        )
        # F15: score each contest shape the reserved CSV actually contains. A
        # single wta score is a ceiling-max ranking, and the allocator's cash
        # branch then applies its floor weighting on top of it, so cash entries
        # ranked on inverted weights. The shapes are known from the entries file,
        # so there is nothing to guess.
        try:
            from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
            from mlb_engine.pipeline.execution_pipeline import _resolve_contest_postures
            reserved_rows = parse_dk_entry_rows(str(entries))
            postures = _resolve_contest_postures(
                reserved_rows, parse_postures_arg(getattr(args, "postures", None)), None)
            slice_shapes = sorted({
                (postures.get(str(r.contest_id)) or {}).get(
                    "contest_shape", "large_field_gpp")
                for r in reserved_rows
            })
        except Exception as exc:  # noqa: BLE001 - shape scoring is a refinement
            print(f"shape resolution failed, scoring wta only: {exc}", file=sys.stderr)
            slice_shapes = None
        candidates = cache.as_candidates(
            projections, requested_n=n_entries, contest_shapes=slice_shapes)
        if len(candidates) < n_entries * 2 and not bank_report["job_list_exhausted"]:
            print(json.dumps({
                "status": "partial",
                "strategy": strategy,
                "candidates": len(candidates),
                "needed_at_least": n_entries * 2,
                "note": "bank still thin; run the same command again to add a slice",
            }, indent=1))
            return 10, {}

    slate_kwargs = dict(kwargs)
    postures = parse_postures_arg(getattr(args, "postures", None))
    if postures:
        slate_kwargs["contest_postures"] = postures

    # The pool report is the evidence behind the lineup gate. Without it run_slate
    # can only say "some players carry a batting order", which is not the same
    # claim.
    slate_kwargs["source_metadata"] = {
        **dict(slate_kwargs.get("source_metadata") or {}),
        "pool_report": pool.get("pool_report"),
    }

    # On the sliced path run_slate never builds the bank, so it has nothing to
    # record about how the candidates were produced and diagnostics.json would
    # say only "candidates_override". The cache's own report is the equivalent
    # evidence and belongs in the immutable run record for the same reason
    # (F11): the run record is this project's memory of what was shipped.
    if bank_report is not None:
        slate_kwargs["metadata"] = {
            **dict(slate_kwargs.get("metadata") or {}),
            "bank_diagnostics": {"source": "bank_cache", "strategy": strategy,
                                 **{k: v for k, v in bank_report.items()
                                    if k != "candidates"},
                                 "payload_report": dict(cache.last_payload_report)},
            "bank_warnings": [
                w for w in [
                    (f"{bank_report.get('jobs_failed')} cache jobs failed"
                     if bank_report.get("jobs_failed") else None),
                    ("the job list was not exhausted; this bank is a slice, not "
                     "the full search" if not bank_report.get("job_list_exhausted")
                     else None),
                    (f"budget exhausted after {bank_report.get('elapsed_s')}s"
                     if bank_report.get("budget_exhausted") else None),
                    # F13/F15: both were previously invisible in the run record.
                    (f"{bank_report.get('jobs_timed_out')} cache jobs hit the solver "
                     f"time limit and are retryable on another slice"
                     if bank_report.get("jobs_timed_out") else None),
                    (f"{cache.last_payload_report.get('scoring_failed')} candidates "
                     f"could not be scored and allocate on raw objective"
                     if cache.last_payload_report.get("scoring_failed") else None),
                ] if w
            ],
        }

    # F4 gates that this build genuinely cannot evidence, assumed explicitly and
    # printed. A build given no odds map is a different state from a build whose
    # odds matched nothing; only the first is assumable, and the assumption is
    # recorded in diagnostics rather than papered over with a default of True.
    assumed: list[str] = []
    if not f1_by_player_id:
        assumed.append("odds_gate_passed")
    if not f5_by_player_id:
        assumed.append("weather_gate_passed")
    assumed += [g for g in parse_assume_gates_arg(getattr(args, "assume_gates", None))
                if g not in assumed]
    for gate in assumed:
        print(f"gate assumed (not checked): {gate}", file=sys.stderr)
    if assumed:
        slate_kwargs["assume_gates"] = assumed

    result = run_slate(
        runs_root=str(REPO / "runs"),
        salary_csv=str(salary), entries_csv=str(entries),
        approve=True, requested_n=n_entries,
        candidates_override=candidates,
        # Same enrichment inputs the probe frame used. run_slate reassembles the
        # frame internally, so passing anything less here would build the bank on
        # enriched projections and then certify against unenriched ones.
        **enrich_kwargs,
        # Always bounded, even on the direct path. The estimate above decides
        # strategy; this makes a wrong estimate degrade to a smaller bank instead
        # of a killed process that leaves nothing behind.
        bank_time_budget_s=max(deadline - time.monotonic() - 6.0, 5.0),
        portfolio_controls_override=args.controls_override,
        **slate_kwargs,
    )

    # Contest identity, one line per contest, with where it came from. The
    # objective the portfolio is built to is the single most consequential
    # inference in the build and it used to be invisible.
    for cid, info in sorted((result.get("posture_by_contest") or {}).items()):
        src = info.get("posture_source") or "name_inference"
        extra = ""
        if info.get("matched_pattern"):
            extra = f" [matched '{info['matched_pattern']}'"
            if info.get("competing_patterns"):
                extra += f", also matched {info['competing_patterns']}"
            extra += "]"
        print(f"contest {cid} {info.get('posture')} ({src}){extra}: "
              f"{info.get('contest_name')}", file=sys.stderr)

    if not result.get("passed"):
        for blocker in result.get("contest_identity_blockers") or []:
            print(f"contest identity: {blocker}", file=sys.stderr)
        # A failed joint allocation is frequently a small-slate control
        # infeasibility, not a real "no legal lineup" wall: too few games means
        # too few distinct SP pairs and team stacks to keep every portfolio
        # control (max_shared_players, exposure caps) satisfied at once for a
        # large requested_n. The engine already computes the exact structural
        # floor and a remedy per failing check (see feasibility.checks); surface
        # it here so the fix is "rerun with --controls-override" instead of a
        # from-scratch debugging session.
        feas = result.get("feasibility") or {}
        payload = {"status": "not_certified", "errors": result.get("errors")}
        if not feas.get("passed", True):
            payload["feasibility"] = feas
            payload["hint"] = (
                "one or more portfolio controls are structurally infeasible for "
                "this pool/entry count (see feasibility.checks[].remedy). Rerun "
                "with --controls-override '{\"max_shared_players\": <n>, ...}' "
                "set to at least the named floors. This raises diversity caps to "
                "match the slate, not a strategy or player-pool change."
            )
        print(json.dumps(payload, indent=1))
        return 3, {}

    delivered = result.get("delivered_path") or result.get("output_path")
    checks = verify_classic(salary, Path(delivered))
    exposure = portfolio_exposure(salary, Path(delivered))
    brief = {
        "status": "certified" if checks["passed"] else "verify_failed",
        "contest_type": "classic",
        "date": args.date,
        "entries": n_entries,
        "delivered_path": delivered,
        # Repo-relative and hashed. Every delivered_path recorded on 2026-07-25
        # was absolute against a session mount that no longer exists, and no
        # brief stated which bytes it was describing.
        "delivered_path_repo": manifest_repo_relative(delivered),
        "delivered_sha256": manifest_sha256(delivered),
        "upload_manifest": manifest_repo_relative(
            REPO / "outputs" / args.date / "upload_manifest.json"),
        "pool_blockers_overridden": hard if (hard and args.ignore_pool_blockers) else [],
        "pool_blockers_soft": soft,
        "run_id": result.get("run_id"),
        "gates": {
            "workflow_valid": result.get("workflow_valid"),
            "selection_certified": result.get("selection_certified"),
            "allocation_certified": result.get("allocation_certified"),
        },
        "solve": {
            "strategy": strategy,
            "single_lineup_s": round(single_s, 2),
            "bank": bank_report,
        },
        "slate_clock": {
            "first_lock_game_id": clock.get("first_lock_game_id"),
            "first_lock_utc": clock.get("first_lock_utc"),
            "minutes_to_deadline": clock.get("minutes_to_deadline"),
            "salary_cross_check": (clock.get("salary_cross_check") or {}).get("agrees"),
        },
        "pool": {
            "teams": len(report.get("teams") or {}),
            "platoon_source": pool.get("platoon_source"),
            "warnings": report.get("warnings") or [],
            "blockers": report.get("blockers") or [],
        },
        "exposure": exposure,
        "verification": checks,
        "controls_override_applied": args.controls_override,
        "enrichment": summarize_enrichment(
            reference["status"], enrichment, f4_report, degraded_reason,
            f1_report, f5_report),
    }
    return (0 if checks["passed"] else 3), brief


# --------------------------------------------------------------------------- #
# Showdown
# --------------------------------------------------------------------------- #
def showdown_handedness(args, slate_dir: Path, df) -> tuple[dict, dict, dict]:
    """Return (bat_side, pitcher_hand_by_team, note) for a Showdown pool.

    The platoon component of the Base prior needs a hitter's side and the
    OPPOSING declared starter's hand. Neither is in the DK salary file, so this
    reads the lineups feed. Missing handedness is not fatal: the prior falls
    back to a flat 1.00 and the affected teams are named in the brief, which is
    the honest outcome. Silently flattening it is not, because the prior_note
    still claims a platoon factor was applied.
    """
    note: dict = {"source": None, "hitters_with_side": 0, "teams_with_hand": 0}
    feed_path = Path(args.lineups) if args.lineups else slate_dir / "lineups_feed.json"
    feed = None
    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
            note["source"] = str(feed_path)
            note["age_minutes"] = feed_age_minutes(feed)
        except Exception as exc:
            note["warning"] = f"unreadable lineups feed: {exc}"
    if feed is None:
        try:
            feed = fetch_lineups(args.date, slate_dir / "lineups_feed.json")
            note["source"] = "fetched"
        except Exception as exc:
            note["warning"] = f"lineups feed unavailable ({exc}); platoon stays flat"
            return {}, {}, note

    teams = set(df["Team"].unique()) if len(df) else set()
    bat_side: dict = {}
    hand: dict = {}
    for game in (feed.get("games") or []):
        for side in ("away", "home"):
            block = game.get(side) or {}
            # fetch_lineups writes team_abbrev; the other two are accepted so a
            # hand-rolled pre-fetch feed (the Cowork sandbox path) also works.
            abbrev = (block.get("team_abbrev") or block.get("team")
                      or block.get("abbrev"))
            for hitter in (block.get("lineup") or []):
                if hitter.get("bat_side") and hitter.get("name"):
                    bat_side[str(hitter["name"])] = str(hitter["bat_side"])
            pitcher = block.get("probable_pitcher") or block.get("probable") or {}
            if abbrev and pitcher.get("hand"):
                hand[str(abbrev)] = str(pitcher["hand"])
    note["hitters_with_side"] = sum(1 for n in bat_side if n in set(df["Name"]))
    note["teams_with_hand"] = len([t for t in hand if t in teams])
    # pitcher_hand is keyed by the team a hitter FACES, so invert: a hitter on
    # LAD is graded against the NYM starter's hand.
    facing = {}
    for _, row in df.iterrows():
        opp = str(row["Opponent"])
        if opp in hand:
            facing[opp] = hand[opp]
    return bat_side, facing, note


def showdown_moneyline(args, df) -> tuple[dict, dict]:
    """Return ({team: american odds}, note) for the single Showdown game."""
    try:
        odds, note = load_odds_packet(args)
    except Exception as exc:
        return {}, {"warning": f"odds unavailable ({exc}); entries split evenly"}
    teams = sorted(df["Team"].unique()) if len(df) else []
    for entry in (odds or {}).values():
        ml = (entry or {}).get("moneyline") or {}
        if all(t in ml for t in teams) and teams:
            return {t: float(ml[t]) for t in teams}, dict(note, matched=True)
    return {}, dict(note or {}, matched=False,
                    warning="no moneyline matched this game's teams; entries "
                            "split evenly between the two sides")


def run_showdown(args, slate_dir: Path, salary: Path, entries: Path) -> tuple[int, dict]:
    from mlb_engine.optimize import showdown as sd
    from mlb_engine.optimize import showdown_theses as st

    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv, slate_clock

    df = sd.melt_showdown_salary_csv(str(salary))
    clock = slate_clock(players=parse_dk_salary_csv(str(salary)))
    reserved = sd.read_showdown_reserved_rows(str(entries))
    # Only blank reserved rows are fillable; a complete row is immutable, and
    # blank rows are what block certification when left unfilled.
    rows = [r for r in (reserved.get("reserved") or []) if not r.get("is_complete")]
    n_entries = min(args.entries, len(rows)) if args.entries else len(rows)
    if not n_entries:
        print(json.dumps({"status": "no_blank_reserved_entries"}, indent=1))
        return 4, {}

    overrides = args.controls_override or {}
    cpt_cap = overrides.get("max_cpt_exposure_pct", sd.DEFAULT_MAX_CPT_EXPOSURE_PCT)
    share_cap = overrides.get("max_shared_players", sd.DEFAULT_MAX_SHARED_PLAYERS)

    # Handedness and the moneyline are what make the ladder more than a relabeled
    # points-max bank, so gather them before deciding the path. Both are
    # best-effort: a Showdown build must not fail because an odds endpoint is
    # down, it must say the input was missing and build anyway.
    bat_side, pitcher_hand, feed_note = showdown_handedness(args, slate_dir, df)
    moneyline, odds_note = showdown_moneyline(args, df)

    basis = str(df["Pool_Basis"].iloc[0]) if len(df) else "empty"
    posted = int(df["Batting_Order"].notna().sum()) if len(df) else 0
    # The ladder is conditioned on batting order and declared starters. With
    # nothing posted there is no order to condition on, so the templates would be
    # labels over a pool the engine cannot actually distinguish. Fall back rather
    # than ship a thesis name that means nothing.
    use_ladder = (basis == "declared_starters" and posted >= 2 * 9)

    ladder_meta: dict = {}
    solve_diag: dict = {}
    cpt_diagnostics: dict = {}
    report: dict = {}

    if use_ladder:
        priced = st.apply_base_prior(df, bat_side=bat_side, pitcher_hand=pitcher_hand)
        ladder_meta = st.build_thesis_ladder(priced, n_entries, moneyline=moneyline,
                                             max_cpt_exposure_pct=cpt_cap)
        theses = ladder_meta["theses"]
        solved = st.solve_ladder(priced, theses, max_shared_players=share_cap,
                                 diagnostics=solve_diag)
        if any(lu is None for lu in solved):
            print(json.dumps({"status": "ladder_infeasible",
                              "unsolved": [t["name"] for t, lu in zip(theses, solved)
                                           if lu is None]}, indent=1))
            return 3, {}
        bank = list(solved)
        report = st.portfolio_report(priced, theses, solved)
        certs = [sd.certify_showdown(lineup, priced) for lineup in bank]
    else:
        bank = sd.build_showdown_bank(df, n=n_entries, max_cpt_exposure_pct=cpt_cap,
                                      max_shared_players=share_cap,
                                      diagnostics=cpt_diagnostics)
        if len(bank) < n_entries:
            print(json.dumps({"status": "bank_short",
                              "built": len(bank), "needed": n_entries}, indent=1))
            return 3, {}
        bank = bank[:n_entries]
        certs = [sd.certify_showdown(lineup, df) for lineup in bank]

    failed = [c for c in certs if not c.get("passed")]
    if failed:
        print(json.dumps({"status": "not_certified",
                          "errors": [c.get("errors") for c in failed]}, indent=1))
        return 3, {}

    # zip() silently truncates to the shorter side, so a bank short of the
    # reserved-row count left the remainder blank and shipped. Say so instead.
    if len(bank) < len(rows):
        print(json.dumps({
            "status": "bank_short_of_reserved_rows",
            "reserved_blank_rows": len(rows),
            "lineups_built": len(bank),
            "shortfall": len(rows) - len(bank),
            "note": "a blank reserved row blocks certification; lower --entries-count "
                    "to the number built, or rerun to deepen the bank",
        }, indent=1))
        return 3, {}

    out_dir = REPO / "outputs" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"DKEntries_showdown{slate_tag_suffix(salary)}.csv"
    assignments = [
        {"entry_id": row["entry_id"], "roster_ids": list(lineup["roster_ids"])}
        for row, lineup in zip(rows, bank)
    ]
    write_report = sd.write_showdown_entries(str(entries), str(dest), assignments)
    if not write_report.get("passed"):
        print(json.dumps({"status": "showdown_export_failed",
                          "errors": write_report.get("errors")}, indent=1))
        return 3, {}
    try:
        from mlb_engine.entries.upload_manifest import record_delivery
        record_delivery(
            date=args.date, delivered_file=dest, contest_type="showdown",
            slate_tag=slate_tag_suffix(salary).lstrip("_"),
            contest_ids=sorted({r["contest_id"] for r in rows}),
            contest_names=sorted({r.get("contest_name", "") for r in rows}),
            entries=len(assignments), run_id=None, status="delivered",
            certification="review_grade",
            notes="Showdown ships review-grade; it does not pass the three "
                  "certification gates. See CLAUDE.md.",
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails a build
        print(f"upload manifest not recorded: {exc}", file=sys.stderr)
    template = sd.verify_template_preserved(str(entries), str(dest))

    if use_ladder:
        cap_count = ladder_meta.get("captain_cap_count")
        captain_counts = report.get("captain_exposure") or {}
        relaxed_slots = ((ladder_meta.get("captain_cap_relaxed") or 0)
                         + (solve_diag.get("captain_lock_relaxed") or 0))
        overlap_relaxed = solve_diag.get("overlap_relaxed") or 0
        max_overlap = report.get("max_pairwise_overlap")
    else:
        cap_count = cpt_diagnostics.get("cap_count")
        captain_counts = cpt_diagnostics.get("captain_exposure") or {}
        relaxed_slots = cpt_diagnostics.get("relaxed_slots") or 0
        overlap_relaxed = cpt_diagnostics.get("overlap_relaxed_slots") or 0
        max_overlap = None
    captain_exposure = {
        key: {"count": count, "pct": round(100.0 * count / n_entries, 1)}
        for key, count in sorted(captain_counts.items(), key=lambda kv: -kv[1])
    }
    realized_cpt_pct = max((v["pct"] for v in captain_exposure.values()), default=0.0)

    brief = {
        # Showdown ships as v0.2-review (cpt exposure cap added 2026-07-23) and
        # Phase 3 is not complete, so this path is labeled review-grade. It is
        # not the Classic certification contract.
        "status": "review_grade_build",
        "contest_type": "showdown",
        "date": args.date,
        "entries": n_entries,
        "delivered_path": str(dest),
        "delivered_path_repo": manifest_repo_relative(dest),
        "delivered_sha256": manifest_sha256(dest),
        "upload_manifest": manifest_repo_relative(
            REPO / "outputs" / args.date / "upload_manifest.json"),
        "showdown_module_version": sd.VERSION,
        "pool": {
            "players": int(len(df)),
            "basis": (str(df["Pool_Basis"].iloc[0]) if len(df) else "empty"),
            "declared_starters": int(df["Is_Declared_Starter"].sum()) if len(df) else 0,
            "posted_hitters": int(df["Batting_Order"].notna().sum()) if len(df) else 0,
        },
        "slate_clock": {
            "first_lock_utc": clock.get("first_lock_utc"),
            "minutes_to_deadline": clock.get("minutes_to_deadline"),
            "past_deadline": clock.get("past_deadline"),
        },
        "certification": {
            "per_lineup_passed": all(c.get("passed") for c in certs),
            "template_preserved": template.get("passed"),
            "write_report": write_report,
        },
        "captain_exposure": {
            "cap_pct": cpt_cap,
            "cap_count": cap_count,
            "realized_max_pct": realized_cpt_pct,
            "by_player": captain_exposure,
            "relaxed_slots": relaxed_slots,
        },
        "diversity": {
            "max_shared_players": share_cap,
            "max_pairwise_overlap": max_overlap,
            "overlap_relaxed_slots": overlap_relaxed,
            "all_unique_rosters": report.get("all_unique_rosters") if use_ladder else None,
        },
        "construction": ({
            "mode": "thesis_ladder",
            "module_version": st.VERSION,
            "win_share_basis": ladder_meta.get("win_share_basis"),
            "favorite": (ladder_meta.get("shape") or {}).get("favorite"),
            "win_share": (ladder_meta.get("shape") or {}).get("win_share"),
            "allocation": ladder_meta.get("allocation"),
            "bullpen_teams": (ladder_meta.get("shape") or {}).get("bullpen_teams"),
            "platoon_unresolved_teams": list(
                (priced.attrs.get("platoon_unresolved_teams") or [])),
            "handedness": feed_note,
            "odds": odds_note,
            "lineups": report.get("lineups"),
            "player_exposure": report.get("player_exposure"),
        } if use_ladder else {
            "mode": "points_max_bank",
            "reason": (f"pool basis is {basis!r} with {posted} posted hitters; the "
                       "thesis ladder needs both posted batting orders to "
                       "condition on, so it was not used"),
        }),
        "caution": (f"showdown.py is v{sd.VERSION} and Phase 3 is not complete. "
                    "Per-lineup checks, template preservation, the captain "
                    "exposure cap, and the roster-overlap bound passed, but this "
                    "is not the Classic three-gate certification. Review before "
                    "uploading."
                    + (f" NOTE: the {cap_count}-lineup captain cap relaxed on "
                       f"{relaxed_slots} slot(s) because the pool couldn't "
                       "support it without leaving a reserved row blank -- check "
                       "captain_exposure.by_player before uploading."
                       if relaxed_slots else "")
                    + (f" NOTE: the {share_cap}-player overlap bound relaxed on "
                       f"{overlap_relaxed} slot(s); those lineups are still "
                       "distinct but share more than {share_cap} players with an "
                       "earlier one."
                       if overlap_relaxed else "")
                    + (" NOTE: no moneyline was available, so entries were split "
                       "evenly between the two sides rather than weighted to the "
                       "market."
                       if use_ladder and ladder_meta.get("win_share_basis")
                       == "even_split_no_market_input" else "")),
    }
    return (0 if template.get("passed") else 3), brief


def portfolio_exposure(salary_csv: Path, entries_csv: Path) -> dict:
    """Aggregate stack and SP-pair exposure across the delivered portfolio.

    The per-entry view alone does not answer the question worth asking, which is
    how concentrated the portfolio is. Computing it here means nobody has to
    re-join the export against the salary file by hand to write the brief.
    """
    import collections

    with salary_csv.open(encoding="utf-8-sig", newline="") as fh:
        salary = {r["ID"]: r for r in csv.DictReader(fh)}
    primary, pitchers, pairs, n = collections.Counter(), collections.Counter(), set(), 0
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 14 or not row[0].strip().isdigit():
                continue
            ids = [c.strip() for c in row[4:14]]
            if any(p not in salary for p in ids):
                continue
            n += 1
            teams = collections.Counter(salary[p]["TeamAbbrev"] for p in ids[2:])
            team, size = teams.most_common(1)[0]
            primary[f"{team} ({size})"] += 1
            for p in ids[:2]:
                pitchers[salary[p]["Name"]] += 1
            pairs.add(frozenset(ids[:2]))
    pct = lambda c: {k: f"{v}/{n}" for k, v in c.most_common()}
    return {
        "lineups": n,
        "primary_stacks": pct(primary),
        "pitcher_exposure": pct(pitchers),
        "distinct_sp_pairs": len(pairs),
        "note": "counts across the delivered portfolio; deterministic review "
                "proxies, never ROI, win rate, or probability",
    }


VALID_POSTURES = ("cash", "wta_satellite", "single_entry", "small_gpp",
                  "large_gpp", "mme")


def parse_postures_arg(value: str | None) -> dict[str, str]:
    """'<id_or_name>=<posture>,...' -> {key: posture}, validated eagerly.

    A typo here would silently fall through name inference to large_gpp, which is
    the exact failure the flag exists to close, so an unknown posture is an error
    at parse time rather than a value nothing reads.
    """
    if not value:
        return {}
    out: dict[str, str] = {}
    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit(f"--postures entry {item!r} is not <contest>=<posture>")
        key, posture = (x.strip() for x in item.split("=", 1))
        if posture not in VALID_POSTURES:
            raise SystemExit(
                f"--postures: unknown posture {posture!r}; valid: "
                + ", ".join(VALID_POSTURES))
        out[key] = posture
    return out


import re as _re

# SOFT pool blockers: they degrade the build and print, they do not stop it.
# Everything else from build_slate_pool is HARD. Keeping the soft list explicit
# and short means a new blocker is hard by default, which is the safe direction.
SOFT_POOL_BLOCKER_RE = _re.compile(
    r"(stale|days old|refresh|reference file|platoon file is)", _re.IGNORECASE)

ASSUMABLE_GATES = ("salary_gate_passed", "entry_grid_gate_passed",
                   "lineup_gate_passed", "pitcher_audit_gate_passed",
                   "weather_gate_passed", "odds_gate_passed")


def parse_assume_gates_arg(value: str | None) -> list[str]:
    if not value:
        return []
    out = []
    for name in str(value).split(","):
        name = name.strip()
        if not name:
            continue
        if name not in ASSUMABLE_GATES:
            raise SystemExit(f"--assume-gates: unknown gate {name!r}; valid: "
                             + ", ".join(ASSUMABLE_GATES))
        out.append(name)
    return out


BARE_STAGED_NAMES = {"DKSalaries.csv", "DKEntries.csv"}


def _stage(source: Path, dest: Path) -> Path:
    """Copy an uploaded file into the slate directory, writably.

    Uploads arrive on a read-only mount, so a plain copy inherits mode 500 and the
    next slate cannot overwrite it. Replace rather than write in place.

    The bare ``DKSalaries.csv`` / ``DKEntries.csv`` names are what
    ``tools/late_swap.py`` and ``tools/solver_probe.py`` read by default, and
    ``data/slates/<date>/`` is keyed on date alone. Staging Showdown data at
    those names points the deadline-critical tools at a six-slot file they will
    read as ten-slot. It happened on 2026-07-25: the staged Classic pair went
    md5-identical to its ``_showdown`` twins. Showdown always stages under a
    suffixed name.
    """
    if source.resolve() == dest.resolve():
        return dest
    if dest.name in BARE_STAGED_NAMES:
        with source.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            first = next(reader, [])
        looks_showdown = (
            "CPT" in [str(c).strip().upper() for c in header]
            or any(str(c).strip().upper() in ("CPT", "UTIL") for c in first[:6])
        )
        if looks_showdown:
            raise ValueError(
                f"refusing to stage Showdown data at the bare Classic name "
                f"{dest.name}: {source} carries CPT/UTIL geometry. "
                f"tools/late_swap.py and tools/solver_probe.py default to this "
                f"name and would read it at Classic width. Stage Showdown under "
                f"a suffixed name."
            )
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            dest.chmod(0o644)
    dest.write_bytes(source.read_bytes())
    try:
        dest.chmod(0o644)
    except OSError:
        pass
    return dest


def count_reserved(entries_csv: Path) -> int:
    n = 0
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip().isdigit():
                n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salary", required=True)
    ap.add_argument("--entries", dest="entries_csv", required=True)
    ap.add_argument("--lineups", help="mlb-lineups feed JSON; fetched if omitted")
    ap.add_argument("--odds",
                    help="game-odds JSON (raw the-odds-api events, an "
                         "mlb-game-odds payload, or a slate_bundle). Feeds the "
                         "F1 game-environment prior. When omitted, totals are "
                         "fetched if THE_ODDS_API_KEY is set, else F1 stays 1.0.")
    ap.add_argument("--date", help="slate date; derived from the salary file if omitted")
    ap.add_argument("--no-rotowire", dest="rotowire", action="store_false",
                    help="skip the RotoWire projected-lineup fallback for TBD teams "
                         "and use only the FanGraphs reference")
    ap.set_defaults(rotowire=True)
    ap.add_argument("--entries-count", dest="entries", type=int,
                    help="override the reserved-entry count")
    ap.add_argument("--max-seconds", type=float, default=35.0,
                    help="wall clock this invocation may use before saving and "
                         "asking to be rerun")
    ap.add_argument("--brief", help="write the brief JSON here")
    ap.add_argument("--ignore-pool-blockers", action="store_true",
                    help="build despite a HARD pool blocker. The override is "
                         "printed and recorded in the brief. Reach for this only "
                         "when you have read the blocker and know it is wrong.")
    ap.add_argument("--assume-gates", dest="assume_gates", default=None,
                    help="comma-separated pre-export gates to certify without "
                         "checking, for the T-5 fast path. Each one is recorded "
                         "verbatim in diagnostics.json, so the artifact states "
                         "which checks were skipped instead of implying they ran. "
                         "Valid: " + ", ".join(ASSUMABLE_GATES))
    ap.add_argument("--postures", default=None,
                    help="comma-separated <contest_id_or_name>=<posture> pairs, e.g. "
                         "'192707612=wta_satellite,192707473=cash'. Postures: cash, "
                         "wta_satellite, single_entry, small_gpp, large_gpp, mme. "
                         "These override name inference entirely. The ledger Quick "
                         "Card's standing instruction is to never trust the "
                         "inference; this flag is how to obey it. A contest whose "
                         "name matches no archetype blocks the build until it is "
                         "named here or added to the archetypes CSV.")
    ap.add_argument("--controls-override", dest="controls_override", type=json.loads,
                    default=None,
                    help="JSON dict of portfolio_controls_override, e.g. "
                         "'{\"max_shared_players\": 8}'. Use when a build fails "
                         "with a feasibility hint naming a control floor; this "
                         "raises diversity caps, it never changes the player pool. "
                         "Showdown reads \"max_cpt_exposure_pct\" from the same "
                         "dict (default 0.35) to cap how much of the bank a "
                         "single captain can fill; pass null to disable it.")
    ap.add_argument("--bundle",
                    help="slate_bundle.json from tools/fetch_slate_bundle.py. "
                         "Supplies the per-venue forecast for F5. Park factors "
                         "apply without it; wind does not.")
    ap.add_argument("--reference-dir", default=None,
                    help="directory holding the projection enrichment inputs "
                         "(default data/reference/)")
    ap.add_argument("--reference-max-age-days", type=float, default=14.0,
                    help="warn in the brief when an enrichment input is older "
                         "than this (default 14). Stale inputs are still used; "
                         "they are reported, not blocked.")
    ap.add_argument("--no-enrichment", dest="enrichment", action="store_false",
                    help="build on AvgPointsPerGame x batting-order factor only, "
                         "skipping the xwOBA correction, xISO and K-rate ceilings, "
                         "and the F4 matchup factor. For reproducing an old build; "
                         "not for live slates.")
    ap.set_defaults(enrichment=True)
    ap.add_argument("--feed-max-age-minutes", type=float, default=90.0,
                    help="refetch a disk-cached lineups feed older than this "
                         "(default 90). Lineups confirm through the afternoon, so "
                         "a stale feed downgrades confirmed teams to projected "
                         "orders while better information exists.")
    args = ap.parse_args()

    started = time.monotonic()
    deadline = started + args.max_seconds

    salary, entries = Path(args.salary), Path(args.entries_csv)
    if not salary.exists() or not entries.exists():
        print(json.dumps({"status": "missing_inputs"}, indent=1))
        return 4

    args.date = args.date or slate_date_from_salary(salary)
    contest = detect_contest_type(salary, entries)

    slate_dir = REPO / "data" / "slates" / args.date
    slate_dir.mkdir(parents=True, exist_ok=True)
    # Classic and Showdown builds for the same date used to stage to the same
    # DKSalaries.csv/DKEntries.csv filenames, so a Showdown build for a date
    # already carrying a Classic build (or vice versa) silently overwrote the
    # other's staged inputs mid-run (hit 2026-07-23: a Showdown SD@ATL stage
    # clobbered an in-flight Classic build's salary/entries CSVs). Classic
    # keeps the bare filenames CLAUDE.md documents and that late_swap.py /
    # solver_probe.py already default to; Showdown gets distinct filenames so
    # the two contest types can never collide on the same date again.
    suffix = "_showdown" if contest == "showdown" else ""
    # The contest-type suffix separates Classic from Showdown but not one Classic
    # draftgroup from another on the same date. Compare game sets and move the
    # prior draftgroup's staged inputs, brief, and delivered file aside rather
    # than overwriting them.
    signature = slate_signature(salary)
    prior_salary = slate_dir / f"DKSalaries{suffix}.csv"
    out_dir = REPO / "outputs" / args.date
    if prior_salary.exists():
        prior_sig = slate_signature(prior_salary)
        if prior_sig["games"] and prior_sig["games"] != signature["games"]:
            print(f"different draftgroup for {args.date}: staged "
                  f"{prior_sig['tag']}, incoming {signature['tag']}", file=sys.stderr)
            preserve_prior_slate(
                [prior_salary,
                 slate_dir / f"DKEntries{suffix}.csv",
                 out_dir / f"DKEntries{suffix}.csv",
                 out_dir / f"build_brief{suffix}.json"],
                prior_sig["tag"],
            )
    staged_salary = _stage(salary, slate_dir / f"DKSalaries{suffix}.csv")
    staged_entries = _stage(entries, slate_dir / f"DKEntries{suffix}.csv")

    feed_note = None
    if contest == "showdown":
        code, brief = run_showdown(args, slate_dir, staged_salary, staged_entries)
    else:
        feed_path = Path(args.lineups) if args.lineups else slate_dir / "lineups_feed.json"
        if args.lineups:
            feed = json.loads(Path(args.lineups).read_text(encoding="utf-8"))
            # A supplied feed overwrote the staged one unconditionally, so a feed
            # for the wrong day or a hand-edited one destroyed the good copy and
            # left nothing to fall back to. The staged feed is the durable input;
            # it is replaced only by a feed that covers this draftgroup.
            staged_feed = slate_dir / "lineups_feed.json"
            feed_teams = {
                str((game.get(side) or {}).get("team_abbrev") or "").upper()
                for game in (feed.get("games") or []) for side in ("away", "home")
            }
            from mlb_engine.intake.slate_intake_manager import (
                parse_dk_salary_csv as _parse_salary,
            )
            slate_teams = {sp.team.upper() for sp in _parse_salary(str(salary))
                           if sp.team}
            covered = len(slate_teams & feed_teams)
            if slate_teams and covered * 2 < len(slate_teams):
                print(json.dumps({
                    "status": "supplied_feed_rejected",
                    "feed": str(args.lineups),
                    "slate_teams": sorted(slate_teams),
                    "covered": covered,
                    "note": "the supplied feed covers under half this draftgroup's "
                            "teams, so it is a feed for a different slate. The "
                            "staged feed was NOT overwritten.",
                }, indent=1))
                return 3, {}
            staged_feed.write_text(json.dumps(feed), encoding="utf-8")
            feed_note = {"source": str(args.lineups), "age_minutes": feed_age_minutes(feed),
                         "draftgroup_coverage": f"{covered}/{len(slate_teams)}"}
        elif feed_path.exists():
            # Lineups confirm continuously through the afternoon, so a feed left on
            # disk from the morning quietly downgrades confirmed teams to projected
            # orders at exactly the moment better information exists. Age it.
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
            age = feed_age_minutes(feed)
            if age is None or age > args.feed_max_age_minutes:
                try:
                    feed = fetch_lineups(args.date, feed_path)
                    feed_note = {"source": "refetched", "replaced_age_minutes": age}
                except Exception as exc:  # network failure must not kill the build
                    feed_note = {"source": str(feed_path), "age_minutes": age,
                                 "warning": f"stale feed reused; refetch failed: {exc}"}
                    print(feed_note["warning"], file=sys.stderr)
            else:
                feed_note = {"source": str(feed_path), "age_minutes": age}
        else:
            feed = fetch_lineups(args.date, feed_path)
            feed_note = {"source": "fetched", "age_minutes": 0.0}
        print(f"lineups feed: {json.dumps(feed_note)}", file=sys.stderr)
        code, brief = run_classic(args, slate_dir, staged_salary, staged_entries,
                                  feed, deadline)

    if brief:
        if args.odds and Path(args.odds).exists():
            brief["odds_source"] = args.odds
        brief["elapsed_s"] = round(time.monotonic() - started, 1)
        brief["labels"] = ("deterministic review proxies and labeled priors only; "
                           "never ROI, win rate, cash rate, or probability")
        brief["slate"] = {"tag": signature["tag"], "games": len(signature["games"]),
                          "first_lock_local": signature["first_lock"]}
        if feed_note is not None:
            brief["lineups_feed"] = feed_note
        out = Path(args.brief) if args.brief else (
            REPO / "outputs" / args.date / f"build_brief{suffix}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(brief, indent=1), encoding="utf-8")
        # A second, slate-tagged copy so evidence survives a same-date rebuild even
        # when the prior-slate preserve step did not run (same draftgroup, rerun).
        if not args.brief:
            out.with_name(f"build_brief{suffix}_{signature['tag']}.json").write_text(
                json.dumps(brief, indent=1), encoding="utf-8")
        print(json.dumps(brief, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
