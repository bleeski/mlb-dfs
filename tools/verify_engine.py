"""Run the complete offline acceptance suite and save machine-readable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
NEW_PATHS = [
    "mlb_engine/production",
    "tools/dfs.py",
    "tools/bootstrap_engine.py",
    "tools/verify_engine.py",
    "tools/benchmark_engine.py",
    "tests/test_production.py",
    "tests/test_greenfield_regressions.py",
    "tests/conftest.py",
]


def main() -> int:
    python = (
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if Path(sys.executable).resolve() != python.resolve():
        if not python.exists():
            print("Setup needed: python tools/bootstrap_engine.py")
            return 2
        return subprocess.call(
            [str(python), "-B", str(Path(__file__).resolve()), *sys.argv[1:]]
        )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (
        args.output or ROOT / ".tmp" / ("verification_" + uuid.uuid4().hex[:8])
    ).resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTHONUTF8="1"
    )
    source = []
    for folder in ("mlb_engine", "tools", "tests", "skills/generate-lineups/scripts"):
        source.extend(sorted((ROOT / folder).rglob("*.py")))

    def fingerprint():
        return hashlib.sha256(
            b"".join(
                p.relative_to(ROOT).as_posix().encode() + p.read_bytes() for p in source
            )
        ).hexdigest()

    before = fingerprint()
    stages = []
    commands = [
        (
            "full_pytest",
            [
                str(python),
                "-B",
                "-m",
                "pytest",
                "tests",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(output / "temp"),
                "--junitxml",
                str(output / "pytest.xml"),
            ],
        ),
        (
            "undefined_names",
            [
                str(python),
                "-m",
                "ruff",
                "check",
                "mlb_engine",
                "tools",
                "tests",
                "skills/generate-lineups/scripts",
                "--select",
                "F821,F822,F823",
            ],
        ),
        ("production_lint", [str(python), "-m", "ruff", "check", *NEW_PATHS]),
        (
            "production_format",
            [str(python), "-m", "ruff", "format", "--check", *NEW_PATHS],
        ),
        ("git_diff_check", ["git", "diff", "--check"]),
        (
            "git_diff_check_crlf",
            ["git", "-c", "core.whitespace=cr-at-eol", "diff", "--check"],
        ),
    ]
    for name, command in commands:
        print(f"Running {name}; detailed output is being saved.", flush=True)
        start = time.perf_counter()
        with (output / (name + ".log")).open("wb") as log:
            result = subprocess.run(
                command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        stages.append(
            {
                "name": name,
                "exit_code": result.returncode,
                "seconds": time.perf_counter() - start,
            }
        )
    compile_errors = []
    for index, path in enumerate(source):
        try:
            py_compile.compile(
                str(path), cfile=str(output / "compiled" / f"{index}.pyc"), doraise=True
            )
        except py_compile.PyCompileError as exc:
            compile_errors.append(str(exc))
    after = fingerprint()
    # Preserve pre-existing downloaded CSVs, including their original CRLF bytes.
    # The ordinary check still runs and its failure remains visible in the report.
    raw_diff = next(s for s in stages if s["name"] == "git_diff_check")
    violations = set(
        re.findall(
            r"^(.+?):\d+: trailing whitespace\.$",
            (output / "git_diff_check.log").read_text(
                encoding="utf-8", errors="replace"
            ),
            re.MULTILINE,
        )
    )
    protected = {
        "data/reference/expected_stats_batting.csv",
        "data/reference/expected_stats_pitching.csv",
    }
    baseline = ROOT / "docs/greenfield/2026-09-09/raw_artifact_hashes.json"
    hashes = (
        {r["path"]: r["sha256"] for r in json.loads(baseline.read_text())}
        if baseline.exists()
        else {}
    )
    preserved_crlf_only = (
        raw_diff["exit_code"] != 0
        and bool(violations)
        and violations <= protected
        and all(
            hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == hashes.get(p)
            for p in violations
        )
        and next(s for s in stages if s["name"] == "git_diff_check_crlf")["exit_code"]
        == 0
    )
    report = {
        "passed": all(
            s["exit_code"] == 0
            or (s["name"] == "git_diff_check" and preserved_crlf_only)
            for s in stages
        )
        and not compile_errors
        and before == after,
        "stages": stages,
        "compiled_files": len(source),
        "compile_errors": compile_errors,
        "source_before_sha256": before,
        "source_after_sha256": after,
        "source_unchanged_during_verification": before == after,
        "preexisting_crlf_files_preserved": sorted(violations)
        if preserved_crlf_only
        else [],
        "output": str(output),
    }
    (output / "verification.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
