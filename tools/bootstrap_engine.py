"""Install the pinned, free production runtime without changing global Python."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import venv


def main() -> int:
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        print("Install Python 3.11, 3.12, or 3.13, then run this command again.")
        return 2
    root = Path(__file__).resolve().parents[1]
    target = root / ".venv"
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(target)
    else:
        subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "--disable-pip-version-check",
            "-r",
            str(root / "requirements-production.lock"),
        ],
        check=True,
    )
    subprocess.run(
        [str(python), "-B", str(root / "tools/dfs.py"), "doctor"], check=True
    )
    print("Ready. Run: python tools/dfs.py demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
