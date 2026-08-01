# Next-session prompts

Written 2026-07-31 by DEV. Delete each once used; this file is scratch, not a
contract. Prompt A (DEV, remove `reuse_penalty`) was used and deleted on
2026-08-01; it shipped as R36 Finding 11. The ARCHIVE prompt below can run at
any time, but never during a live build.

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

There are two DEV fragments waiting for you.
ledger/inbox/2026-07-31_DEV_paste-placeholder-quick-card.md corrects the
Quick Card's test count and proposes one new invariant about positional
placeholders; its count (589) is itself one generation behind, and
ledger/inbox/2026-08-01_DEV_quick-card-count-591.md supersedes it on the
count question (591). Merge both and delete the fragments.

One thing worth knowing before you fit anything: R10's gate was decided on
2026-07-31 and now conditions on the satellite archetype, so the archive you are
about to bring current is the substrate for that work. Ownership and outcome
counts stay conditioned on archetype and field size and are never pooled across
them.

Commit with a descriptive message when tracked files change.
```
