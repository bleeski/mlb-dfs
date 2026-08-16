# Cowork sandbox disk can be full at session start, which blocks the scipy preflight

Filed by BUILD, 2026-08-14, from the 2138_4g late slate. Cost about 3 minutes
of a 20-minute window.

## What happened

The skill's preflight (`pip install -r requirements.txt --break-system-packages`)
failed at T-18:

```
OSError: [Errno 28] No space left on device: '/sessions/<session>/.local'
```

`/sessions` was at 100% (9.8G used, 0 available). The session's own home
directory held only 288K of that, so nothing under it was mine to reclaim and
clearing pip caches freed nothing.

## What worked

The root filesystem is a different device with room, and `/opt` is not
writable, but `/tmp` is:

```bash
df -h /   # /dev/sda1, 2.7G available
mkdir -p /tmp/pylibs
TMPDIR=/var/tmp pip install --target /tmp/pylibs --no-cache-dir -q \
  "numpy>=2.0" "pandas>=2.2" "scipy>=1.13"
export PYTHONPATH=/tmp/pylibs
```

19 seconds, and `PYTHONPATH=/tmp/pylibs` carried across every later bash call
in the session, including the certified build. `TMPDIR=/var/tmp` matters
because pip's default build dir lands on the full device.

## Proposed change

Put the fallback in `skills/generate-lineups/SKILL.md` next to the preflight, so
it is one copy-paste rather than a diagnosis under a clock. Suggested wording:
if the install fails with `Errno 28`, do not try to reclaim space under
`/sessions`; install to `/tmp/pylibs` with `TMPDIR=/var/tmp` and export
`PYTHONPATH`.

Better: have the preflight detect the condition itself. `tools/env_probe.py`
already exists and is the natural home. Check free space on the target device
before installing, pick a writable device with room, and print the exact
`PYTHONPATH` export the rest of the session needs.

The general note the skill already makes is worth reinforcing here: the
preflight is never the step to skip under deadline pressure, and its failure
mode is not always a slow install. Tonight it was a full disk, and the error
text points at a directory that is not the problem.
