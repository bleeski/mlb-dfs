---
name: mlb-standings-pull-checklist
description: Generate the list of DraftKings MLB contests Ben has entered that still need their standings pulled and dropped in data/standings/inbox/ before the miner can archive them, and hand it back as a clickable HTML checklist plus a regenerated CONTESTS_AWAITING_STANDINGS.md. Use this whenever Ben asks what standings we need to pull, what contests are missing standings, to regenerate or refresh the awaiting-standings list, for a pull checklist, or says something like "what do we need to pull down", "give me the standings checklist", or "what's left to pull", even if he doesn't name the file or the tool. Also use it to record a contest as unrecoverable (dead pull, stays zero bytes) or as a placeholder/synthetic ID so future runs stop listing it. This is not generate-lineups, which builds lineups from an uploaded salary/entries CSV, and not mlb-lineups, which fetches probable pitchers and batting orders: this skill only finds which already-entered contests are missing a standings export.
---

# Standings pull checklist

Ben enters a lot of DraftKings contests, mostly small satellites and qualifiers
that feed larger tournaments. Each one needs its standings CSV pulled from DK
by hand — DraftKings is never automated, per CLAUDE.md's hard guardrail — and
dropped in `data/standings/inbox/` before the field miner can archive it. That
"which contests am I still missing" question used to get answered by hand-
scanning `outputs/*/DKEntries*.csv` against the archive and the inbox; three
sessions did it three times (2026-07-28, 08-02, 08-03) before it became
`tools/awaiting_standings.py` (R43). This skill is the thin wrapper around that
tool for a Cowork session: run it, present the result, done.

## What it produces

- `data/standings/CONTESTS_AWAITING_STANDINGS.md` — the pull list, oldest
  slate date first (DK's export is known to age out some days after a contest
  settles, so the oldest unpulled contests are the ones at the most risk, not
  the newest).
- `data/standings/standings_pulls_<date>.html` — the same list as a clickable
  checklist. Clicking a contest's "Open export" link opens the DK download in
  a new tab **and** checks that row's box, so working the list is one click
  per contest, not two.

Read the tool's own docstring (`python tools/awaiting_standings.py --help`, or
just open the file) if you want the exact scan logic — 9-digit Contest IDs on
filled entry rows in `outputs/*/DKEntries*.csv`, minus anything already in
`data/archive/*/mined_*.json` or `data/standings/inbox/`, minus
`data/standings/recorded_exceptions.json`.

## Before running it: take the inbox claim

This writes into `data/standings/`, which is ARCHIVE's surface in the
multi-session contract (CLAUDE.md). Take the claim first so a concurrent
ARCHIVE session doesn't collide with you mid-write:

```bash
python tools/claim.py take inbox --role ARCHIVE --scope "standings pull checklist"
```

A `HELD` result names the owner — stop and report it to Ben rather than
writing anyway; it is never yours to override. Release when you're done
presenting the result:

```bash
python tools/claim.py release inbox
```

## Run it

```bash
python tools/awaiting_standings.py scan
```

That's the whole command. It prints the two paths it wrote and the total
count, e.g. `wrote data/standings/CONTESTS_AWAITING_STANDINGS.md (95
contests, 5 dates)`. It never touches the network and never fetches
DraftKings — every URL it emits is built from a contest ID already sitting in
one of Ben's own delivered files, which CLAUDE.md's guardrail explicitly
allows. If you just want to see the list without writing anything (to sanity
check before a run, or to answer a quick question in chat), add `--check`.

## Present the result

Call `present_files` on the HTML path so Ben gets a clickable card, and give
him a one-line summary — total count, how many slate dates, and which date is
oldest (the thing he should pull first). Do not re-paste the whole contest
list into chat; the file is the deliverable and he can open it. If the count
is small (a handful of contests), it's fine to also just name them inline
instead of generating the HTML — use judgment.

Two things worth flagging in your summary if they're non-empty, because they
mean the scan found something a human should look at rather than silently
swallowing it:

- **Non-DK IDs on filled entry rows** in the markdown's "do not pull" section
  — a Contest ID that isn't 9 digits showed up on some entry row. That's
  usually a manual/test row (CLAUDE.md's own examples are `0` and `900`), but
  say what it was and which file, since it could also mean a real contest
  entry is malformed.
- A big jump in the open count since the last run — worth a sentence, not an
  alarm. Contests get entered faster than they get pulled; that's the normal
  shape of this list.

## Recording a dead pull or a placeholder

When Ben (or a prior session) confirms a pull came back at 0 bytes on a
second attempt — the "DK's export ages out" failure mode from the 2026-07-25
ledger note — record it so the tool stops asking for it:

```bash
python tools/awaiting_standings.py mark-unrecoverable <contest_id> \
  --reason "zero bytes on second pull, <date>"
```

For a Contest ID that turns out to be synthetic or a placeholder rather than
a real DK contest (the kind of thing that shows up in a hand-built or
templated DKEntries file), use `mark-placeholder` instead:

```bash
python tools/awaiting_standings.py mark-placeholder <contest_id> \
  --name "<contest name>" --reason "<why it's not a real contest>"
```

Both just append to `data/standings/recorded_exceptions.json` — no ledger
edit, no claim beyond the inbox one you already hold for this run.

## This is not

- **generate-lineups** — builds a lineup portfolio from an uploaded
  DKSalaries + DKEntries CSV. That skill produces the entries; this one
  chases the results after the contest is over.
- **mlb-lineups** — fetches today's probable pitchers and batting orders.
  Unrelated question, same word "lineups," different meaning entirely.

If Ben asks to actually pull the standings, mine them, or upload anything —
stop. Pulling is his manual click, mining is `mlb_engine.field.field_miner`
via the archival runbook (`docs/cowork_archival_runbook.md`, Job 1), and
uploads never happen from a session at all. This skill's job ends at handing
him the checklist.

## For Ben, if he wants to run it himself

```powershell
cd C:\Users\benja\Documents\Claude\mlb-dfs
python tools\awaiting_standings.py scan
```

The HTML lands at `data\standings\standings_pulls_<date>.html` — open it in
a browser while logged into DraftKings.
