"""Golden replay migration gate for the archived 2026-06-03 slate.

Phase 0 migration gate (CLAUDE.md "Authority"; MANIFEST.md "Still open").
Replays a real DraftKings salary export and a real BLANK reserved-entries
DKEntries file through ``mlb_engine.pipeline.execution_pipeline.run_slate``
-- the one production front door, per CLAUDE.md's "Authority" section --
exactly as a live build would call it, then asserts:

1. All three certification gates pass (``workflow_valid``,
   ``selection_certified``, ``allocation_certified``), both on the
   ``run_slate`` return value and on the persisted ``diagnostics.json``.
2. A normalized allocation summary -- entry-to-lineup assignments, a
   player exposure summary, and the SP pair distribution -- is stable
   against a frozen baseline under ``tests/golden/``.

Nothing else in the migration plan proceeds until this test is green
twice in a row from a clean checkout.

Anchor slate history: the guide's original prompt named 2026-06-29;
that slate's DKSalaries CSV and DKEntries file are gone, only the
post-slate mined JSONs and ownership CSV survived, and those are not
run_slate inputs. A 2026-06-28 file Ben found next turned out to be a
record of already-submitted lineups, not a blank reserved-entries
template, so run_initial_build correctly refused every entry as
"already complete and immutable" -- the right guardrail, wrong file
type, and not fixable by filtering the player pool. 2026-06-03 is
anchored instead: Ben supplied DKSalaries.csv, a genuinely BLANK
DKEntries.csv (18 reserved entries across 3 real contests, every roster
cell empty), and contest-standings-191020573.csv. Files copied to
data/archive/2026-06-03/ as DKSalaries_2026-06-03.csv,
DKEntries_2026-06-03.csv, and standings_191020573.csv (the standings
file is not a run_slate input; it is kept for a future post-slate
archival pass per CLAUDE.md's "Post-slate" section, not used here).

Design note on the projection source: the archive has no live lineups
feed / platoon JSON that fed the confirmed-pool intake front door
(``live_data_adapters.build_slate_pool``) on the day of the actual
build -- that feed is transient market data and was never designated
for archival (see docs/cowork_archival_runbook.md). So this replay
builds ``projection_rows`` directly from the salary file's own
``AvgPointsPerGame`` column for every hitter, plus the documented
``emergency_proxy`` mode (projection_builder v1.4) -- a real, labeled,
deterministic path through the same front door, just without the
confirmed/TBD pool filter.

Design note on pitcher filtering (load-bearing, not cosmetic): the raw
salary file lists every SP-eligible pitcher on each team's active
roster (9-11 per team here), not just that day's probable starter,
because the real filter for that is live_data_adapters.build_slate_pool
with declared_pitchers, which this replay does not have. Feeding all of
them to the optimizer blew up: build_diverse_candidate_bank enumerates
every viable SP PAIR to guarantee bank coverage, an O(n^2) cost in
distinct SPs, and 41 unfiltered SPs across 4 teams made a single
candidate-bank build run 40+ seconds without finishing. Capping each
team to its top 2 SPs by salary (a proxy for "the probable starter plus
one emergency alternate") cut that to ~8 SPs and the whole build to
under 10 seconds. This is a real, separate finding worth tracking on
its own, independent of migration status: build_diverse_candidate_bank
does not scale gracefully to a full, unfiltered salary file, which the
existing tiny synthetic fixtures in test_core.py would never surface.

Design note on requested_n and portfolio controls: run_slate's default
requested_n (one candidate lineup per reserved entry) still timed out
even against the SP-capped pool, because the joint allocation MILP
across 3 differently-shaped contests needs either more distinct
candidates or looser exposure caps to find a feasible assignment inside
a reasonable solve time, and asking for more candidates is itself the
expensive step. requested_n=8 with loosened portfolio_controls_override
(the same LOOSE-style caps test_core.py's own fixtures use, permitting
candidate reuse across entries) resolved this in under 10 seconds with
all three gates passing. Reusing one strong lineup across multiple
reserved entries in the same or adjacent contests is a normal, legal
multi-entry strategy, not a shortcut; this is a documented, exposed
run_slate parameter, not an undocumented workaround.

Baseline history. A frozen baseline is re-frozen only on evidence, and this
one has moved once:

  2026-09-03, R293(a). `build_diverse_candidate_bank`'s augmentation skip was
  reversed -- it excluded the SP pair's OWN teams, so it attempted the opponent
  stacks the anti-correlation rows bar and never attempted the legal own-team
  stack. Fixing the direction changes which (pair, team) jobs the pass spends
  its budget on, so the order candidates are appended in changes, so the
  candidate_id numbering changes. Isolated by reverting that ONE edit with the
  rest of R293 in place: the baseline came back GREEN, so nothing else in the
  item moves a k=0 build. Measured before re-freezing, and it is why the
  re-freeze is a numbering change and not a portfolio change: the DELIVERED
  PORTFOLIO is identical -- the same 8 distinct lineups, the same multiset of
  18 rosters, byte-identical `exposure_summary`, byte-identical
  `sp_pair_distribution`, and the same entry-to-contest mapping. What moved is
  which entry holds which of the same lineups (14 of 18 permuted, all within
  their own contest). `golden_replay_production_2026-06-03.json` did not move
  at all. All three gates pass on the new run, and legality needs no separate
  check: an identical roster multiset cannot contain a construction the frozen
  one did not.

Every diagnostic this test touches is a deterministic review proxy or an
observed outcome -- never a win-rate, ROI, or probability claim.
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv, validate_salary_schema
from mlb_engine.pipeline.execution_pipeline import run_slate

REPO_ROOT = Path(__file__).resolve().parents[1]
SLATE_DATE = "2026-06-03"
ARCHIVE_DIR = REPO_ROOT / "data" / "archive" / SLATE_DATE
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
GOLDEN_PATH = GOLDEN_DIR / f"golden_replay_{SLATE_DATE}.json"

ENTRIES_HEADER_PREFIX = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]
TOP_SP_PER_TEAM = 2
REQUESTED_N = 8
LOOSE_CONTROLS = {
    "max_player_exposure_pct": 1.0,
    "max_pitcher_exposure_pct": 1.0,
    "max_primary_stack_exposure_pct": 1.0,
    # R343 (CC-2), 2026-09-15. The fourth exposure ceiling joins the three
    # above it at 1.0, and the reason is this dict's own name: the loose replay
    # exists to hold the CAPS out of the way so the baseline measures the front
    # door's construction. A new cap arriving at its posture default would
    # quietly change what this gate is a gate on. Opened here, the frozen
    # baseline is byte-identical across CC-2, which is the evidence that the
    # item moves nothing except where a cap is actually asked for -- the
    # production replay below runs the posture default and DOES move.
    "max_team_exposure_pct": 1.0,
    # R405, 2026-09-23, for the same reason as the team cap above: the loose
    # replay holds the caps out of the way. Opened here, the cap also asks the
    # direct bank for no cluster-limited jobs, so the loose baseline measures
    # the construction it always measured and does not move.
    "max_consensus_cluster_share_pct": 1.0,
    # R406, 2026-09-23. Sleeves OFF here, for the same reason: they are a
    # portfolio-shaping choice (Ben's default ON), and the loose replay exists
    # to measure the front door's construction with the shaping held out of the
    # way. Off, the loose baseline is byte-identical across R406; the
    # production replay below runs them and re-freezes.
    "classic_sleeves": False,
    "max_sp_pair_repetition": 50,
    "max_shared_players": 9,
    "max_candidate_reuse": 20,
}


def _read_header(path: Path) -> List[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])


def _find_archive_inputs(archive_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Content-sniff the archive dir for the DK salary export and the
    DKEntries reserved-entries file, independent of filename convention.

    Matches the real parsers' own validation (dk_entries_manager's exact
    4-column header check; slate_intake_manager's validate_salary_schema)
    rather than guessing from a filename pattern.
    """
    salary_csv: Optional[Path] = None
    entries_csv: Optional[Path] = None
    for path in sorted(archive_dir.glob("*.csv")):
        header = _read_header(path)
        if not header:
            continue
        if [c.strip() for c in header[:4]] == ENTRIES_HEADER_PREFIX:
            entries_csv = path
            continue
        if validate_salary_schema(str(path)).get("passed"):
            salary_csv = path
    return salary_csv, entries_csv


