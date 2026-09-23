#!/usr/bin/env python3
"""late_swap.py -- run a late swap without reassembling the call by hand.

run_late_swap is a good API but it was only ever exercised inside tests/test_core.py,
so a live swap meant discovering, one failure at a time: the argument order of
build_status_map_from_lineups_feed, that stack_constraints keys on 'team' and not
'primary_team', that workflow_gates is required on execute_portfolio, that
candidates need roster_slot_ids in ENTRY_ROSTER_SLOTS order rather than a player
list, and that entry requirements carry excluded_new_teams which forbids
introducing any new player from a game that has already locked. That last rule is
correct and load-bearing; none of it was documented outside a test. This wraps the
whole path in one command.

F16 added the identity and verification this path was missing. It resolves each
contest's posture and shape the way the build does instead of stamping every
entry ``large_wta``; it scores candidates in each contest's own shape instead of
handing the allocator unscored rosters; it checks the disk feed's date and age;
and it scores the incumbent lineup against the chosen one and refuses a
downgrade without ``--accept-downgrade``.

R29(2): the latest-run pointer is promoted after the mirror to ``outputs/``,
not at certification time. A refused run leaves the pointer naming the last
genuinely delivered portfolio, so the next swap resolves its parent correctly
and needs no ``--allow-parent-mismatch``.

Usage:
    python tools/late_swap.py --date 2026-07-22 \
        --parent-entries runs/<run_id>/final/DKEntries.csv \
        [--salary runs/<run_id>/inputs/DKSalaries.csv] \
        [--budget 30] [--solver-budget 15] [--lineups <fresh feed.json>] \
        [--entry-ids 123,456] [--dry-run] \
        [--postures <contest_id>=cash,...] [--accept-downgrade]

The money-and-entry wall still applies: this writes a CSV. Nothing here uploads,
enters a contest, or moves money. Lineups move only at Ben's manual upload.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import uuid
from pathlib import Path

# F19: pinned before any import, for the same reason as build_slate.py. This
# path writes a file that goes to DraftKings. Script-only, so importing this
# module never replaces the importer's process.
if (__name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0"
        and sys.executable):
    try:
        os.execve(sys.executable, [sys.executable, *sys.argv],
                  {**os.environ, "PYTHONHASHSEED": "0"})
    except OSError:
        pass

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mlb_engine.intake.live_data_adapters import (  # noqa: E402
    build_slate_pool, build_status_map_from_lineups_feed,
)
from mlb_engine.entries.dk_entries_manager import (  # noqa: E402
    assert_contest_geometry, parse_dk_entry_rows,
)
from mlb_engine.optimize.bank_cache import BankCache, extend_bank, pool_signature  # noqa: E402
from mlb_engine.entries.upload_manifest import (  # noqa: E402
    record_delivery, stage_salary_for_delivery, unrecorded_name,
)
from mlb_engine.pipeline.execution_pipeline import (  # noqa: E402
    _assemble_projection_frame, _merged_controls_for_build, _slate_feasibility,
    controls_for_report, derive_roster_id_maps,
    resolve_shape_bands, slate_game_count,
    _resolve_contest_postures, _slate_tag, feasibility_floors_from,
    promote_deferred_run, run_late_swap, unresolved_contest_blockers,
)
from mlb_engine.swap.late_swap_manager import build_entry_requirements  # noqa: E402

VALID_POSTURES = ("cash", "wta_satellite", "single_entry", "small_gpp",
                  "large_gpp", "mme")

# Past this the disk feed is describing a different state of the world than the
# one the swap is being made in. It is a warning, not a block: a swap runs at
# T-minutes and refusing on feed age would be the process preventing the lineup.
# A feed for the WRONG DATE is a different thing and does block.
FEED_AGE_WARN_MINUTES = 90

# R388(e). What the manifest records for a swap that took a downgrade under
# --accept-downgrade. CLAUDE.md (R386): the file ships review-grade, and it used
# to be recorded `certified` whenever the gates passed, so preflight stamped it
# `upload_ready`. `preflight_upload.REVIEW_GRADE_REASONS` carries the same key.
DOWNGRADE_LABEL = "review_grade_downgrade_accepted"

# F4: these were eight hardcoded True values on the path that runs closest to
# lock with the least verification. A swap does not re-derive weather, odds, or a
# pitcher audit, and it has no business claiming it did. What it can state is
# what it actually checks: the salary file parsed, the entry grid parsed, and the
# parent's posted lineups were read. The rest are declared assumptions, and
# ``assumed_gates`` in the artifact names them.
WORKFLOW_GATES = {
    "projection_schema_gate_passed": True, "optimizer_gate_passed": True,
}
# Named here rather than derived so the list is reviewable in one place. A swap
# that wants a real weather gate has to be given a weather map.
LATE_SWAP_ASSUMED_GATES = [
    "pitcher_audit_gate_passed", "weather_gate_passed", "odds_gate_passed",
]
# R29(3): the flat PORTFOLIO_CONTROLS dict that used to live here is deleted, not
# retained as a fallback. It applied one set of caps to every contest shape, and
# its max_sp_pair_repetition of 1 was tighter than every multi-entry posture in
# STRATEGY_DEFAULTS, so a portfolio that was legal when built failed this
# script's caps before the swap did any work. Controls come from
# resolve_swap_controls, which reads the postures in the file being refined and
# floors them the way the build does; a default that can disagree with the build
# is a second source of truth for the same number, and keeping one around to fall
# back to is how it comes back.


def swap_certification(result: dict, downgraded: list) -> str:
    """The manifest label for a delivered swap (R388(e)): failing gates win,
    then an accepted downgrade, then `certified`."""
    if not result.get("workflow_valid"):
        return "not_certified"
    return DOWNGRADE_LABEL if downgraded else "certified"


def lateswap_dest_name(slate_tag: str, run_id: str) -> str:
    """DKEntries_lateswap_<tag>_<runid8>.csv (R21).

    The old fixed name silently overwrote the previous swap. The tag is the
    same value the build's mirror uses, so the manifest supersession key
    (contest_type, slate_tag) matches and the swap replaces the parent build
    as "the" delivery for this slate; the run-id suffix makes two swaps two
    files instead of one overwrite.
    """
    tag = str(slate_tag or "").strip() or "untagged"
    suffix = str(run_id or "").rsplit("_", 1)[-1][:8] or "norun"
    return f"DKEntries_lateswap_{tag}_{suffix}.csv"


def resolve_swap_controls(postures, override, solver_budget,
                          requirements=None, projections=None,
                          excluded_player_ids=None, stripped_out=None,
                          never_relax=()) -> dict:
    """Merged portfolio controls for the swap, with the joint solve bounded (R25).

    R29(3): these used to be one flat dict applied to every contest, and its
    ``max_sp_pair_repetition: 1`` was tighter than every MULTI-ENTRY posture in
    STRATEGY_DEFAULTS (``small_gpp`` and ``wta_satellite`` 2, ``large_gpp`` and
    ``mme`` 3). A swap is certified against the WHOLE delivered portfolio, not
    just the authorized entries, so a portfolio that was legal when built failed
    this script's own caps before the swap did any work. On 2026-07-29 that cost
    the first twenty minutes of a correction chain and a dozen calls spent
    growing a bank that was never the problem.

    They are now derived exactly as the build derives them: the same
    ``_merged_controls_for_build`` (tightest cap wins across the contests present
    in this file) floored by the same ``_slate_feasibility``. Both halves matter.
    Without the floors the swap re-derives the UNFLOORED caps, which on a thin
    slate are tighter than the ones the build shipped, and the untouched entries
    violate them: the same failure arriving through the automatic path instead of
    the operator's. Pass ``requirements`` and ``projections`` to get the floors;
    omit them and the merge is unfloored, which is correct only when there is no
    frame to measure.

    Two postures are not a relaxation of the old dict and it is worth saying so
    plainly rather than letting the docstring overclaim. ``single_entry`` keeps
    ``max_sp_pair_repetition: 1``, which is right: one entry cannot repeat a
    pair. ``cash`` carries NO controls, so a cash-only swap enforces none, and
    that matches the build exactly -- which is the point of this change. A
    portfolio-level cap on a posture the engine calls a weak architectural fit is
    a number nobody chose; inheriting the build's silence is honest, and the
    pre-solve line prints the empty set so it is visible rather than assumed.

    The entry-level joint MILP reads its time limit from
    ``controls['time_limit']`` (contest_allocator, default 30s). That was
    reachable only through --controls-override and documented nowhere, so a
    swap that had to fit a bounded call window had no supported way to shrink
    its one monolithic stage. --solver-budget is that way; an explicit
    --controls-override time_limit still wins, because an operator who passed
    JSON meant it.

    R388(b). ``never_relax`` is the build's `--never-relax`, restated: the swap
    is the merge's third door, and a feasibility floor here must not raise a
    control the build held below it, or the refined file is graded against a
    looser cap than the one it was built to.
    """
    floors: dict = {}
    if requirements is not None and projections is not None:
        floors = feasibility_floors_from(_slate_feasibility(
            postures, requirements, projections, excluded_player_ids))
    # R37(2)(a)+(b), 2026-08-28. The shape bands ride the swap for the reason
    # R29(3) already established for the feasibility floors: one implementation,
    # because two would diverge and the weaker one would report success. Omitting
    # them here would have the swap re-derive a LOOSER floor than the build
    # shipped (4 where the build applied 5), which is the safe direction for
    # legality and the wrong one for truth -- the swapped file would carry a
    # portfolio the build's own stated construction rule does not describe, and
    # nothing would say so.
    #
    # Without a projection frame there is no game count, so the bands resolve
    # unavailable and this is the pre-band merge exactly. That is the same
    # condition under which the floors are skipped two lines up.
    shape_bands = resolve_shape_bands(
        postures,
        game_count=slate_game_count(projections) if projections is not None else None,
    )
    # R333 / R343. The swap is the THIRD production door through this merge and
    # the one `late_swap.py:214` below already names the game cap on: without
    # the id maps a swap re-derives controls the build enforced and cannot
    # enforce them, which is the exact failure R29(3) closed for the feasibility
    # floors, arriving through a new control. Derived from the same frame by the
    # same function the build uses; None where no frame was supplied, which is
    # the same condition that skips the floors and the bands above.
    roster_id_maps = (derive_roster_id_maps(projections)
                      if projections is not None else None)
    controls = dict(_merged_controls_for_build(
        postures, None, feasibility_floors=floors, shape_bands=shape_bands,
        roster_id_maps=roster_id_maps, never_relax=never_relax or ()))
    if solver_budget is not None:
        controls["time_limit"] = float(solver_budget)
    controls.update(override or {})
    # R405. The consensus-cluster cap is derived like every other control and
    # then STRIPPED, the item's one declined door. Enforced here it would bind
    # against a swap bank that holds no cluster-limited jobs and against
    # untouched rows that may already exceed it, so a legal refinement inside a
    # lock window would refuse on a cap the swap cannot satisfy. It is stripped
    # even when typed in --controls-override, and `stripped_out` names what was
    # removed so the caller says so out loud. Enforcement is a rider on R284.
    for key in SWAP_UNENFORCED_CONTROLS:
        if key in controls:
            value = controls.pop(key)
            if stripped_out is not None:
                stripped_out[key] = value
    return controls


#: R405. Controls the swap derives and does not enforce; see `resolve_swap_controls`.
SWAP_UNENFORCED_CONTROLS = ("max_consensus_cluster_share_pct",
                            "consensus_cluster_min_members")


def consensus_cluster_summary(block) -> str:
    """R405. One line for an allocator `consensus_cluster` block, or why not."""
    if not block:
        return "not recorded"
    members = [m.get("player_id") for m in (block.get("members") or [])]
    hist = block.get("delivered_member_count_histogram") or {}
    n = sum(int(v) for v in hist.values())
    return (f"{len(members)} member(s) at >= "
            f"{float(block.get('min_bank_share') or 0):.0%} bank share, "
            f"{block.get('delivered_at_k_or_more')}/{n} entries carry "
            f"{block.get('min_members_k')}+ (histogram {hist}); members "
            f"{members[:12]}")


def parent_consensus_cluster(runs_root: Path, parent_run_id):
    """R405. The parent build's cluster block, read from its immutable run record."""
    if not parent_run_id:
        return None
    path = Path(runs_root) / str(parent_run_id) / "final" / "diagnostics.json"
    try:
        diag = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return ((diag.get("allocation") or {}).get("consensus_cluster")) or None


