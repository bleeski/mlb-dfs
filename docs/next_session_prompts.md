# Next-session prompts

Written 2026-07-31 by DEV. Delete each once used; this file is scratch, not a
contract. The DEV prompt is the recommended next session. The ARCHIVE one can
run before or after it, but never during a live build.

---

## Prompt A — DEV, ship the reuse_penalty removal

```
Role: DEV. Job is R36 Finding 11, which Ben decided on 2026-07-31 and which is
recorded in CHANGELOG.md under "Decided, not yet shipped": REMOVE the
reuse_penalty term from the joint allocator rather than invert it. The reasoning
is in the backlog under R36; do not re-litigate the decision, but do tell me if
implementing it surfaces a fact that should change it.

Session start per CLAUDE.md, with five things specific to this tree.
First, the audit expects PASS v2.26.0 25 modules 589 tests across five gated
suites: test_core 375, test_showdown 49, test_upload_integrity 100,
test_golden_replay 9, test_paste_lineups 56.
Second, test_core does NOT fit a 45s Cowork call as a single run. Split it by
test class into roughly four groups and run those.
Third, scipy. The .pylibs/ directory on the mount is BROKEN and will fail with
ImportError on scipy._lib._pep440. Do not try to repair it, it is not in DEV's
write set. Install from the local wheel instead:
  pip install .wheels/scipy-1.15.3-*.whl --target /tmp/pylibs --no-deps --no-cache-dir
then run everything with PYTHONPATH=/tmp/pylibs TMPDIR=/tmp PYTHONHASHSEED=0.
TMPDIR must be overridden because the default points at a full filesystem.
Fourth, check `df -h /sessions` before you start. It was at 100% with 77MB free
on 2026-07-30, and .pylibs/ plus .wheels/ are 94MB of that. A build or a test
run that fills the disk fails in confusing ways. If Ben has cleared them, the
wheel install above will not work and you should say so rather than improvise.
Fifth, a stale zero-byte .git/index.lock appeared last session from an
interrupted BUILD. If git refuses the index, check the lock's age before
removing it, and never remove a fresh one.
Take the engine claim as DEV before any write.

The work.
1. mlb_engine/allocate/contest_allocator.py:1625-1627. The objective assignment
   `objective[y_offset:] = reuse_penalty * 0.01` is the whole defect. Remove the
   term. Note that `use_y` is only true when max_shared_players is set, which is
   the core of why the term is redundant rather than merely misnamed.
2. There is a real sub-decision here and it is yours to recommend: what happens
   to the `reuse_penalty` controls key. Silently accepting a control that now
   does nothing is worse than the bug, because the next reader will assume it
   works. Rejecting it loudly and rejecting it at the wrong layer are different
   costs. Make the call, state it, and note that the LEGACY
   `assign_lineups_to_contests` path at lines 798-800 uses the same key on an
   EXCESS variable and is correctly signed, so the key is not dead everywhere.
3. Expect tests/test_golden_replay.py to move. That is the point of a golden.
   Read the diff before re-pinning and say what changed. The coefficient is 0.02
   against scores normalised to [-100, 0], so the prediction is that only
   near-ties move; a golden that shifts more than that is evidence the
   prediction was wrong and I want to hear it. Re-pin deliberately, never
   regenerate blind.
4. Grep for reuse_penalty in SKILL.md, MLB_Classic.md and any controls
   documentation. A parameter whose documented behaviour was never its real
   behaviour has probably been described somewhere in the wrong direction.
5. Tests: one that pins the objective vector carrying no y term, and one that
   pins two near-tie candidates no longer collapsing onto a single reused
   lineup. The second is the behavioural one and matters more.

Deliverable: one commit, explicit paths only, never git add -A. Re-pin the test
count in tools/audit.py, CLAUDE.md and SKILL.md. Move R36 Finding 11 from
Decided to a shipped CHANGELOG entry, leaving the Decided entry in place per the
convention at the top of that file, and mark the backlog item LANDED.

Explicitly not this session: R10, which is decided and unblocked but wants a
current archive first; the ARCHIVE standings backlog; and the reference-data
refresh, which is blocked at the sandbox proxy (baseballsavant.mlb.com and
fangraphs.com both 403 on the tunnel) and has to run on Ben's machine.

Then tell me whether the golden diff shows a real strategy change or only
near-tie churn, because that is the difference between a cleanup and a
portfolio change I need to think about.
```

---

## Prompt B — ARCHIVE, clear the standings backlog

```
Role: ARCHIVE. Take the ledger and inbox claims first; a claim you cannot take
turns this run into a report and not a write. Do not run this during a live
build: check claims/ for a lit slate beacon before starting, and note that two
beacons from 2026-07-30 (1910_6g and sealad_sd) were abandoned without a
RELEASED file, so a lit beacon needs its age and its outputs checked rather than
being trusted at face value.

Four things are pending and they are all yours.
1. 83 CSVs are sitting in data/standings/inbox/. Roughly 46 are already mined.
   Mine what is new. The inbox is FLAT by contract: do not sort it into
   per-contest-type folders, because the miner reads Classic vs Showdown off the
   lineup cells and a folder is a second copy of that fact that can disagree.
2. 53 contests from 2026-07-29 still need standings pulled. The list is already
   generated. You may emit the exportfullstandingscsv URLs from the contest IDs
   in Ben's files, but you never fetch DraftKings; Ben clicks them himself.
3. CONTESTS_AWAITING_STANDINGS.md still says "nothing is open" and is dated
   07-28. Bring it current.
4. PENDING_MINE_2026-07-28.md is a dead file whose own header says to delete it.
   Delete it.

There is also a DEV fragment waiting for you at
ledger/inbox/2026-07-31_DEV_paste-placeholder-quick-card.md. It corrects the
Quick Card's test count, which is stale at 546/359 and should read 583, and
proposes one new invariant about positional placeholders. Merge it and delete
the fragment.

One thing worth knowing before you fit anything: R10's gate was decided on
2026-07-31 and now conditions on the satellite archetype, so the archive you are
about to bring current is the substrate for that work. Ownership and outcome
counts stay conditioned on archetype and field size and are never pooled across
them.

Commit with a descriptive message when tracked files change.
```