def _projection_rows_from_salary_csv(salary_csv: Path) -> List[Dict[str, Any]]:
    """Per-player rows for the emergency-proxy path.

    Only Player_ID + Base are supplied; Team/Position/Game_ID/Opponent are
    re-derived authoritatively from the salary file during assembly
    (execution_pipeline._assemble_projection_frame). Base is DK's own
    AvgPointsPerGame. Hitters: every rostered player with a positive
    average. Pitchers: capped at the top TOP_SP_PER_TEAM by salary per
    team -- see the module docstring's pitcher-filtering note for why
    this is load-bearing, not cosmetic.
    """
    sp_by_team: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    rows: List[Dict[str, Any]] = []
    for player in parse_dk_salary_csv(str(salary_csv)):
        avg = player.raw.get("AvgPointsPerGame") or player.raw.get("Avg Points Per Game")
        try:
            base = float(avg)
        except (TypeError, ValueError):
            continue
        if base <= 0:
            continue
        row = {"Player_ID": player.player_id, "Base": base, "_salary": player.salary}
        if player.raw.get("Position") == "SP":
            sp_by_team[player.team].append(row)
        elif player.raw.get("Position") == "RP":
            continue  # relief pitchers are never probable starters; excluded like real production would
        else:
            rows.append(row)
    for team_rows in sp_by_team.values():
        team_rows.sort(key=lambda r: -r["_salary"])
        rows.extend(team_rows[:TOP_SP_PER_TEAM])
    for row in rows:
        row.pop("_salary", None)
    return rows