# Every portfolio-control violation the entries validator can report, mapped to
# the control that produced it. R29(3): a swap that fails on one of these has a
# controls problem, and a swap that fails on "no compatible candidate" has a
# bank or pins problem. They used to be indistinguishable in the output, so the
# session chased the wrong one; each now names itself.
#
# R61 added the last two. `validate_dk_entries_file` reports overlap violations
# as "entries A/B share N>M" and game-exposure violations as "game G exposure
# N>M", and neither prefix was here, so the two controls that most often bind on
# a swap fell through to the bare else branch with no control named at all.
_CONTROL_BY_ERROR_PREFIX = (
    ("player ", "max_player_exposure_pct"),
    ("pitcher ", "max_pitcher_exposure_pct"),
    ("primary stack ", "max_primary_stack_exposure_pct"),
    ("SP pair ", "max_sp_pair_repetition"),
    ("entries ", "max_shared_players"),
    ("game ", "max_game_exposure_pct_by_game"),
    # R343 adds the seventh. The validator reports a team footprint violation as
    # "team T footprint N>M"; without this prefix it would fall through to the
    # bare else branch with no control named, which is the gap R61 closed for
    # the two above it.
    ("team ", "max_team_exposure_pct"),
)

# R61: the allocator's own refusals arrive here already carrying their ordered
# remedies, and appending a cap-loosening steer to one would contradict the
# sentence above it. This function adds nothing to them, and that holds WITHOUT a
# special case, on two facts a test pins rather than trusts. No refusal string
# starts with any prefix in the map above, so none is annotated and none reaches
# the trailer. And allocator errors never arrive alongside validator errors,
# because `execute_portfolio` returns on `not allocation["passed"]` before the
# export gates run. An explicit guard was written for this first and deleted: it
# could not be made to fail under mutation, because it could not change the
# output of any reachable input. See `test_an_allocator_refusal_is_not_re_steered`
# for what actually holds the invariant.


