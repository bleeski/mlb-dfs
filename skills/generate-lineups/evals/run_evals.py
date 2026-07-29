"""Fixture-backed eval runner for the generate-lineups skill (R6d). v1.0

Every eval in evals.json is a machine-checkable fixture: a command, an
expected exit code, artifact-state assertions, and forbidden claims. This
runner materializes fixtures into a scratch directory (date-shifting the
archived 2026-06-03 slate to tomorrow so lock clocks read live), runs each
command offline, and asserts. Prose expectations are gone on purpose: an
eval that cannot fail by exit code or artifact state is a vibe, not a gate.

Offline discipline: --lineups is always a materialized fixture feed,
--no-rotowire is always passed, and THE_ODDS_API_KEY is stripped from the
child environment, so nothing here ever fetches.

Not wired into tools/audit.py: the audit gates the four test suites; these
evals are the skill-development harness. Run them when the skill or its
scripts change:

    python skills/generate-lineups/evals/run_evals.py [--only ID] [--keep]

Exit 0 all evals pass, 1 any fail, 3 harness/fixture error.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
SKILL_DIR = EVALS_DIR.parent
REPO = SKILL_DIR.parent.parent
INPUTS = EVALS_DIR / "inputs"
ARCHIVE = REPO / "data" / "archive" / "2026-06-03"
SHOWDOWN_FIXTURES = REPO / "tests" / "fixtures" / "showdown"

ARCHIVE_DATE_US = "06/03/2026"          # as it appears in Game Info
ARCHIVE_DATE_ISO = "2026-06-03"


def _target_dates(shift: str):
    """Return (us_date, iso_date, utc_stamp_by_game_index) for a shift mode."""
    if shift == "past":
        return ARCHIVE_DATE_US, ARCHIVE_DATE_ISO, ["2026-06-03T22:40:00Z", "2026-06-03T22:45:00Z"]
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    us = tomorrow.strftime("%m/%d/%Y")
    iso = tomorrow.isoformat()
    stamps = [f"{iso}T22:40:00Z", f"{iso}T22:45:00Z"]
    return us, iso, stamps


def materialize_classic(work: Path, shift: str = "future",
                        mutate_probable_team: str | None = None) -> None:
    """Copy the archived classic pair + fixture feed into ``work``.

    ``shift='future'`` rewrites every date to tomorrow so lock clocks are
    live; ``shift='past'`` leaves 2026-06-03 in place, which is the past-lock
    scenario by construction. ``mutate_probable_team`` replaces that team's
    probable pitcher name with one no salary row carries (the
    absent-confirmed-starter scenario).
    """
    us, iso, stamps = _target_dates(shift)
    salary_text = (ARCHIVE / "DKSalaries_2026-06-03.csv").read_text(encoding="utf-8-sig")
    (work / "DKSalaries.csv").write_text(
        salary_text.replace(ARCHIVE_DATE_US, us), encoding="utf-8")
    shutil.copy(ARCHIVE / "DKEntries_2026-06-03.csv", work / "DKEntries.csv")
    feed = json.loads((INPUTS / "lineups_feed_classic.template.json").read_text(encoding="utf-8"))
    feed["date"] = iso
    feed["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    for i, game in enumerate(feed["games"]):
        game["game_date_utc"] = stamps[min(i, len(stamps) - 1)]
        if mutate_probable_team:
            for side in ("away", "home"):
                block = game[side]
                if block["team_abbrev"] == mutate_probable_team and block.get("probable_pitcher"):
                    block["probable_pitcher"]["name"] = "Nobody Anywhere"
    (work / "lineups_feed.json").write_text(json.dumps(feed), encoding="utf-8")


def materialize_showdown(work: Path) -> None:
    shutil.copy(SHOWDOWN_FIXTURES / "DKSalaries_showdown_MIN_CHC.csv", work / "DKSalaries.csv")
    shutil.copy(SHOWDOWN_FIXTURES / "DKEntries_showdown_MIN_CHC.csv", work / "DKEntries.csv")


def materialize_satellite_entries(work: Path, n: int = 3, contest_id: str = "555001") -> None:
    """A one-contest, multi-ticket satellite grid over the classic slate."""
    with (work / "DKEntries.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    width = len(header)

    def pad(cells):
        return (cells + [""] * width)[:width]

    out = [header]
    for i in range(n):
        out.append(pad([str(777000 + i), "MLB Satellite to the Big One [3 Entry Max]",
                        contest_id, "$5"]))
    with (work / "DKEntries_satellite.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(out)


def materialize_stale_manifest(work: Path) -> None:
    """A delivered file whose manifest row records the WRONG sha256."""
    import hashlib
    materialize_showdown(work)  # any real template shape works; use showdown pair
    delivered = work / "DKEntries.csv"
    digest = hashlib.sha256(delivered.read_bytes()).hexdigest()
    wrong = ("0" * 12) + digest[12:]
    manifest = {"version": "1.1", "date": ARCHIVE_DATE_ISO, "deliveries": [{
        "delivered_file": delivered.name, "sha256": digest, "contest_type": "showdown",
        "slate_tag": "eval", "contest_ids": ["1"], "entries": 1, "status": "candidate",
        "certification": "review_grade", "projection_tier": "proxy",
        "strategy_state": {"state": "clean", "counts": {}}}]}
    (work / "upload_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work / "expected_sha.txt").write_text(wrong, encoding="utf-8")


MATERIALIZERS = {
    "classic": lambda work, spec: materialize_classic(work, shift=spec.get("shift", "future"),
                                                      mutate_probable_team=spec.get("mutate_probable_team")),
    "showdown": lambda work, spec: materialize_showdown(work),
    "classic+satellite": lambda work, spec: (materialize_classic(work),
                                             materialize_satellite_entries(work)),
    "stale_manifest": lambda work, spec: materialize_stale_manifest(work),
}


def _substitute(token: str, work: Path) -> str:
    out = token.replace("${WORK}", str(work)).replace("${REPO}", str(REPO))
    if "${EXPECTED_SHA}" in out:
        out = out.replace("${EXPECTED_SHA}", (work / "expected_sha.txt").read_text().strip())
    return out


def run_eval(spec: dict, keep: bool) -> dict:
    work = Path(tempfile.mkdtemp(prefix=f"eval{spec['id']}_"))
    result = {"id": spec["id"], "name": spec["name"], "work": str(work), "failures": []}
    try:
        MATERIALIZERS[spec["fixture"]](work, spec.get("fixture_options", {}))
        argv = [sys.executable] + [_substitute(t, work) for t in spec["command"]]
        env = dict(os.environ)
        env.pop("THE_ODDS_API_KEY", None)   # evals never fetch odds
        env["PYTHONHASHSEED"] = "0"
        for key, value in (spec.get("env") or {}).items():
            env[key] = _substitute(value, work)
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=spec.get("timeout_s", 120), env=env, cwd=str(REPO))
        output = proc.stdout + "\n" + proc.stderr
        if proc.returncode != spec["expected_exit_code"]:
            result["failures"].append(
                f"exit {proc.returncode} != expected {spec['expected_exit_code']}; "
                f"tail: {output.strip()[-400:]}")
        for artifact in spec.get("expected_artifacts", []):
            path = Path(_substitute(artifact["path"], work))
            if artifact.get("must_exist", True) != path.exists():
                result["failures"].append(
                    f"artifact {path.name}: exists={path.exists()} wanted "
                    f"{artifact.get('must_exist', True)}")
                continue
            if path.exists() and "json_equals" in artifact:
                payload = json.loads(path.read_text(encoding="utf-8"))
                for pointer, wanted in artifact["json_equals"].items():
                    node = payload
                    for part in pointer.split("."):
                        node = node.get(part) if isinstance(node, dict) else None
                    if node != wanted:
                        result["failures"].append(
                            f"artifact {path.name}: {pointer} == {node!r}, wanted {wanted!r}")
        for pattern in spec.get("required_output", []):
            if not re.search(pattern, output, re.IGNORECASE):
                result["failures"].append(f"required output missing: /{pattern}/")
        for pattern in spec.get("forbidden_claims", []):
            if re.search(pattern, output, re.IGNORECASE):
                result["failures"].append(f"forbidden claim present: /{pattern}/")
    except Exception as exc:  # noqa: BLE001 - harness reports, never hides
        result["failures"].append(f"harness error: {exc!r}")
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    return result


class RepoSurfaceGuard:
    """Snapshot data/slates/, outputs/ and the per-slate bank caches, restore exactly.

    build_slate.py stages inputs into the repo's data/slates/<date>/ and
    delivers into outputs/<date>/ no matter where its arguments live, so an
    eval run leaves real slate surfaces carrying eval byproducts: a staged
    2026-07-30 slate, an outputs/2026-07-30/upload_manifest.json with an eval
    delivery row a REAL build the next day would read, and eval files landing
    beside genuinely archived staging (observed 2026-07-29, all three). Both
    roots total a few MB, so the honest fix is a full snapshot at runner
    start and a byte-exact restore at the end: new paths deleted, changed or
    deleted paths restored from the snapshot.

    R28, 2026-07-29: the guard reached one directory short of the damage.
    build_slate also writes ``runs/bank_cache_<date>_<poolsig>.json``, which
    was outside ROOTS, so every eval run left a per-slate bank cache behind.
    Two consequences, both observed on the same day. Evals stopped being
    reproducible: a leftover eight-candidate cache short-circuited the bank
    build and the identical command refused in 4.6s where clean runs certify
    in about 26s, which is a pinned exit code decided by whether someone ran
    the eval before. And the worse half, the reason this is guarded rather
    than documented: that file is keyed by slate date and pool signature, so
    a REAL build for the same date would read an eval's bank. runs/ is NOT
    guarded wholesale -- it holds live run directories and the promotion
    pointer, and snapshotting those would fight a concurrent build (the
    multi-session contract's BUILD role owns them). Only the bank caches,
    which are derived data that any build can rebuild, are covered.
    """

    ROOTS = ("data/slates", "outputs")
    # Derived, per-slate, safe to delete: rebuilding one costs a slice.
    FILE_GLOBS = ("runs/bank_cache_*.json",)

    def __init__(self):
        self.backup = Path(tempfile.mkdtemp(prefix="eval_surface_guard_"))
        for root in self.ROOTS:
            source = REPO / root
            if source.exists():
                shutil.copytree(source, self.backup / root, symlinks=True)
        self.saved_files = {}
        for pattern in self.FILE_GLOBS:
            for live in REPO.glob(pattern):
                if not live.is_file():
                    continue
                rel = live.relative_to(REPO)
                target = self.backup / "_files" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live, target)
                self.saved_files[rel] = target

    def restore(self) -> list:
        actions = []
        for root in self.ROOTS:
            live_root, saved_root = REPO / root, self.backup / root
            saved = {p.relative_to(saved_root) for p in saved_root.rglob("*")} if saved_root.exists() else set()
            live = {p.relative_to(live_root) for p in live_root.rglob("*")} if live_root.exists() else set()
            for rel in sorted(live - saved, key=lambda p: -len(p.parts)):
                target = live_root / rel
                actions.append(f"removed {root}/{rel}")
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            for rel in saved:
                source, target = saved_root / rel, live_root / rel
                if source.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not target.exists() or target.read_bytes() != source.read_bytes():
                    actions.append(f"restored {root}/{rel}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        for pattern in self.FILE_GLOBS:
            for live in sorted(REPO.glob(pattern)):
                if not live.is_file():
                    continue
                rel = live.relative_to(REPO)
                if rel not in self.saved_files:
                    actions.append(f"removed {rel}")
                    live.unlink(missing_ok=True)
        for rel, source in sorted(self.saved_files.items()):
            target = REPO / rel
            if not target.exists() or target.read_bytes() != source.read_bytes():
                actions.append(f"restored {rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        shutil.rmtree(self.backup, ignore_errors=True)
        return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", type=int, default=None, help="run a single eval id")
    parser.add_argument("--keep", action="store_true", help="keep scratch dirs for inspection")
    args = parser.parse_args()
    spec_path = EVALS_DIR / "evals.json"
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"run_evals: cannot read {spec_path}: {exc}")
        return 3
    evals = [e for e in payload["evals"] if args.only is None or e["id"] == args.only]
    if not evals:
        print(f"run_evals: no eval with id {args.only}")
        return 3
    guard = RepoSurfaceGuard()
    any_failed = False
    try:
        for spec in evals:
            verdict = run_eval(spec, args.keep)
            status = "PASS" if not verdict["failures"] else "FAIL"
            any_failed = any_failed or bool(verdict["failures"])
            print(f"{status}  eval {spec['id']}: {spec['name']}")
            for failure in verdict["failures"]:
                print(f"      {failure}")
            if args.keep:
                print(f"      scratch: {verdict['work']}")
    finally:
        for action in guard.restore():
            print(f"surface-guard: {action}")
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
