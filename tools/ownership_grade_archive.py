#!/usr/bin/env python3
"""ownership_grade_archive.py -- grade the ownership prior over the ARCHIVE (R306).

WHY THIS IS A TOOL AND NOT A RUNBOOK STEP. `ownership_pred.py grade` has
existed since R135 and grades ONE contest against ONE prediction file, given a
salary file and an archetype the operator supplies by hand. The R306 filing
found the consequence on disk: `grep -rn "Ownership prior grade" ledger/`
returns zero blocks, one grade has ever been run, and its result lives in a
module docstring. The constraint was never sample count -- 27 archive dates and
379 mined contests are sitting there -- it is that nothing's loop calls
`grade`. A runbook step would have the same property a runbook step had for the
last six weeks: it is a thing a session must remember. So the loop is a tool,
it resolves its own inputs, and it writes fragments a later ARCHIVE session
merges.

WHAT IT DOES NOT DO. It writes nothing under `ledger/` itself. Only ARCHIVE
edits the ledger (CLAUDE.md's multi-session contract), so this drops fragments
in `ledger/inbox/` and the owning role merges them. It touches no control, no
posture and no optimizer input; it reads the archive and measures error.

THE SAVED-PREDICTION PATH (R342(b1), `--saved`). The default path above rebuilds
each prediction with TODAY's code, scores only the players DK listed in a contest
(the zero tail never reaches the join), and passes no odds. The 2026-09-14 research
graded the files BUILD saved before first pitch instead. `--saved` is that grade:
it reads `outputs/*/ownership_pred_*.json`, says which file a contest used and why
(identity, pre-lock, salary-file sha256), never calls `build_prediction`, scores
every row of the saved prediction with 0.0 for a player nobody rostered, spreads the
flat baseline over those same rows, and reads the odds state off the saved file.
It reports two universes side by side, the whole salary file and a pool proxy scored
after R342(a)'s own rescale, and replays the pre-registered challenger on held-out
dates. The inputs are gitignored: it runs where BUILD saved them (benbook).

TRUTHFUL LABELS. Every number this emits is an observed count from an archived
DK standings export, or a deterministic statistic over one. A Spearman here is
a rank correlation between two measured shares. Nothing is a win rate, a cash
rate, an ROI figure, an edge, or a probability claim, and one contest never
moves a prior.

CONDITIONING. The ledger requires archetype and field-size conditioning and
forbids pooling across them. Every measurement below is per contest; the only
cross-contest figures are MEDIANS OF PER-CONTEST STATISTICS inside one
archetype and one field-size band, labelled as such, and never a statistic
recomputed over a merged player set.

    python tools/ownership_grade_archive.py --out ledger/inbox
    python tools/ownership_grade_archive.py --contest 193621098 --stdout
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

VERSION = "v1.1"

# Field-size bands. Two of the three boundaries are READ from the allocator
# rather than restated, so the banding cannot drift into a fourth vocabulary
# for contest size. The first cut hardcoded them and got MID_FIELD_MAX_ENTRANTS
# wrong (2000, written as 5000); its own test caught it, which is the argument
# for importing the constant instead of quoting it.
#
# The 100 boundary IS added here, and the reason is the self-inclusion caveat
# rather than tidiness: the archive's Showdown fields run from 20 entries up,
# Ben's own entries sit in the denominator of every one of them, and a
# 20-entry satellite banded with a 500-entry contest hides exactly the bias the
# caveat is about.
SMALL_FIELD_BAND_MAX = 100


def _field_bands() -> Tuple[Tuple[str, int, int], ...]:
    from mlb_engine.allocate.contest_allocator import (
        MID_FIELD_MAX_ENTRANTS, SMALL_FIELD_MAX_ENTRANTS,
    )
    edges = sorted({SMALL_FIELD_BAND_MAX, int(SMALL_FIELD_MAX_ENTRANTS),
                    int(MID_FIELD_MAX_ENTRANTS)})
    bands, low = [], 1
    for edge in edges:
        bands.append((f"f_{low:04d}_{edge:04d}", low, edge))
        low = edge + 1
    bands.append((f"f_{low:04d}_plus", low, 10 ** 9))
    return tuple(bands)


FIELD_BANDS: Tuple[Tuple[str, int, int], ...] = _field_bands()


def field_band(size: Optional[int]) -> str:
    if size is None:
        return "f_unknown"
    for label, low, high in FIELD_BANDS:
        if low <= int(size) <= high:
            return label
    return "f_unknown"


def contest_names_on_disk(root: Path = REPO_ROOT) -> Dict[str, str]:
    """{Contest ID: Contest Name} from every DKEntries file on disk.

    An archived contest carries no name: the standings export has none and the
    mined file stores none. The DKEntries files Ben downloaded to enter do, and
    the join is on the 9-digit Contest ID, exact, never inferred. This is the
    only way an archived contest gets an archetype at all, and a contest whose
    name is not on disk is REFUSED rather than defaulted.
    """
    names: Dict[str, str] = {}
    patterns = ("outputs/*/DKEntries*.csv", "data/slates/*/DKEntries*.csv",
                "runs/*/inputs/DKEntries*.csv", "runs/*/final/DKEntries*.csv")
    for pattern in patterns:
        for path in sorted(glob.glob(str(Path(root) / pattern))):
            try:
                with open(path, encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        cid = str(row.get("Contest ID") or "").strip()
                        name = str(row.get("Contest Name") or "").strip()
                        if name and cid.isdigit() and len(cid) == 9:
                            names.setdefault(cid, name)
            except (OSError, csv.Error):
                continue
    return names


def salary_candidates(slate_date: str, root: Path = REPO_ROOT) -> List[str]:
    out: set = set()
    for pattern in (f"data/slates/{slate_date}/DKSalaries*.csv",
                    f"runs/*{slate_date}*/inputs/DKSalaries*.csv",
                    f"outputs/{slate_date}/DKSalaries*.csv"):
        out.update(glob.glob(str(Path(root) / pattern)))
    return sorted(out)


def _field_size(blob: Mapping[str, Any]) -> Tuple[Optional[int], str]:
    """(field size, which fact answered). Never a guess, and never silent.

    ``own_results.field_size`` is the contest's own recorded size and is
    preferred. It is absent on 19 archived contests, and the first cut of this
    tool refused all 19 with a message blaming the CONTEST TYPE -- the type
    resolved fine, the size was missing, and an operator reading that refusal
    would go and edit the shape map. That is the R290(c) failure mode (a
    refusal that names the wrong cause costs the reader the time it takes to
    disprove it), so the fallback and the message are both fixed here.

    The fallback is ``meta.entries_total`` on a mined record whose coverage is
    ``full``: a full standings export lists every entry, so its entry count IS
    the field size. On a partial export it is not, and that case gets no
    fallback and a refusal that says which fact is missing.
    """
    raw = (blob.get("own_results") or {}).get("field_size")
    try:
        if raw is not None:
            return int(raw), "own_results.field_size"
    except (TypeError, ValueError):
        pass
    if str(blob.get("coverage") or "") == "full":
        total = (blob.get("meta") or {}).get("entries_total")
        try:
            if total is not None and int(total) > 0:
                return int(total), "meta.entries_total (coverage=full)"
        except (TypeError, ValueError):
            pass
    return None, "unavailable"


def resolve_archetype(name: str, field_size: Optional[int]
                      ) -> Tuple[Optional[str], str, str]:
    """(archetype, exactness, reason) for one archived contest, or a refusal.

    Two existing definitions, chained, and no third one minted here:
    ``contest_library.infer_from_name`` turns a DK contest name into an
    inferred contest TYPE, and ``ownership_prior.archetype_for_contest_facts``
    turns that type plus the field size into the prior's archetype through the
    allocator's own shape logic.
    """
    from mlb_engine.field.contest_library import (
        infer_from_name, load_archetype_rows,
    )
    from mlb_engine.field.ownership_prior import archetype_for_contest_facts

    rows = load_archetype_rows()
    if not rows:
        return None, "", "data/reference/dk_contest_archetypes.csv is missing"
    hit = infer_from_name(name, rows)
    if not hit:
        return None, "", f"no archetype pattern matches the contest name {name!r}"
    ctype = str(hit.get("inferred_type") or "")
    # Which fact is missing, said plainly. `archetype_for_contest_facts`
    # returns None for an unknown type AND for an unusable field size, and one
    # message covering both sends a reader to edit the shape map when the shape
    # map is fine.
    if field_size is None or int(field_size) <= 0:
        return None, "", (
            f"the archived record carries no usable field size, so the "
            f"contest type {ctype!r} (resolved fine, from the name) cannot be "
            "narrowed to an archetype; the shape map is not the problem")
    resolved = archetype_for_contest_facts(
        ctype, field_size, hit.get("inferred_max_entries") or 1)
    if not resolved:
        return None, "", (f"contest type {ctype!r} (from the name) resolves to no "
                          "archetype at field size {0}; add it to the shape map "
                          "or record the contest's real type".format(field_size))
    return resolved[0], resolved[1], ""


def mined_contests(only: Optional[str] = None,
                   root: Path = REPO_ROOT) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(Path(root).glob("data/archive/*/mined_*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cid = str(blob.get("contest_id") or "")
        if only and cid != str(only):
            continue
        out.append({"path": path, "contest_id": cid,
                    "contest_type": str(blob.get("contest_type") or ""),
                    "slate_date": str(blob.get("slate_date") or ""),
                    "blob": blob})
    return out


def grade_one(record: Mapping[str, Any], names: Mapping[str, str]) -> Dict[str, Any]:
    """Grade one archived contest. Never raises; a refusal is a returned reason."""
    from mlb_engine.field.field_miner import parse_standings_export, resolve_salary_file
    from ownership_pred import (
        actuals_from_standings, build_prediction, captain_actuals_from_entries,
        grade_captain_prediction, grade_prediction,
    )

    cid = record["contest_id"]
    out: Dict[str, Any] = {"contest_id": cid, "slate_date": record["slate_date"],
                           "contest_type": record["contest_type"]}
    blob = record["blob"]
    field_size, size_source = _field_size(blob)
    out["field_size"] = field_size
    out["field_size_source"] = size_source
    out["field_band"] = field_band(field_size)

    name = names.get(cid)
    if not name:
        out["refused"] = "no DKEntries row on disk carries this Contest ID, so "\
                         "the contest has no name and therefore no archetype"
        return out
    out["contest_name"] = name
    archetype, exactness, why = resolve_archetype(name, field_size)
    if not archetype:
        out["refused"] = why
        return out
    out["archetype"], out["archetype_exactness"] = archetype, exactness

    hits = list(REPO_ROOT.glob(f"data/archive/*/contest-standings-{cid}.csv"))
    if not hits:
        out["refused"] = "no standings export on disk for this contest"
        return out
    standings_path = hits[0]
    parsed = parse_standings_export(str(standings_path))

    pick = resolve_salary_file(parsed, salary_candidates(record["slate_date"]))
    if not pick.get("path"):
        out["refused"] = f"no salary file resolved: {pick.get('reason')}"
        return out
    out["salary_file"] = str(Path(pick["path"]).name)

    try:
        prediction = build_prediction(pick["path"], slate_tag=f"archive_{cid}",
                                      slate_date=record["slate_date"],
                                      archetypes=[archetype])
    except ValueError as exc:
        out["refused"] = f"prediction refused: {exc}"
        return out
    inputs = prediction.get("inputs") or {}
    out["inputs_applied"] = sorted(
        key for key in ("batting_order", "implied_totals", "probable_sp",
                        "base_projection")
        if (inputs.get(key) or {}).get("applied"))
    out["inputs_inert"] = sorted(
        key for key in ("batting_order", "implied_totals", "probable_sp",
                        "base_projection")
        if not (inputs.get(key) or {}).get("applied"))

    actual, meta = actuals_from_standings(str(standings_path))
    if not actual:
        out["refused"] = "the standings export yielded no complete lineups to recompute ownership from"
        return out
    try:
        grade = grade_prediction(prediction, actual, archetype,
                                 contest_id=cid, field_size=field_size)
    except ValueError as exc:
        out["refused"] = f"grade refused: {exc}"
        return out
    grade["standings"] = meta
    out["roster_grade"] = grade

    # R306 step 3. The captain market, on Showdown contests only.
    markets = (prediction.get("showdown_markets") or {}).get("applied")
    if record["contest_type"] == "showdown" and markets:
        crosswalk = ((prediction.get("crosswalk") or {})
                     .get("name_norm_to_player_id") or {})
        pool = [str(r["Player_ID"]) for r in (prediction.get("players") or [])]
        entries = blob.get("entries") or []
        cap_actual, cap_meta = captain_actuals_from_entries(entries, crosswalk, pool)
        if cap_meta["complete_entries"] >= 10:
            out["captain_actuals"] = cap_meta
            for market in ("captain", "showdown_roster"):
                if market == "captain":
                    measured = cap_actual
                else:
                    measured = _person_actuals_from_entries(entries, crosswalk, pool)
                try:
                    out[f"{market}_grade"] = grade_captain_prediction(
                        prediction, measured, archetype, contest_id=cid,
                        field_size=field_size, market=market)
                except ValueError as exc:
                    out[f"{market}_grade_refused"] = str(exc)
        else:
            out["captain_skipped"] = (
                f"only {cap_meta['complete_entries']} complete entries carry a "
                "captain; below the 10 this measurement needs")
    return out


def _person_actuals_from_entries(
    entries: Sequence[Mapping[str, Any]],
    crosswalk: Mapping[str, str],
    pool_player_ids: Sequence[str],
) -> Dict[str, float]:
    """{Player_ID: realized six-slot person %}, zero-filled over the pool.

    Counted off ``players_norm`` for the same reason ``captain_norm`` is
    counted off entries rather than read from DK's table: the export's
    right-hand block is truncated, and a market that must sum to 600% cannot be
    measured from a truncated list. The zero tail is included, per the pool
    argument in ``captain_actuals_from_entries``.
    """
    complete = [e for e in entries if e.get("lineup_complete")]
    counts: Dict[str, int] = {}
    for entry in complete:
        for norm in (entry.get("players_norm") or []):
            counts[str(norm)] = counts.get(str(norm), 0) + 1
    n = len(complete)
    actual = {str(pid): 0.0 for pid in sorted({str(p) for p in pool_player_ids})}
    for norm in sorted(counts):
        pid = crosswalk.get(norm)
        if pid is not None and str(pid) in actual:
            actual[str(pid)] = round(100.0 * counts[norm] / n, 4) if n else 0.0
    return actual


def _median(values: Sequence[float]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None]
    return round(statistics.median(clean), 3) if clean else None


def _cell(grade: Optional[Mapping[str, Any]], key: str) -> Optional[float]:
    if not grade:
        return None
    return (grade.get("overall") or {}).get(key)


def archetype_fragment(archetype: str, results: Sequence[Mapping[str, Any]],
                       today: str) -> str:
    """One inbox note for one archetype. Per contest; medians labelled as such."""
    lines = [
        f"# Ownership prior grade | archetype `{archetype}` | "
        f"{len(results)} archived contest(s)",
        "",
        f"Filed {today} by DEV (R306 step 1), from "
        "`tools/ownership_grade_archive.py`. ARCHIVE merges into the "
        "calibration ledger.",
        "",
        "Every row is ONE contest measured on its own. Nothing below is pooled "
        "across contests: the summary lines are MEDIANS OF PER-CONTEST "
        "STATISTICS within one archetype and one field-size band, never a "
        "statistic recomputed over a merged player set. Every figure is an "
        "observed count from an archived DK standings export or a "
        "deterministic statistic over one; the Spearman is a rank correlation "
        "between two measured shares. Nothing here is a win rate, a cash rate, "
        "an ROI figure, an edge, or a probability claim, and one contest never "
        "moves a prior.",
        "",
        "**Self-inclusion caveat, carried forward.** Ben's own entries sit in "
        "the denominator of every contest he entered, and the small fields "
        "here are where that bites hardest. A larger sample dilutes the bias "
        "and does not remove it, and a four-figure field is a different "
        "archetype rather than a bigger version of a small one -- which is "
        "what the field-size banding is for.",
        "",
    ]
    for band, _low, _high in FIELD_BANDS + (("f_unknown", 0, 0),):
        rows = [r for r in results if r.get("field_band") == band]
        if not rows:
            continue
        lines += [f"## Field band `{band}` -- {len(rows)} contest(s)", "",
                  "| contest | date | field | Spearman | mean signed err (pts) "
                  "| MAE (pts) | joined | beats flat-budget | tilts inert |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda x: str(x.get("contest_id"))):
            g = r.get("roster_grade") or {}
            overall = g.get("overall") or {}
            join = g.get("join") or {}
            verdict = g.get("verdict") or {}
            lines.append(
                f"| `{r['contest_id']}` | {r.get('slate_date')} "
                f"| {r.get('field_size')} "
                f"| {overall.get('spearman_rank_corr')} "
                f"| {overall.get('mean_signed_error_pct_points')} "
                f"| {overall.get('mae_pct_points')} "
                f"| {join.get('joined_players')} "
                f"| {verdict.get('beats_flat_budget')} "
                f"| {', '.join(r.get('inputs_inert') or []) or 'none'} |")
        rho = _median([_cell(r.get("roster_grade"), "spearman_rank_corr")
                       for r in rows])
        signed = _median([_cell(r.get("roster_grade"),
                                "mean_signed_error_pct_points") for r in rows])
        mae = _median([_cell(r.get("roster_grade"), "mae_pct_points")
                       for r in rows])
        beat = sum(1 for r in rows
                   if ((r.get("roster_grade") or {}).get("verdict") or {})
                   .get("beats_flat_budget"))
        lines += [
            "",
            f"- Median of the per-contest Spearmans in this band: **{rho}** "
            f"(n={len(rows)} contests).",
            f"- Median of the per-contest mean signed errors: **{signed}** "
            f"points. Positive means the prior OVER-predicts the level.",
            f"- Median of the per-contest MAEs: {mae} points. Beats a "
            f"flat-budget allocation in {beat} of {len(rows)}.",
            "",
        ]
    return "\n".join(lines) + "\n"


def captain_fragment(results: Sequence[Mapping[str, Any]], today: str) -> str:
    rows = [r for r in results if r.get("captain_grade")]
    lines = [
        "# Showdown captain and roster market grade | "
        f"{len(rows)} archived contest(s)",
        "",
        f"Filed {today} by DEV (R306 steps 2-3), from "
        "`tools/ownership_grade_archive.py`. ARCHIVE merges into the "
        "calibration ledger.",
        "",
        "Two distributions over the same collapsed people, each against its "
        "own realized shares, per contest and never pooled. `captain` is the "
        "100% one-slot market counted off `entries[].captain_norm`; "
        "`roster` is the 600% six-slot market counted off "
        "`entries[].players_norm`. Both include the ZERO TAIL: on a Showdown "
        "slate the salary file is the contest's player pool, so a player "
        "nobody captained has an observed share of 0.0, and dropping those "
        "truncates the sample at the end the prior is most likely to get "
        "wrong. Each Spearman is a rank correlation between two measured "
        "shares over one contest. Nothing here is a win rate, a cash rate, an "
        "ROI figure, an edge, or a probability claim.",
        "",
        "**The signed error column is near zero BY CONSTRUCTION here, and it is "
        "not evidence the level is right.** Both the prior and the realized "
        "shares allocate the same budget (100% or 600%) over the same "
        "zero-filled pool, so their means are equal and the mean signed error "
        "is an accounting identity rather than a measurement. It is printed "
        "because its ABSENCE would mean a player left the pool between the "
        "softmax and the join. Read MAE and the Spearman instead; and note "
        "that the Classic figures in the sibling fragments do NOT have this "
        "property, because that join drops players DK listed without a share.",
        "",
        "**Self-inclusion caveat, carried forward.** Ben's own entries sit in "
        "these denominators, most heavily in the smallest fields.",
        "",
        "| contest | date | field | archetype | cpt rho | cpt signed | "
        "cpt MAE | roster rho | roster signed | distinct cpts | zero-cpt |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda x: (int(x.get("field_size") or 0),
                                         str(x.get("contest_id")))):
        cap, ros = r.get("captain_grade") or {}, r.get("showdown_roster_grade") or {}
        meta = r.get("captain_actuals") or {}
        co, ro = cap.get("overall") or {}, ros.get("overall") or {}
        lines.append(
            f"| `{r['contest_id']}` | {r.get('slate_date')} "
            f"| {r.get('field_size')} | {r.get('archetype')} "
            f"| {co.get('spearman_rank_corr')} "
            f"| {co.get('mean_signed_error_pct_points')} "
            f"| {co.get('mae_pct_points')} "
            f"| {ro.get('spearman_rank_corr')} "
            f"| {ro.get('mean_signed_error_pct_points')} "
            f"| {meta.get('distinct_captains')} "
            f"| {meta.get('zero_captain_players')} |")
    lines.append("")
    for band, _low, _high in FIELD_BANDS:
        in_band = [r for r in rows if r.get("field_band") == band]
        if not in_band:
            continue
        lines.append(
            f"- `{band}` ({len(in_band)} contests): median per-contest captain "
            f"Spearman **{_median([_cell(r['captain_grade'], 'spearman_rank_corr') for r in in_band])}**, "
            f"median captain signed error "
            f"**{_median([_cell(r['captain_grade'], 'mean_signed_error_pct_points') for r in in_band])}** pts; "
            f"median roster Spearman "
            f"{_median([_cell(r.get('showdown_roster_grade'), 'spearman_rank_corr') for r in in_band])}, "
            f"median roster signed error "
            f"{_median([_cell(r.get('showdown_roster_grade'), 'mean_signed_error_pct_points') for r in in_band])} pts.")
    lines += [
        "",
        "Medians are medians OF PER-CONTEST STATISTICS inside one field band, "
        "never a statistic recomputed over a merged player set.",
        "",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# R342(b1): grade the SAVED pre-lock prediction, never a rebuild
# ---------------------------------------------------------------------------
#
# `grade_one` rebuilds each prediction with TODAY's code (`build_prediction`),
# scores only the players DK listed in a contest (the zero tail drops out of the
# join), spreads its flat baseline over the whole salary file but scores it on
# the joined rows only, and passes no odds. The 2026-09-14 research
# (outputs/standings_research_2026-09-14, analysis_spec.md: "Do not reconstruct
# predictions from today's code. Include zero-actual players.") graded the files
# BUILD saved before first pitch instead. This path is that grade, as a tool: it
# reads `outputs/*/ownership_pred_*.json`, says which file a contest used and why,
# and never calls `build_prediction`.

SAVED_SCHEMA = "ownership_grade_saved/v1"
SAVED_PREDICTION_SCHEMA = "ownership_pred/v1"

# The 2026-09-14 pre-registered challenger, frozen as filed (analysis_spec.md,
# "Challenger diagnostic"): saved shares raised to an exponent, multiplied by a
# factor when the player has no recorded pre-lock role, renormalized to the
# 800-hitter and 200-pitcher budgets with 100% marginal caps. The first 60% of
# the calendar dates train (complete-pool MAE, equal date weighting), the rest
# are held out. It tests missing concentration and role attention, never roster
# availability, and four held-out dates are too few for a promotion claim.
CHALLENGER_EXPONENTS = (0.75, 1.0, 1.5, 2.0, 3.0)
CHALLENGER_FACTORS = (0.05, 0.10, 0.25, 1.00)
CHALLENGER_TRAIN_FRACTION = 0.6

# Prediction bins for the calibration read (predicted share, percentage points).
CALIBRATION_BINS = ((0.0, 1.0), (1.0, 5.0), (5.0, 10.0), (10.0, 20.0),
                    (20.0, 100.0001))

# A prediction's rows are 2dp and the budget sums carry that rounding.
BUDGET_TOLERANCE_PER_ROW = 0.005

SAVED_METRICS = ("mae", "rostered_mae", "calibration_gap", "top10_recall")


def load_saved_predictions(root: Path = REPO_ROOT) -> Dict[str, List[Dict[str, Any]]]:
    """{slate_date: [saved prediction, ...]} from `outputs/*/ownership_pred_*.json`.

    Indexed by the file's OWN ``slate_date``, not its folder, because the folder
    is where BUILD happened to write it. Each payload gains ``_source`` (the
    repo-relative path) and ``_file_sha256`` (the bytes on disk now), so a grade
    can say which file it read and prove the file is the one it graded.
    """
    import hashlib

    index: Dict[str, List[Dict[str, Any]]] = {}
    root = Path(root)
    for path in sorted(root.glob("outputs/*/ownership_pred_*.json")):
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("schema") != SAVED_PREDICTION_SCHEMA:
            continue
        payload["_source"] = path.relative_to(root).as_posix()
        payload["_file_sha256"] = hashlib.sha256(raw).hexdigest()
        index.setdefault(str(payload.get("slate_date") or ""), []).append(payload)
    return index


def salary_identity(salary_path: str) -> Dict[str, Any]:
    """The contest's own salary snapshot, reduced to what a saved file must match.

    ``by_norm`` is {normalized name: {(Player_ID, salary, team), ...}}; a name that
    carries two identities on one slate is ambiguous and can match nothing.
    ``first_game_utc`` is the earliest Game Info start (the slate's first lock),
    read through the intake's own ``parse_game_info_datetime``.
    """
    import hashlib
    from datetime import timezone

    from mlb_engine.field.field_miner import normalize_name
    from mlb_engine.intake.slate_intake_manager import (
        parse_dk_salary_csv, parse_game_info_datetime,
    )

    raw = Path(salary_path).read_bytes()
    by_norm: Dict[str, set] = {}
    starts = []
    for player in parse_dk_salary_csv(str(salary_path)):
        by_norm.setdefault(normalize_name(player.name), set()).add(
            (str(player.player_id), float(player.salary),
             str(player.team).strip().upper()))
        when = parse_game_info_datetime(player.game_info)
        if when is not None:
            starts.append(when.astimezone(timezone.utc))
    return {"path": str(salary_path), "sha256": hashlib.sha256(raw).hexdigest(),
            "by_norm": by_norm,
            "first_game_utc": min(starts).isoformat() if starts else None}


def _parse_utc(text: Any):
    from datetime import datetime, timezone

    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def match_saved_prediction(
    contest_names: Sequence[str],
    identity: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[Mapping[str, Any]], List[Dict[str, Any]]]:
    """(chosen saved prediction or None, every candidate considered and why).

    The research's rule (``reproduce/ownership.py``). A candidate is eligible
    when every name the contest's complete lineups roster appears in the saved
    file exactly once with the salary file's own Player_ID and salary (and team,
    when the saved row names one). Among the eligible, prefer a file saved BEFORE
    the slate's first game, then one whose recorded salary-file sha256 equals
    this salary file's, then the latest ``generated_utc``. The caller refuses a
    chosen file that was saved after lock.
    """
    from mlb_engine.field.field_miner import normalize_name

    first_start = _parse_utc(identity.get("first_game_utc"))
    considered: List[Dict[str, Any]] = []
    eligible: List[Tuple[Tuple[bool, bool, str], Mapping[str, Any], Dict[str, Any]]] = []
    for pred in candidates:
        rows_by_norm: Dict[str, List[Mapping[str, Any]]] = {}
        for row in pred.get("players") or []:
            rows_by_norm.setdefault(normalize_name(row.get("Name", "")), []).append(row)
        problem = ""
        for name in sorted(contest_names):
            rows = rows_by_norm.get(name) or []
            ids = identity["by_norm"].get(name) or set()
            if len(rows) != 1 or len(ids) != 1:
                problem = f"{name!r} is not one identity in both files"
                break
            row = rows[0]
            pid, salary, team = next(iter(ids))
            if (str(row.get("Player_ID")) != pid
                    or float(row.get("salary") or 0.0) != salary
                    or (row.get("team") and str(row["team"]).strip().upper() != team)):
                problem = f"{name!r} differs in Player_ID, salary or team"
                break
        generated = str(pred.get("generated_utc") or "")
        generated_dt = _parse_utc(generated) if generated else None
        checkable = bool(generated_dt and first_start)
        prelock = bool(checkable and generated_dt < first_start)
        sha_match = ((pred.get("salary_file") or {}).get("sha256")
                     == identity.get("sha256"))
        info = {"source": pred.get("_source"), "file_sha256": pred.get("_file_sha256"),
                "generated_utc": generated or None,
                "first_game_utc": identity.get("first_game_utc"),
                "prelock": prelock, "prelock_checkable": checkable,
                "salary_sha256_match": bool(sha_match),
                "identity_ok": not problem, "identity_problem": problem or None}
        considered.append(info)
        if not problem:
            eligible.append(((prelock, bool(sha_match), generated), pred, info))
    if not eligible:
        return None, considered
    eligible.sort(key=lambda item: item[0], reverse=True)
    chosen = eligible[0][1]
    for info in considered:
        info["chosen"] = info["source"] == chosen.get("_source")
    return chosen, considered


def rostered_shares_exact(entries: Sequence[Mapping[str, Any]]) -> Tuple[Dict[str, float], int]:
    """({normalized name: % of complete lineups rostering the player}, n), UNROUNDED.

    ``field_miner.rostered_by_player_norm`` is the definition and rounds to 2dp.
    That rounding turns a 0.004% share into 0.00 (a rostered player reading as
    unrostered) and ties the small shares a rank correlation then cannot order:
    on 194075378 it moved the rostered-player MAE by 0.22 and the Spearman by
    0.05 against the research's unrounded counts. This counts the same lineups
    the same way and keeps the precision; a test pins the two to each other at 2dp.
    """
    from collections import Counter

    counts: Counter = Counter()
    n = 0
    for entry in entries or []:
        if not entry.get("lineup_complete"):
            continue
        n += 1
        for name in set(entry.get("players_norm") or ()):
            counts[str(name)] += 1
    if not n:
        return {}, 0
    return {name: 100.0 * c / n for name, c in sorted(counts.items())}, n


def saved_pool_rows(prediction: Mapping[str, Any], archetype: str,
                    shares: Mapping[str, float]) -> List[Dict[str, Any]]:
    """One row per player of the SAVED prediction, zero tail included.

    The universe is the prediction's own ``own_pct_by_player_id`` for the
    archetype (every salary-file row, bench included), and ``actual`` is the
    contest's measured share with 0.0 for a player no complete lineup rostered.
    ``rostered`` is membership in the share map, never ``actual > 0``.
    ``role_known`` is the research's: an arm carries a probable flag, a bat a
    batting-order slot, recorded before lock.
    """
    from mlb_engine.field.field_miner import normalize_name

    own = prediction["archetypes"][archetype]["own_pct_by_player_id"]
    rows = []
    for player in prediction.get("players") or []:
        pid = str(player["Player_ID"])
        if pid not in own:
            continue
        norm = normalize_name(player.get("Name", ""))
        features = player.get("features") or {}
        pool = str(player.get("pool"))
        role_known = (bool(features.get("probable_sp")) if pool == "pitcher"
                      else features.get("batting_order") is not None)
        rows.append({"pid": pid, "norm": norm, "pool": pool,
                     "predicted": float(own[pid]),
                     "actual": float(shares.get(norm, 0.0)),
                     "rostered": norm in shares, "role_known": bool(role_known)})
    return rows


def _top_ids(values: Sequence[float], k: int = 10) -> List[int]:
    """Indices of the k largest values, ties broken by row order (stable)."""
    return sorted(range(len(values)), key=lambda i: (-values[i], i))[:k]


def pool_metrics(rows: Sequence[Mapping[str, Any]], values: Sequence[float],
                 orders: bool = True) -> Dict[str, Any]:
    """Per-contest review metrics of ``values`` over ``rows``. Zero tail included.

    ``orders=False`` is the flat baseline: it gives every player in a pool the same
    number, so it ranks nothing, and a rank correlation or a top-10 recall over it
    would only measure which row came first. Both are reported as None.
    """
    from ownership_pred import _spearman
    from mlb_engine.field.ownership_prior import (
        HITTER_BUDGET_PCT, PITCHER_BUDGET_PCT,
    )

    n = len(rows)
    actual = [float(r["actual"]) for r in rows]
    err = [float(v) - a for v, a in zip(values, actual)]
    rostered = [bool(r["rostered"]) for r in rows]
    ros_err = [abs(e) for e, flag in zip(err, rostered) if flag]
    out: Dict[str, Any] = {"n": n, "rostered_players": len(ros_err)}
    out["mae"] = round(sum(abs(e) for e in err) / n, 4) if n else None
    out["rostered_mae"] = round(sum(ros_err) / len(ros_err), 4) if ros_err else None
    out["mean_signed_error"] = round(sum(err) / n, 4) if n else None
    rho = _spearman(list(values), actual) if n >= 3 and orders else None
    out["spearman"] = round(rho, 4) if rho is not None else None
    # Top-10 recall of the ten most-owned. A tie at the cutoff makes the figure depend
    # on row order; it says so.
    if n >= 10 and orders:
        ranked = sorted(values, reverse=True)
        hit = set(_top_ids(actual)) & set(_top_ids(values))
        out["top10_recall"] = round(len(hit) / 10.0, 4)
        out["top10_tie_at_cutoff"] = bool(len(ranked) > 10 and ranked[9] == ranked[10])
    else:
        out["top10_recall"] = None
        out["top10_tie_at_cutoff"] = None
    out["zero_actual_pred_mass"] = round(
        sum(float(v) for v, flag in zip(values, rostered) if not flag), 3)
    out["unknown_role_pred_mass"] = round(
        sum(float(v) for v, r in zip(values, rows) if not r["role_known"]), 3)
    out["unknown_role_actual_mass"] = round(
        sum(a for a, r in zip(actual, rows) if not r["role_known"]), 3)
    by_pool: Dict[str, Any] = {}
    for pool in ("hitter", "pitcher"):
        ix = [i for i, r in enumerate(rows) if r["pool"] == pool]
        if not ix:
            continue
        p_err = [err[i] for i in ix]
        p_rho = _spearman([float(values[i]) for i in ix], [actual[i] for i in ix]) if len(ix) >= 3 else None
        by_pool[pool] = {"n": len(ix),
                         "mae": round(sum(abs(e) for e in p_err) / len(ix), 4),
                         "mean_signed_error": round(sum(p_err) / len(ix), 4),
                         "spearman": round(p_rho, 4) if p_rho is not None else None,
                         "pred_sum": round(sum(float(values[i]) for i in ix), 2),
                         "actual_sum": round(sum(actual[i] for i in ix), 2),
                         "max_share": round(max(float(values[i]) for i in ix), 2),
                         "min_share": round(min(float(values[i]) for i in ix), 2)}
    out["by_pool"] = by_pool
    budgets = {"hitter": HITTER_BUDGET_PCT, "pitcher": PITCHER_BUDGET_PCT}
    out["budget"] = {
        "within_bounds": all(0.0 <= float(v) <= 100.0 for v in values),
        "on_budget": all(
            abs(p["pred_sum"] - budgets[pool])
            <= max(1.0, BUDGET_TOLERANCE_PER_ROW * p["n"])
            for pool, p in by_pool.items()),
    }
    bins = []
    gap = 0.0
    for low, high in CALIBRATION_BINS:
        ix = [i for i, v in enumerate(values) if low <= float(v) < high]
        if not ix:
            continue
        mean_pred = sum(float(values[i]) for i in ix) / len(ix)
        mean_act = sum(actual[i] for i in ix) / len(ix)
        gap += len(ix) / n * abs(mean_pred - mean_act)
        bins.append({"bin": [low, min(high, 100.0)], "n": len(ix),
                     "mean_predicted": round(mean_pred, 3),
                     "mean_actual": round(mean_act, 3)})
    out["bins"] = bins
    out["calibration_gap"] = round(gap, 4) if n else None
    return out


def flat_budget_values(rows: Sequence[Mapping[str, Any]]) -> List[float]:
    """800/N_hitters and 200/N_pitchers over the SAME rows the prior is scored on."""
    from mlb_engine.field.ownership_prior import (
        HITTER_BUDGET_PCT, PITCHER_BUDGET_PCT,
    )

    counts = {"hitter": 0, "pitcher": 0}
    for r in rows:
        counts[r["pool"]] = counts.get(r["pool"], 0) + 1
    budgets = {"hitter": HITTER_BUDGET_PCT, "pitcher": PITCHER_BUDGET_PCT}
    return [budgets[r["pool"]] / counts[r["pool"]] if counts.get(r["pool"]) else 0.0
            for r in rows]


def rescaled_to_pool_values(rows: Sequence[Mapping[str, Any]]) -> List[float]:
    """The saved prior as the build now reads it: R342(a)'s own rescale, not a copy."""
    import pandas as pd

    from mlb_engine.field.ownership_prior import (
        PROJECTED_OWNERSHIP_COLUMN, renormalize_ownership_to_frame,
    )

    frame = pd.DataFrame({
        "Position": ["P" if r["pool"] == "pitcher" else "OF" for r in rows],
        PROJECTED_OWNERSHIP_COLUMN: [float(r["predicted"]) for r in rows]})
    out, _ = renormalize_ownership_to_frame(frame)
    return [float(v) for v in out[PROJECTED_OWNERSHIP_COLUMN]]