def _normalize_ids(raw: str) -> Tuple[str, ...]:
    return tuple(sorted(x for x in (raw or "").split("/") if x))


def _summarize_allocation(assignments_path: Path) -> Dict[str, Any]:
    """Derive the stable, run-id-independent allocation summary this gate
    freezes and diffs: entry-to-lineup assignments, player exposure, and
    SP pair distribution.

    Built from assignments.csv rather than the raw diagnostics.json
    because diagnostics.json embeds a fresh run_id, run_dir, and absolute
    paths on every single run, even when the underlying selection is
    byte-for-byte identical.
    """
    with assignments_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assignment_rows: List[Dict[str, Any]] = []
    exposure: Counter[str] = Counter()
    sp_pairs: Counter[str] = Counter()

    for row in rows:
        lineup_ids = _normalize_ids(row.get("lineup_ids", ""))
        sp_ids = _normalize_ids(row.get("sp_ids", ""))
        assignment_rows.append({
            "entry_id": row.get("entry_id", ""),
            "contest_id": row.get("contest_id", ""),
            "contest_shape": row.get("contest_shape", ""),
            "candidate_id": row.get("candidate_id", ""),
            "lineup_signature": row.get("lineup_signature", ""),
            "primary_stack": row.get("primary_stack", ""),
            "lineup_ids": list(lineup_ids),
            "sp_ids": list(sp_ids),
        })
        exposure.update(lineup_ids)
        if sp_ids:
            sp_pairs["+".join(sp_ids)] += 1

    assignment_rows.sort(key=lambda r: (r["contest_id"], r["entry_id"]))

    return {
        "entry_count": len(assignment_rows),
        "assignments": assignment_rows,
        "exposure_summary": dict(sorted(exposure.items())),
        "sp_pair_distribution": dict(sorted(sp_pairs.items())),
    }


