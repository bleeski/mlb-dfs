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
import sys
import time
import urllib.request
from pathlib import Path

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
    feed = {"date": date, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "games": games}
    dest.write_text(json.dumps(feed), encoding="utf-8")
    return feed


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
            top = sorted(teams.items(), key=lambda kv: -kv[1])[:2]
            lineups.append({"entry_id": eid, "salary": total, "stack": top})
    return {"passed": not failures, "failures": failures, "lineups": lineups}


# --------------------------------------------------------------------------- #
# Classic
# --------------------------------------------------------------------------- #
def run_classic(args, slate_dir: Path, salary: Path, entries: Path,
                feed: dict, deadline: float) -> tuple[int, dict]:
    from mlb_engine.intake.live_data_adapters import build_slate_pool
    from mlb_engine.optimize.bank_cache import BankCache, extend_bank
    from mlb_engine.pipeline.execution_pipeline import (
        _assemble_projection_frame, run_slate,
    )

    pool = build_slate_pool(str(salary), feed)
    report = pool["pool_report"]
    clock = pool.get("clock") or {}
    kwargs = pool["run_slate_kwargs"]

    n_entries = args.entries or count_reserved(entries)
    projections, _ = _assemble_projection_frame(
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

    bank_path = REPO / "runs" / f"bank_cache_{args.date}.json"
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
        candidates = cache.as_candidates()
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
    result = run_slate(
        runs_root=str(REPO / "runs"),
        salary_csv=str(salary), entries_csv=str(entries),
        approve=True, requested_n=n_entries,
        candidates_override=candidates,
        # Always bounded, even on the direct path. The estimate above decides
        # strategy; this makes a wrong estimate degrade to a smaller bank instead
        # of a killed process that leaves nothing behind.
        bank_time_budget_s=max(deadline - time.monotonic() - 6.0, 5.0),
        **slate_kwargs,
    )

    if not result.get("passed"):
        print(json.dumps({"status": "not_certified",
                          "errors": result.get("errors")}, indent=1))
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
    }
    return (0 if checks["passed"] else 3), brief


# --------------------------------------------------------------------------- #
# Showdown
# --------------------------------------------------------------------------- #
def run_showdown(args, slate_dir: Path, salary: Path, entries: Path) -> tuple[int, dict]:
    from mlb_engine.optimize import showdown as sd

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

    bank = sd.build_showdown_bank(df, n=n_entries)
    if len(bank) < n_entries:
        print(json.dumps({"status": "bank_short",
                          "built": len(bank), "needed": n_entries}, indent=1))
        return 3, {}

    certs = [sd.certify_showdown(lineup, df) for lineup in bank[:n_entries]]
    failed = [c for c in certs if not c.get("passed")]
    if failed:
        print(json.dumps({"status": "not_certified",
                          "errors": [c.get("errors") for c in failed]}, indent=1))
        return 3, {}

    out_dir = REPO / "outputs" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "DKEntries_showdown.csv"
    assignments = [
        {"entry_id": row["entry_id"], "roster_ids": list(lineup["roster_ids"])}
        for row, lineup in zip(rows, bank[:n_entries])
    ]
    write_report = sd.write_showdown_entries(str(entries), str(dest), assignments)
    template = sd.verify_template_preserved(str(entries), str(dest))

    brief = {
        # Showdown ships as v0.1-review and Phase 3 is not complete, so this path
        # is labeled review-grade. It is not the Classic certification contract.
        "status": "review_grade_build",
        "contest_type": "showdown",
        "date": args.date,
        "entries": n_entries,
        "delivered_path": str(dest),
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
        "caution": ("showdown.py is v0.1-review and Phase 3 is not complete. "
                    "Per-lineup checks and template preservation passed, but this "
                    "is not the Classic three-gate certification. Review before "
                    "uploading."),
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


def _stage(source: Path, dest: Path) -> Path:
    """Copy an uploaded file into the slate directory, writably.

    Uploads arrive on a read-only mount, so a plain copy inherits mode 500 and the
    next slate cannot overwrite it. Replace rather than write in place.
    """
    if source.resolve() == dest.resolve():
        return dest
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
    ap.add_argument("--odds", help="mlb-game-odds JSON, used for the brief only")
    ap.add_argument("--date", help="slate date; derived from the salary file if omitted")
    ap.add_argument("--entries-count", dest="entries", type=int,
                    help="override the reserved-entry count")
    ap.add_argument("--max-seconds", type=float, default=35.0,
                    help="wall clock this invocation may use before saving and "
                         "asking to be rerun")
    ap.add_argument("--brief", help="write the brief JSON here")
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
    staged_salary = _stage(salary, slate_dir / "DKSalaries.csv")
    staged_entries = _stage(entries, slate_dir / "DKEntries.csv")

    if contest == "showdown":
        code, brief = run_showdown(args, slate_dir, staged_salary, staged_entries)
    else:
        feed_path = Path(args.lineups) if args.lineups else slate_dir / "lineups_feed.json"
        if args.lineups:
            feed = json.loads(Path(args.lineups).read_text(encoding="utf-8"))
            (slate_dir / "lineups_feed.json").write_text(json.dumps(feed), encoding="utf-8")
        elif feed_path.exists():
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
        else:
            feed = fetch_lineups(args.date, feed_path)
        code, brief = run_classic(args, slate_dir, staged_salary, staged_entries,
                                  feed, deadline)

    if brief:
        if args.odds and Path(args.odds).exists():
            brief["odds_source"] = args.odds
        brief["elapsed_s"] = round(time.monotonic() - started, 1)
        brief["labels"] = ("deterministic review proxies and labeled priors only; "
                           "never ROI, win rate, cash rate, or probability")
        out = Path(args.brief) if args.brief else (
            REPO / "outputs" / args.date / "build_brief.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(brief, indent=1), encoding="utf-8")
        print(json.dumps(brief, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