def challenger_values(rows: Sequence[Mapping[str, Any]], exponent: float,
                      factor: float) -> List[float]:
    """The pre-registered transform over ``rows``, through the prior's own water-fill."""
    from mlb_engine.field.ownership_prior import (
        HITTER_BUDGET_PCT, PITCHER_BUDGET_PCT, _bounded_marginals,
    )

    out = [0.0] * len(rows)
    for pool, budget in (("pitcher", PITCHER_BUDGET_PCT), ("hitter", HITTER_BUDGET_PCT)):
        ix = [i for i, r in enumerate(rows) if r["pool"] == pool]
        if not ix:
            continue
        weights = {str(i): max(float(rows[i]["predicted"]), 1e-9) ** float(exponent)
                   * (1.0 if rows[i]["role_known"] else float(factor)) for i in ix}
        shares = _bounded_marginals(weights, budget)
        for i in ix:
            out[i] = float(shares[str(i)])
    return out


def _universe_grades(rows: Sequence[Mapping[str, Any]], *, rescale: bool) -> Dict[str, Any]:
    """Every variant's per-contest metrics over one universe of rows.

    ``saved`` is the prediction as emitted. On the pool-proxy universe ``rescale``
    adds ``saved_rescaled`` (what R342(a) hands the solver) and that is the
    comparator, because the raw file spends its budget on rows the pool lacks.
    """
    out: Dict[str, Any] = {
        "rows": len(rows),
        "saved": pool_metrics(rows, [r["predicted"] for r in rows]),
        "flat_budget": pool_metrics(rows, flat_budget_values(rows), orders=False),
        "challenger_grid": {}}
    if rescale:
        out["saved_rescaled"] = pool_metrics(rows, rescaled_to_pool_values(rows))
    for exponent in CHALLENGER_EXPONENTS:
        for factor in CHALLENGER_FACTORS:
            out["challenger_grid"][f"{exponent:g}|{factor:g}"] = pool_metrics(
                rows, challenger_values(rows, exponent, factor))
    return out