class GoldenReplayTests(unittest.TestCase):
    """Phase 0 migration gate: replay the archived 2026-06-03 slate."""

    salary_csv: Path
    entries_csv: Path

    @classmethod
    def setUpClass(cls) -> None:
        if not ARCHIVE_DIR.exists():
            raise unittest.SkipTest(f"data/archive/{SLATE_DATE}/ does not exist; nothing to replay")

        salary_csv, entries_csv = _find_archive_inputs(ARCHIVE_DIR)
        missing = []
        if salary_csv is None:
            missing.append("a DraftKings salary export CSV (Position/Name+ID/Salary/TeamAbbrev columns)")
        if entries_csv is None:
            missing.append(
                "the DKEntries reserved-entries CSV (header starting "
                "'Entry ID, Contest Name, Contest ID, Entry Fee')"
            )
        if missing:
            found = sorted(p.name for p in ARCHIVE_DIR.iterdir())
            raise unittest.SkipTest(
                f"data/archive/{SLATE_DATE}/ is missing " + " and ".join(missing) + ". "
                f"copy the real {SLATE_DATE} DKSalaries CSV and a BLANK DKEntries file "
                f"into data/archive/{SLATE_DATE}/ and re-run. Currently in that folder: {found}"
            )
        cls.salary_csv = salary_csv
        cls.entries_csv = entries_csv

    def test_front_door_certifies_and_matches_golden_baseline(self) -> None:
        projection_rows = _projection_rows_from_salary_csv(self.salary_csv)
        self.assertTrue(projection_rows, "no usable AvgPointsPerGame rows found on the archived salary CSV")

        with tempfile.TemporaryDirectory() as tmp:
            runs_root = Path(tmp) / "runs"

            # Mirror the real per-slate loop (CLAUDE.md): review the checkpoint
            # plan before the certified build.
            plan = run_slate(
                runs_root=runs_root,
                salary_csv=self.salary_csv,
                entries_csv=self.entries_csv,
                projection_rows=projection_rows,
                projection_mode="emergency_proxy",
                requested_n=REQUESTED_N,
                portfolio_controls_override=LOOSE_CONTROLS,
                approve=False,
            )
            self.assertTrue(plan["passed"], plan.get("errors"))
            self.assertEqual(plan["status"], "plan_pending_approval")
            self.assertFalse((runs_root).exists(), "approve=False must not create a run directory")

            result = run_slate(
                runs_root=runs_root,
                salary_csv=self.salary_csv,
                entries_csv=self.entries_csv,
                projection_rows=projection_rows,
                projection_mode="emergency_proxy",
                requested_n=REQUESTED_N,
                portfolio_controls_override=LOOSE_CONTROLS,
                approve=True,
                # This replay supplies no odds map, no weather map, and no
                # pitcher_roles, so those three gates have no evidence behind
                # them (F4). Assuming them explicitly keeps the replay's subject
                # the certified byte output rather than the gate axis, and the
                # assumption is recorded in the run's diagnostics.
                #
                # lineup_gate_passed joined them on 2026-08-04 (R53). This is an
                # emergency_proxy replay: the rows carry Player_ID and Base only,
                # so no row carries a batting order and no pool_report is passed.
                # The gate used to read the truthiness of a summary dict that is
                # always truthy and certified anyway, with "4 players carry a
                # batting order" as its recorded evidence. It now reports no
                # evidence, and no evidence blocks -- so the replay has to state
                # the assumption like the other three.
                assume_gates=["odds_gate_passed", "weather_gate_passed",
                              "pitcher_audit_gate_passed", "lineup_gate_passed"],
            )

            self.assertTrue(result["passed"], result.get("errors"))
            self.assertTrue(result["workflow_valid"], "workflow_valid gate failed")
            self.assertTrue(result["selection_certified"], "selection_certified gate failed")
            self.assertTrue(result["allocation_certified"], "allocation_certified gate failed")

            diagnostics_path = Path(result["diagnostics_path"])
            self.assertTrue(diagnostics_path.exists(), "diagnostics.json was not written")
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            for gate in ("workflow_valid", "selection_certified", "allocation_certified"):
                self.assertTrue(diagnostics.get(gate), f"diagnostics.json {gate} is not true")

            summary = _summarize_allocation(Path(result["assignments_path"]))
            summary["slate_date"] = SLATE_DATE
            summary["certification"] = {
                "workflow_valid": True, "selection_certified": True, "allocation_certified": True,
            }
            summary["source"] = {"salary_csv": self.salary_csv.name, "entries_csv": self.entries_csv.name}

            if not GOLDEN_PATH.exists():
                GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
                GOLDEN_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                self.fail(
                    f"No golden baseline existed at {GOLDEN_PATH}; froze this run as the new "
                    "baseline (expected on the first run ever). Re-run this test now -- it "
                    "must come back green against what was just written -- then commit the "
                    "baseline file."
                )

            baseline = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
            self.assertEqual(
                summary, baseline,
                f"allocation diagnostics drifted from the frozen golden baseline at {GOLDEN_PATH}: "
                "entry-to-lineup assignments, exposure summary, or SP pair distribution changed "
                "for an unchanged input slate.",
            )


PRODUCTION_GOLDEN_PATH = GOLDEN_DIR / f"golden_replay_production_{SLATE_DATE}.json"
ENRICHMENT_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "enrichment"
PRODUCTION_POSTURES = {
    "191020573": "wta_satellite", "191020574": "wta_satellite", "191047506": "large_gpp",
}
# The one recorded operator action that makes this thin archived grid certify
# under otherwise-untouched production controls (see the class docstring). One
# key, one notch: the satellite/large_gpp merge resolves player exposure to
# 0.40, and 0.40 x 18 entries floors to 7 appearances against a 4-game bank
# whose rosters cannot avoid overlapping that hard. 0.50 is the first rung
# that certifies; pitcher (0.43), stack (0.35), shared-players, and pair caps
# all stay at their production-merged values and all visibly bind in the
# frozen assignment (exposure_max is exactly 9 = 0.50 x 18; no SP pair
# appears more than twice).
PRODUCTION_CERT_OVERRIDE = {"max_player_exposure_pct": 0.5}


