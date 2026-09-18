# The post-run retro

The build skill ends at the hand-over. This is what happens after, once the
file is with Ben and the clock no longer matters.

It exists because the run is the only place some defects are visible. The brief
is a rich self-report about the INPUTS — what was degraded, what was requested
and never applied, which controls were overridden, what relaxations were spent.
It says nothing about the session's own conduct: a tool that misfired, a
fallback nobody reached for, twenty minutes spent on a dead end, an ordering
that would have cost the slate under a real clock. Nobody else will see those,
because nobody else was here.

## When

After delivery. Never inside the T-window, and never before the file is in
Ben's hands — the T-schedule exists because optional work has cost slates, and
this is optional work. On a tight slate, deliver, close out, and run the retro
afterwards. If the session ends before you get to it, that is the right
trade: a late retro costs nothing, a late file costs everything.

## The bar

**No findings means file nothing.** This is the rule most likely to be broken,
because a retro with an empty output feels like a retro that failed. It is not.
A clean run is the normal case and the correct report for it is one line in
chat. Manufacturing a finding to look thorough puts a false premise on the
board, and `.claude/rules/board.md` already records that two of three fragments
filed on 2026-09-08 had a false or unscoped premise.

**Verify before filing.** Grep the tree for the mechanism you think you found.
"The brief said X" is an observation; "the code does X at file:line" is a
finding. File the second.

**Truthful labels still bind.** "What went well" is about process, never
outcome. You do not know whether the portfolio was good; you know whether the
build was clean, the gates passed, and the procedure held.

## The four layers, and where each one goes

Adapted from `docs/2026-07-22_build_process_postmortem.md`, whose severity table
already sorted failures this way.

| Layer | What it looks like | Route |
|---|---|---|
| **Engine / tool** | a default, a code path, an exit code, a missing field in an artifact | `docs/backlog_inbox/<date>_<ROLE>_<slug>.md`. A DEV session may write the `docs/backlog.md` row directly instead |
| **Process** | the skill told you the wrong thing, or told you nothing where it should have | edit the skill if you are DEV; otherwise a fragment |
| **Environment / host** | a blocked host, a missing key, a container fact | tell Ben in chat. He is the only one who can change it, and a fragment about it will sit unread |
| **Ergonomics** | it worked but cost more calls than it should have | fragment, lowest priority; batch these |

Two routing facts worth knowing. A fragment is create-only for every role but
its owner: only ARCHIVE merges `ledger/inbox/`, only DEV merges
`docs/backlog_inbox/` and writes the board. And `outputs/<date>/` is gitignored
and the container is ephemeral, so a retro written there does not survive the
session — if it has findings, they go in a tracked fragment or they are gone.

## What to actually look at

Not a checklist to fill in. These are the places findings have actually come
from:

- **The clock.** When was the file gate-clean, and when did Ben get it? Those
  should be the same minute. Anything between them is work that would have
  cost the slate under a real deadline.
- **Every degraded input.** For each one: was it truly unavailable, or was
  there a fallback you did not reach for? A 403 is evidence that one path is
  shut, not that the capability is gone.
- **Every number you passed by hand.** Where did it come from? A literal in a
  recipe is a constant somebody tuned for a host that may not be this one.
- **Every tool that failed.** Did it fail the way its contract says it should?
  An unhandled traceback where the docs promise an exit code is a finding.
- **What the artifact does not say.** A brief key the skill tells you to read,
  that is not there on this contest type, is a divergence between the docs and
  the implementation.
- **Anything you were surprised by.** Surprise is the cheapest defect detector
  and it does not survive the session.

## Reporting it

`## Reporting back` in the skill body is explicit that the delivery message is
not for narrating the steps you took. The retro does not change that. Findings
go in the fragment; chat gets one line naming what you filed and where, plus
anything in the Environment layer, which is the one layer that has to reach
Ben directly.
