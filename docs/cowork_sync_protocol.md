# Cowork sync protocol: disk, container, GitHub

Tracked companion to CLAUDE.md's multi-session contract. Written 2026-08-10
(R102). This file is the one place the sync procedure lives; CLAUDE.md points
here and does not repeat it.

## The topology, and why it is not three things

There are three locations but **two filesystems**.

| Location | What it is |
| --- | --- |
| `C:\Users\benja\Documents\Claude\mlb-dfs` | Ben's disk. The real repo. |
| `/sessions/<id>/mnt/mlb-dfs` | The SAME files, mounted into a session's Linux VM. |
| the cloud container | A separate filesystem. Empty at session start, discarded at session end. |

The Windows folder and the mount cannot drift, because they are one thing seen
twice. Every real sync question is therefore about the container, or about
GitHub.

`git status` on the mount is not evidence of drift on its own. The mount hands
git different mtimes for identical bytes, so porcelain reports ` M` while
`git diff HEAD` is empty. Confirm against content before believing it, or run
`python tools/sync_check.py`, which does that for you.

## What each caller can reach

- **The mount has no network.** `.git/FETCH_HEAD` has never existed. No Cowork
  session can `git pull` or `git push` against Ben's disk, in either
  direction. That step is always Ben's, in a Windows terminal. `origin/main`
  on the mount is a remote-tracking ref that moves only when Ben pushes, so it
  answers "does my disk carry commits GitHub does not" and cannot answer "has
  GitHub moved ahead of me".
- **The container reaches github.com.** `bleeski/mlb-dfs` is private, so a
  credential is required. Without one, the container cannot clone, and the
  disk-to-container path is the tarball bridge below.
- **Neither can reach DraftKings.** Unchanged, and not negotiable. See the
  guardrails in CLAUDE.md.

## The credential, and how it must travel

Store a fine-grained PAT scoped to `bleeski/mlb-dfs` alone, Contents read and
write, as `GH_PAT=` in the gitignored `.env` at the repo root.

Move it to the container by staging `.env` as a file and sourcing it there.
**Never `cat`, `grep`, `echo` or otherwise print the token over `device_bash`**:
tool output is transcript, and that breaks the project's own no-API-keys
guardrail as surely as writing it to a file would. Checking whether the key
exists is fine; `grep -c '^GH_PAT=' .env` returns a count and not a value.

`sync_check.py` treats a token shorter than 20 characters as absent. The
container ships `GH_TOKEN` and `GITHUB_TOKEN` preset to 14-character
placeholders, and an auth failure against a placeholder reads like a network
outage, which sends you debugging the wrong thing.

## The loop

1. **Session start.** `python tools/sync_check.py`. Exit 0 means the disk
   carries nothing GitHub lacks and nothing is uncommitted. Exit 2 names what
   drifted. Then the usual gates: `python tools/claim.py dirt --role <role>`
   and the audit.
2. **Work.** Engine work belongs in the container when the suite matters: it
   runs in about 30 seconds there against several minutes chunked on the mount,
   where a `device_bash` call is capped at 45 seconds and cannot hold a full
   run. Small edits are fine written directly on the mount.
3. **Session end.** Commit on the mount, one git operation per call, staging by
   explicit path. Then tell Ben to push. A session that ends without committing
   leaves its work exposed: on 2026-08-10 an orphaned session left a complete,
   green, 707-line write set uncommitted for three hours, and only the dirt
   gate caught it.

## Container commit identity

The container's git is preconfigured as `Claude <noreply@anthropic.com>` with
`commit.gpgsign=true` against an Anthropic signing key. Any commit made there
carries that identity. Set `user.name` and `user.email` explicitly before
committing in the container, or commit on the mount instead, where Ben's
`.git/config` identity already applies.

## What never goes through git

`runs/`, `outputs/`, `data/slates/<date>/`, `ledger/inbox/` fragments and raw
DK exports are gitignored runtime data. They move disk-to-container by
`device_stage_files` and container-to-disk by `SendUserFile` +
`device_commit_files`. Note that `tar -x` FAILS over the mount ("Cannot open:
File exists", because the mount cannot unlink), so the write-back is: extract
to the device VM's `$HOME` (not `/tmp`, which is not writable), then
`cat $STAGE/$f > $REPO/$f` per file, because `cat >` truncates in place and
needs no unlink.

## Known limits, stated rather than papered over

- **The engine mutex is nominal, not real.** `claim.py take engine` produces
  `claims/engine_<date>`, which mutexes correctly. But a session that runs
  `take engine_myslug` gets its own directory and blocks nobody, and sessions
  have routinely done that: 2026-07-29 alone carries `engine_2026-07-29`,
  `engine_2026-07-29_r6` and `engine_2026-07-29_r28`. Take the BARE resource
  name for anything that is genuinely a mutex. Tightening this is open backlog,
  because making it real starts blocking sessions that today proceed.
- **A hand-written `RELEASED` marker does not release a claim.** owner.json is
  authoritative, and the precedence cannot be flipped: `take` clears the marker
  with unlink, which fails on this mount, so a marker-authoritative rule would
  report a live claim as free. `check` and `sweep` now name any claim in that
  state and print the command that completes it.
- **A fresh clone cannot run the suite green.** It needs untracked fixtures.
  Tracking them is open backlog; until then, container runs start from a
  tarball of the working tree, not from GitHub.
