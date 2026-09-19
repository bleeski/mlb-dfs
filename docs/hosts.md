# Hosts

Filed 2026-09-17 under R355, when the move to Claude Code in the cloud made a
two-host description wrong in a way that broke the first command a build session
runs. Host facts were scattered across `CLAUDE.md`, `docs/cowork_sandbox.md`,
`.claude/rules/engine.md`, `.claude/skills/dev-session/SKILL.md` and
`skills/generate-lineups/SKILL.md`, and disagreed with each other.

Three hosts run this repo. They differ in ways that have each cost a session, so
the facts live here rather than in `CLAUDE.md`, and the ones a program needs are
resolved by `mlb_engine/repo_env.py` rather than written down twice.

**Ask the code, not this table, for a number.** `repo_env.host_profile()` probes
the host and returns the call budget, whether `rm` works, whether `/tmp` persists,
and the ceiling the host declares. `tools/solver_probe.py` and
`tools/autobuild.py` already read it; anything new should too. This table is for
the things a program cannot probe.

| | Claude Code, cloud container | Claude Code, Ben's Windows machine | Cowork (legacy) |
|---|---|---|---|
| **How it is reached** | Claude desktop app, Claude iOS app, claude.ai/code | the repo folder opened locally | the Cowork app |
| **Roles** | DEV, ARCHIVE, BUILD | DEV | BUILD, ARCHIVE |
| **Shell** | bash | PowerShell | bash |
| **Call budget** | `repo_env.call_budget_s()`, ~630s | ~900s | 130s inner, ~180s real |
| **Full gate in one call** | yes, measured ~5 min | yes, ~9 min | no, use the split gate |
| **`rm`** | works | works | NO: `mv` into `_to_delete/` |
| **`/tmp`** | persists across calls | use `python`, not bash idioms | per-call |
| **Dependencies** | `.venv`, installed by the SessionStart hook | pinned `.venv` | vendored `.pylibs/` |
| **Where the repo lives** | fresh clone, reclaimed when the session ends | Ben's disk | a mounted device VM |
| **DK files in** | attached in chat, under `/mnt/user-data` | Ben's Downloads folder | the container uploads path |
| **Deliverable out** | handed back into the conversation | on disk | committed to the mount |
| **Claims mutex** | container-local, means nothing (`claim.py` says so, R359) | real | real |
| **Secrets** | environment variables on the cloud environment ONLY | `REPO/.env` or the environment | `REPO/.env` |
| **Egress** | measured per session, never assumed (R367) | open | measured per session |

## Secrets

`repo_env.resolve_secret` looks in exactly two places: the process environment,
then `<repo>/.env`. `.env` is gitignored, so **on a cloud container it can never
exist** -- the clone is fresh every session. A key must therefore be set as an
environment variable on the cloud environment itself, and nothing in the repo
can do that for you.

The live consequence, unchanged until it is: `THE_ODDS_API_KEY` does not resolve
in a cloud container, so F1 (the implied-team-total factor) is neutral
slate-wide on every build run there. `enrichment.counts.f1_games_priced` reads 0
and the brief says so; read it rather than assuming F1 was live.

Two documents asserted the opposite from the Cowork era and were corrected or
retired in R368: `docs/cowork_migration_handoff.md` ("`.env` exists at the repo
root with a real key") is now in `docs/legacy/`, and `docs/cowork_sandbox.md`'s
`GH_PAT` line is scoped to the host it is true on.

## Egress

**Measured, never asserted.** `python tools/env_probe.py --egress` prints one
line naming what this host reached just now, and the SessionStart hook prints it
at the top of every session. Six hosts, concurrent, capped at about ten seconds,
with the CLIENT named per host because it matters: FanGraphs answers 403 to
urllib's fingerprint and 200 to curl (R317(a)).

Why it is measured rather than written down: three places in this repo recorded
three different answers for the same two hosts, and each was true where it was
taken -- `mlb_engine/intake/paste_odds.py` says the odds API is proxy-gated
(R236), `skills/generate-lineups/SKILL.md` records it answering 200 (R316), and
the 2026-09-18 build fragment records 403. Egress belongs to the host and the
environment's network policy, not to the repository.

A `401` from the odds API is REACHABLE-without-a-key, which is the ordinary
state here; it is not a block. Nothing in this probe touches DraftKings, and
nothing ever will: that wall is absolute and those reads are Ben's, by hand.

## The call-budget escape hatch

`MLB_DFS_CALL_BUDGET_S` is read FIRST by `repo_env.call_budget_s()` and is the
supported way to plan a deliberately long call. It exists because the automatic
version is unsafe: `declared_ceiling_s` reads `BASH_DEFAULT_TIMEOUT_MS`, which is
what a call gets when the caller passes **no explicit timeout**, while
`BASH_MAX_TIMEOUT_MS` is merely the largest a caller may request. Resolving the
budget from the maximum would plan 1260s of work into a call that gets killed at
900s, losing the whole call. So the hatch is explicit and deliberate, and it is
the right mechanism rather than a limitation to engineer around.

## The cloud container is the default, and it is ephemeral

Everything not committed is lost when the session ends. Two consequences worth
internalising:

- **Push before you stop.** A commit that was never pushed is gone. `/ship` says
  to push a branch even mid-work rather than leave it in a container.
- **`outputs/` and `runs/` do not survive.** They are gitignored, so a certified
  file that is only written to disk cannot reach Ben. A cloud BUILD hands the
  file back into the conversation with its sha256.

`claims/` is gitignored and each container is isolated, so a claim taken here is
visible to nobody and `dirt` will always read "none held". **In the cloud the
BRANCH is the mutex**: one session, one branch, one PR. The claim mechanism stays
because the other two hosts share a disk and genuinely need it.

## Windows

The shell is PowerShell, so prefer a `python` entry point to a bash idiom. Paths
in tests go through `Path`, never string concatenation. Host facts specific to
Ben's machine go in `CLAUDE.local.md` (gitignored), not here.

## Cowork (legacy)

Kept because the mount still exists, not because new work should target it. The
parts that bite:

- The mount grants create and truncate, not unlink. `rm`, `cp` over an existing
  file, and `tar -x` fail; `mv` and `cat >` work. Finished files go in
  `_to_delete/`.
- **The git lock is a CLASS, not `index.lock`.** `HEAD.lock` and
  `next-index-*.lock` block every git write with the same message, so sweeping
  one name reads a still-blocked repo as clean. `find .git -name '*.lock'`, and
  move aside only locks older than ~120s when another session may be live.
- `git status` on the mount is not evidence of drift: it hands git different
  mtimes for identical bytes, so porcelain reports ` M` while `git diff HEAD` is
  empty. Confirm against content.
- The inner bash budget is 130s and the real ceiling about 180s with an explicit
  timeout. One number, this one; do not re-derive it per call (R271).

The full procedure is `docs/cowork_sandbox.md`.
