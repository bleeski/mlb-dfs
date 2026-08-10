#!/usr/bin/env python3
"""claim.py -- the multi-session claim protocol as one command (R19).

CLAUDE.md's multi-session contract is the authority; this tool is its hands.
Cowork sessions sharing this repo coordinate through the filesystem alone, and
the one atomic primitive that survives every mount is mkdir: it creates the
claim directory or it fails because another session already did. Everything
else here is bookkeeping around that single fact.

State lives in claims/<name>/owner.json (role, scope, taken_utc,
released_utc). A claim is HELD while released_utc is null. Release also
touches a RELEASED marker file, so a plain directory listing answers the
question; owner.json stays authoritative because creating a file never needs
the delete grant that removing one does.

A hand-written RELEASED marker therefore does NOT release a claim, and the
precedence cannot be flipped to make it: `take` clears the marker with
unlink, which fails on this mount, so a marker-authoritative rule would make
every re-taken claim read as free while a session held it. Failing closed on
a stale HELD is the safe direction; failing open on a live claim is not. What
the tool owes the reader instead is loudness, so `check` and `sweep` name any
claim carrying a marker with released_utc still null and print the one
command that completes it (R102, after a marker-only release left an engine
claim reading HELD for three hours on 2026-08-10).
Re-taking a released claim rewrites owner.json, which is check-then-write
rather than atomic; that is acceptable for an advisory tripwire, and the
atomic mkdir still guards the case that matters, the first take.

Naming: ``take ledger|inbox|engine`` appends _<utc-date>; a resource that
already starts with ``slate_`` is used verbatim, because a slate claim
carries its date in its own name (claims/slate_<date>_<tag>, exactly as
SKILL.md instructs). Yesterday's claims are stale by definition; a stale
claim today is Ben's to arbitrate, and nothing here ever deletes or takes
over another session's claim.

``dirt`` is the session-start foreign-dirt gate: it classifies ``git status
--porcelain`` against a role's write set. Run it BEFORE your first write; at
that moment every dirty path inside your set is foreign by definition. The
fragment inboxes (ledger/inbox/, docs/backlog_inbox/) never block anyone:
pending fragments are the protocol working, not a conflict. BUILD's write
surfaces (runs/, outputs/, data/slates/) are gitignored and invisible to
porcelain, so BUILD's real protection is the slate claim, not this gate.

Exit codes, matching preflight's conventions:
  0  ok: took, re-took, released, free, or no blocking dirt
  2  held by another session, or foreign dirt inside the write set
  3  usage or IO error

Deterministic bookkeeping. Nothing here locks anything for real; a session
that skips the protocol is stopped by nothing. The contract makes violations
loud, never impossible.

Usage:
    python tools/claim.py take slate_2026-07-29_1905 --role BUILD --scope "main slate"
    python tools/claim.py take ledger --role ARCHIVE --scope "job 1 mining"
    python tools/claim.py check [ledger]
    python tools/claim.py release ledger
    python tools/claim.py sweep
    python tools/claim.py dirt --role DEV
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ROLES = ("BUILD", "ARCHIVE", "DEV", "SOLO")

# Tracked write surfaces per role, for `dirt`. Prefix match on repo-relative
# posix paths. BUILD's surfaces are gitignored, hence the empty tuple.
WRITE_SETS = {
    "BUILD": (),
    "ARCHIVE": ("ledger/", "data/archive/", "data/standings/", "data/reference/"),
    "DEV": ("mlb_engine/", "tools/", "tests/", "docs/", "skills/", "CLAUDE.md",
            "MLB_Classic.md", "MANIFEST.md", ".gitignore", ".gitattributes",
            "requirements.txt"),
}
WRITE_SETS["SOLO"] = tuple(sorted(set(WRITE_SETS["ARCHIVE"]) | set(WRITE_SETS["DEV"])))

# Create-only surfaces every role may write; pending files here are the
# fragment protocol working, never a conflict.
FRAGMENT_PREFIXES = ("ledger/inbox/", "docs/backlog_inbox/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _claims_dir(root: Path) -> Path:
    return Path(root) / "claims"


def _claim_name(resource: str, date: str) -> str:
    resource = str(resource).strip().strip("/")
    if resource.startswith("slate_"):
        return resource  # a slate claim carries its date in its own name
    return f"{resource}_{date}"


def _read_owner(claim: Path) -> dict:
    try:
        return json.loads((claim / "owner.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_owner(claim: Path, payload: dict) -> None:
    (claim / "owner.json").write_text(
        json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def _is_held(claim: Path) -> bool:
    owner = _read_owner(claim)
    if owner:
        return not owner.get("released_utc")
    # No readable owner.json: a bare directory is treated as held, because
    # assuming a half-written claim is free is the wrong default.
    return not (claim / "RELEASED").exists()


def _release_incomplete(claim: Path) -> bool:
    """A RELEASED marker sits here while owner.json still reads held.

    Someone released by hand instead of through `release`. The claim is very
    likely free, but the tool must not assume it (see the module docstring on
    why the precedence cannot be flipped), and it must not stay quiet either.
    """
    return (claim / "RELEASED").exists() and _is_held(claim)


def _incomplete_note(name: str) -> str:
    return (f"         RELEASED marker present but owner.json still holds it: "
            f"a hand-written marker does not release. Complete it with "
            f"`python tools/claim.py release {name}`")


def _is_stale(name: str) -> bool:
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", name)
    return bool(dates) and max(dates) < _today()


def cmd_take(args: argparse.Namespace) -> int:
    name = _claim_name(args.resource, args.date or _today())
    claims = _claims_dir(args.root)
    claims.mkdir(exist_ok=True)
    target = claims / name
    payload = {"role": args.role, "scope": args.scope or "",
               "taken_utc": _utc_now(), "released_utc": None}
    try:
        target.mkdir()
    except FileExistsError:
        if _is_held(target):
            owner = _read_owner(target)
            print(f"HELD  {name} by {owner.get('role', '?')} since "
                  f"{owner.get('taken_utc', '?')}"
                  + (f"  scope: {owner['scope']}" if owner.get("scope") else ""))
            if _release_incomplete(target):
                print(_incomplete_note(name))
            if getattr(args, "beacon", False):
                print("beacon already lit: a parallel build is running; builds "
                      "never block builds, so proceed and note it to Ben")
                return 0
            print("never delete or take over another session's claim; a stale "
                  "claim is Ben's to arbitrate")
            return 2
        _write_owner(target, payload)
        try:
            (target / "RELEASED").unlink()
        except OSError:
            pass  # marker removal needs the delete grant; owner.json is authoritative
        print(f"re-took {name} as {args.role} (release-then-retake is "
              f"check-then-write, not atomic; the mkdir guards the first take)")
        return 0
    _write_owner(target, payload)
    print(f"took {name} as {args.role}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    claims = _claims_dir(args.root)
    if args.resource:
        name = _claim_name(args.resource, args.date or _today())
        target = claims / name
        if not target.exists():
            print(f"free  {name} (no claim)")
            return 0
        if _is_held(target):
            owner = _read_owner(target)
            print(f"HELD  {name} by {owner.get('role', '?')} since "
                  f"{owner.get('taken_utc', '?')}")
            if _release_incomplete(target):
                print(_incomplete_note(name))
            return 2
        print(f"free  {name} (released)")
        return 0
    if not claims.is_dir():
        print("no claims")
        return 0
    rows = sorted(p for p in claims.glob("*") if p.is_dir())
    if not rows:
        print("no claims")
        return 0
    for claim in rows:
        owner = _read_owner(claim)
        held = _is_held(claim)
        state = "HELD" if held else "released"
        stale = "  STALE (Ben arbitrates)" if held and _is_stale(claim.name) else ""
        print(f"{state:<8} {claim.name}  role={owner.get('role', '?')} "
              f"taken={owner.get('taken_utc', '?')}{stale}")
        if _release_incomplete(claim):
            print(_incomplete_note(claim.name))
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    name = _claim_name(args.resource, args.date or _today())
    target = _claims_dir(args.root) / name
    if not target.exists():
        print(f"ERROR  no claim at claims/{name}", file=sys.stderr)
        return 3
    owner = _read_owner(target)
    owner.setdefault("role", "?")
    owner["released_utc"] = _utc_now()
    _write_owner(target, owner)
    (target / "RELEASED").touch()
    print(f"released {name}")
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    claims = _claims_dir(args.root)
    if not claims.is_dir():
        print("no stale held claims")
        return 0
    stale = [c for c in sorted(claims.glob("*"))
             if c.is_dir() and _is_held(c) and _is_stale(c.name)]
    if not stale:
        print("no stale held claims")
        return 0
    for claim in stale:
        owner = _read_owner(claim)
        print(f"STALE  {claim.name}  role={owner.get('role', '?')} "
              f"taken={owner.get('taken_utc', '?')}  Ben arbitrates; nothing "
              f"is deleted here")
        if _release_incomplete(claim):
            print(_incomplete_note(claim.name))
    return 0


def _porcelain(root: Path) -> str:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise OSError(f"git status failed: {proc.stderr.strip()}")
    return proc.stdout


def cmd_dirt(args: argparse.Namespace) -> int:
    write_set = WRITE_SETS[args.role]
    try:
        text = args.porcelain if args.porcelain is not None else _porcelain(args.root)
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3
    blocks: list[str] = []
    for line in text.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:  # rename: the destination is the live path
            path = path.split(" -> ", 1)[1].strip().strip('"')
        posix = path.replace("\\", "/")
        if posix.startswith("claims/"):
            continue
        if any(posix.startswith(prefix) for prefix in FRAGMENT_PREFIXES):
            print(f"frag   (awaiting merge, never blocks): {posix}")
            continue
        if any(posix == p or posix.startswith(p) for p in write_set):
            print(f"BLOCK  (inside {args.role} write set, foreign until this "
                  f"session wrote it): {posix}")
            blocks.append(posix)
        else:
            print(f"note   (outside {args.role} write set, report and leave "
                  f"alone): {posix}")
    if args.role == "BUILD":
        print("note   BUILD's write surfaces (runs/, outputs/, data/slates/) "
              "are gitignored; the slate claim is the protection, not this gate")
    if blocks:
        print(f"BLOCKED  {len(blocks)} dirty path(s) inside the {args.role} "
              f"write set; name the owner before touching anything")
        return 2
    print(f"clean for {args.role}: no foreign dirt inside the write set")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="the multi-session claim protocol as one command")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("take", help="take a claim (atomic mkdir)")
    p.add_argument("resource", help="ledger | inbox | engine | slate_<date>_<tag>")
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--scope", help="one line: what this session is doing")
    p.add_argument("--date", help="UTC date suffix; defaults to today")
    p.add_argument("--beacon", action="store_true",
                   help="advisory presence marker: a claim someone else holds "
                        "is noted and exits 0 instead of 2. BUILD lights slate "
                        "beacons this way, because builds never block builds; "
                        "engine, ledger, and inbox stay mutexes and never use "
                        "this flag.")

    p = sub.add_parser("check", help="list claims, or one resource's state")
    p.add_argument("resource", nargs="?")
    p.add_argument("--date")

    p = sub.add_parser("release",
                       help="write released_utc and touch the RELEASED marker")
    p.add_argument("resource")
    p.add_argument("--date")

    sub.add_parser("sweep", help="report stale held claims; deletes nothing")

    p = sub.add_parser("dirt", help="session-start foreign-dirt gate")
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--porcelain", help=argparse.SUPPRESS)  # test seam

    args = ap.parse_args(argv)
    handler = {"take": cmd_take, "check": cmd_check, "release": cmd_release,
               "sweep": cmd_sweep, "dirt": cmd_dirt}[args.cmd]
    try:
        return handler(args)
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
