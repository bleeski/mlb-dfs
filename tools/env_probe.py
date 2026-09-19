"""Probe-then-install for the engine runtime (R7). v1.1

The rule this tool enforces: a warm session never touches pip. The probe
first checks the repo's own `.pylibs/` for a vendored copy of the engine deps
(R42(a): three live incidents, 2026-08-01 and twice more on 2026-08-03, were
this tool recommending -- or running -- an install that reliably fails
ENOSPC in the Cowork sandbox's small `$HOME` volume, while a working copy
already sat one directory over). If `.pylibs` covers everything, it goes on
sys.path and the probe is warm with zero installs and zero network. Only
when `.pylibs` genuinely does not cover the pins does the probe fall through
to comparing each __version__ against requirements.lock and confirming
scipy.optimize.milp resolves. All green is exit 0 in about a second.
Anything else prints the one install command (or runs it under --install) so
a cold sandbox becomes the locked environment, never whatever PyPI resolves
that day.

Exit codes: 0 warm (or --install made it warm); 2 cold, or install failed to
produce the locked environment; 3 the lock file is missing or unparseable,
which is a repo problem, not an environment problem — regenerate per the lock
header, never fall back to an unpinned resolve here.

Transitive pins in the lock exist for cold installs; warmth is judged on the
engine deps alone, so a sandbox carrying a newer pytz is warm, not dirty.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

VERSION = "v1.2"
ENGINE_DEPS = ("numpy", "pandas", "scipy")

# R353. The gate imports these; `tests/conftest.py`,
# `tests/test_greenfield_regressions.py` and `tests/test_production.py` all fail
# to LOAD without them, and the gate then prints "test suite FAILED", which
# reads as a code defect and is a missing dependency. Before R353 the lock did
# not carry them at all, so a *successful* install still could not reach PASS.
# Checked by import name, not by pinned version: a host carrying a newer pytest
# runs the same tests, where a newer numpy does not run the same solver.
TEST_DEPS = ("pytest", "pydantic")

# The interpreters `requirements.lock` carries wheel hashes for. Adding a host
# outside this set means adding its hashes to the lock, never `--no-deps` and
# never an unpinned fallback resolve.
SUPPORTED_CP_TAGS = ("cp310", "cp311", "cp313")

LOCK_NAME = "requirements.lock"
VENDORED_DIRNAME = ".pylibs"
_PIN_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s\\;]+)")
_HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def interpreter_tag() -> str:
    """This interpreter's cp tag, e.g. `cp311`. R353.

    pip's hash failure names neither the host's tag nor the lock's, so the
    operator reads "someone may have tampered with them" when the real fact is
    "cp311 host, cp310 lock". Every message this tool prints about hashes says
    the tag.
    """
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def vendored_pylibs(root: Path) -> Optional[Path]:
    """<root>/.pylibs if it exists and holds at least one entry.

    R42(a): a prior session's `tools/wheel_fetch.py` plus an extract, or a
    prior `--install`, can leave a fully-working, importable copy of the
    engine deps here. It is a legitimate warm source, not a last resort --
    checking it costs one directory listing; checking site-packages only
    after a failed pip install costs the rest of the T-5 window (2026-08-03,
    twice).
    """
    candidate = root / VENDORED_DIRNAME
    try:
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    except OSError:
        return None
    return None


def ensure_vendored_on_path(root: Path) -> Optional[Path]:
    """Put `.pylibs` at the front of sys.path if it looks usable; return it.

    Front, not back: a vendored copy that exists at all is the version this
    repo already validated (see `.pylibs/*.dist-info`), and it wins over
    whatever the ambient site-packages happens to carry -- the same
    resolution-authority argument that makes requirements.lock, not PyPI's
    latest, the source of truth for a cold install.
    """
    # The explicit project runtime owns its ABI and pins. An old Linux .pylibs
    # directory must not shadow Windows wheels in the verified virtualenv.
    if Path(sys.prefix).resolve() == (root / ".venv").resolve():
        return None
    vendored = vendored_pylibs(root)
    if vendored is not None:
        path_str = str(vendored)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    return vendored


def parse_lock(text: str) -> Dict[str, str]:
    """Return {distribution_name: pinned_version} from lock text."""
    pins: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--hash"):
            continue
        match = _PIN_RE.match(line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def parse_lock_hashes(text: str) -> Dict[str, list]:
    """Return {distribution_name: [sha256, ...]} from lock text. R353.

    A pin owns every `--hash` line up to the next pin, whether they sit on the
    same logical line behind backslash continuations or on their own lines. The
    lock deliberately carries SEVERAL hashes per binary pin -- one per supported
    interpreter -- because pip accepts the wheel matching any one of them. Before
    R353 it carried one, belonging to cp310, and `--require-hashes` turned every
    other host into a hard failure.
    """
    hashes: Dict[str, list] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PIN_RE.match(stripped)
        if match:
            current = match.group(1).lower()
            hashes.setdefault(current, [])
        if current is not None:
            hashes[current].extend(_HASH_RE.findall(stripped))
    return hashes


def installed_versions() -> Dict[str, Optional[str]]:
    """Import each engine dep in-process; None where the import fails."""
    found: Dict[str, Optional[str]] = {}
    for name in ENGINE_DEPS:
        try:
            module = __import__(name)
            found[name] = str(getattr(module, "__version__", "unknown"))
        except ImportError:
            found[name] = None
    return found


def test_deps_present() -> Dict[str, bool]:
    """Import each test dep in-process. R353. Importability only: see TEST_DEPS."""
    return {name: _importable(name) for name in TEST_DEPS}


def _importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def milp_available() -> bool:
    try:
        from scipy.optimize import milp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def evaluate(installed: Dict[str, Optional[str]], pins: Dict[str, str],
             milp_ok: bool,
             test_deps: Optional[Dict[str, bool]] = None) -> Dict[str, object]:
    """Pure decision: warm iff every engine dep imports at its pinned version,
    the solver entry point resolves, and every test dep imports. Tested
    directly; keep it pure.

    R353 added the test-dep tier. `test_deps` defaults to None, meaning NOT
    PROBED, and a caller that does not probe them gets the pre-R353 answer
    rather than a silent pass -- the callers that matter (main, the gate) pass
    them. A session whose engine deps are warm while pytest is absent used to
    read "env warm" here and then "test suite FAILED" from the gate three
    minutes later, which is the confusion this tier exists to end.
    """
    missing = [n for n in ENGINE_DEPS if installed.get(n) is None]
    unpinned = [n for n in ENGINE_DEPS if n not in pins]
    mismatched = [
        f"{n} {installed[n]} != {pins[n]}"
        for n in ENGINE_DEPS
        if installed.get(n) is not None and n in pins and installed[n] != pins[n]
    ]
    missing_test = ([n for n in TEST_DEPS if not test_deps.get(n)]
                    if test_deps is not None else [])
    warm = (not missing and not mismatched and not unpinned and milp_ok
            and not missing_test)
    return {"warm": warm, "missing": missing, "mismatched": mismatched,
            "unpinned": unpinned, "milp_ok": milp_ok,
            "missing_test_deps": missing_test}


VENV_DIRNAME = ".venv"


def venv_python(root: Path) -> Path:
    """Where a repo-local virtualenv puts its interpreter, per platform."""
    if sys.platform == "win32":
        return root / VENV_DIRNAME / "Scripts" / "python.exe"
    return root / VENV_DIRNAME / "bin" / "python"


def ensure_venv(root: Path) -> tuple:
    """Create `<root>/.venv` if absent; return (python_path, created). R353.

    Why a virtualenv rather than the system interpreter. `--require-hashes`
    refuses the install unless EVERY transitive requirement is pinned, which
    includes `packaging` (pytest needs it). Debian ships `packaging` into the
    system interpreter with no RECORD file, so pip cannot uninstall it to honour
    that pin: measured 2026-09-17, "Cannot uninstall packaging 24.0, RECORD file
    not found. Hint: The package was installed by debian." Leaving it unpinned
    instead fails the other way, on a clean runner that has no `packaging` at
    all. The two only conflict inside a SHARED interpreter. A virtualenv has
    neither problem, and it retires `--break-system-packages`, which was always
    a way of saying "write into a directory the OS owns".
    """
    python = venv_python(root)
    if python.exists():
        return python, False
    subprocess.run([sys.executable, "-m", "venv", str(root / VENV_DIRNAME)],
                   check=True)
    return python, True


def _install_command(lock_path: Path, python: Optional[Path] = None) -> list:
    """The one install command. `python` selects the interpreter to install into.

    `--break-system-packages` is present ONLY for the legacy system-interpreter
    path (a Cowork sandbox, or a host that predates `--venv`); a virtualenv is
    not a system interpreter and does not need it.
    """
    if python is not None:
        return [str(python), "-m", "pip", "install", "-r", str(lock_path),
                "--require-hashes", "-q"]
    return [sys.executable, "-m", "pip", "install", "-r", str(lock_path),
            "--require-hashes", "--break-system-packages", "-q"]


def _reprobe_subprocess(python: Optional[Path] = None) -> bool:
    """Fresh interpreter, because this process's failed imports are cached.

    R353: also re-probes the TEST deps. An install that leaves pytest missing is
    not a warm environment, and reporting it as one is what sent a session into
    the gate to be told `test suite FAILED`.
    """
    code = ("import numpy, pandas, scipy, pytest, pydantic; "
            "from scipy.optimize import milp; "
            "print(numpy.__version__, pandas.__version__, scipy.__version__)")
    exe = str(python) if python is not None else sys.executable
    result = subprocess.run([exe, "-c", code], capture_output=True, text=True)
    return result.returncode == 0


def _hash_coverage_note(lock_path: Path) -> str:
    """What to read a pip hash failure as. R353.

    pip's message on a hash mismatch is "THESE PACKAGES DO NOT MATCH THE HASHES
    FROM THE REQUIREMENTS FILE ... someone may have tampered with them". On
    2026-09-16 that cost a session several minutes of the wrong investigation:
    the bytes were authentic and the lock was single-platform. So whenever an
    install fails, say this host's tag and how many hashes each binary pin
    carries, which is the fact that distinguishes the two readings.
    """
    tag = interpreter_tag()
    try:
        hashes = parse_lock_hashes(lock_path.read_text(encoding="utf-8"))
    except OSError:
        return f"env_probe: host is {tag}; could not re-read {lock_path} to count hashes."
    thin = sorted(n for n in ENGINE_DEPS if len(hashes.get(n, [])) < 2)
    lines = [
        f"env_probe: this host is {tag}. If pip reported a HASH MISMATCH, read it "
        f"as a lock that does not cover {tag}, not as tampering: the binary "
        f"wheels differ per interpreter and each needs its own --hash line.",
        f"env_probe: {lock_path.name} is meant to cover "
        f"{', '.join(SUPPORTED_CP_TAGS)}.",
    ]
    if thin:
        lines.append(
            f"env_probe: single-hash pins found for {thin} -- that is the "
            f"pre-R353 shape and it fails on every interpreter but one. "
            f"Regenerate per the lock header.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Egress (R367, 2026-09-19)
# ---------------------------------------------------------------------------
# Three documents in this repo state a different answer to "can this host reach
# the odds API", and each was true where it was taken:
# `intake/paste_odds.py` says proxy-gated (R236), `SKILL.md:393-398` records 200
# (R316), the 2026-09-18 build fragment records 403. Egress is a property of the
# host and the environment's network policy, not of the repository, so a document
# is the wrong place to freeze one. Measure it once per session instead and let
# every doc point here.
#
# Two things this deliberately does NOT do. It never touches DraftKings -- that
# wall is absolute and reads are manual. And it never reports "blocked" for a
# host it merely failed to parse: an unknown result says so.
EGRESS_TIMEOUT_S = 6.0
#: Whole-probe cap. Six hosts are probed concurrently, so a blackholed network
#: costs this once rather than six times -- and a blackhole is exactly the case
#: the probe exists to detect, so it must not be the slow path.
EGRESS_TOTAL_CAP_S = 10.0

#: ``(label, url, client)``. The client matters and is reported: FanGraphs
#: answers 403 to urllib's fingerprint and 200 to curl (R317(a),
#: `.claude/rules/engine.md`), so probing it with the wrong one would report a
#: block that the fetcher does not actually hit.
EGRESS_TARGETS = (
    ("statsapi", "https://statsapi.mlb.com/api/v1/teams?sportId=1", "urllib"),
    ("odds", "https://api.the-odds-api.com/v4/sports", "urllib"),
    ("savant", "https://baseballsavant.mlb.com/leaderboard/expected_statistics", "urllib"),
    ("mlb-lineups", "https://www.mlb.com/starting-lineups", "urllib"),
    # The URL `tools/fetch_fangraphs_platoon.py:62` actually fetches. Probing
    # some other FanGraphs path measured a different thing: `/roster-resource/
    # depth-charts` answers 500 to curl while this one answers 200.
    ("fangraphs", "https://www.fangraphs.com/roster-resource/platoon-lineups/angels", "curl"),
    ("open-meteo", "https://api.open-meteo.com/v1/forecast?latitude=40&longitude=-74", "urllib"),
)


def _probe_one(label: str, url: str, client: str) -> str:
    """``label=<status>`` for one host. Never raises."""
    try:
        if client == "curl":
            out = subprocess.run(
                # A plain GET, not `-I` and not `-L`: measured 2026-09-19,
                # FanGraphs answers HEAD with 500 and GET with 200, and any
                # 3xx already proves the host answered. A probe reporting a
                # status the real fetcher never sees is worse than no probe.
                ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                 "--max-time", str(int(EGRESS_TIMEOUT_S)), url],
                capture_output=True, text=True, timeout=EGRESS_TIMEOUT_S + 2)
            code = (out.stdout or "").strip()
            return f"{label} {code}" if code.isdigit() and code != "000" else f"{label} unreachable"
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "mlb-dfs-egress-probe"})
        with urllib.request.urlopen(req, timeout=EGRESS_TIMEOUT_S) as resp:
            return f"{label} {resp.status}"
    except Exception as exc:  # noqa: BLE001 - every failure is a reading
        import urllib.error
        if isinstance(exc, urllib.error.HTTPError):
            # A 401 means reachable-without-a-key, which is NOT a block and is
            # the ordinary state of the odds API here; a 403 on CONNECT is.
            return f"{label} {exc.code}"
        if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) or \
                "timed out" in str(exc).lower():
            # Slow and blocked are different facts. Saying so stops a session
            # concluding "gated" from what was a busy host.
            return f"{label} timeout"
        return f"{label} unreachable"


def egress_line() -> str:
    """One line naming what this host could reach, just now.

    Concurrent, capped, and it never fails the caller: a probe that cannot
    answer says `unknown`, because "the probe broke" and "the host is blocked"
    are different facts and only one of them is about the network.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: Dict[str, str] = {}
    try:
        with ThreadPoolExecutor(max_workers=len(EGRESS_TARGETS)) as pool:
            futures = {pool.submit(_probe_one, *target): target[0]
                       for target in EGRESS_TARGETS}
            for future in as_completed(futures, timeout=EGRESS_TOTAL_CAP_S):
                label = futures[future]
                results[label] = future.result()
    except Exception:  # noqa: BLE001 - a cap hit is a reading, not a crash
        pass
    ordered = []
    for label, _url, client in EGRESS_TARGETS:
        text = results.get(label, f"{label} unknown")
        ordered.append(f"{text} ({client})" if client != "urllib" else text)
    return "egress: " + ", ".join(ordered)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the engine runtime against requirements.lock; "
                    "warm exits 0 without touching pip.")
    parser.add_argument("--install", action="store_true",
                        help="on a cold probe, run the locked install and re-probe")
    parser.add_argument("--venv", action="store_true",
                        help="install into <repo>/.venv instead of this "
                             "interpreter, creating it if absent (R353). Use this "
                             "anywhere the interpreter is shared with an OS "
                             "package manager, which is every Linux container.")
    parser.add_argument("--lock", default=None,
                        help="lock file path (default: repo requirements.lock)")
    parser.add_argument("--egress", action="store_true",
                        help="print one line naming what this host can reach "
                             "right now, and exit. Never touches DraftKings.")
    args = parser.parse_args(argv)

    if args.egress:
        print(egress_line())
        return 0

    root = repo_root()
    lock_path = Path(args.lock) if args.lock else root / LOCK_NAME
    if not lock_path.exists():
        print(f"env_probe: lock file missing: {lock_path}; regenerate per the "
              "lock header. Not falling back to an unpinned resolve.")
        return 3
    pins = parse_lock(lock_path.read_text(encoding="utf-8"))
    if not all(n in pins for n in ENGINE_DEPS):
        print(f"env_probe: lock file at {lock_path} does not pin all of "
              f"{ENGINE_DEPS}; regenerate per the lock header.")
        return 3

    vendored = ensure_vendored_on_path(root)
    verdict = evaluate(installed_versions(), pins, milp_available(),
                       test_deps=test_deps_present())
    if verdict["warm"]:
        versions = " ".join(f"{n} {pins[n]}" for n in ENGINE_DEPS)
        if vendored is not None:
            print(f"env warm (vendored at {vendored}): {versions}; milp OK; "
                  f"pip skipped. Other commands this session need "
                  f"PYTHONPATH={vendored} too -- a subprocess does not "
                  f"inherit this probe's sys.path.")
        else:
            print(f"env warm (site-packages): {versions}; milp OK; pip skipped")
        return 0

    detail = "; ".join(
        [f"missing {verdict['missing']}" if verdict["missing"] else ""] +
        [f"mismatched {verdict['mismatched']}" if verdict["mismatched"] else ""] +
        ["milp unavailable" if not verdict["milp_ok"] else ""] +
        [f"test deps missing {verdict['missing_test_deps']} (the gate cannot "
         f"load two suites without them)"
         if verdict["missing_test_deps"] else ""])
    detail = "; ".join(p for p in detail.split("; ") if p)
    if vendored is not None:
        detail += f" (checked {vendored} first, not sufficient)"
    if not args.install:
        print(f"env cold: {detail}")
        print("install: " + " ".join(_install_command(lock_path)))
        return 2

    target: Optional[Path] = None
    if args.venv:
        try:
            target, created = ensure_venv(root)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"env_probe: could not create {root / VENV_DIRNAME}: {exc}")
            return 2
        print(f"env cold: {detail}; installing from {lock_path.name} into "
              f"{VENV_DIRNAME}/ "
              f"({'created' if created else 'existing'}, host {interpreter_tag()})")
    else:
        print(f"env cold: {detail}; installing from {lock_path.name} "
              f"(host {interpreter_tag()})")

    result = subprocess.run(_install_command(lock_path, target))
    if result.returncode != 0:
        print(f"env_probe: locked install failed (pip exit {result.returncode})")
        print(_hash_coverage_note(lock_path))
        return 2
    if not _reprobe_subprocess(target):
        print("env_probe: install ran but the re-probe still fails; stop and say so")
        return 2
    if target is not None:
        # The caller's shell does not inherit this; say so rather than letting a
        # session install successfully and then run the gate on the wrong python.
        print(f"env warm after locked install into {VENV_DIRNAME}. "
              f"Every command this session runs must use {target}, or put "
              f"{target.parent} first on PATH.")
    else:
        print("env warm after locked install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
