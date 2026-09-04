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

VERSION = "v1.0"

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


def contest_names_on_disk() -> Dict[str, str]:
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
        for path in sorted(glob.glob(str(REPO_ROOT / pattern))):
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


def salary_candidates(slate_date: str) -> List[str]:
    out: set = set()
    for pattern in (f"data/slates/{slate_date}/DKSalaries*.csv",
                    f"runs/*{slate_date}*/inputs/DKSalaries*.csv",
                    f"outputs/{slate_date}/DKSalaries*.csv"):
        out.update(glob.glob(str(REPO_ROOT / pattern)))
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


def mined_contests(only: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(REPO_ROOT.glob("data/archive/*/mined_*.json")):
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
        out["refused"] = "the standings export yielded no %Drafted rows"
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
    args = parser.parse_args(list(argv) if argv is not None else None)

    import datetime
    today = args.date or datetime.date.today().isoformat()
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