def _saved_inputs(prediction: Mapping[str, Any]) -> Dict[str, Any]:
    """Which emit-time inputs the SAVED file applied, read from the file itself."""
    inputs = prediction.get("inputs") or {}
    keys = ("batting_order", "implied_totals", "probable_sp", "base_projection")
    return {
        "applied": sorted(k for k in keys if (inputs.get(k) or {}).get("applied")),
        "inert": sorted(k for k in keys if not (inputs.get(k) or {}).get("applied")),
        "implied_totals_source": (inputs.get("implied_totals") or {}).get("source"),
    }


def recorded_salary_files(root: Path, predictions: Sequence[Mapping[str, Any]],
                          cache: Optional[Dict[str, Any]] = None) -> List[str]:
    """Salary files on disk whose BYTES are the ones a saved prediction recorded.

    `salary_candidates` finds a slate's file by a glob on the folder name, and the
    path a saved file records is often a LATER slate's: `data/slates/<date>/
    DKSalaries.csv` is overwritten when the next draft group is staged, and run
    folders carry `YYYYMMDD`, not `YYYY-MM-DD`. On 2026-08-19 the 3-game slate's
    salary file survives only in `runs/20260819T225247Z_ee45d0cf/inputs/`, so four
    contests resolved no salary file at all. The saved file's own sha256 names
    the bytes it was built from, so the bytes are looked up by it. ``cache`` holds
    the one-time hash index across a run's contests.
    """
    import hashlib

    root = Path(root)
    cache = cache if cache is not None else {}
    index = cache.get("salary_sha_index")
    if index is None:
        index = {}
        for pattern in ("data/slates/*/DKSalaries*.csv", "runs/*/inputs/DKSalaries*.csv",
                        "outputs/*/DKSalaries*.csv"):
            for path in sorted(root.glob(pattern)):
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    continue
                index.setdefault(digest, []).append(str(path))
        cache["salary_sha_index"] = index
    wanted = {str((p.get("salary_file") or {}).get("sha256") or "") for p in predictions}
    return sorted({path for sha in wanted - {""} for path in index.get(sha, [])})