def classify_swap_failure(errors, controls, bank_report=None) -> list[str]:
    """Annotate each failure with the control that is binding, or say it is not one.

    R61's corrosive half, and the third instance of the pattern R98(2) closed.
    Every cap violation used to end with "pass it with --controls-override",
    which teaches cap-loosening as THE fix for a swap that fails at the gate.
    Two things were wrong with that. It made no distinction between a control
    that reaches an engine-named structural floor -- where raising to the floor
    is arithmetic and changes nothing else -- and an exposure cap that has no
    floor at all, where any value that clears the file is a portfolio strategy
    decision that concentrates the entered set. And it never asked whether the
    bank was a completed search, so a refusal against a bank explored to 1.8%
    read exactly like a refusal against an exhausted one.

    The vocabulary is `contest_allocator`'s: STRUCTURAL_FLOOR_CONTROLS versus
    STRATEGY_CAP_CONTROLS, ordered as `build_slate.infeasibility_hint` orders
    them -- bank growth first where the bank is still a slice, then arithmetic,
    then the strategy decision. Reused rather than restated, so a third copy of
    the split cannot drift from the first two.
    """
    from mlb_engine.allocate.contest_allocator import (
        STRATEGY_CAP_CONTROLS, STRUCTURAL_FLOOR_CONTROLS,
    )

    lines: list[str] = []
    named_structural: set[str] = set()
    named_strategy: set[str] = set()
    for err in errors or []:
        text = str(err)
        control = next((name for prefix, name in _CONTROL_BY_ERROR_PREFIX
                        if text.startswith(prefix)), None)
        if control:
            value = controls.get(control, "unset")
            if control in STRUCTURAL_FLOOR_CONTROLS:
                named_structural.add(control)
                kind = ("reaches an engine-named structural floor, so raising it "
                        "to that floor is arithmetic")
            else:
                # STRATEGY_CAP_CONTROLS plus max_game_exposure_pct_by_game, which
                # the constant does not list because it is per-game and keyed
                # rather than one number. It is the same class: a ceiling with no
                # engine-named floor under it.
                named_strategy.add(control)
                kind = ("has NO engine-named floor" if control in STRATEGY_CAP_CONTROLS
                        or control == "max_game_exposure_pct_by_game"
                        else "is not an engine-classified control")
                kind += (", so any value that clears this file is a portfolio "
                         "strategy decision")
            lines.append(f"  {text}  [binding control: {control}={value}; it {kind}]")
        elif "no compatible candidate" in text:
            lines.append(f"  {text}  [not a portfolio control: this entry's "
                         f"pins and excluded_new_teams admit none of the bank's "
                         f"candidates. Check that the entry's locked slots are "
                         f"what you expect before growing anything]")
        else:
            lines.append(f"  {text}")

    # Bank first, exactly as the allocator now does it. A refusal against a
    # partial search is a fact about the candidates that got built.
    report = bank_report or {}
    if report.get("job_list_exhausted") is False and (named_structural or named_strategy):
        attempted = report.get("jobs_attempted")
        total = report.get("jobs_total")
        scope = ""
        if attempted is not None and total:
            scope = (f" ({int(attempted)} of {int(total)} jobs attempted, "
                     f"{float(attempted) / float(total) * 100:.1f}%)")
        lines.append(
            f"  GROW THE BANK FIRST: the job list was not exhausted{scope}, so "
            f"these caps bound the candidates that got built, not this slate. "
            f"Re-run the same command with a larger --budget; the cache resumes."
        )
    if named_structural or named_strategy:
        parts = []
        if named_structural:
            parts.append(
                f"ARITHMETIC, not strategy: [{', '.join(sorted(named_structural))}] "
                f"reach an engine-named structural floor")
        if named_strategy:
            parts.append(
                f"A STRATEGY DECISION: [{', '.join(sorted(named_strategy))}] have "
                f"no floor, and the minimum value that clears this file is not a "
                f"recommendation")
        lines.append("  " + ". ".join(parts) + ".")
        lines.append(
            "  Before overriding anything, check the parent build's own values: a "
            "swap re-deriving a cap TIGHTER than the build shipped is the common "
            "cause (R29(3)), and restating the parent's number is not a strategy "
            "change. --controls-override takes JSON.")
    return lines


def _load_entry_rosters(path: Path) -> dict[str, list[str]]:
    """Entry ID -> its ten current Player_IDs, read from a DKEntries file."""
    import csv

    out: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) >= 14 and row[0].strip().isdigit():
                out[row[0].strip()] = [c.strip() for c in row[4:14] if c.strip()]
    return out


