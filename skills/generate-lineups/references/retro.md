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

## Start with the facts, which a tool now extracts (R371)

```bash
python tools/retro.py --date <slate_date> --handover-utc "$(TZ=UTC date -Is)"
```

Five of the six things the next section asks for are already in the artifacts,
and reconstructing them from scrollback is how they get lost when the context
compacts. `retro.py` reads the tracked delivery record (R369) plus the build
brief beside it and prints: the gate-clean stamp and the gap to hand-over, every
degraded input the build reported, every number it ran on with the artifact that
says whether a human chose it, every refusal exit code against its documented
meaning, and every brief key `SKILL.md` names that this brief does not carry.

`--handover-utc` is the one fact no artifact holds. Nothing stamps the moment
Ben got the file, so the session supplies it or the gap is not computed. It is
never guessed.

Since R372 it also prints **repo agent runs**: every `dfs-qa` or `dfs-premise`
run on the date, with its wall time, the model that served it and its findings
count, read from `data/agent_runs/<date>/`. `findings: not stated` means the
agent dropped the `FINDINGS: <n>` line its definition requires, and it is never
read as zero. There is no token figure and there will not be one: the
`SubagentStop` payload does not carry a token count, so cost here is wall time
and findings per run.

**It judges nothing, and that is deliberate.** An absent brief key may be a docs
defect or a correct conditional; a degraded input may or may not have had a
fallback; a gap may or may not be a finding. The tool reports the fact and
stops. Everything below is still yours, and the bar above still binds: no
findings means file nothing.

Run it in the session that built the slate. `outputs/` is gitignored and a cloud
container is reclaimed at session end, so the brief is gone afterwards; the
record survives and the sections that need the brief say so by name rather than
coming back empty.

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
