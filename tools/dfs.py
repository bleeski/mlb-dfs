"""Single operator entry point. Re-executes in the pinned local environment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def environment() -> None:
    python = (
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    # R338 step 7, XS fix. This compared the two INTERPRETER paths resolved, and
    # on POSIX a venv's `bin/python` is a symlink to the base binary, so both
    # sides resolve to the same file whether or not the caller is inside the
    # venv. The guard then read "already in it" for a plain `python3
    # tools/dfs.py` and ran the workflow against the system interpreter with
    # none of the pinned packages -- the one thing this function exists to
    # prevent. `sys.prefix` is the venv root inside a venv and the base prefix
    # outside one, which is the fact being asked about, and it needs no symlink
    # resolution to answer it.
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        if not python.exists():
            raise SystemExit("Setup needed: python tools/bootstrap_engine.py")
        env = dict(
            os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTHONUTF8="1"
        )
        raise SystemExit(
            subprocess.call(
                [str(python), "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
                env=env,
            )
        )
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    environment()
    from mlb_engine.production.contracts import Controls, EvidenceBundle, EdgeGateOutput
    from mlb_engine.production.demo import execute_demo
    from mlb_engine.production.evidence import UnavailableLiveProvider
    from mlb_engine.production.state import StateStore, atomic_write, json_bytes
    from mlb_engine.production.workflow import error_text, run, runtime_identity

    parser = argparse.ArgumentParser(
        description="Verified DraftKings MLB export workflow; platform upload remains manual."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check the pinned runtime and solver")
    demo = sub.add_parser(
        "demo", help="Run fictional initial-build and late-scratch fixtures"
    )
    demo.add_argument("--output", type=Path)
    schema = sub.add_parser(
        "schemas", help="Write the strict input schema and documented example"
    )
    schema.add_argument(
        "--output", type=Path, default=ROOT / "outputs/greenfield_schemas"
    )
    sub.add_parser(
        "live-provider", help="Check whether an authorized live provider exists"
    )
    intake = sub.add_parser(
        "intake",
        help="Create factual input sheets with authoritative IDs already filled",
    )
    intake.add_argument("--salary", type=Path, required=True)
    intake.add_argument("--entries", type=Path, required=True)
    intake.add_argument("--output", type=Path, required=True)
    freeze = sub.add_parser(
        "freeze", help="Validate input sheets and freeze their evidence bundle"
    )
    freeze.add_argument("--input", type=Path, required=True)
    watch = sub.add_parser(
        "watch",
        help="Monitor supplied local evidence snapshots; no live connector or platform upload",
    )
    watch.add_argument("--salary", type=Path, required=True)
    watch.add_argument("--evidence", type=Path, required=True)
    watch.add_argument("--output", type=Path, default=ROOT / "outputs/production")
    watch.add_argument("--scope", required=True)
    watch.add_argument("--entry-id", action="append", required=True)
    watch.add_argument("--controls", type=Path)
    watch.add_argument("--interval", type=float, default=30)
    watch.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="0 runs until stopped; positive values bound the poll count",
    )
    for command in ("run", "late-swap"):
        p = sub.add_parser(command)
        p.add_argument("--salary", type=Path, required=True)
        p.add_argument("--entries", type=Path, required=True)
        p.add_argument("--evidence", type=Path, required=True)
        p.add_argument("--output", type=Path, default=ROOT / "outputs/production")
        p.add_argument("--controls", type=Path)
        p.add_argument("--baseline-only", action="store_true")
        if command == "late-swap":
            p.add_argument("--parent", type=Path, required=True)
            p.add_argument("--entry-id", action="append", required=True)
        p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
        p.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    for command in ("verify", "recover"):
        p = sub.add_parser(command)
        p.add_argument("--output", type=Path, default=ROOT / "outputs/production")
        p.add_argument("--scope", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = {"status": "ready", **runtime_identity()}
        elif args.command == "live-provider":
            UnavailableLiveProvider().read()
        elif args.command == "intake":
            from mlb_engine.production.intake import create_intake

            result = create_intake(args.salary, args.entries, args.output)
        elif args.command == "freeze":
            from mlb_engine.production.intake import freeze_intake

            result = freeze_intake(args.input)
        elif args.command == "watch":
            import time
            from mlb_engine.production.monitor import tick

            if args.interval < 5 or args.cycles < 0:
                raise ValueError(
                    "monitor interval must be at least five seconds; cycles must be nonnegative"
                )
            controls = (
                Controls.model_validate_json(args.controls.read_bytes())
                if args.controls
                else Controls()
            )

            def monitored_worker(salary, parent, evidence, output, **kwargs):
                destination = output / "invocations" / (uuid.uuid4().hex + ".json")
                destination.parent.mkdir(parents=True, exist_ok=True)
                command = [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve()),
                    "late-swap",
                    "--salary",
                    str(salary),
                    "--entries",
                    str(parent),
                    "--parent",
                    str(parent),
                    "--evidence",
                    str(evidence),
                    "--output",
                    str(output),
                    "--worker",
                    "--result-file",
                    str(destination),
                ]
                for eid in args.entry_id:
                    command.extend(["--entry-id", eid])
                if args.controls:
                    command.extend(["--controls", str(args.controls)])
                subprocess.run(
                    command,
                    timeout=controls.total_seconds + 15,
                    check=False,
                    stdout=subprocess.DEVNULL,
                )
                if not destination.exists():
                    raise RuntimeError("monitor worker exited without a durable result")
                return json.loads(destination.read_bytes())

            token, previous_notice, count = None, None, 0
            while args.cycles == 0 or count < args.cycles:
                try:
                    token, result = tick(
                        args.salary,
                        args.evidence,
                        args.output,
                        args.scope,
                        set(args.entry_id),
                        token,
                        controls,
                        runner=monitored_worker,
                    )
                except Exception as exc:
                    result = {
                        "status": "blocked",
                        "RELEASE_DECISION": "DO_NOT_UPLOAD",
                        "errors": [error_text(exc)],
                    }
                notice = json.dumps(
                    {
                        k: result.get(k)
                        for k in (
                            "status",
                            "export_sha256",
                            "errors",
                            "RELEASE_DECISION",
                        )
                    },
                    sort_keys=True,
                )
                if result["status"] != "unchanged" and notice != previous_notice:
                    print(json.dumps(result, indent=2), flush=True)
                    previous_notice = notice
                count += 1
                if args.cycles == 0 or count < args.cycles:
                    time.sleep(args.interval)
            return 0
        elif args.command == "schemas":
            args.output.mkdir(parents=True, exist_ok=True)
            for model in (Controls, EvidenceBundle, EdgeGateOutput):
                atomic_write(
                    args.output / (model.__name__ + ".schema.json"),
                    json_bytes(model.model_json_schema()),
                )
            result = {"status": "written", "output": str(args.output.resolve())}
        elif args.command == "demo":
            output = args.output or ROOT / "outputs" / (
                "verified_demo_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + "_"
                + uuid.uuid4().hex[:6]
            )
            full = execute_demo(output)
            result = {
                k: full[k]
                for k in ("status", "label", "raw_inputs_unchanged")
                if k in full
            }
            result["result_file"] = str(output.resolve() / "demo_result.json")
            result["safe_export"] = full.get("late_swap", {}).get("safe_export")
        elif args.command in {"verify", "recover"}:
            store = StateStore(args.output)
            run_id = store.current(args.scope)
            if not run_id:
                raise ValueError("no committed export for this scope")
            store.verify_bundle(run_id)
            safe = store.recover_safe(args.scope)
            diagnostic = json.loads(
                (store.root / "runs" / run_id / "final/diagnostics.json").read_bytes()
            )
            expired = datetime.now(timezone.utc) >= datetime.fromisoformat(
                diagnostic["recheck_at"]
            )
            result = {
                "status": "integrity_verified",
                "safe_export": str(safe),
                "valid_as_of": diagnostic["valid_as_of"],
                "recheck_at": diagnostic["recheck_at"],
                "RELEASE_DECISION": "DO_NOT_UPLOAD"
                if expired
                else diagnostic["RELEASE_DECISION"],
                "freshness_recheck_required": expired,
            }
        else:
            controls = (
                Controls.model_validate_json(args.controls.read_bytes())
                if args.controls
                else Controls()
            )
            if args.baseline_only:
                controls = controls.model_copy(update={"enhance": False})
            if not args.worker:
                # The worker's shared solve deadline is supplemented by a process
                # boundary so native solver or filesystem stalls cannot hang the operator.
                result_file = (
                    args.output.resolve() / "invocations" / (uuid.uuid4().hex + ".json")
                )
                result_file.parent.mkdir(parents=True, exist_ok=True)
                raw_args = list(argv) if argv is not None else sys.argv[1:]
                command = [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve()),
                    *raw_args,
                    "--worker",
                    "--result-file",
                    str(result_file),
                ]
                try:
                    subprocess.run(
                        command,
                        timeout=controls.total_seconds + 15,
                        check=False,
                        stdout=subprocess.DEVNULL,
                    )
                except subprocess.TimeoutExpired:
                    result = {
                        "status": "blocked",
                        "RELEASE_DECISION": "DO_NOT_UPLOAD",
                        "errors": [
                            "Hard process deadline reached; committed safe exports remain available. Run recover with the prior scope."
                        ],
                    }
                else:
                    result = (
                        json.loads(result_file.read_bytes())
                        if result_file.exists()
                        else {
                            "status": "blocked",
                            "RELEASE_DECISION": "DO_NOT_UPLOAD",
                            "errors": ["Worker exited without a durable result."],
                        }
                    )
            else:
                result = run(
                    args.salary,
                    args.entries,
                    args.evidence,
                    args.output,
                    controls=controls,
                    authorized_entry_ids=set(args.entry_id)
                    if args.command == "late-swap"
                    else None,
                    parent=args.parent if args.command == "late-swap" else None,
                )
                if args.result_file:
                    atomic_write(args.result_file, json_bytes(result))
        print(json.dumps(result, indent=2, allow_nan=False))
        return 2 if result.get("status") in {"blocked", "failed"} else 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "RELEASE_DECISION": "DO_NOT_UPLOAD",
                    "errors": [error_text(exc)],
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