def _parse_postures(value: str | None) -> dict[str, str]:
    """'<contest_id_or_name>=<posture>,...' -> dict, validated eagerly.

    Same contract and same vocabulary as build_slate.py --postures. A typo that
    resolved to a silent default would be the exact failure this closes.
    """
    out: dict[str, str] = {}
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit(f"--postures entry {item!r} is not <contest>=<posture>")
        key, posture = (x.strip() for x in item.split("=", 1))
        if posture not in VALID_POSTURES:
            raise SystemExit(f"--postures: unknown posture {posture!r}; valid: "
                             + ", ".join(VALID_POSTURES))
        out[key] = posture
    return out


def _score_roster(projections, roster_ids, shape: str) -> float | None:
    """Contest-fit score for one roster under one contest shape.

    The same function and the same mode the bank payload is scored with, so the
    incumbent and the chosen lineup are compared on one scale. Returns None when
    the roster cannot be scored (an id absent from the frame), which reads as
    "no comparison available" and never as "no downgrade".
    """
    from mlb_engine.optimize.optimizer_v3 import (
        score_lineup_candidate, _mode_for_contest_shape,
    )

    ids = [str(p) for p in roster_ids if str(p).strip()]
    frame = projections.copy()
    frame["__pid__"] = frame["Player_ID"].astype(str)
    by_id = frame.set_index("__pid__", drop=False)
    present = [p for p in ids if p in by_id.index]
    if not ids or len(present) != len(ids):
        return None
    try:
        score = score_lineup_candidate(
            by_id.loc[present], projections,
            mode=_mode_for_contest_shape(shape, "wta"),
            contest_shape=shape,
        )
    except Exception:  # noqa: BLE001 - a scoring failure is not a downgrade
        return None
    value = score.get("contest_fit_score")
    return float(value) if value is not None else None


def resolve_swap_inputs(explicit_salary, explicit_lineups, slate_dir) -> tuple[Path, Path]:
    """(salary, lineups feed) for this swap: an explicit path always wins.

    R29(4). Both defaults are the shared, date-keyed staged names, which any
    concurrent build for the same date may overwrite while this swap is running.
    Resolution lives in one function so the salary path and the feed path cannot
    acquire different rules, and so "the explicit path wins" is a fact a test can
    assert without running a swap.
    """
    slate = Path(slate_dir)
    salary = Path(explicit_salary) if explicit_salary else slate / "DKSalaries.csv"
    feed = Path(explicit_lineups) if explicit_lineups else slate / "lineups_feed.json"
    return salary, feed


