#!/usr/bin/env python3
"""tools/stage_slate.py -- Phase 1 intake wiring (migration guide, Phase 1).

Make ``data/slates/<date>/`` sufficient input for a build in one command.

Given a date, this loads the four staged artifacts from that folder --
``slate_bundle.json`` (the mlb-lineups-shaped feed plus DK/FD totals plus
per-venue weather, produced by ``tools/fetch_slate_bundle.py``), the platoon
JSON, the DKSalaries CSV, and the DKEntries reserved-entries CSV -- runs the
confirmed-pool intake front door
(``live_data_adapters.build_slate_pool``), computes the deterministic F4
matchup prior via ``compute_f4_factors`` over
``extract_opposing_probables``/``extract_batter_hands``, parses the odds packet
via ``parse_the_odds_api_totals``, and assembles the exact ``run_slate`` kwargs.

The acceptance bar (migration guide, Phase 1): one command stages tonight's
slate and ``run_slate(approve=False)`` returns a clean checkpoint with no file
pasted or uploaded by hand. Manual lineups-feed construction stays documented in
CLAUDE.md as the fallback path, nothing more.

The DKSalaries CSV stays authoritative for Player_ID, salary, team, and
eligibility (CLAUDE.md "Authority"); this tool never corrects it against
real-world rosters. Everything here is deterministic intake bookkeeping and
labeled priors -- never a projection edge, ROI, win-rate, or probability claim.

Usage:
  python tools/stage_slate.py [--date YYYY-MM-DD] [--slates-dir data/slates]
                              [--reference-dir data/reference]
                              [--runs-root runs] [--no-enrich]
                              [--checkpoint] [--json]
                              [--salary-csv P] [--entries-csv P]
                              [--bundle-json P] [--platoon-json P]

  --checkpoint  after staging, call run_slate(approve=False) and print the
                slate clock, the pool report, and the single Blockers line.
  --json        print a compact JSON summary of the assembled kwargs
                (ids and counts, never full projection rows).

Exit codes: 0 staged, 1 the checkpoint did not pass, 2 an input is missing or
malformed, 4 two files match one intake role and the tool will not guess --
name the one you are building with the matching flag.

A slate dir routinely holds more than one DK export: two Classic draftgroups
plus the day's showdowns, all downloaded to the same folder. Sniffing cannot
choose between them, so more than one match per role is a block (R70), never a
silent pick.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ENTRIES_HEADER_PREFIX = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]

# What actually happens when the slate dir holds no platoon JSON. A constant so
# the claim is pinnable: the previous wording promised a top-9 AvgPointsPerGame
# fallback, which stopped being true when build_slate_pool began loading
# DEFAULT_PLATOON_REFERENCE for a None platoon_json (R70 rider).
NO_PLATOON_IN_DIR_NOTE = (
    "no platoon JSON in the slate dir; TBD-lineup teams take "
    "data/reference/fangraphs_platoon_lineups.json (subject to the R27 "
    "staleness policy), and top-9 AvgPointsPerGame only if that reference is "
    "missing too"
)


def _today_et() -> str:
    # R65's one ET authority. This was a hardcoded UTC-4 until 2026-08-14,
    # citing fetch_slate_bundle's own approximation -- which R65 had already
    # migrated, leaving this the last copy. UTC-4 flips the DATE for any
    # instant between 04:00 and 05:00 UTC, so a late-night session could stage
    # tomorrow's folder.
    from mlb_engine.repo_env import today_et
    return today_et()


def _read_header(path: Path) -> List[str]:
    import csv
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])


class AmbiguousSlateInput(ValueError):
    """More than one file in the slate dir matches one intake role (R70).

    Carries ``role``, ``candidates`` and ``flag`` so a caller can report the
    named list rather than a count. A sniffer cannot choose between two
    legitimate DK exports -- on the routine two-classic-slates day both are
    real slates and only the operator knows which one is being built -- so the
    ambiguity is stated and the named flag is the channel out of it.
    """

    def __init__(self, role: str, candidates: List[Path], flag: str) -> None:
        self.role = role
        self.candidates = list(candidates)
        self.flag = flag
        names = ", ".join(p.name for p in self.candidates)
        super().__init__(
            f"{len(self.candidates)} files match the {role} role in "
            f"{self.candidates[0].parent}: {names}. Name the one you are "
            f"building with `{flag} <path>`. Staging the wrong draftgroup is "
            f"silent all the way to the upload file, so this is a block."
        )


def _resolve_override(role: str, slate_dir: Path, override: str | Path, flag: str) -> Path:
    """An operator-typed path for one intake role. Missing is a block.

    R69's precedent applies: an operator-typed identifier is fixed by
    correcting one argument, so it hard-gates rather than degrading to a
    warning.

    A relative path resolves against THE SLATE DIR FIRST, and the directory the
    operator typed is preserved. The first cut of this function did neither: it
    tested ``Path(override).exists()`` -- which is CWD-relative -- before
    falling back, and then flattened the fallback to ``.name``. Run from the
    repo root, where a stray ``DKSalaries.csv`` and ``DKEntries.csv`` from
    2026-07-27 sit beside a ``slate_bundle.json`` from 07-21,
    ``--salary-csv DKSalaries.csv --date 2026-07-19`` staged the ROOT files
    against the 07-19 bundle and printed ``salary=DKSalaries.csv``, a line
    byte-identical to a correct in-dir resolution. That is R70's own defect
    re-entering through R70's remedy, so the resolution order is part of the
    fix and not an implementation detail.
    """
    typed = Path(override)
    candidates = [typed] if typed.is_absolute() else [slate_dir / typed, typed]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"{flag} names a {role} file that does not exist: {override} "
        f"(looked in {slate_dir} first, then the working directory)")


def _provenance(path: Path, slate_dir: Path) -> str:
    """How a resolved input is named in ``sources`` and in the printed line.

    In-dir files show their basename, which is what the operator recognizes.
    Anything else shows its FULL path, because a file from outside the slate
    dir wearing a bare filename is exactly how the wrong draftgroup travels
    unnoticed.
    """
    try:
        if path.resolve().parent == slate_dir.resolve():
            return path.name
    except OSError:
        pass
    return str(path)


def _sole(role: str, candidates: List[Path], flag: str) -> Optional[Path]:
    """Exactly one candidate, or None, or a block naming every candidate."""
    if not candidates:
        return None
    if len(candidates) > 1:
        raise AmbiguousSlateInput(role, candidates, flag)
    return candidates[0]


def _find_salary_and_entries(
    slate_dir: Path,
    *,
    salary_override: Optional[str | Path] = None,
    entries_override: Optional[str | Path] = None,
) -> Tuple[Optional[Path], Optional[Path]]:
    """Content-sniff the slate dir for the DK salary export and the DKEntries
    reserved-entries file, independent of filename convention -- the same
    discipline tests/test_golden_replay.py uses: the entries file by its exact
    4-column header, the salary file by validate_salary_schema.

    R70: this used to keep the LAST match per role, because both branches
    assigned into one variable inside the loop. Against the real
    ``data/slates/2026-07-30/`` layout that staged
    ``DKSalaries_showdown_1415_1g_sd.csv`` + ``DKEntries_showdown_1415_1g_sd.csv``
    -- a 1-game showdown pair -- on a Classic day, with no warning. Two
    Classic exports in one dir (``DKSalaries.csv`` +
    ``DKSalaries_1910_6g.csv``) is the ROUTINE layout, not an edge case: 17 of
    the dirs under data/slates/ carry more than one salary export. Neither
    filename convention nor sort order nor mtime is authority over which slate
    the operator is building, so every match is collected and more than one is
    a block.
    """
    from mlb_engine.intake.slate_intake_manager import validate_salary_schema

    def _is_entries(path: Path) -> bool:
        try:
            header = _read_header(path)
        except Exception:
            return False
        return bool(header) and [c.strip() for c in header[:4]] == ENTRIES_HEADER_PREFIX

    salary_csv = entries_csv = None
    if salary_override is not None:
        salary_csv = _resolve_override("salary", slate_dir, salary_override, "--salary-csv")
        if _is_entries(salary_csv):
            raise ValueError(
                f"--salary-csv {salary_csv.name} is a DKEntries file, not a salary "
                f"export (its header starts '{', '.join(ENTRIES_HEADER_PREFIX)}'). "
                f"The two flags are swapped.")
    if entries_override is not None:
        entries_csv = _resolve_override("entries", slate_dir, entries_override, "--entries-csv")
        if not _is_entries(entries_csv):
            raise ValueError(
                f"--entries-csv {entries_csv.name} does not start with "
                f"'{', '.join(ENTRIES_HEADER_PREFIX)}', so it is not a DKEntries "
                f"reserved-entries file. The two flags may be swapped.")
    if salary_csv is not None and entries_csv is not None:
        # Both roles named: nothing needs sniffing, and scanning anyway lets an
        # undecodable CSV elsewhere in the dir raise a codec error that names no
        # file for a resolution that did not depend on it.
        return salary_csv, entries_csv

    salary: List[Path] = []
    entries: List[Path] = []
    for path in sorted(slate_dir.glob("*.csv")):
        try:
            header = _read_header(path)
            if not header:
                continue
            if [c.strip() for c in header[:4]] == ENTRIES_HEADER_PREFIX:
                entries.append(path)
                continue
            if validate_salary_schema(str(path)).get("passed"):
                salary.append(path)
        except Exception:
            # Unreadable or undecodable: it is not a candidate for either role.
            continue

    if salary_csv is None:
        salary_csv = _sole("salary", salary, "--salary-csv")
    if entries_csv is None:
        entries_csv = _sole("entries", entries, "--entries-csv")
    return salary_csv, entries_csv


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_platoon_shaped(obj: Any) -> bool:
    """Does this JSON carry what ``build_projected_order`` actually reads?

    That function iterates ``platoon['teams']`` for entries with ``abbrev``
    (platoon_order_adapter.py). A lineups-shaped feed has ``games``, not
    ``teams``, so it fills nothing -- and passing one anyway is worse than
    passing nothing, because ``build_slate_pool`` loads
    ``DEFAULT_PLATOON_REFERENCE`` only when ``platoon_json is None``. A bad
    guess therefore costs the good default (R70).
    """
    if not isinstance(obj, Mapping):
        return False
    teams = obj.get("teams")
    return isinstance(teams, list) and bool(teams)


def _find_bundle_and_platoon(
    slate_dir: Path,
    *,
    bundle_override: Optional[str | Path] = None,
    platoon_override: Optional[str | Path] = None,
) -> Tuple[Optional[Path], Optional[Path], Optional[Path], List[str]]:
    """Resolve the three JSON artifacts. Prefer conventional names, then sniff.

    - bundle: ``slate_bundle.json`` if present -- ``fetch_slate_bundle.py``
      writes that exact name, so a conventional hit is unambiguous by
      construction -- else any *.json carrying a ``bundle_version`` or
      ``lineups`` key, where more than one candidate blocks.
    - platoon: any ``*platoon*.json``, else the remaining non-bundle,
      non-declared JSON -- and in both cases only if it is platoon-SHAPED.
      R70: the unvalidated fallback took the first remaining JSON, which on
      the real 07-30 dir is ``_home_sides_feed.json``, a lineups feed. It has
      no ``teams``, so it projected no orders AND suppressed the reference
      file that would have. A rejected guess falls through to None so
      ``build_slate_pool`` loads its default, and says which file it rejected.
    - declared_pitchers: ``declared_pitchers.json`` if present (optional; the
      feed's own probables are used when it is absent).

    Returns (bundle, platoon, declared, notes).
    """
    notes: List[str] = []
    jsons = sorted(slate_dir.glob("*.json"))
    declared = next((p for p in jsons if p.name == "declared_pitchers.json"), None)

    if bundle_override is not None:
        bundle: Optional[Path] = _resolve_override(
            "slate bundle", slate_dir, bundle_override, "--bundle-json")
    else:
        bundle = next((p for p in jsons if p.name == "slate_bundle.json"), None)
        if bundle is None:
            sniffed = []
            for p in jsons:
                if p == declared:
                    continue
                try:
                    obj = _load_json(p)
                except Exception:
                    continue
                if isinstance(obj, Mapping) and ("bundle_version" in obj or "lineups" in obj):
                    sniffed.append(p)
            bundle = _sole("slate bundle", sniffed, "--bundle-json")

    if platoon_override is not None:
        platoon: Optional[Path] = _resolve_override(
            "platoon", slate_dir, platoon_override, "--platoon-json")
        try:
            obj = _load_json(platoon)
        except Exception as exc:
            raise ValueError(f"--platoon-json is unreadable ({platoon.name}): {exc}") from exc
        if not _is_platoon_shaped(obj):
            # Operator-typed identifier: one argument fixes it, so it blocks.
            raise ValueError(
                f"--platoon-json {platoon.name} carries no non-empty 'teams' "
                f"list, so build_projected_order would fill no orders from it. "
                f"Point it at a FanGraphs platoon-lineups JSON, or omit the "
                f"flag to use data/reference/fangraphs_platoon_lineups.json.")
        return bundle, platoon, declared, notes

    named = [p for p in jsons if "platoon" in p.name.lower()]
    pool = named or [p for p in jsons if p not in (bundle, declared)]
    platoon = None
    rejected: List[str] = []
    for p in pool:
        try:
            obj = _load_json(p)
        except Exception:
            rejected.append(f"{p.name} (unreadable)")
            continue
        if _is_platoon_shaped(obj):
            platoon = p
            break
        rejected.append(f"{p.name} (no 'teams' list)")
    if platoon is None and rejected:
        notes.append(
            "no platoon-shaped JSON in the slate dir; rejected " +
            ", ".join(rejected) +
            ". Falling through to data/reference/fangraphs_platoon_lineups.json.")
    return bundle, platoon, declared, notes


def stage_slate(
    date: str,
    slates_dir: str | Path = REPO_ROOT / "data" / "slates",
    reference_dir: str | Path = REPO_ROOT / "data" / "reference",
    runs_root: Optional[str | Path] = REPO_ROOT / "runs",
    enrich: bool = True,
    declared_pitchers: Optional[Mapping[str, str]] = None,
    salary_csv_override: Optional[str | Path] = None,
    entries_csv_override: Optional[str | Path] = None,
    bundle_json_override: Optional[str | Path] = None,
    platoon_json_override: Optional[str | Path] = None,
    stale_platoon_policy: str = "warn",
) -> Dict[str, Any]:
    """Stage ``data/slates/<date>/`` into ready-to-splat ``run_slate`` kwargs.

    Returns a dict with ``run_slate_kwargs`` (splat straight into
    ``run_slate``), plus the ``odds_packet``, ``pool_report``, ``clock``,
    ``f4_report``, ``weather``, resolved ``sources``, and ``warnings`` for the
    checkpoint and the morning brief. Deterministic bookkeeping only.
    """
    from mlb_engine.intake.live_data_adapters import (
        build_slate_pool, parse_the_odds_api_totals, salary_game_times,
    )
    from mlb_engine.projections.projection_builder import (
        compute_f4_factors, load_savant_expected_stats,
    )

    slate_dir = Path(slates_dir) / date
    if not slate_dir.exists():
        raise FileNotFoundError(f"slate folder does not exist: {slate_dir}")

    warnings: List[str] = []

    salary_csv, entries_csv = _find_salary_and_entries(
        slate_dir,
        salary_override=salary_csv_override,
        entries_override=entries_csv_override,
    )
    if salary_csv is None:
        raise FileNotFoundError(
            f"no DKSalaries CSV found in {slate_dir} (a DraftKings salary export "
            f"with Position/Name+ID/Salary/TeamAbbrev columns). Download it from "
            f"DraftKings and drop it in that folder."
        )
    if entries_csv is None:
        raise FileNotFoundError(
            f"no DKEntries reserved-entries CSV found in {slate_dir} (header must "
            f"start 'Entry ID,Contest Name,Contest ID,Entry Fee'). Download it from "
            f"DraftKings and drop it in that folder."
        )

    bundle_path, platoon_path, declared_path, json_notes = _find_bundle_and_platoon(
        slate_dir,
        bundle_override=bundle_json_override,
        platoon_override=platoon_json_override,
    )
    warnings.extend(json_notes)
    if bundle_path is None:
        raise FileNotFoundError(
            f"no slate_bundle.json found in {slate_dir}. Run "
            f"`python tools/fetch_slate_bundle.py --date {date} "
            f"--out {slate_dir}/slate_bundle.json` first."
        )
    # R296(c), the third member of the same class. Every OTHER `_load_json` call
    # in this file is wrapped -- the sniff loop, the platoon override, the
    # declared-pitcher file -- and this one, the bundle the whole stage depends
    # on, was bare: a truncated `slate_bundle.json` (the ordinary consequence of
    # a killed fetch) raised JSONDecodeError instead of the FileNotFoundError
    # sibling's named remedy eight lines above.
    try:
        bundle = _load_json(bundle_path)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"{bundle_path.name} cannot be read or parsed ({type(exc).__name__}: "
            f"{exc}). A truncated bundle is what a killed fetch leaves behind; "
            f"re-run `python tools/fetch_slate_bundle.py --date {date} "
            f"--out {bundle_path}`."
        ) from exc
    lineups_feed = bundle.get("lineups")
    if not lineups_feed or not (lineups_feed.get("games")):
        raise ValueError(
            f"{bundle_path.name} has no usable lineups feed (bundle['lineups']['games'] "
            f"is empty). The MLB Stats API fetch in fetch_slate_bundle.py may have failed; "
            f"see bundle['warnings']: {bundle.get('warnings')}"
        )
    for w in bundle.get("warnings") or []:
        warnings.append(f"bundle: {w}")

    platoon_json: Optional[Any] = None
    if platoon_path is not None:
        try:
            platoon_json = _load_json(platoon_path)
        except Exception as exc:
            warnings.append(f"platoon JSON unreadable ({platoon_path.name}): {exc}")
    elif not json_notes:
        # R70 rider, found while fixing the sniff: this used to say TBD teams
        # "will fall back to top-9 AvgPointsPerGame", which stopped being true
        # when build_slate_pool started loading DEFAULT_PLATOON_REFERENCE
        # whenever platoon_json is None. Top-9 APPG is the fallback only if
        # that reference file is also absent. Telling the operator their TBD
        # teams have no projected order when they do is the same
        # steers-you-wrong class as the two defects above.
        warnings.append(NO_PLATOON_IN_DIR_NOTE)

    if declared_pitchers is None and declared_path is not None:
        try:
            declared_pitchers = _load_json(declared_path)
        except Exception as exc:
            warnings.append(f"declared_pitchers.json unreadable: {exc}")

    # THE intake front door (CLAUDE.md per-slate loop step 1).
    #
    # stale_platoon_policy is passed EXPLICITLY, matching the two other scripted
    # doors (late_swap.py:578, build_slate.py:1325) per R27. Before the platoon
    # validation above, a dir holding only a lineups feed had that feed mistaken
    # for the platoon file, so DEFAULT_PLATOON_REFERENCE never loaded and R27's
    # age gate never fired here at all. Now it loads -- which means inheriting
    # the engine default 'block' would have made this checkpoint STRICTER than
    # the build door it previews, as a side effect of fixing something else. The
    # reference is routinely a few days old; a hard blocker at T-10 on a
    # review-only door is not the same call the build makes.
    pool = build_slate_pool(
        salary_csv=str(salary_csv),
        lineups_feed=lineups_feed,
        platoon_json=platoon_json,
        declared_pitchers=declared_pitchers,
        stale_platoon_policy=stale_platoon_policy,
    )

    # An input from outside the slate dir is legal -- an operator may point at
    # another folder deliberately -- but it is never silent.
    for role, path in (("salary", salary_csv), ("entries", entries_csv),
                       ("bundle", bundle_path), ("platoon", platoon_path)):
        if path is not None and _provenance(path, slate_dir) != path.name:
            warnings.append(
                f"{role} file is OUTSIDE {slate_dir}: {path}. Confirm it is the "
                f"same slate as the rest of these inputs.")

    reference = Path(reference_dir)
    savant_batting = reference / "expected_stats_batting.csv"
    savant_pitching = reference / "expected_stats_pitching.csv"
    # R278. The K-rate input moved from a manual FanGraphs export to MLB
    # StatsAPI. The engine kwarg it feeds is still `fangraphs_pitching_csv`,
    # deliberately: that parameter is SHAPE-based (any CSV with Name and a K-rate
    # column) and the golden replay still feeds it a frozen FanGraphs file, so
    # the identifier rename is filed separately rather than ridden in here.
    fangraphs_pitching = reference / "statsapi_season_pitching.csv"

    # F4 deterministic matchup prior: opposing-SP contact quality (Savant
    # pitching frame) times the platoon hand factor. Neutral (1.0) where an
    # opposing probable or its Savant row is missing; still a labeled prior.
    pitching_table = None
    if savant_pitching.exists():
        try:
            pitching_table = load_savant_expected_stats(savant_pitching)
        except Exception as exc:
            warnings.append(f"savant pitching frame unreadable; F4 quality neutral: {exc}")
    f4_by_player_id, f4_report = compute_f4_factors(
        pool["team_by_player_id"],
        pool["opposing_probables"],
        pitching_table,
        pool["batter_hands"],
    )

    # Odds packet: parsed for the checkpoint and the brief. Not a run_slate
    # input in the current engine (the odds gate is static; only the opt-in
    # tail scanner consumes game environment), so it rides alongside the kwargs.
    odds_raw = bundle.get("odds_raw_totals")
    odds_packet: Dict[str, Any]
    if odds_raw:
        try:
            # F18: the salary file resolves which doubleheader leg is on this
            # slate, for odds exactly as for the lineups feed.
            odds_packet = parse_the_odds_api_totals(
                odds_raw, fetched_at=bundle.get("fetched_at"),
                slate_game_times=salary_game_times(str(salary_csv)))
            for leg in odds_packet.get("doubleheader_legs_dropped") or []:
                warnings.append(
                    f"odds doubleheader leg dropped: {leg['game_id']} @ "
                    f"{leg['start_utc']} total {leg.get('total')} ({leg['reason']})")
        except Exception as exc:
            odds_packet = {"odds_by_game_id": {}, "warning": f"odds parse failed: {exc}"}
            warnings.append(f"odds packet parse failed: {exc}")
    else:
        odds_packet = {"odds_by_game_id": {}, "note": "no odds in bundle (skipped or fetch failed)"}

    # Assemble the exact run_slate kwargs: pool kwargs + salary/entries + the
    # F4 map + the reference enrichments (each only if the file is present).
    kwargs: Dict[str, Any] = dict(pool["run_slate_kwargs"])
    kwargs["salary_csv"] = str(salary_csv)
    kwargs["entries_csv"] = str(entries_csv)
    kwargs["projection_mode"] = "emergency_proxy"
    kwargs["f4_by_player_id"] = f4_by_player_id or None
    if runs_root is not None:
        kwargs["runs_root"] = str(runs_root)
    if enrich:
        if savant_batting.exists():
            kwargs["savant_batting_csv"] = str(savant_batting)
        if savant_pitching.exists():
            kwargs["savant_pitching_csv"] = str(savant_pitching)
        if fangraphs_pitching.exists():
            kwargs["fangraphs_pitching_csv"] = str(fangraphs_pitching)

    pool_report = pool["pool_report"]
    for b in pool_report.get("blockers") or []:
        warnings.append(f"pool blocker: {b}")

    return {
        "date": date,
        "run_slate_kwargs": kwargs,
        "odds_packet": odds_packet,
        "pool_report": pool_report,
        "clock": pool.get("clock"),
        "f4_report": f4_report,
        "weather": bundle.get("weather"),
        "sources": {
            "slate_dir": str(slate_dir),
            "salary_csv": _provenance(salary_csv, slate_dir),
            "entries_csv": _provenance(entries_csv, slate_dir),
            "slate_bundle": _provenance(bundle_path, slate_dir),
            "platoon_json": _provenance(platoon_path, slate_dir) if platoon_path else None,
            "declared_pitchers": (
                _provenance(declared_path, slate_dir) if declared_path else None),
        },
        "warnings": warnings,
    }


def _kwargs_summary(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact, ID-and-count view of the assembled kwargs. Never dumps rows."""
    rows = kwargs.get("projection_rows") or []
    return {
        "salary_csv": kwargs.get("salary_csv"),
        "entries_csv": kwargs.get("entries_csv"),
        "projection_mode": kwargs.get("projection_mode"),
        "projection_rows": len(rows),
        "confirmed_hitter_ids": len(kwargs.get("confirmed_hitter_ids") or []),
        "confirmed_teams": list(kwargs.get("confirmed_teams") or []),
        "pitcher_roles": len(kwargs.get("pitcher_roles") or {}),
        "platoon_order_by_player_id": len(kwargs.get("platoon_order_by_player_id") or {}),
        "f4_by_player_id": len(kwargs.get("f4_by_player_id") or {}),
        "enrichments": [
            k for k in ("savant_batting_csv", "savant_pitching_csv", "fangraphs_pitching_csv")
            if kwargs.get(k)
        ],
    }


def _print_staging(staged: Mapping[str, Any]) -> None:
    src = staged["sources"]
    summary = _kwargs_summary(staged["run_slate_kwargs"])
    pr = staged["pool_report"]
    print(f"staged {staged['date']} from {src['slate_dir']}")
    print(f"  salary={src['salary_csv']}  entries={src['entries_csv']}  "
          f"bundle={src['slate_bundle']}  platoon={src['platoon_json']}")
    print(f"  pool: {pr['kept']} kept / {pr['dropped']} dropped of {pr['salary_rows_total']} "
          f"salary rows ({pr['hitters_kept']} hitters, {pr['pitchers_kept']} pitchers)")
    print(f"  kwargs: {summary['projection_rows']} rows, "
          f"{summary['confirmed_hitter_ids']} confirmed hitters, "
          f"{summary['pitcher_roles']} arms, "
          f"{summary['platoon_order_by_player_id']} platoon slots, "
          f"F4 on {summary['f4_by_player_id']} hitters")
    print(f"  odds: {len(staged['odds_packet'].get('odds_by_game_id') or {})} games; "
          f"enrichments: {summary['enrichments'] or 'none'}")
    blockers = pr.get("blockers") or []
    print(f"  Blockers: {'; '.join(blockers) if blockers else 'none'}")
    if staged["warnings"]:
        print("  warnings:")
        for w in staged["warnings"]:
            print(f"    - {w}")


def _et(iso_utc: Optional[str]) -> Optional[str]:
    """UTC ISO -> 'HH:MM ET' through the repo's one ET authority.

    ``repo_env.now_et`` exists because a hardcoded UTC-4 is an hour wrong in
    EST months (R65 names that exact bug in fetch_slate_bundle). The first cut
    of this helper hardcoded UTC-4 anyway, citing ``_today_et`` below as the
    convention -- but that helper was the un-migrated leftover R65 left behind,
    so the new code inherited a stale precedent. A postseason slate was told
    its first lock was an hour later than it is, on the T-schedule's one
    budgeting instrument, while ``minutes_to_deadline`` stayed right: the wall
    clock and the numeric budget disagreed by 60 minutes.

    An unparseable timestamp returns a LABEL, not None. None printed as
    ``first_lock=None``, which is the exact symptom R70(b) removed.
    """
    if not iso_utc:
        return None
    from mlb_engine.repo_env import now_et
    try:
        dt = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except ValueError:
        return "unparseable"
    if dt.tzinfo is None:
        return "unparseable(naive)"
    return now_et(dt).strftime("%H:%M ET")


def _format_clock(clock: Mapping[str, Any]) -> str:
    """The T-schedule's one budgeting instrument, read off the keys
    ``slate_clock()`` actually emits.

    R70(b): this printed ``first_lock=None deadline=None minutes_remaining=None``
    on every run, because it read ``first_lock_et`` / ``delivery_deadline_et``
    / ``minutes_remaining`` and the function returns ``first_lock_utc`` /
    ``deadline_utc`` / ``minutes_to_deadline``. Three keys, none of them real,
    and the blank was indistinguishable from a slate with no parseable game
    times -- which is the one case that genuinely has no clock and now says so.
    """
    if not clock:
        return "  slate_clock: absent from the checkpoint payload"
    if not clock.get("available", True):
        return (f"  slate_clock: unavailable -- "
                f"{clock.get('note') or 'no parseable game datetimes'} "
                f"(source={clock.get('source')})")
    mins = clock.get("minutes_to_deadline")
    line = (f"  slate_clock: first_lock={_et(clock.get('first_lock_utc'))} "
            f"deliver_by={_et(clock.get('deadline_utc'))} "
            f"(T-{clock.get('buffer_minutes')}) "
            f"minutes_to_deadline={mins}")
    if clock.get("past_deadline"):
        line += "  PAST DEADLINE: present the best certified file now"
    return line


def _run_checkpoint(kwargs: Mapping[str, Any]) -> int:
    from mlb_engine.pipeline.execution_pipeline import run_slate

    plan = run_slate(approve=False, **kwargs)
    ck = plan.get("checkpoint") or {}
    clock = ck.get("slate_clock") or {}
    print("--- run_slate(approve=False) checkpoint ---")
    print(f"  passed={plan.get('passed')}  status={plan.get('status')}")
    if plan.get("errors"):
        print(f"  errors: {plan['errors']}")
    print(_format_clock(clock))
    feas = ck.get("feasibility") or {}
    binding = feas.get("binding_constraints") or []
    ck_warnings = ck.get("warnings") or []
    blockers = [w for w in ck_warnings if "blocker" in str(w).lower()] or binding
    print(f"  Blockers: {'; '.join(str(b) for b in blockers) if blockers else 'none'}")
    return 0 if plan.get("passed") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage data/slates/<date>/ into run_slate kwargs")
    parser.add_argument("--date", default=_today_et(), help="ET slate date YYYY-MM-DD (default: today ET)")
    parser.add_argument("--slates-dir", default=str(REPO_ROOT / "data" / "slates"))
    parser.add_argument("--reference-dir", default=str(REPO_ROOT / "data" / "reference"))
    parser.add_argument("--runs-root", default=str(REPO_ROOT / "runs"))
    parser.add_argument("--no-enrich", action="store_true",
                        help="skip the Savant/FanGraphs enrichment CSVs")
    parser.add_argument("--checkpoint", action="store_true",
                        help="after staging, run run_slate(approve=False) and print the checkpoint")
    parser.add_argument("--json", action="store_true",
                        help="print a compact JSON summary of the assembled kwargs")
    # R70: the sniffer blocks when two files match one role, because a slate
    # dir routinely holds two Classic draftgroups plus the day's showdowns and
    # nothing in the filenames says which one is being built. These four are
    # the channel out of that block.
    parser.add_argument("--salary-csv", default=None,
                        help="name the DKSalaries export when the slate dir holds more than one")
    parser.add_argument("--entries-csv", default=None,
                        help="name the DKEntries reserved-entries file when the dir holds more than one")
    parser.add_argument("--bundle-json", default=None,
                        help="name the slate bundle when the dir holds more than one candidate")
    parser.add_argument("--platoon-json", default=None,
                        help="name the FanGraphs platoon-lineups JSON (must carry a 'teams' list)")
    parser.add_argument("--stale-platoon-policy", default="warn", choices=("warn", "block"),
                        help="R27 age gate on the platoon reference; 'warn' matches the "
                             "other scripted doors (default), 'block' is the engine default")
    args = parser.parse_args()

    try:
        staged = stage_slate(
            date=args.date,
            slates_dir=args.slates_dir,
            reference_dir=args.reference_dir,
            runs_root=args.runs_root,
            enrich=not args.no_enrich,
            salary_csv_override=args.salary_csv,
            entries_csv_override=args.entries_csv,
            bundle_json_override=args.bundle_json,
            platoon_json_override=args.platoon_json,
            stale_platoon_policy=args.stale_platoon_policy,
        )
    except AmbiguousSlateInput as exc:
        # Exit 4: the inputs are legal and the tool refuses to guess between
        # them. Distinct from exit 2 (an input is missing or malformed) so a
        # driver can tell "name the file" from "go download the file".
        print(f"stage_slate: {exc}", file=sys.stderr)
        return 4
    except (FileNotFoundError, ValueError) as exc:
        print(f"stage_slate: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "date": staged["date"],
            "kwargs_summary": _kwargs_summary(staged["run_slate_kwargs"]),
            "sources": staged["sources"],
            "odds_games": len(staged["odds_packet"].get("odds_by_game_id") or {}),
            "warnings": staged["warnings"],
        }, indent=2))
    else:
        _print_staging(staged)

    if args.checkpoint:
        return _run_checkpoint(staged["run_slate_kwargs"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
