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
   run. Small edits are fine written directly on the mount. When the gate has
   to run ON the mount, it has a supported split since R152: repeat
   `python tools/audit.py --gate-run` until it says complete, then
   `python tools/audit.py --gate-report --terse`. It records per test class
   under `.audit_gate/` against a content fingerprint of the tree, so editing
   between calls resets the run rather than mixing two trees, and only a
   complete assembly may print the clean pinned line.
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
to a directory ON THE MOUNT, then `cat $STAGE/$f > $REPO/$f` per file, because
`cat >` truncates in place and needs no unlink.

**Guard that loop before you run it, because `cat src > dst` truncates the
destination before it reads the source.** On 2026-08-11 the device VM's
`/sessions` filesystem hit 100%, `mkdir` for the extraction directory failed,
and the loop then emptied seven tracked files — `tools/sync_check.py`,
`tools/audit.py`, `tests/test_core.py`, `CLAUDE.md`,
`skills/generate-lineups/SKILL.md`, this file and `CHANGELOG.md` — before
discovering there was nothing to copy. All seven came back from HEAD; any
uncommitted edit to them would not have. Two rules, both cheap: extract to the
mount rather than the VM's `$HOME`, which is a small fixed allowance that fills
silently, and per file assert the staged source exists and is non-empty BEFORE
opening the destination:

```
[ -s "$STAGE/$f" ] && cat "$STAGE/$f" > "$REPO/$f" || echo "SKIP empty/missing $f"
```

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
  R62 vendored the paste suite's two salary files under
  `tests/fixtures/slates/` on 2026-08-10, which removed eight of that suite's
  nine `skipUnless` guards and its entry in `SUITE_PRECONDITIONS`; the ninth
  is a Showdown guard already satisfied by a tracked fixture. The remaining
  gap is other suites' fixtures. Until it closes, container runs start from a
  tarball of the working tree, not from GitHub.
- **GitHub's default branch is `main`, and `master` is deleted.** Verified
  2026-08-18 from Ben's Windows machine, and the command is the citation:

  ```
  git ls-remote --symref origin HEAD  ->  ref: refs/heads/main   HEAD
  git fetch --prune                   ->  - [deleted]  (none) -> origin/master
  ```

  This bullet said the opposite from 2026-08-12 to 2026-08-18
  and the correction is worth more than the fact. The old reading was TRUE when
  taken: the same command returned `ref: refs/heads/master  HEAD` at
  `d0212c2` (2026-08-04) on 2026-08-11, R111(b) asked Ben for the setting
  change, he made it, and no document was updated — so five documents kept
  asserting a stale value with a verification date attached, which reads as
  MORE trustworthy than an unsourced claim, not less. A dated reading is
  evidence of what was true then and says nothing about now, which is why the
  citations here name the command and its output rather than the person who
  ran it.
  **Nothing on this disk can re-read it offline.** `origin/HEAD` is a local
  cache from
  the last `set-head`; `origin/master` survives a deletion indefinitely because
  a push never prunes; and `ls-remote --symref` needs the credential and
  outbound network, which the device VM does not have (R147). The only reading
  is `git ls-remote --symref origin HEAD` from Ben's own machine or a container
  holding `GH_PAT` — which, since R148(a), is what `tools/audit.py` runs itself
  whenever the fetch reaches the remote, reporting `default_branch_source:
  remote` when it asked and R147's classified reason when it could not. Re-read
  it before repeating it, and clear a dead remote-tracking ref with
  `git fetch --prune`.
- **`sync_check.py` hardcodes `main` (R111(a), still open).** Three reads of
  `refs/heads/main` (`:238`, `:255`, `:280`) regardless of what is checked out,
  so on any other branch it prints `disk main ?` and then gives remedies for a
  branch the caller is not on. The default-branch fix REDUCED this one's blast
  radius without closing it — a fresh clone now lands on `main`, so the common
  case agrees by luck rather than by reading `.git/HEAD` — which is the shape
  worth naming: a gate that is right for the wrong reason fails silently the
  first time someone works on a topic branch. It also tells every caller to "push from
  Windows", which is wrong for a container holding a working credential.
- **`.git/index.lock` goes stale here and `rm` cannot clear it (R109).** The
  mount grants create and truncate but not unlink, so an interrupted git
  write leaves a zero-byte lock that blocks every later commit, and git's own
  documented remedy — delete the file — is the one operation that fails. Seen
  2026-07-28, 2026-07-29 and 2026-08-10. The same asymmetry shows up all over
  this mount: `rm` returns "Operation not permitted", `cp` over an existing
  file returns "Invalid argument", while `mv` and `cat >` both work.

  **The remedy, in order.** First confirm the lock is dead rather than a live
  session mid-write: it is zero bytes and its mtime is minutes or hours old,
  and `pgrep -x git` finds nothing. A live git write is not yours to clear.
  Use `-x`, not `-f "git "`: the sandbox runs each call as `bash -c <command>`,
  so a `-f` pattern matches the calling shell's own command line and reports
  LIVE every time (hit 2026-08-12, with both locks ten hours dead). Then move
  the lock aside rather than deleting it, which needs no unlink grant and
  leaves the evidence in place:

  ```
  ls -la .git/*.lock                       # size and mtime; 0 bytes and old
  pgrep -x git || mv .git/index.lock .git/index.lock.stale-$(date -u +%Y%m%dT%H%M%SZ)
  ```

  Use a timestamped suffix, never a fixed one. Fixed names collide with the
  residue already there and then the `mv` itself fails: `.git/index.lock.bak`,
  `.stale`, `.stale2`, `.stale3`, `deadlock_*` and `tmp_probe_dead` are all
  sitting in `.git/` today for exactly that reason. Check `HEAD.lock` the same
  way; it strands the same commit. The residue can only be swept with Ben's
  explicit delete grant, so it accumulates, and that is cosmetic rather than
  harmful — a `.lock.stale-<ts>` file blocks nothing.