class GoldenProductionReplayTests(unittest.TestCase):
    """R6(b): the production-controls, real-enrichment golden gate.

    The loose replay above proves the front door still certifies and its bytes
    are stable, but it runs LOOSE_CONTROLS and no enrichment inputs, so the
    enrichment stack and the portfolio controls sit outside the one
    end-to-end gate. This class closes that gap with two scenarios over the
    same archived 2026-06-03 slate, the same live-built candidate bank, and
    the same frozen enrichment fixtures:

    1. PURE: explicit production postures (the Quick Card forbids trusting
       name inference), zero overrides. Until 2026-09-23 the engine PROVED
       this grid jointly infeasible: R5's satellite caps against the 30-
       candidate bank failed on control interaction, not on any single cap,
       and the checkpoint's pool-keyed feasibility arithmetic could not see it
       (floors key on pool counts; the interaction lives in the bank). R405(c)
       added the cluster-limited bucket production now builds, the bank grew
       to 58 distinct lineups, and the same grid CERTIFIES -- bank growth doing
       what R98(2) says it does first. Whichever verdict the grid gets, error
       text included, is frozen. If caps, floors, the allocator, or the bank
       builder change behavior, this baseline moves and says so. The
       checkpoint-green-then-build-infeasible disagreement stays pinned as an
       AGREEMENT between the plan and the build (R28), whichever way the grid
       resolves.

    2. CERTIFIED: the same run plus the minimal recorded operator action the
       thin-slate contract prescribes ("explicit overrides win", surfaced in
       controls_feasibility): PRODUCTION_CERT_OVERRIDE, one key one notch.
       Everything else is production-merged and binds in the output. All
       three gates pass and the allocation is frozen with aggregates and
       assignment asserted SEPARATELY, so a drift report names the layer
       that moved.

    Enrichment is real and live: the frozen Savant/FanGraphs fixture CSVs
    join through the same DK-keyed crosswalks production uses, the xwOBA
    correction applies (projection rows carry AvgPointsPerGame exactly so it
    can), xISO and K-rate land on Ceiling, and the value guard clips. The
    fixture copies are frozen because data/reference/ refreshes between
    sessions and a golden gate may not read moving inputs.

    The bank is built in-test through the sliced production path
    (bank_cache.extend_bank), which exhausts this pool's 64 (SP pair, stack
    team) jobs in about a second where the joint auto-bank path needs
    minutes. job_list_exhausted is asserted, so a slow box fails loudly
    rather than silently freezing a partial bank; solver determinism across
    machines is backed by requirements.lock pinning scipy (R7).

    Total cost is a few seconds, which is what lets this run inside the
    session-start audit macro's one-call budget.
    """

    payload: Dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        GoldenReplayTests.setUpClass()
        cls.salary_csv = GoldenReplayTests.salary_csv
        cls.entries_csv = GoldenReplayTests.entries_csv
        for name in ("expected_stats_batting_frozen_2026-07-25.csv",
                     "expected_stats_pitching_frozen_2026-07-25.csv",
                     "fangraphs_season_pitching_frozen_2026-07-16.csv"):
            if not (ENRICHMENT_FIXTURES / name).exists():
                raise unittest.SkipTest(f"enrichment fixture missing: {name}")

        from mlb_engine.optimize.bank_cache import BankCache, extend_bank
        from mlb_engine.pipeline.execution_pipeline import _assemble_projection_frame

        rows = _projection_rows_from_salary_csv(cls.salary_csv)
        for r in rows:
            # The xwOBA correction is applied to AvgPointsPerGame (base_in) and
            # writes Base (base_out); rows that carry only Base leave the
            # correction structurally inert, which is exactly the silent no-op
            # this gate exists to catch.
            #
            # Base MOVES to AvgPointsPerGame rather than being copied to it
            # (R57). The production intake front door, live_data_adapters._pool_row,
            # emits AvgPointsPerGame and no Base at all; Base is derived from it
            # during assembly. A row carrying BOTH is an operator-supplied Base,
            # which the correction is no longer allowed to overwrite, so copying
            # made this replay silently stop exercising the enrichment it exists
            # to pin. Same numbers either way -- the baseline does not move.
            r["AvgPointsPerGame"] = r.pop("Base")
        enr = dict(
            savant_batting_csv=ENRICHMENT_FIXTURES / "expected_stats_batting_frozen_2026-07-25.csv",
            savant_pitching_csv=ENRICHMENT_FIXTURES / "expected_stats_pitching_frozen_2026-07-25.csv",
            fangraphs_pitching_csv=ENRICHMENT_FIXTURES / "fangraphs_season_pitching_frozen_2026-07-16.csv",
        )
        projections, _ = _assemble_projection_frame(
            salary_csv=cls.salary_csv, projection_rows=[dict(r) for r in rows],
            projection_mode="emergency_proxy", source_metadata=None, **enr)

        with tempfile.TemporaryDirectory() as tmp:
            cache = BankCache(Path(tmp) / "bank.json")
            report = extend_bank(cache, projections, time_budget_s=60)
            assert report["job_list_exhausted"], (
                "the sliced bank build did not exhaust its job list inside the "
                f"budget; freezing a partial bank would freeze noise: {report}")
            # R405(c), 2026-09-23. The production sliced door now builds a
            # cluster-limited bucket after the ordinary one whenever the merged
            # posture controls carry a consensus cap below 1.0, and these
            # postures do (0.50). The bank here mirrors that door -- the same
            # derivation, the same candidate ceiling build_slate uses -- because
            # a production gate over a bank production no longer builds would
            # freeze a question no build asks. Exhaustion is asserted for the
            # reason above.
            from mlb_engine.pipeline.execution_pipeline import (
                _merged_controls_for_build, _resolve_contest_postures,
                build_consensus_limited_jobs, resolve_consensus_limited_request)
            from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
            _rows = parse_dk_entry_rows(str(cls.entries_csv))
            _postures = _resolve_contest_postures(_rows, PRODUCTION_POSTURES, None)
            _n = len(_rows)
            # R415. build_slate's cap now comes from the host; the golden pins
            # Cowork's 130s budget so it is the same on every host, and that is
            # exactly the `max(_n * 12, 60)` this line used to spell out.
            from mlb_engine.repo_env import BANK_REFERENCE_BUDGET_S, bank_max_candidates
            _total_max = bank_max_candidates(_n, budget_s=BANK_REFERENCE_BUDGET_S)
            consensus_request = resolve_consensus_limited_request(
                _merged_controls_for_build(_postures, None), _n, _total_max)
            assert consensus_request["active"], consensus_request
            limited = build_consensus_limited_jobs(
                cache, projections, consensus_request, time_budget_s=60,
                max_candidates=_total_max)
            assert (limited.get("report") or {}).get("job_list_exhausted"), (
                f"the cluster-limited bucket did not exhaust: {limited}")
            # R406, 2026-09-23. The sliced door then builds the sleeves (Ben's
            # default ON): chalk-fails and environment in this cache, salary-
            # only in a sibling cache, each sized to twice its entries. Mirrored
            # here with the same request and the same helper. On this two-game
            # slate the environment sleeve is DROPPED (its top two games are the
            # whole slate), which the frozen aggregates record.
            from mlb_engine.allocate.contest_allocator import consensus_cluster_members
            from mlb_engine.optimize.classic_sleeves import environment_teams_of, tag_sleeves
            from mlb_engine.pipeline.execution_pipeline import (
                build_sleeve_jobs, resolve_sleeve_bank_request, sleeve_candidates)
            _sleeve_entries = [
                {"entry_id": str(r.entry_id), "contest_id": str(r.contest_id),
                 "posture": _postures[str(r.contest_id)]["posture"],
                 "contest_shape": _postures[str(r.contest_id)]["contest_shape"]}
                for r in _rows]
            sleeve_request = resolve_sleeve_bank_request(_sleeve_entries, {}, projections)
            assert sleeve_request["active"], sleeve_request
            salary_cache = BankCache(Path(tmp) / "bank_salary_only.json")
            sleeve_jobs = build_sleeve_jobs(
                cache, projections, sleeve_request,
                consensus_members=consensus_cluster_members(
                    cache.as_candidates(None))["member_ids"],
                time_budget_s=60, salary_cache=salary_cache)
            candidates = tag_sleeves(cache.as_candidates(
                projections, requested_n=18,
                contest_shapes=["satellite", "large_field_gpp"]),
                environment_teams_of(sleeve_request))
            candidates += sleeve_candidates(
                cache, salary_cache, projections, requested_n=18,
                contest_shapes=["satellite", "large_field_gpp"], base=candidates)

            common = dict(
                salary_csv=cls.salary_csv, entries_csv=cls.entries_csv,
                projection_mode="emergency_proxy",
                contest_postures=PRODUCTION_POSTURES,
                candidates_override=candidates,
                # lineup_gate_passed: same reason as GoldenReplayTests above --
                # emergency_proxy rows carry no batting order, so R53's gate has
                # nothing to verify and says so instead of certifying vacuously.
                assume_gates=["odds_gate_passed", "weather_gate_passed",
                              "pitcher_audit_gate_passed",
                              "lineup_gate_passed"], **enr)

            pure = run_slate(runs_root=Path(tmp) / "runs_pure",
                             projection_rows=[dict(r) for r in rows],
                             approve=True, **common)
            plan = run_slate(runs_root=Path(tmp) / "runs_plan",
                             projection_rows=[dict(r) for r in rows],
                             portfolio_controls_override=PRODUCTION_CERT_OVERRIDE,
                             approve=False, **common)
            # R28(1): the same grid at approve=False with NO override, which is
            # the sequence the item is about -- checkpoint-green at review,
            # proven-infeasible at approve. The plan verdict now has to name it.
            pure_plan_root = Path(tmp) / "runs_pure_plan"
            pure_plan = run_slate(runs_root=pure_plan_root,
                                  projection_rows=[dict(r) for r in rows],
                                  approve=False, **common)
            cls.pure_plan_root_exists = pure_plan_root.exists()
            cls.pure_plan_joint = pure_plan.get("joint_allocation") or {}
            cls.cert_plan_joint = plan.get("joint_allocation") or {}
            cert = run_slate(runs_root=Path(tmp) / "runs_cert",
                             projection_rows=[dict(r) for r in rows],
                             portfolio_controls_override=PRODUCTION_CERT_OVERRIDE,
                             approve=True, **common)

            cls.pure_result = {"passed": pure.get("passed"), "errors": list(pure.get("errors") or [])}
            cls.plan_passed = bool(plan.get("passed"))
            cls.cert_result = cert
            cls.cert_gates = {g: cert.get(g) for g in (
                "workflow_valid", "selection_certified", "allocation_certified")}
            summary = _summarize_allocation(Path(cert["assignments_path"]))
            diag = json.loads(Path(cert["diagnostics_path"]).read_text(encoding="utf-8"))
            pe = diag.get("projection_enrichment") or {}
            cls.payload = {
                "meta": {
                    "slate_date": SLATE_DATE,
                    "postures": PRODUCTION_POSTURES,
                    "cert_override": PRODUCTION_CERT_OVERRIDE,
                    "source": {"salary_csv": cls.salary_csv.name,
                               "entries_csv": cls.entries_csv.name},
                },
                "pure_verdict": cls.pure_result,
                "aggregates": {
                    "bank": {
                        "candidates": len(candidates),
                        "jobs_total": report["jobs_total"],
                        "conditions_signature": report["conditions_signature"],
                        # R405(c). The limited bucket, beside the ordinary one.
                        "consensus_limited": {
                            "built": limited["report"].get("built_this_slice"),
                            "conditions_signature":
                                limited["report"].get("conditions_signature"),
                            "cluster_members": limited.get("cluster_members"),
                            "m": limited.get("m"),
                        },
                        # R406. What each sleeve built, and the one dropped.
                        "classic_sleeves": {
                            "expected_entries": sleeve_request["expected_entries"],
                            "dropped": sleeve_request["dropped"],
                            "built": {k: v.get("built") for k, v in
                                      sorted((sleeve_jobs.get("sleeves") or {}).items())},
                        },
                    },
                    "enrichment": {
                        "xwoba_applied": (pe.get("xwoba") or {}).get("applied"),
                        "xwoba_non_neutral": (pe.get("xwoba") or {}).get("non_neutral_applied"),
                        "ceiling_differentiated": (pe.get("ceiling") or {}).get("differentiated_rows"),
                        "pitcher_ceiling_differentiated": (pe.get("pitcher_ceiling") or {}).get("differentiated_rows"),
                        "value_guard_clipped": (pe.get("value_guard") or {}).get("clipped_count"),
                    },
                    "entry_count": summary["entry_count"],
                    "exposure_summary": summary["exposure_summary"],
                    "sp_pair_distribution": summary["sp_pair_distribution"],
                    # R405. The cap's realized shape is frozen with the rest, so
                    # a drift in who the consensus is or how many entries carry
                    # it names this layer rather than surfacing as moved rows.
                    "consensus_cluster": {
                        k: (cert.get("consensus_cluster") or {}).get(k)
                        for k in ("status", "count", "min_members_k",
                                  "source_lineups",
                                  "delivered_member_count_histogram",
                                  "delivered_at_k_or_more")
                    } | {"member_ids": [
                        m.get("player_id") for m in
                        ((cert.get("consensus_cluster") or {}).get("members") or [])]},
                    # R406. How the allocator seated the entries across sleeves,
                    # and how many fell back.
                    "classic_sleeves": {
                        k: (cert.get("classic_sleeves") or {}).get(k)
                        for k in ("status", "entries_by_sleeve", "candidates_by_sleeve",
                                  "relaxations")
                    },
                },
                "assignments": summary["assignments"],
            }

    @classmethod
    def _baseline(cls) -> Dict[str, Any]:
        if not PRODUCTION_GOLDEN_PATH.exists():
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            PRODUCTION_GOLDEN_PATH.write_text(
                json.dumps(cls.payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            raise AssertionError(
                f"No production golden baseline existed at {PRODUCTION_GOLDEN_PATH}; froze "
                "this run as the new baseline (expected on the first run ever). Re-run now "
                "-- it must come back green -- then commit the baseline file.")
        return json.loads(PRODUCTION_GOLDEN_PATH.read_text(encoding="utf-8"))

    def test_certified_scenario_passes_all_three_gates(self) -> None:
        self.assertTrue(self.plan_passed, "approve=False checkpoint did not pass")
        for gate, value in self.cert_gates.items():
            self.assertTrue(value, f"{gate} is not true on the certified scenario")

    def test_pure_production_postures_verdict_is_pinned(self) -> None:
        """The frozen refusal is a property of THIS BANK, not of this grid.

        Read carefully before quoting this baseline as a claim about the engine.
        R28 was written around "today's engine cannot certify the archived
        18-entry, three-contest grid", which was measured here and is true only
        of the 30-candidate sliced bank this replay freezes. Through the build
        path's larger auto-bank the same grid CERTIFIES (build_slate, clean
        tree, 3 of 3 runs, ~26s, 2026-07-29; eval 0 pins it at exit 0). Both
        facts are real and they do not conflict: the caps bind against a small
        bank and clear against a big one, which is exactly why R28(1) made the
        approve=False checkpoint solve the bank it actually has instead of
        inferring feasibility from pool arithmetic.
        """
        baseline = self._baseline()
        self.assertEqual(
            {"passed": self.pure_result["passed"], "errors": self.pure_result["errors"]},
            baseline["pure_verdict"],
            "the PURE production-postures verdict moved: either caps/floors/"
            "allocator behavior drifted, or the sliced bank this replay builds "
            "changed size (investigate before touching the baseline). Note this "
            "pins the sliced-bank verdict only; the auto-bank path certifies "
            "this same grid, which is not a contradiction.")

    def test_aggregates_match_baseline(self) -> None:
        baseline = self._baseline()
        self.assertEqual(
            self.payload["aggregates"], baseline["aggregates"],
            "production-replay AGGREGATES drifted (bank composition, enrichment "
            "counters, exposure summary, or SP-pair distribution) for an "
            "unchanged input slate.")

    def test_assignment_matches_baseline(self) -> None:
        baseline = self._baseline()
        self.assertEqual(
            self.payload["assignments"], baseline["assignments"],
            "production-replay ASSIGNMENT drifted: entry-to-lineup mapping "
            "changed for an unchanged input slate while aggregates may still "
            "match; this is the selection/allocation layer moving on its own.")

    # ------------------------------------------------------------------
    # R28(1): the checkpoint predicts the build, or says it did not check
    # ------------------------------------------------------------------

    def test_plan_verdict_and_build_verdict_agree_on_the_pure_grid(self) -> None:
        """The item's headline case, pinned as an agreement rather than a value.

        Before R28(1) this grid was checkpoint-green and approve-infeasible.
        The plan solves the build's own candidates here, so agreement is exact
        and any divergence is a real regression, not fixture noise.

        R405(c), 2026-09-23: this asserted the refusal VALUE as well, which was
        a property of the 30-candidate bank rather than of the agreement. With
        the cluster-limited bucket the bank holds 58 distinct lineups and the
        pure grid certifies, so the test now pins both directions of the one
        thing it exists for: a refusal the plan predicts with the same sentence,
        or a certification the plan predicts as `would_certify`. The frozen
        `pure_verdict` in the baseline still pins which of the two it is.
        """
        joint = self.pure_plan_joint
        if self.pure_result["passed"]:
            self.assertEqual(joint.get("verdict"), "would_certify",
                             f"the PURE build certified while the plan said: {joint}")
            self.assertEqual(joint.get("errors"), [])
            return
        self.assertEqual(joint.get("verdict"), "proven_infeasible",
                         f"the plan no longer predicts the PURE grid's refusal: {joint}")
        self.assertEqual(
            joint.get("errors"), self.pure_result["errors"],
            "the plan's proven-infeasible text drifted from the error the build "
            "actually raises; the checkpoint is only worth its budget while the "
            "two are the same sentence.")

    def test_plan_verdict_and_build_verdict_agree_on_the_certified_grid(self) -> None:
        joint = self.cert_plan_joint
        self.assertEqual(joint.get("verdict"), "would_certify",
                         f"the plan no longer predicts the certified grid: {joint}")
        self.assertEqual(joint.get("errors"), [])
        self.assertTrue(self.cert_gates["allocation_certified"],
                        "the build did not certify allocation while the plan said it would")

    def test_the_plan_solve_is_exact_and_names_itself_so(self) -> None:
        """Both scenarios hand in candidates_override, so the plan solves the
        build's own bank and must not claim more or less than that."""
        for label, joint in (("pure", self.pure_plan_joint), ("cert", self.cert_plan_joint)):
            with self.subTest(scenario=label):
                self.assertTrue(joint.get("exact_for_this_build"), joint)
                self.assertEqual(joint.get("bank_source"), "candidates_override", joint)
                self.assertTrue(joint.get("summary"), "a verdict with no summary is silence")

    def test_approve_false_still_creates_no_run_directory(self) -> None:
        """The plan solve is speculative and must stay side-effect free; a run
        directory at approve=False would make a review indistinguishable from a
        build in runs/."""
        self.assertFalse(self.pure_plan_root_exists,
                         "approve=False created a runs root")


if __name__ == "__main__":
    unittest.main()
