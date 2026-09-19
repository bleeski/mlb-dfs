# The adversarial QA brief (R344)

**v1, 2026-09-19.** Ben's instruction, 2026-09-12. This file is the standing
brief for the agentic half of "poke holes in it". Version it in place: a run
that finds the brief wrong edits this file and says so in the retro, so the
brief accumulates instead of being re-improvised per slate.

`tools/qa_portfolio.py` is the deterministic incumbent and it stays. This pass
is a subagent that reads the incumbent's output ONCE and looks for what the
incumbent does not measure. It is bounded by SKILL.md's "poke holes" step: two
iterations at most, only with time on the clock.

The repo agent that runs it is `.claude/agents/dfs-qa.md` (R372). It is invoked
deliberately, never automatically, and it is handed artifact PATHS, never a
repo to explore. The first run cost ~109k tokens, 4m00s wall and 10 tool calls
for five findings of which one was acted on; the paths are the whole of why the
second run should cost less.

## What it is not

Report only. It never edits the delivered file, never writes under `runs/`,
never re-runs the build, and never touches DraftKings by any client. It states
gaps rather than filling them: the first run's most useful sentence was "I did
not verify cap feasibility for any specific swap."

A finding is a question, not a verdict. Heavy exposure to a low implied total
is a leverage play or an oversight and the pass cannot tell which. Say which
you believe and why, and leave the call to Ben.

## The two requirements the first run failed

These are first because they are the two that cost something.

**1. Liveness has a shelf life of about two minutes: re-pull LAST, and
clock-stamp every claim.** On 2026-09-12 "Zero dead slots" was written at 12:57 and was
false at 12:58, when MIN posted two dead bats in entry 5251499964. Ben's
question at 12:59 found it; the pass did not. An unstamped "checked" is worse
than unchecked, because it is load-bearing and nothing downstream knows how old
it is.

  * Re-pull the lineups feed as the LAST act before writing the report, after
    every other axis is already drafted.
  * Every liveness claim carries the clock time it was true at, in the sentence
    that makes it. "Zero dead slots as of 12:57 ET" is a claim; "zero dead
    slots" is not.
  * Print `TZ=America/New_York date` in the same call that produces the figure,
    and never state a clock time this turn did not print (CLAUDE.md's R318
    rule, which applies here verbatim).
  * A side still TBD at write time is a stated gap, not a pass.

**2. Read the ownership prior, or say the leverage axis died.** The first run
could not read `outputs/<date>/ownership_pred_<tag>.json` (`Name: None`,
predictions nested under `features`) and lost axis 3 entirely, silently. The
emit-schema fix that makes it readable is **R276's**, not this brief's, and
until it lands this is a known gap: if the prior cannot be parsed, say so by
name in the report and mark axis 3 NOT RUN. Never let a dead axis read as a
clean one.

## The three axes

**Axis 1: mispriced assets and whether a Pareto improvement exists.** Against
the salary file and the build's own projections, is there a swap that raises
projected points without raising salary, or lowers salary without lowering
points? Hitter signals: batting-order slot against salary, a confirmed 1-5 bat
priced like a 7-9 one, a platoon edge the build did not price. Pitcher signals:
implied total faced, opposing lineup handedness, park. Traps are findings only
when ROSTERED, not when merely present in the pool.

Cost every recommendation. A swap you cannot price is a gap, not a finding: say
"a rebuild to act on this costs 66s warm (measured on 1310_9g) / cold is a full
bank rebuild" so the recommendation arrives with its price attached. A hand
swap you have not checked for cap feasibility is stated as unchecked.

**Axis 2: dual-objective adherence, at contest AND portfolio level, as one
frontier.** CLAUDE.md's dual objective: large wins and no total washout are the
same frontier, and concentration wins a winner-take-all ticket while losing
every entry at once. The washout axis binds at the PORTFOLIO level, so a
per-contest read alone is not an answer. Report both ends. Where the portfolio
sits on the frontier is Ben's call; where it sits is yours to state.

**Axis 3: leverage against SOURCED ownership.** Only against the ownership
prior on disk, labeled as the prior it is. Never against a remembered field,
never against a number this pass invented. If the prior is unreadable, see
requirement 2.

## Truthful labels, verbatim

Everything this pass produces is a deterministic review proxy or a labeled
prior. Never ROI, profitability, win rate, cash rate, edge, or a probability.
Never "upload-ready" unless `workflow_valid`, `selection_certified` and
`allocation_certified` all pass on a certified Classic export; Showdown is
review-grade and never upload-ready. Archived results are observed outcomes,
not graded predictions.

## The walls this pass runs inside

  * The DKSalaries CSV is authoritative for IDs, salaries, teams, eligibility
    and posted batting orders. Never correct it against a real-world roster.
  * Never propose reducing the legal player pool. A trim is invisible in the
    certified output and it is Ben's call, never a session's.
  * Never fetch DraftKings by any client. FanGraphs 403s scripted pulls, so a
    FanGraphs refresh is post-slate work in a browser session, not a pre-lock
    step.
  * Never log, echo, or write an API key.

## The budget, and partial-in-time beats complete-late

A hard wall-clock budget is set by the caller and stated in the report. When it
runs out, ship what is drafted with the unrun axes named as NOT RUN. A complete
report after the lock is worth nothing; three axes and a stated gap before it
is worth the slate. Under CLAUDE.md's T-schedule, at T-10 or later this pass is
an optional step and skipping it entirely is the right call.

## The report

State, in this order: the wall-clock budget and what it cost; each axis with
its findings or NOT RUN with a reason; every liveness claim with its clock
stamp; every gap stated as a gap; the rebuild cost of every recommendation.
End with the machine-readable line the SubagentStop hook reads (R372):

```
FINDINGS: <n>
```

`<n>` is the count of findings in the report, `0` when there are none. It is
the last line and it is never omitted: the hook records `null` when it is
missing, which loses the run's only cost-per-finding number.
