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

VERSION = "v1.1"
ENGINE_DEPS = ("numpy", "pandas", "scipy")
LOCK_NAME = "requirements.lock"
VENDORED_DIRNAME = ".pylibs"
_PIN_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)")


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


def milp_available() -> bool:
    try:
        from scipy.optimize import milp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def evaluate(installed: Dict[str, Optional[str]], pins: Dict[str, str],
             milp_ok: bool) -> Dict[str, object]:
    """Pure decision: warm iff every engine dep imports at its pinned version
    and the solver entry point resolves. Tested directly; keep it pure."""
    missing = [n for n in ENGINE_DEPS if installed.get(n) is None]
    unpinned = [n for n in ENGINE_DEPS if n not in pins]
    mismatched = [
        f"{n} {installed[n]} != {pins[n]}"
        for n in ENGINE_DEPS
        if installed.get(n) is not None and n in pins and installed[n] != pins[n]
    ]
    warm = not missing and not mismatched and not unpinned and milp_ok
    return {"warm": warm, "missing": missing, "mismatched": mismatched,
            "unpinned": unpinned, "milp_ok": milp_ok}


def _install_command(lock_path: Path) -> list:
    return [sys.executable, "-m", "pip", "install", "-r", str(lock_path),
            "--require-hashes", "--break-system-packages", "-q"]


def _reprobe_subprocess() -> bool:
    """Fresh interpreter, because this process's failed imports are cached."""
    code = ("import numpy, pandas, scipy; from scipy.optimize import milp; "
            "print(numpy.__version__, pandas.__version__, scipy.__version__)")
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True)
    return result.returncode == 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the engine runtime against requirements.lock; "
                    "warm exits 0 without touching pip.")
    parser.add_argument("--install", action="store_true",
                        help="on a cold probe, run the locked install and re-probe")
    parser.add_argument("--lock", default=None,
                        help="lock file path (default: repo requirements.lock)")
    args = parser.parse_args(argv)

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
    verdict = evaluate(installed_versions(), pins, milp_available())
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
        ["milp unavailable" if not verdict["milp_ok"] else ""])
    detail = "; ".join(p for p in detail.split("; ") if p)
    if vendored is not None:
        detail += f" (checked {vendored} first, not sufficient)"
    if not args.install:
        print(f"env cold: {detail}")
        print("install: " + " ".join(_install_command(lock_path)))
        return 2

    print(f"env cold: {detail}; installing from {lock_path.name}")
    result = subprocess.run(_install_command(lock_path))
    if result.returncode != 0:
        print(f"env_probe: locked install failed (pip exit {result.returncode})")
        return 2
    if not _reprobe_subprocess():
        print("env_probe: install ran but the re-probe still fails; stop and say so")
        return 2
    print("env warm after locked install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
