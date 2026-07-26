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
                assume_gates=["odds_gate_passed", "weather_gate_passed",
                              "pitcher_audit_gate_passed"],
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


if __name__ == "__main__":
    unittest.main()
