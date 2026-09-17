# The Cowork sandbox: what binds a BUILD or ARCHIVE session there

Moved out of CLAUDE.md on 2026-09-15 (R301(2)) when DEV moved to Claude Code on
Ben's machine. Nothing here binds a Claude Code session: the full gate runs in one
call there, `rm` works, and there is no inner bash ceiling. Everything here binds
a Cowork session, whose device VM mounts Ben's disk at `$HOME/mnt/mlb-dfs`.
`docs/cowork_sync_protocol.md` owns the disk / container / GitHub topology; this
file owns the per-call mechanics. CLAUDE.md's `## Sandbox` owns the one number.

## The inner bash budget is 130s. One number, this one.

Cowork's real per-call ceiling is about 180s when the call passes an explicit
timeout, and the safe inner budget underneath it is 130, which is also
`--gate-budget`'s value in the gate command below and `solver_probe`'s default.
A session that reached for `timeout 168` against a ~164s harness ceiling on
2026-09-01 lost the call and its work with it; the number came from a different
measurement. Do not re-derive it per call (R271).

## The gate does not fit one call, so it has a supported split (R152, R271)

Measured 2026-08-18 on the device mount: `tests.test_core` alone needs ~89s and
one of its tests needs 35.8s by itself. Run:

    python tools/audit.py --gate-run --gate-budget 130 --gate-ceiling 165

until it prints `GATE COMPLETE` (exit 3 means more remains), then

    python tools/audit.py --gate-report --terse

which prints the same pinned `PASS ...` line the single call prints when every
unit ran, and `GATE INCOMPLETE ...` when it did not. Only a complete assembly may
print that line. Completeness is CLASS coverage, not a matching count; every
record is stamped with a content fingerprint of the tree, so an edit mid-run
resets the state rather than mixing two trees; a unit that cannot finish in one
call is NAMED rather than skipped. State lives in `.audit_gate/` (gitignored);
`--gate-reset` starts over. Measured 2026-08-29: one `--gate-run` assembled all
five suites warm, five did it from a cold `__pycache__`. Budget for five. The two
pytest suites R338 added are one call each at ~1s and ~6s and ride inside that
budget. Set the ceiling env if the hardcode bites: `MLB_GATE_CEILING_S=155`.

Backgrounding the gate is the trap, not the workaround: `nohup` and `setsid`
both die with the call, the log comes back EMPTY (which reads exactly like a
silent pass), and a killed `audit.py` strands the next commit on a zero-byte
`.git/index.lock`.

The gate is the session's job by POLICY, not impossibility: a gate the operator
runs is a gate the session that changed the code did not (R271(c)). The one
licensed exception is a session that cannot reach the mount at all; a container
reproduction is PARTIAL by construction and may never be quoted as the mount's
gate, so there the real gate is the one thing only Ben's machine can produce,
and asking for exactly that one thing is correct.

## The mount grants create and truncate, not unlink (R109)

`rm`, `cp` over an existing file, and `tar -x` fail; `mv` and `cat >` work.
Files a session is finished with go into `_to_delete/` (gitignored; Ben empties
it). Session scratch goes in `tools/_scratch_<tag>/` (gitignored at any depth);
when `/sessions` or `$HOME` is full it is the only writable scratch, and a
`git commit -F -` heredoc avoids writing the message to `$HOME`.

**The git lock is a CLASS, not `index.lock`.** `HEAD.lock` and
`next-index-*.lock` block every git write with the same message `index.lock`
produces, so a session sweeping only the one name reads a still-blocked repo as
clean. Diagnose with `find .git -name '*.lock'` and `mv` each hit aside with a
timestamped suffix. Sweep at session start AND before every git write: on this
mount a plain `git status` leaves a fresh `index.lock` behind, so the read that
says the tree is clean is itself what blocks the next `add`. When a concurrent
session may be live, only move locks older than ~120s.

`git status` on the mount is not evidence of drift on its own: the mount hands
git different mtimes for identical bytes, so porcelain reports ` M` while
`git diff HEAD` is empty. Confirm against content, or run
`python tools/sync_check.py`.

## Network is a measurement, not a property (R316)

This file's predecessor asserted the device VM had no network, and measured on
2026-09-06 every clause was false: the audit fetched, `sync_check.py` reached
GitHub, and `curl` returned 200 from api.github.com, statsapi.mlb.com,
baseballsavant.mlb.com, fangraphs.com and pypi.org. MEASURE egress in either
direction; the audit names which of three things stopped a fetch (R147). Disk can
still run ahead of GitHub whenever a session commits without pushing, and the
audit names that too -- though since R350 (Ben, 2026-09-16) sessions PUSH as well
as commit, so it is no longer the standing state it was when this paragraph was
written. GitHub's default branch is `main` and
`master` is deleted (verified 2026-08-18 with `git ls-remote --symref origin
HEAD`); a clone can carry a stale `origin/master` indefinitely because a push
never prunes.

## Chat uploads, scheduled tasks, and the container

Files Ben attaches to a Cowork chat land in the container's uploads path and are
invisible to `device_bash`; copy them to the outputs path and commit them to the
mount with `device_commit_files`. A container clone of the repo is cheap
(`GH_PAT` in `REPO/.env`) and is how a full audit runs when the mount is dead,
labelled as a container reproduction. Scheduled tasks: none exist as of
2026-09-15; a scheduled run would be ARCHIVE, would take the ledger and inbox
claims first, and a claim it cannot take turns the run into a report, never a
write.