def load_archetype_map(path: str) -> Dict[str, str]:
    """{contest id: archetype} from a CSV with `cid` and `archetype` columns.

    The operator's PROVISIONAL assignment, used instead of the production
    resolver. The 2026-09-14 research named archetypes from the contest title with
    its own rules ("Saved archetype selection is name-inferred and provisional"),
    and today's resolver reads titles the research could not (R446/R447), so
    reproducing the research's figures needs the research's own assignment. The
    report says which source a run used.
    """
    from mlb_engine.field.ownership_prior import ARCHETYPE_PARAMS

    mapping: Dict[str, str] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            cid = str(row.get("cid") or "").strip()
            archetype = str(row.get("archetype") or "").strip()
            if not cid:
                continue
            if archetype not in ARCHETYPE_PARAMS:
                raise ValueError(f"{path}: contest {cid} names unknown archetype {archetype!r}; "
                                 f"known: {', '.join(sorted(ARCHETYPE_PARAMS))}")
            mapping[cid] = archetype
    return mapping


def grade_saved_one(record: Mapping[str, Any], names: Mapping[str, str],
                    saved_index: Mapping[str, Sequence[Mapping[str, Any]]],
                    root: Path = REPO_ROOT,
                    archetype_map: Optional[Mapping[str, str]] = None,
                    cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Grade one archived Classic contest against the SAVED prediction. Never raises.

    A refusal is a returned ``status`` and ``refused`` reason, in the research's
    own vocabulary where it has one. Nothing here calls ``build_prediction``. An
    unexpected error in one contest (an unreadable salary file, a malformed saved
    payload) comes back as ``GRADE_ERROR`` naming the exception, so it cannot end a
    multi-minute pass over the other contests.
    """
    try:
        return _grade_saved_one(record, names, saved_index, root, archetype_map, cache)
    except Exception as exc:  # noqa: BLE001 -- the contract above
        return {"contest_id": record.get("contest_id"), "slate_date": record.get("slate_date"),
                "contest_type": record.get("contest_type"), "status": "GRADE_ERROR",
                "refused": f"{type(exc).__name__}: {exc}"}


def _grade_saved_one(record: Mapping[str, Any], names: Mapping[str, str],
                     saved_index: Mapping[str, Sequence[Mapping[str, Any]]],
                     root: Path, archetype_map: Optional[Mapping[str, str]],
                     cache: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    from mlb_engine.field.field_miner import parse_standings_export, resolve_salary_file

    root = Path(root)
    cid = record["contest_id"]
    blob = record["blob"]
    out: Dict[str, Any] = {"contest_id": cid, "slate_date": record["slate_date"],
                           "contest_type": record["contest_type"]}
    field_size, size_source = _field_size(blob)
    out.update({"field_size": field_size, "field_size_source": size_source,
                "field_band": field_band(field_size)})

    def refuse(status: str, why: str) -> Dict[str, Any]:
        out["status"], out["refused"] = status, why
        return out

    if str(record["contest_type"]) != "classic":
        return refuse("NOT_CLASSIC",
                      "the saved grade is the Classic 1000% roster market; Showdown is "
                      "graded on its own 600% and 100% markets and not here")
    name = names.get(cid)
    if name:
        out["contest_name"] = name
    if archetype_map and cid in archetype_map:
        archetype, exactness = archetype_map[cid], "MAPPED"
    else:
        if not name:
            return refuse("NO_CONTEST_NAME", "no DKEntries row on disk carries this Contest ID, "
                          "so the contest has no name and therefore no archetype")
        archetype, exactness, why = resolve_archetype(name, field_size)
        if not archetype:
            return refuse("NO_ARCHETYPE", why)
    out["archetype"], out["archetype_exactness"] = archetype, exactness
    candidates = list(saved_index.get(record["slate_date"]) or [])
    if not candidates:
        # Before the (large) standings parse: a date BUILD saved nothing for has
        # nothing to grade, and the archive holds 379 contests across 60-odd dates.
        out["saved_candidates"] = []
        return refuse("NO_MATCHING_SAVED_PREDICTION",
                      f"no saved prediction is dated {record['slate_date']}")

    hits = sorted(root.glob(f"data/archive/*/contest-standings-{cid}.csv"))
    if not hits:
        return refuse("NO_STANDINGS", "no standings export on disk for this contest")
    standings = parse_standings_export(str(hits[0]))
    pick = resolve_salary_file(
        standings, sorted(set(salary_candidates(record["slate_date"], root))
                          | set(recorded_salary_files(root, candidates, cache))))
    if not pick.get("path"):
        return refuse("NO_SALARY_IDENTITY", f"no salary file resolved: {pick.get('reason')}")
    identity = salary_identity(pick["path"])
    shares, denominator = rostered_shares_exact(standings.get("entries") or [])
    if not shares:
        return refuse("NO_COMPLETE_LINEUPS", "the standings export yielded no complete "
                      "lineups to recompute ownership from")

    chosen, considered = match_saved_prediction(sorted(shares), identity, candidates)
    out["saved_candidates"] = considered
    if chosen is None:
        return refuse("NO_MATCHING_SAVED_PREDICTION",
                      f"{len(considered)} saved prediction(s) on {record['slate_date']}; "
                      "none carries every rostered name with this salary file's identity")
    info = next(c for c in considered if c.get("chosen"))
    out["saved"] = {**info, "slate_tag": chosen.get("slate_tag"),
                    "prior_version": chosen.get("prior_version"),
                    "tool_version": chosen.get("tool_version"),
                    "salary_file_recorded": (chosen.get("salary_file") or {}).get("path"),
                    "inputs": _saved_inputs(chosen)}
    if not info["prelock_checkable"]:
        return refuse("PRELOCK_UNVERIFIABLE",
                      f"{info['source']} has generated_utc {info['generated_utc']!r} and the salary "
                      f"file's first game is {info['first_game_utc']!r}: one of the two is missing "
                      "or unparseable, so \"saved before lock\" cannot be checked")
    if not info["prelock"]:
        return refuse("SAVED_AFTER_LOCK",
                      f"{info['source']} was generated {info['generated_utc']}, not before "
                      f"the slate's first game {info['first_game_utc']}")
    if archetype not in (chosen.get("archetypes") or {}):
        return refuse("MISSING_ARCHETYPE", f"{info['source']} carries no archetype {archetype!r}")

    rows = saved_pool_rows(chosen, archetype, shares)
    mass = sum(r["actual"] for r in rows)
    if abs(mass - 1000.0) > 0.01:
        return refuse("ACTUAL_MASS_NOT_COMPLETE",
                      f"the saved file's players carry {mass:.2f} of the contest's 1000 "
                      "points of rostered share, so some rostered player is not in it")
    if len({r["norm"] for r in rows}) != len(rows):
        return refuse("PREDICTED_NAME_AMBIGUITY", "two saved players normalize to one name")

    out["status"] = "GRADED"
    out["actual"] = {"basis": "entry_block_recompute, unrounded", "complete_lineups": denominator,
                     "rostered_players": len(shares), "standings": str(hits[0].name)}
    out["whole_file"] = _universe_grades(rows, rescale=False)
    pool = [r for r in rows if r["role_known"]]
    out["pool_proxy"] = _universe_grades(pool, rescale=True) if pool else None
    out["pool_proxy_off_pool_actual"] = round(
        sum(r["actual"] for r in rows if not r["role_known"]), 3)
    return out


# -- aggregation ------------------------------------------------------------

def _equal_date_mean(rows: Sequence[Mapping[str, Any]], getter) -> Optional[float]:
    """Mean over dates of mean over slates of mean over contests (the research's weighting)."""
    by_date: Dict[str, Dict[str, List[float]]] = {}
    for r in rows:
        value = getter(r)
        if value is None:
            continue
        by_date.setdefault(r["slate_date"], {}).setdefault(
            str((r.get("saved") or {}).get("source")), []).append(float(value))
    if not by_date:
        return None
    per_date = [sum(sum(v) / len(v) for v in slates.values()) / len(slates)
                for slates in by_date.values()]
    return sum(per_date) / len(per_date)


def _variant_getter(universe: str, variant: str, metric: str,
                    cell: Optional[str] = None):
    def get(result: Mapping[str, Any]):
        block = result.get(universe)
        if not block:
            return None
        node = block["challenger_grid"][cell] if variant == "challenger" else block.get(variant)
        return None if node is None else node.get(metric)
    return get


def _plain_mean(rows: Sequence[Mapping[str, Any]], getter) -> Optional[float]:
    """Mean over contests, unweighted (the research's per-date delta definition)."""
    values = [float(getter(r)) for r in rows if getter(r) is not None]
    return sum(values) / len(values) if values else None


def _delta(after: Optional[float], before: Optional[float]) -> Optional[float]:
    return None if after is None or before is None else after - before


def _held_out_by_band(held: Sequence[Mapping[str, Any]], best: str) -> List[Dict[str, Any]]:
    """The held-out comparison conditioned on archetype and field band, never pooled.

    Per contest, the challenger's MAE minus its comparator's (negative: the challenger is
    closer), then the median of those per-contest differences inside one archetype and
    one field band, with how many contests went each way. The equal-date means above are
    the pre-registered reproduction; this is the conditioned read the ledger requires.
    """
    groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for r in held:
        groups.setdefault((str(r.get("archetype") or "unknown"),
                           str(r.get("field_band") or "f_unknown")), []).append(r)
    out = []
    for (archetype, band), rows in sorted(groups.items()):
        whole = [r["whole_file"]["challenger_grid"][best]["mae"] - r["whole_file"]["saved"]["mae"]
                 for r in rows]
        pool = [r["pool_proxy"]["challenger_grid"][best]["mae"]
                - r["pool_proxy"]["saved_rescaled"]["mae"] for r in rows if r.get("pool_proxy")]
        out.append({"archetype": archetype, "field_band": band, "contests": len(rows),
                    "whole_file_median_delta_mae": _median(whole),
                    "whole_file_challenger_closer": sum(1 for d in whole if d < 0),
                    "pool_proxy_contests": len(pool),
                    "pool_proxy_median_delta_mae": _median(pool),
                    "pool_proxy_challenger_closer": sum(1 for d in pool if d < 0)})
    return out


def split_dates(dates: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Calendar dates: the first 60% train, the rest held out (the pre-registered split)."""
    import math

    ordered = sorted(set(dates))
    ntrain = max(1, int(math.floor(len(ordered) * CHALLENGER_TRAIN_FRACTION)))
    return ordered[:ntrain], ordered[ntrain:]


def summarize_saved(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The reproduction summary and the held-out gate, from per-contest results."""
    graded = [r for r in results if r.get("status") == "GRADED"]
    dates = sorted({r["slate_date"] for r in graded})
    train, holdout = split_dates(dates)
    summary: Dict[str, Any] = {
        "contests": len(graded), "slates": len({r["saved"]["source"] for r in graded}),
        "dates": len(dates), "train_dates": train, "holdout_dates": holdout}
    summary["saved_prior_whole_file"] = {
        key: _equal_date_mean(graded, _variant_getter("whole_file", "saved", key))
        for key in ("mae", "rostered_mae", "spearman", "top10_recall",
                    "zero_actual_pred_mass", "unknown_role_pred_mass",
                    "unknown_role_actual_mass", "calibration_gap")}
    if not holdout:
        summary["challenger"] = None
        return summary
    train_rows = [r for r in graded if r["slate_date"] in train]
    # Grid order (exponent, then factor, ascending), so a tie takes the first cell as the
    # research's idxmin did; a string sort would put "1.5|0.05" ahead of "1|0.05".
    grid_order = [f"{e:g}|{f:g}" for e in CHALLENGER_EXPONENTS for f in CHALLENGER_FACTORS]
    scored = {cell: _equal_date_mean(
        train_rows, _variant_getter("whole_file", "challenger", "mae", cell))
        for cell in grid_order}
    best = min((c for c in grid_order if scored[c] is not None),
               key=lambda c: scored[c], default=None)
    if best is None:
        summary["challenger"] = None
        return summary
    held = [r for r in graded if r["slate_date"] in holdout]
    gate: Dict[str, Any] = {}
    for universe, comparator in (("whole_file", "saved"), ("pool_proxy", "saved_rescaled")):
        rows = [r for r in held if r.get(universe)]
        table = {}
        for metric in SAVED_METRICS:
            base = _equal_date_mean(rows, _variant_getter(universe, comparator, metric))
            chal = _equal_date_mean(rows, _variant_getter(universe, "challenger", metric, best))
            lower_is_better = metric != "top10_recall"
            beats = None if base is None or chal is None else (
                chal < base if lower_is_better else chal > base)
            table[metric] = {"comparator": base, "challenger": chal, "beats": beats}
        legal = all(((r[universe]["challenger_grid"][best]["budget"])["within_bounds"]
                     and r[universe]["challenger_grid"][best]["budget"]["on_budget"])
                    for r in rows)
        table["legal_budgets"] = {"comparator": None, "challenger": legal, "beats": legal}
        gate[universe] = {
            "comparator": comparator, "contests": len(rows), "metrics": table,
            "challenger_beats_on_every_metric": all(
                v["beats"] for v in table.values())}
    summary["challenger"] = {
        "selected_cell": {"exponent": float(best.split("|")[0]),
                          "unknown_role_factor": float(best.split("|")[1])},
        "train_mae": scored[best], "gate": gate,
        "by_archetype_band": _held_out_by_band(held, best),
        "held_out_flat_budget": {
            universe: {key: _equal_date_mean(
                [r for r in held if r.get(universe)], _variant_getter(universe, "flat_budget", key))
                for key in ("mae", "rostered_mae", "calibration_gap")}
            for universe in ("whole_file", "pool_proxy")},
        "date_deltas_mae": {
            d: _delta(_plain_mean([r for r in held if r["slate_date"] == d],
                                  _variant_getter("whole_file", "challenger", "mae", best)),
                      _plain_mean([r for r in held if r["slate_date"] == d],
                                  _variant_getter("whole_file", "saved", "mae")))
            for d in holdout}}
    return summary


def saved_report(results: Sequence[Mapping[str, Any]], summary: Mapping[str, Any],
                 today: str) -> str:
    """The saved-grade report. Per contest first; summaries are labeled and never pooled."""
    graded = [r for r in results if r.get("status") == "GRADED"]
    refused = [r for r in results if r.get("status") != "GRADED"]

    def f(value: Any, places: int = 3) -> str:
        return "n/a" if value is None else f"{value:.{places}f}"

    lines = [
        f"# Ownership prior graded on its SAVED pre-lock files | {len(graded)} Classic contest(s)",
        "",
        f"Filed {today} by DEV (R342(b1)), from `tools/ownership_grade_archive.py --saved`. "
        "Every figure is a deterministic review proxy of a labeled, uncalibrated structural prior "
        "against ownership recomputed from archived DK standings. Nothing here is a win rate, a "
        "cash rate, an ROI figure, an edge, or a probability claim; one contest never moves a prior.",
        "",
        "**What this reads.** The `outputs/*/ownership_pred_*.json` BUILD saved before first pitch, "
        "matched to each contest by player identity (Player_ID, salary, team) against the contest's "
        "own salary file, preferring a file saved before the slate's first game with the same "
        "salary-file sha256. It never calls `build_prediction`. The zero tail is in the error term, "
        "the flat baseline spreads 800/200 over the same rows it is scored on, and the odds state is "
        "read from the saved file itself (`inputs.implied_totals.applied`), not from a packet on disk.",
        "",
        f"**Archetype source.** {summary.get('archetype_source') or 'the production resolver'}.",
        "",
        "**Two universes, stated plainly.** `whole_file`: every salary-file row of the saved "
        "prediction, which is the research's \"complete pool\". `pool_proxy`: only the rows with a "
        "recorded pre-lock role (a batting-order slot or a probable flag), scored after R342(a)'s "
        "own rescale to 800/200, which is what the solver reads. The proxy is NOT the build's pool: a "
        "TBD side's platoon-projected nine and a declared pitcher are not recorded in the saved file.",
        "",
    ]
    sp = summary.get("saved_prior_whole_file") or {}
    lines += [
        "## Reproduction of the 2026-09-14 saved-prior figures",
        "",
        f"{summary.get('contests')} contests, {summary.get('slates')} saved slate predictions, "
        f"{summary.get('dates')} dates. Equal-date mean of per-contest statistics (the research's "
        "weighting, which averages across archetypes and field sizes as the pre-registration "
        "did: a reproduction check, not a conditioned result; the conditioned tables are below):",
        "",
        "| figure | this run | 2026-09-14 research (68 contests, 13 slates, 8 dates) |",
        "|---|---|---|",
        f"| complete-pool MAE (pts) | {f(sp.get('mae'), 3)} | 3.40 |",
        f"| rostered-player MAE | {f(sp.get('rostered_mae'), 3)} | 9.08 |",
        f"| Spearman | {f(sp.get('spearman'), 3)} | 0.643 |",
        f"| top-10 recall | {f(sp.get('top10_recall'), 3)} | 0.282 |",
        f"| predicted mass on never-rostered players (of 1000) | "
        f"{f(sp.get('zero_actual_pred_mass'), 1)} | 465.5 |",
        "",
    ]
    ch = summary.get("challenger")
    if ch:
        cell = ch["selected_cell"]
        lines += [
            "## The pre-registered challenger, held-out dates",
            "",
            f"Train {', '.join(summary['train_dates'])}; held out {', '.join(summary['holdout_dates'])}. "
            f"Cell selected on the train dates by whole-file MAE: exponent {cell['exponent']:g}, "
            f"unknown-role factor {cell['unknown_role_factor']:g} (train MAE {f(ch['train_mae'], 3)}).",
            "",
        ]
        for universe in ("whole_file", "pool_proxy"):
            g = ch["gate"][universe]
            lines += [
                f"### `{universe}` (comparator: `{g['comparator']}`, {g['contests']} held-out contests)",
                "",
                "| metric | comparator | challenger | challenger better |",
                "|---|---|---|---|"]
            for metric, v in g["metrics"].items():
                lines.append(f"| {metric} | {f(v['comparator'])} | "
                             f"{v['challenger'] if metric == 'legal_budgets' else f(v['challenger'])} "
                             f"| {v['beats']} |")
            lines += ["", f"Challenger better on every named metric: "
                      f"**{g['challenger_beats_on_every_metric']}**.", ""]
        lines += [
            "### Held-out, conditioned on archetype and field band",
            "",
            "The tables above are the pre-registered equal-date means over every archetype and "
            "field size. This is the conditioned read: per contest, the challenger's MAE minus its "
            "comparator's (negative: the challenger is closer), the median of those differences "
            "inside one archetype and one field band, and how many contests went the challenger's way.",
            "",
            "| archetype | band | contests | whole-file median diff | closer | pool-proxy median diff "
            "| closer |",
            "|---|---|---|---|---|---|---|"]
        for b in ch["by_archetype_band"]:
            lines.append(
                f"| {b['archetype']} | {b['field_band']} | {b['contests']} "
                f"| {f(b['whole_file_median_delta_mae'])} | {b['whole_file_challenger_closer']} of {b['contests']} "
                f"| {f(b['pool_proxy_median_delta_mae'])} | {b['pool_proxy_challenger_closer']} of {b['pool_proxy_contests']} |")
        lines += [
            "",
            "Held-out flat-budget baseline over the same rows: "
            + "; ".join(f"`{u}` MAE {f(v['mae'])}, rostered MAE {f(v['rostered_mae'])}"
                        for u, v in ch["held_out_flat_budget"].items()) + ".",
            "",
            "Held-out whole-file MAE change by date (mean over the date's contests, the research's "
            "definition): "
            + ", ".join(f"{d} {f(v, 3)}" for d, v in sorted(ch["date_deltas_mae"].items())) + ".",
            ""]
    lines += ["## Per contest (never pooled)", "",
              "| contest | date | archetype | field | band | saved file | pre-lock | sha match | tilts inert "
              "| MAE | rostered MAE | rho |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(graded, key=lambda x: (x["slate_date"], x["contest_id"])):
        s, w = r["saved"], r["whole_file"]["saved"]
        lines.append(
            f"| `{r['contest_id']}` | {r['slate_date']} | {r['archetype']} | {r['field_size']} "
            f"| {r['field_band']} | `{s['source']}` | {s['prelock']} | {s['salary_sha256_match']} "
            f"| {', '.join(s['inputs']['inert']) or 'none'} | {f(w['mae'], 2)} "
            f"| {f(w['rostered_mae'], 2)} | {f(w['spearman'])} |")
    lines += ["", "## By archetype and field band (medians of per-contest statistics)", ""]
    groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for r in graded:
        groups.setdefault((r["archetype"], r["field_band"]), []).append(r)
    lines += ["| archetype | band | contests | median whole-file MAE | median rostered MAE "
              "| median pool-proxy MAE (rescaled) |", "|---|---|---|---|---|---|"]
    for (arch, band), rows in sorted(groups.items()):
        lines.append(
            f"| {arch} | {band} | {len(rows)} "
            f"| {_median([r['whole_file']['saved']['mae'] for r in rows])} "
            f"| {_median([r['whole_file']['saved']['rostered_mae'] for r in rows])} "
            f"| {_median([((r.get('pool_proxy') or {}).get('saved_rescaled') or {}).get('mae') for r in rows])} |")
    reasons: Dict[str, int] = {}
    for r in refused:
        reasons[r["status"]] = reasons.get(r["status"], 0) + 1
    lines += ["", f"## Refused ({len(refused)})", ""]
    lines += [f"- `{status}` x{count}" for status, count in sorted(reasons.items())] or ["- none"]
    lines += ["", "Medians are medians of per-contest statistics inside one archetype and one field "
              "band, never a statistic recomputed over a merged player set. Self-inclusion caveat "
              "carried forward: Ben's own entries sit in the denominator of every contest he entered.", ""]
    return "\n".join(lines) + "\n"


def _saved_main(args: argparse.Namespace, today: str) -> int:
    """`--saved`: grade the SAVED pre-lock predictions (R342(b1)). Never rebuilds one."""
    root = Path(args.root) if args.root else REPO_ROOT
    names = contest_names_on_disk(root)
    records = mined_contests(args.contest, root)[args.offset:]
    if args.limit:
        records = records[: args.limit]
    if not records:
        print("REFUSED: no mined contests matched", file=sys.stderr)
        return 2
    index = load_saved_predictions(root)
    if not index:
        print("REFUSED: no saved prediction under outputs/*/ownership_pred_*.json "
              "(gitignored: this grade runs where BUILD saved them)", file=sys.stderr)
        return 2
    archetype_map = load_archetype_map(args.archetype_map) if args.archetype_map else None
    source = (f"the operator's map {Path(args.archetype_map).name} (provisional), the production "
              "resolver for any contest it does not name" if archetype_map else
              "the production resolver (contest_library title rules, then the shape map)")
    cache: Dict[str, Any] = {}
    results = [grade_saved_one(record, names, index, root, archetype_map, cache)
               for record in records]
    summary = summarize_saved(results)
    summary["archetype_source"] = source
    text = saved_report(results, summary, today)
    print(text)
    if args.saved_out:
        out_dir = Path(args.saved_out)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{today}_DEV_ownership-prior-saved-grade.md"
        (out_dir / name).write_bytes(text.encode("utf-8"))
        print(f"wrote {out_dir / name}")
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(
            {"schema": SAVED_SCHEMA, "tool_version": VERSION, "summary": summary,
             "graded": [r for r in results if r.get("status") == "GRADED"],
             "refused": [r for r in results if r.get("status") != "GRADED"]},
            indent=1) + "\n").encode("utf-8"))
        print(f"wrote {path}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="ledger/inbox",
                        help="directory for the fragments (default ledger/inbox; "
                             "only ARCHIVE writes ledger/ itself)")
    parser.add_argument("--contest", help="grade one contest id only")
    parser.add_argument("--limit", type=int, help="stop after N contests")
    parser.add_argument("--offset", type=int, default=0,
                        help="skip the first N contests. With --limit and "
                             "--json-out this is how a full archive pass fits "
                             "the mount's bash ceiling: run chunks, then "
                             "--fragments-from the chunk files. Contest order "
                             "is the sorted archive path, so it is stable "
                             "across calls.")
    parser.add_argument("--fragments-from", dest="fragments_from",
                        help="write the fragments from previously written "
                             "--json-out chunk files (a glob) instead of "
                             "grading; the merge is by contest_id, so "
                             "overlapping chunks are safe")
    parser.add_argument("--date", help="today's date for the fragment names")
    parser.add_argument("--budget-seconds", dest="budget_seconds", type=float,
                        default=120.0,
                        help="stop cleanly after this many seconds and print "
                             "the offset to resume from (default 120, under "
                             "the mount's ~180s bash ceiling); 0 disables")
    parser.add_argument("--stdout", action="store_true",
                        help="print the fragments instead of writing them")
    parser.add_argument("--json-out", dest="json_out",
                        help="also write the full per-contest grade JSON here")
    parser.add_argument("--saved", action="store_true",
                        help="R342(b1): grade the SAVED pre-lock predictions "
                             "(outputs/*/ownership_pred_*.json) instead of rebuilding "
                             "each one with today's code; Classic only; prints the "
                             "report (and --json-out). Gitignored inputs: runs where "
                             "BUILD saved them")
    parser.add_argument("--saved-out", dest="saved_out",
                        help="with --saved: also write the report into this directory")
    parser.add_argument("--root", help="with --saved: the repo root to read (tests)")
    parser.add_argument("--archetype-map", dest="archetype_map",
                        help="with --saved: a CSV of `cid,archetype` that replaces the "
                             "production resolver for the contests it names (the "
                             "2026-09-14 research's own assignment reproduces its figures)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    import datetime
    today = args.date or datetime.date.today().isoformat()
    if args.saved:
        if args.fragments_from:
            parser.error("--saved grades the saved predictions itself; it cannot be combined "
                         "with --fragments-from (which merges chunks of the rebuild grade)")
        return _saved_main(args, today)
    if args.fragments_from:
        # Merge by contest_id so an overlapping or re-run chunk cannot put one
        # contest into a band twice, which would silently weight it double in
        # every median below.
        merged: Dict[str, Dict[str, Any]] = {}
        merged_refused: Dict[str, Dict[str, Any]] = {}
        chunks = sorted(glob.glob(args.fragments_from))
        if not chunks:
            print(f"REFUSED: {args.fragments_from} matched no chunk files",
                  file=sys.stderr)
            return 2
        for chunk in chunks:
            blob = json.loads(Path(chunk).read_text(encoding="utf-8"))
            for row in blob.get("graded") or []:
                merged[str(row.get("contest_id"))] = row
            for row in blob.get("refused") or []:
                merged_refused[str(row.get("contest_id"))] = row
        results = [merged[k] for k in sorted(merged)]
        refused = [merged_refused[k] for k in sorted(merged_refused)]
        print(f"merged {len(chunks)} chunk file(s): {len(results)} graded, "
              f"{len(refused)} refused")
    else:
        names = contest_names_on_disk()
        records = mined_contests(args.contest)
        records = records[args.offset:]
        if args.limit:
            records = records[: args.limit]
        if not records:
            print("REFUSED: no mined contests matched", file=sys.stderr)
            return 2

        import time
        started = time.monotonic()
        results, refused, done = [], [], 0
        for index, record in enumerate(records, 1):
            # A full archive pass does not fit one call on this mount (R271's
            # ~180s ceiling), so the pass stops on its own budget and NAMES the
            # offset to resume from, rather than being killed mid-write and
            # losing the chunk. Same shape as the audit gate's --gate-budget.
            if args.budget_seconds and time.monotonic() - started > args.budget_seconds:
                print(f"BUDGET REACHED after {done} contest(s); resume with "
                      f"--offset {args.offset + done}", flush=True)
                break
            result = grade_one(record, names)
            (refused if result.get("refused") else results).append(result)
            done += 1
            print(f"[{index}/{len(records)}] {record['contest_id']} "
                  f"{record['contest_type']:<9} "
                  + (f"REFUSED: {result['refused']}" if result.get("refused")
                     else f"{result.get('archetype')} "
                          f"field {result.get('field_size')} rho "
                          f"{_cell(result.get('roster_grade'), 'spearman_rank_corr')}"),
                  flush=True)
        print(f"NEXT OFFSET {args.offset + done}"
              + ("  (archive exhausted)" if done >= len(records) else ""),
              flush=True)

    by_archetype: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        by_archetype.setdefault(str(result["archetype"]), []).append(result)

    out_dir = REPO_ROOT / args.out
    written = []
    for archetype in sorted(by_archetype):
        text = archetype_fragment(archetype, by_archetype[archetype], today)
        name = f"{today}_DEV_ownership-prior-grade-{archetype.replace('_', '-')}.md"
        if args.stdout:
            print(text)
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_text(text, encoding="utf-8")
            written.append(name)
    if any(r.get("captain_grade") for r in results):
        text = captain_fragment(results, today)
        name = f"{today}_DEV_showdown-captain-market-grade.md"
        if args.stdout:
            print(text)
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_text(text, encoding="utf-8")
            written.append(name)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"schema": "ownership_grade_archive/v1", "tool_version": VERSION,
             "graded": results, "refused": refused}, indent=1) + "\n",
            encoding="utf-8")
        print(f"wrote {path}")

    print()
    print(f"graded {len(results)} contest(s), refused {len(refused)}")
    for archetype in sorted(by_archetype):
        rows = by_archetype[archetype]
        print(f"  {archetype:<20} {len(rows):>3} contest(s); median "
              f"per-contest Spearman "
              f"{_median([_cell(r.get('roster_grade'), 'spearman_rank_corr') for r in rows])}, "
              f"median signed error "
              f"{_median([_cell(r.get('roster_grade'), 'mean_signed_error_pct_points') for r in rows])} pts")
    reasons: Dict[str, int] = {}
    for r in refused:
        key = str(r["refused"]).split(":")[0][:60]
        reasons[key] = reasons.get(key, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  REFUSED x{count}: {reason}")
    for name in written:
        print(f"  wrote {args.out}/{name}")
    print("  Every number is an observed count or a deterministic statistic "
          "over one. Not a win rate, a cash rate, an ROI figure, or a "
          "probability claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