def _feed_age_report(feed: dict, slate_date: str, now: dt.datetime) -> tuple[list[str], list[str]]:
    """(blockers, warnings) about the age and identity of the disk feed."""
    blockers: list[str] = []
    warnings: list[str] = []
    feed_date = str(feed.get("date") or "").strip()[:10]
    if feed_date and feed_date != slate_date:
        blockers.append(
            f"lineups feed is for {feed_date}, this swap is for {slate_date}; "
            f"refetch the feed before swapping"
        )
    elif not feed_date:
        warnings.append("lineups feed carries no date; its identity is unverified")
    fetched = str(feed.get("fetched_at") or "").strip()
    if not fetched:
        warnings.append("lineups feed carries no fetched_at; its age is unknown")
        return blockers, warnings
    try:
        # Python 3.10's fromisoformat rejects a trailing 'Z', and the feeds this
        # reads are written with one. Left unhandled, every real feed reported
        # "age unknown" and the check was decorative.
        when = dt.datetime.fromisoformat(
            fetched[:-1] + "+00:00" if fetched.endswith("Z") else fetched)
    except ValueError:
        warnings.append(f"lineups feed fetched_at {fetched!r} is unparseable")
        return blockers, warnings
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    minutes = (now - when).total_seconds() / 60.0
    if minutes > FEED_AGE_WARN_MINUTES:
        warnings.append(
            f"lineups feed was fetched {minutes:.0f} minutes ago; scratches and "
            f"late lineup changes since then are invisible to this swap"
        )
    return blockers, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", required=True)
    ap.add_argument("--parent-entries", required=True,
                    help="the delivered DKEntries.csv being refined")
    ap.add_argument("--budget", type=float, default=30.0,
                    help="TOTAL seconds across every candidate-generation slice "
                         "(the general slice plus one per pinned entry). This was "
                         "per-slice, so three pinned entries cost four budgets "
                         "before the joint solve began. The bank cache persists "
                         "between runs, so re-running the same command resumes "
                         "instead of restarting.")
    ap.add_argument("--solver-budget", type=float, default=None,
                    help="seconds for the entry-level joint MILP (allocator "
                         "default 30). The swap re-certifies the WHOLE delivered "
                         "portfolio, so this stage is irreducible; bound it to "
                         "fit the call window (sandbox arithmetic: ~15s import + "
                         "--budget + this). A time-limited incumbent is verified "
                         "and accepted, tagged optimality='time_limited', per the "
                         "timeout guardrail.")
    ap.add_argument("--lineups",
                    help="fresher lineups_feed.json for THIS swap, read-only "
                         "(mirrors build_slate.py --lineups). Without it the swap "
                         "reads the shared data/slates/<date>/lineups_feed.json "
                         "cache, which is as old as whatever wrote it and is also "
                         "read and written by concurrent builds.")
    ap.add_argument("--salary",
                    help="DKSalaries.csv for THIS swap, read-only. Without it the "
                         "swap reads data/slates/<date>/DKSalaries.csv, which is "
                         "keyed on date alone and is therefore shared, mutable, "
                         "and clobberable by a concurrent build for the same date. "
                         "build_slate.py preserves a tagged copy "
                         "(DKSalaries_<tag>.csv) for exactly this; point at it and "
                         "the swap stops depending on the staged name.")
    # No --entries-source. Every entries read on this path already comes from
    # --parent-entries (geometry, the reserved grid, the embedded pool, the
    # rosters, and the run's own current_entries_csv), so there is no staged
    # entries file to route around: the operator already points that one
    # wherever they like. A second entries path would let the reserved grid
    # disagree with the file being refined, and nothing checks that.
    ap.add_argument("--entry-ids", help="comma-separated Entry IDs to authorize; "
                                        "default authorizes every reserved entry")
    ap.add_argument("--dry-run", action="store_true",
                    help="report requirements and candidate coverage, do not swap")
    ap.add_argument("--postures", default=None,
                    help="comma-separated <contest_id_or_name>=<posture> pairs, the "
                         "same vocabulary as build_slate.py --postures. A swap used "
                         "to stamp every entry large_wta regardless of what the "
                         "contest was, so a cash entry's high-floor build silently "
                         "became a ceiling build. A contest whose name matches no "
                         "archetype blocks until it is named here.")
    ap.add_argument("--accept-downgrade", action="store_true",
                    help="write the file even when a swapped entry scores below the "
                         "lineup it replaced under its own contest shape. Recorded "
                         "on stderr; there is no silent path.")
    ap.add_argument("--allow-parent-mismatch", action="store_true",
                    help="proceed when --parent-entries does not hash to the "
                         "promoted run's export (R20c blocks this by default, "
                         "because it means the latest promotion is not the "
                         "portfolio this file came from). The mismatch is "
                         "recorded either way.")
    ap.add_argument("--ignore-unresolved-postures", action="store_true",
                    help="proceed when a contest name matches no archetype, "
                         "accepting the fallback posture. Recorded on stderr.")
    ap.add_argument("--never-relax", dest="never_relax", action="append",
                    default=None, metavar="CONTROL[,CONTROL...]",
                    help="restate the parent build's --never-relax (R388(b)): a "
                         "feasibility floor does not raise these controls, so "
                         "the swap grades the portfolio against the caps the "
                         "build held. A name the swap cannot hold (the "
                         "consensus-cluster cap, which a swap does not enforce) "
                         "refuses before anything is read.")
    ap.add_argument("--controls-override", dest="controls_override", type=json.loads,
                    default=None,
                    help="JSON dict merged over the controls derived from this "
                         "file's own contest postures. A swap is certified "
                         "against the WHOLE delivered portfolio, not just the "
                         "authorized entries, so the untouched entries have to "
                         "satisfy these caps too. The derivation now matches the "
                         "build's, so this is only needed when the parent build "
                         "itself passed --controls-override (e.g. a thin slate) "
                         "and the run's own looser values have to be restated.")
    args = ap.parse_args()

    # R296(b), third site. `type=json.loads` accepts any JSON, so `[1,2]`, `5`
    # and `"x"` all parse and then reach `.get()` / `**` as an AttributeError or
    # TypeError at exit 1. build_slate.py had two of these; this is the third
    # and the worst, because this is the tool that runs closest to lock.
    if args.controls_override is not None and not isinstance(
            args.controls_override, dict):
        print(f"--controls-override takes a JSON OBJECT; got "
              f"{type(args.controls_override).__name__} "
              f"({json.dumps(args.controls_override)[:120]}). Nothing was read "
              f"and no swap was attempted.", file=sys.stderr)
        return 4
    # R388(b). The same resolver the build's flag uses, so the two accept the
    # same names; plus the one control the swap derives and then strips.
    from mlb_engine.pipeline.deadline_governor import resolve_never_relax  # noqa: PLC0415
    try:
        swap_never_relax = resolve_never_relax(args.never_relax)
    except ValueError as exc:
        print(f"{exc}. Nothing was read and no swap was attempted.",
              file=sys.stderr)
        return 4
    unheld = sorted(swap_never_relax & set(SWAP_UNENFORCED_CONTROLS))
    if unheld:
        print(f"--never-relax names {', '.join(unheld)}, which a late swap does "
              f"not enforce (R405: its bank holds no cluster-limited jobs), so "
              f"the swap cannot hold it. Nothing was read and no swap was "
              f"attempted.", file=sys.stderr)
        return 4

    slate = REPO / "data" / "slates" / args.date
    # R29(4): the salary path was hardcoded to the shared, date-keyed staged
    # name. On 2026-07-29 a concurrent Showdown build for the same date
    # overwrote it mid-swap, and every entry then failed with "embedded player
    # pool overlaps the salary file at 0.0%". With no flag to point elsewhere,
    # the only route around it was swapping staged files in and out around each
    # of the ~19 remaining calls. Once a run has tagged inputs, a swap should
    # never have to depend on the mutable staging path.
    #
    # R25: the feed path was hardcoded to the same shared per-slate cache, which
    # is as old as whatever wrote it; a swap blocked on hours-old TBD teams that
    # had long since posted. --lineups supplies a fresh feed without touching
    # the shared file other concurrent sessions read and write.
    salary, feed_path = resolve_swap_inputs(args.salary, args.lineups, slate)
    for path in (salary, feed_path, Path(args.parent_entries)):
        if not path.exists():
            print(f"missing input: {path}", file=sys.stderr)
            return 4
    for label, path, flag in (("salary", salary, "--salary"),
                              ("lineups feed", feed_path, "--lineups")):
        shared = path.resolve() == (slate / path.name).resolve()
        print(f"{label}: {path}"
              + ("  [SHARED staging path: a concurrent build for this date can "
                 f"overwrite it mid-swap; pass {flag} at a tagged copy to be "
                 "immune]" if shared else "  [explicit, not the shared staging "
                                          "path]"))

    # This is the tool that runs closest to lock and the one most likely to hit
    # a clobbered staged name. data/slates/<date>/ is keyed on date alone, so a
    # Showdown build for the same date can leave six-slot files at the bare
    # Classic names this script defaults to. Read the geometry before reading
    # anything else, and refuse rather than parse a Showdown file at row[4:14].
    try:
        assert_contest_geometry(salary, Path(args.parent_entries), declared="CLASSIC")
    except ValueError as exc:
        print(f"contest geometry: {exc}", file=sys.stderr)
        return 3

    now = dt.datetime.now(dt.timezone.utc)
    # R296(c). Unguarded until 2026-09-03, and this is the FOURTH door of the
    # class R213 closed in build_slate.main(): a torn `lineups_feed.json` is the
    # ordinary consequence of a killed Cowork call, and here it raised
    # JSONDecodeError past every handler -- exit 1, no `FEED BLOCKER` line, no
    # record, on the tool that runs closest to lock.
    #
    # It BLOCKS rather than degrading to `{"games": []}`, which is the opposite
    # of what `tools/solver_probe.py` does with the same absent file and is
    # deliberate: the probe is a timing instrument and a swap computes
    # locked-game exclusions from this feed. An empty feed there is not a
    # cheaper swap, it is a swap that believes no game has started.
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FEED BLOCKER: {feed_path} cannot be read or parsed "
              f"({type(exc).__name__}: {exc}). A swap derives its locked-game "
              f"exclusions from this feed, so an unreadable one is refused "
              f"rather than treated as empty. Re-fetch it, or pass --lineups at "
              f"a good copy. Nothing was swapped.", file=sys.stderr)
        return 3

    # F16: the feed was read from disk with no check that it describes this
    # slate or this hour. A swap is the one build that runs after lineups move,
    # so a feed for the wrong day is a wrong-slate build with locked-game
    # exclusions computed from the wrong games.
    feed_blockers, feed_warnings = _feed_age_report(feed, args.date, now)
    for warning in feed_warnings:
        print(f"feed: {warning}", file=sys.stderr)
    for blocker in feed_blockers:
        print(f"FEED BLOCKER: {blocker}", file=sys.stderr)
    if feed_blockers:
        return 3

    # F16: contest identity. build_entry_requirements defaults every entry to
    # 'large_wta' when no contest_shapes map is supplied, and this script never
    # supplied one, so a Double Up and a satellite were refined on the same
    # ceiling-max objective. Resolve identity the way the build does.
    reserved_rows = list(parse_dk_entry_rows(args.parent_entries))
    postures = _resolve_contest_postures(
        reserved_rows, _parse_postures(args.postures), None)
    unresolved = unresolved_contest_blockers(postures)
    for blocker in unresolved:
        label = ("POSTURE BLOCKER" if not args.ignore_unresolved_postures
                 else "POSTURE BLOCKER OVERRIDDEN by --ignore-unresolved-postures")
        print(f"{label}: {blocker}", file=sys.stderr)
    if unresolved and not args.ignore_unresolved_postures:
        return 3
    contest_shapes = {cid: str(rec["contest_shape"]) for cid, rec in postures.items()}
    for cid, rec in sorted(postures.items()):
        print(f"contest {cid} {rec['posture']} -> {rec['contest_shape']} "
              f"({rec['posture_source']})")

    status = build_status_map_from_lineups_feed(feed, str(salary))
    for dropped in status.get("doubleheader_legs_dropped") or []:
        print(f"doubleheader: dropped {dropped['game_id']} leg at "
              f"{dropped['start_utc']} ({dropped['reason']})")

    # A swap runs post-lock: confirmed lineups dominate the pool, and the
    # platoon reference only shapes projections for still-TBD teams. Blocking
    # a T-minus swap on that reference's age is the process preventing the
    # lineup (the same reasoning as FEED_AGE_WARN_MINUTES above), so the
    # staleness prints here instead of failing the gate.
    pool = build_slate_pool(str(salary), feed, stale_platoon_policy="warn")
    kwargs = pool["run_slate_kwargs"]
    if pool.get("platoon_source"):
        print(f"platoon fallback: {pool['platoon_source']}")
    for warning in pool["pool_report"].get("warnings") or []:
        print(f"pool: {warning}")
    for blocker in pool["pool_report"].get("blockers") or []:
        print(f"BLOCKER: {blocker}", file=sys.stderr)

    projections, _ = _assemble_projection_frame(
        str(salary), kwargs["projection_rows"], "emergency_proxy", None, None, None,
        projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
    )

    authorized = [e.strip() for e in args.entry_ids.split(",")] if args.entry_ids else None
    requirements = build_entry_requirements(
        args.parent_entries, status["status_by_player_id"], now, contest_shapes,
        mode="reoptimize", authorized_entry_ids=authorized,
        missing_status_policy="treat_as_locked",
    )

    cache_path = REPO / "runs" / f"bank_cache_{args.date}_{pool_signature(salary)}.json"
    cache = BankCache(cache_path)

    # R25: --budget is the TOTAL slicing budget. It used to be per
    # extend_bank call (one general plus one per pinned entry), so three
    # pinned entries cost four budgets before the joint solve ever began;
    # that is the timeout documented in
    # docs/backlog_inbox/2026-07-28_build_late-swap-times-out.md.
    slice_deadline = time.monotonic() + max(1.0, float(args.budget))

    def _slice_budget() -> float:
        return max(1.0, slice_deadline - time.monotonic())

    # A general bank covers entries with no locked slots. Entries that already hold
    # locked players need candidates built against those exact pins and against the
    # excluded-new-teams rule, or the allocator reports "no compatible candidate".
    report = extend_bank(cache, projections, time_budget_s=_slice_budget())
    print(f"bank after the general slice: {report['total_candidates']} candidates "
          f"(+{report['built_this_slice']} this slice, "
          f"{report['jobs_attempted']}/{report['jobs_total']} jobs)")
    if report["superseded_jobs_dropped"]:
        # R101: post-split this can only mean the PROJECTIONS moved since the
        # cache was written, or the file predates the conditions index. Either
        # way it is a purge, and it used to be indistinguishable from a sibling
        # slice quietly deleting the bank.
        print(f"  {report['superseded_jobs_dropped']} stored job(s) dropped: they "
              f"were built under a different projection digest than "
              f"{report['projection_digest']}")

    all_ids = {str(p) for p in projections["Player_ID"]}
    last_report = report
    parent_rosters = _load_entry_rosters(Path(args.parent_entries))
    for requirement in requirements:
        lsa = requirement.get("locked_slot_assignments") or {}
        if not lsa:
            continue
        team_by_id = requirement.get("player_team_by_id") or {}
        excluded_teams = set(requirement.get("excluded_new_teams") or [])
        # "No NEW player from a locked game" means the entry's own current players
        # are still allowed. The requirement dict carries no roster, so it comes
        # from the parent file. Reading it from the requirement instead yields an
        # empty set, which excludes the entry's own pinned players and makes every
        # solve infeasible.
        current = set(parent_rosters.get(requirement["entry_id"], []))
        current |= {str(pid) for pid in lsa.values()}
        excludes = [p for p in all_ids
                    if team_by_id.get(p) in excluded_teams and p not in current]
        slice_report = extend_bank(
            cache, projections, time_budget_s=_slice_budget(),
            locked_slot_assignments=lsa, excludes=excludes,
        )
        last_report = slice_report
        print(f"  entry {requirement['entry_id']}: pinned {sorted(lsa)}, "
              f"+{slice_report['built_this_slice']} targeted candidates "
              f"(bank now {slice_report['total_candidates']})")

    # R101. Before the conditions-signature split this number did not exist:
    # each targeted slice discarded the previous ones, so what the joint solve
    # received was whatever the LAST slice happened to leave behind, and the
    # `bank:` line above described a bank nothing downstream ever saw. Print the
    # union, and print the bucket count, because a bucket is a distinct
    # (excludes, stack bounds) question and their number is the shape of the
    # swap, not noise.
    print(f"bank the joint solve will see: {last_report['total_candidates']} "
          f"candidates across {last_report['conditions_buckets_live']} conditions "
          f"bucket(s), projection digest {last_report['projection_digest']}")

    # F16: scored, and scored in each contest's own shape. as_candidates() with
    # no projections carries roster and objective only: no stack-correlation
    # bonus, no batting-order cluster, and floor_sum reads 0.0, so the cash
    # branch could not tell a high-floor lineup from any other. The swap ranked
    # every candidate on raw objective and called the result a refinement.
    requested_shapes = sorted({str(r.get("contest_shape") or "") for r in requirements
                               if r.get("contest_shape")})
    candidates = cache.as_candidates(
        projections, requested_n=max(1, len(requirements)),
        contest_shapes=requested_shapes,
    )
    payload_report = cache.last_payload_report or {}
    # R101. `bank the joint solve will see: N` and this line's candidate count
    # are the same number now, and the two ways they can differ are both named
    # on this line rather than left for the operator to infer: a roster two
    # buckets both reached, and a candidate whose scoring raised.
    print(f"candidate scoring: {len(candidates)} candidates the solve receives, "
          f"{payload_report.get('scored')} scored, "
          f"{payload_report.get('scoring_failed')} failed, "
          f"{payload_report.get('duplicate_rosters_dropped')} duplicate roster(s) "
          f"collapsed across buckets, shapes {payload_report.get('shapes_scored')}")
    for reason, count in sorted((payload_report.get("scoring_failure_reasons") or {}).items()):
        print(f"  scoring failure x{count}: {reason}", file=sys.stderr)
    if args.dry_run:
        print(json.dumps({"entries": len(requirements),
                          "candidates": len(candidates),
                          "contest_shapes": contest_shapes,
                          "candidate_scoring": payload_report}, indent=1))
        return 0

    swap_stripped: dict = {}
    controls = resolve_swap_controls(
        postures, args.controls_override, args.solver_budget,
        requirements=requirements, projections=projections,
        stripped_out=swap_stripped, never_relax=swap_never_relax)
    if swap_stripped:
        print(f"consensus-cluster cap NOT enforced on a late swap (R405): stripped "
              f"{', '.join(f'{k}={v}' for k, v in sorted(swap_stripped.items()))} "
              f"from the derived controls. The swap's bank holds no "
              f"cluster-limited jobs and untouched rows may already exceed it; "
              f"the parent's cluster and the swapped file's are printed after "
              f"the solve. Enforcement is a rider on R284.", file=sys.stderr)
    # R29(3): print them. A cap that is invisible until it fails is a cap the
    # operator debugs by guessing, and last night that guess was "the bank is
    # thin" for twenty minutes. An empty set prints as such, because a swap that
    # enforces nothing (a cash-only portfolio) has to say so rather than look
    # like a line that failed to render.
    shown = ", ".join(f"{k}={v}" for k, v in sorted(controls.items())
                      if k != "time_limit")
    print("portfolio controls (derived from this file's postures and floored by "
          "slate feasibility, exactly as the build derives them): "
          + (shown or "none for these postures"))
    if args.controls_override:
        print(f"controls overridden by --controls-override: "
              f"{sorted(args.controls_override)}")
    print(f"joint solve next: {len(requirements)} entries, {len(candidates)} "
          f"candidates, time_limit {controls.get('time_limit', 30)}s (the swap "
          f"re-certifies the whole portfolio, so this stage runs over every "
          f"entry, not only the authorized ones)")

    result = run_late_swap(
        runs_root=str(REPO / "runs"),
        current_entries_csv=args.parent_entries,
        status_by_player_id=status["status_by_player_id"],
        as_of=now,
        contest_shapes=contest_shapes,
        salary_csv=str(salary),
        projections=projections,
        candidates=candidates,
        missing_status_policy="treat_as_locked",
        confirmed_order_by_player_id=status["confirmed_order_by_player_id"],
        confirmed_teams=status["confirmed_teams"],
        starter_player_ids=status["starter_player_ids"],
        authorized_entry_ids=authorized,
        allow_parent_mismatch=args.allow_parent_mismatch,
        workflow_gates={**WORKFLOW_GATES, **{g: True for g in LATE_SWAP_ASSUMED_GATES},
                        # Derived, not assumed: all three parsed above or this
                        # script would already have exited.
                        "salary_gate_passed": True,
                        "entry_grid_gate_passed": True,
                        "lineup_gate_passed": bool(status.get("confirmed_teams")),
                        },
        portfolio_controls=controls,
        # R29(2): the downgrade check below can still refuse this file, and a
        # refused run must not leave the latest-run pointer naming it. Promotion
        # happens after the mirror, at the bottom of this function.
        defer_promotion=True,
    )
    print("gates assumed by late swap (not checked): "
          + ", ".join(LATE_SWAP_ASSUMED_GATES), file=sys.stderr)

    if not result.get("passed"):
        print("late swap did not pass:", file=sys.stderr)
        refusal = result.get("allocation", {}).get("refusal") if isinstance(
            result.get("allocation"), dict) else None
        if refusal:
            print(f"refusal: {refusal}", file=sys.stderr)
        for line in classify_swap_failure(result.get("errors"), controls,
                                          bank_report=report):
            print(line, file=sys.stderr)
        return 3

    out = Path(result["output_path"])

    # F16: the swap had no incumbent-vs-chosen comparison at all. The only
    # signal that a lineup had been replaced by a worse one was verify_export's
    # `chg=6`. Score both rosters under the entry's own contest shape and print
    # the delta per changed entry; refuse a net downgrade unless it is asked
    # for. The run directory already exists at this point and stays as the
    # record; what a refusal withholds is the mirrored file, so nothing is
    # uploadable by accident.
    shape_by_entry = {str(r["entry_id"]): str(r.get("contest_shape") or "large_wta")
                      for r in requirements}
    after_rosters = _load_entry_rosters(out)
    downgraded: list[str] = []
    print("entry scores (incumbent -> chosen, in the entry's own contest shape):")
    for entry_id in sorted(shape_by_entry):
        before_ids = parent_rosters.get(entry_id) or []
        after_ids = after_rosters.get(entry_id) or []
        if before_ids == after_ids:
            continue
        shape = shape_by_entry[entry_id]
        before_score = _score_roster(projections, before_ids, shape)
        after_score = _score_roster(projections, after_ids, shape)
        if before_score is None or after_score is None:
            print(f"  {entry_id} [{shape}]: not comparable "
                  f"(a roster id is absent from the projection frame)")
            continue
        delta = after_score - before_score
        print(f"  {entry_id} [{shape}]: {before_score:.2f} -> {after_score:.2f} "
              f"({delta:+.2f})")
        if delta < 0:
            downgraded.append(f"{entry_id} [{shape}] {delta:+.2f}")
    if downgraded and not args.accept_downgrade:
        print("late swap refused: these entries score below the lineups they "
              "replaced:", file=sys.stderr)
        for line in downgraded:
            print(f"  {line}", file=sys.stderr)
        print(f"the run record is at {result.get('run_dir')}; nothing was "
              f"mirrored to outputs/ and the latest-run pointer still names the "
              f"last delivered run, so the next swap needs no override. Re-run "
              f"with --accept-downgrade to take it anyway (a forced swap off a "
              f"scratch is a legitimate downgrade).", file=sys.stderr)
        return 3
    if downgraded:
        print("downgrade accepted by --accept-downgrade: " + "; ".join(downgraded),
              file=sys.stderr)

    # R21: the fixed DKEntries_lateswap.csv silently overwrote the previous
    # swap and landed with no manifest row, which default preflight then
    # hard-fails. The name now carries the draftgroup tag and the swap run's
    # id, the write is staged then replaced, and the delivery is recorded so
    # "which file do I upload" stays one read of one file.
    dest_dir = REPO / "outputs" / args.date
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        slate_tag = _slate_tag(str(salary))
    except Exception:  # noqa: BLE001 - naming must never block the file
        slate_tag = ""
    dest = dest_dir / lateswap_dest_name(slate_tag, str(result.get("run_id") or ""))
    # R96(2). This wrote straight to `dest` and only recorded further down, past
    # the promotion decision -- so a refused promotion returned 3 with an
    # uploadable, unrecorded file sitting in outputs/. That is R29(2)'s window and
    # it is one of the six paths R96 enumerated. The file now lands provisionally
    # under DO_NOT_UPLOAD_ and is promoted only once a row exists, which keeps
    # R29(2)'s own invariant (the mirror exists BEFORE promotion, so a refusal
    # never leaves the pointer naming a run nothing was mirrored from) while
    # making the refusal path self-labelling.
    provisional = unrecorded_name(dest)
    tmp = provisional.with_name(f".{provisional.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(out.read_bytes())
    os.replace(tmp, provisional)

    # R29(2): the promotion held back at run_late_swap lands here, once this
    # file is genuinely a delivery. Promoting at certification time meant a
    # downgrade-refused run still owned the pointer with nothing in outputs/,
    # and the next swap then failed on a parent mismatch that reads like a
    # multi-session collision. The documented workaround was
    # --allow-parent-mismatch on every later call, which is switching off the
    # R20(c) protection because a bug taught the operator to distrust it.
    result = promote_deferred_run(result)
    if not result.get("promoted"):
        print("PROMOTION REFUSED after the file was written:", file=sys.stderr)
        for err in result.get("errors") or []:
            print(f"  {err}", file=sys.stderr)
        print(f"{provisional} holds the lineups and is deliberately named so "
              f"nobody uploads it: the latest-run pointer was not moved, so this "
              f"file is not the recorded delivery and it never got a manifest "
              f"row. Another session promoted while this swap was solving; "
              f"decide which portfolio is the delivery before uploading "
              f"anything.", file=sys.stderr)
        return 3
    print(f"gates: workflow_valid={result.get('workflow_valid')} "
          f"selection={result.get('selection_certified')} "
          f"allocation={result.get('allocation_certified')}")
    # R405. Reported, never enforced here (see `resolve_swap_controls`). The
    # parent's line is the build's own record; the swapped file's is the same
    # function over the swap's bank, so the two can differ in membership.
    print("consensus cluster, parent build: " + consensus_cluster_summary(
        parent_consensus_cluster(REPO / "runs", result.get("parent_run_id"))),
          file=sys.stderr)
    print("consensus cluster, swapped file (against the swap's bank, not "
          "enforced): " + consensus_cluster_summary(result.get("consensus_cluster")),
          file=sys.stderr)
    delivered_sha = ""
    delivered = provisional
    try:
        record = record_delivery(
            date=args.date, delivered_file=dest, hash_source=provisional,
            contest_type="classic",
            slate_tag=slate_tag, contest_ids=sorted(contest_shapes),
            entries=len(after_rosters), run_id=result.get("run_id"),
            status="candidate",
            certification=swap_certification(result, downgraded),
            projection_tier="proxy",  # the swap assembles emergency-proxy projections
            notes=f"late swap; parent {args.parent_entries}",
            # R377. The controls the joint solve ran under, and the one thing a
            # swap relaxes on its own authority: a downgrade taken anyway.
            controls=controls_for_report(
                {k: v for k, v in controls.items() if k != "time_limit"}),
            relaxations={"downgrades_accepted": len(downgraded)},
        )
        delivered_sha = str(record.get("sha256") or "")
        # R96(4): the swap had no salary staging at all, so a late-swapped slate
        # was mineable only if some other path happened to stage the same date.
        stage_salary_for_delivery(args.date, str(salary), slate_tag)
        # R96(2): promote the name only now that a row names it.
        os.replace(provisional, dest)
        delivered = dest
    except Exception as exc:  # noqa: BLE001 - bookkeeping must never block the file
        print(f"MANIFEST NOT RECORDED for {dest.name}: {exc}; the file was NOT "
              f"promoted and is at {provisional.name}, which names itself rather "
              f"than waiting for preflight to hard-fail it", file=sys.stderr)
    print(f"wrote {delivered}")
    if delivered_sha:
        print(f"delivered sha256: {delivered_sha}")
        print(f"verify at upload: tools/preflight_upload.py --entries {delivered} "
              f"--expect-sha256 {delivered_sha[:12]}")
    print("Upload by hand. Nothing here entered a contest or moved money.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
