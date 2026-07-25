"""Resumable wheel fetcher for the bounded Cowork sandbox.

Each bash call is a fresh container with a 45s ceiling, so a large wheel cannot
be downloaded in one shot. This fetches with HTTP Range requests into a
persistent mount directory and can be run repeatedly until complete.

Usage:
    python tools/wheel_fetch.py --dest <dir> --seconds 35 numpy scipy
Exit 0 when every requested wheel is complete, 10 when more calls are needed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

VERSION = "0.1.0"

PY_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
INDEX = "https://pypi.org/pypi/{pkg}/json"
PINNED = "https://pypi.org/pypi/{pkg}/{ver}/json"
CHUNK = 1 << 18


def pick_url(spec: str) -> tuple[str, int, str]:
    """spec is 'pkg' or 'pkg==version'. Returns the cp-tagged manylinux wheel."""
    if "==" in spec:
        pkg, ver = spec.split("==", 1)
        url = PINNED.format(pkg=pkg, ver=ver)
    else:
        pkg, url = spec, INDEX.format(pkg=spec)
    with urllib.request.urlopen(url, timeout=20) as fh:
        meta = json.load(fh)
    for f in meta["urls"]:
        fn = f["filename"]
        if not fn.endswith(".whl"):
            continue
        if "py3-none-any" in fn:
            return f["url"], f["size"], fn
        if PY_TAG not in fn:
            continue
        if "manylinux" not in fn or "x86_64" not in fn:
            continue
        return f["url"], f["size"], fn
    raise SystemExit(f"no suitable wheel for {spec} ({PY_TAG})")


def fetch(url: str, size: int, path: str, deadline: float) -> bool:
    """One connection per call. Buffer in RAM, append to the mount once.

    The sandbox throttles the network and charges a fresh TLS handshake per
    request, so repeated Range requests spend most of the budget on setup.
    Mount writes are also slow, so a single append per call is much cheaper
    than many small ones.
    """
    have = os.path.getsize(path) if os.path.exists(path) else 0
    if have >= size:
        return True
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"})
    buf = bytearray()
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            while time.time() < deadline:
                block = resp.read(CHUNK)
                if not block:
                    break
                buf += block
    except Exception as exc:  # partial progress is still progress
        print(f"  stream ended early: {exc}")
    if buf:
        with open(path, "ab") as fh:
            fh.write(buf)
        have += len(buf)
    return have >= size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("packages", nargs="+")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--seconds", type=float, default=35.0)
    args = ap.parse_args()

    os.makedirs(args.dest, exist_ok=True)
    deadline = time.time() + args.seconds
    incomplete = []

    for pkg in args.packages:
        url, size, fn = pick_url(pkg)
        path = os.path.join(args.dest, fn)
        done = fetch(url, size, path, deadline)
        have = os.path.getsize(path) if os.path.exists(path) else 0
        pct = 100.0 * have / size if size else 0.0
        print(f"{fn}: {have}/{size} ({pct:.1f}%) {'done' if done else 'partial'}")
        if not done:
            incomplete.append(fn)

    if incomplete:
        print("INCOMPLETE:", ", ".join(incomplete))
        return 10
    print("ALL COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
