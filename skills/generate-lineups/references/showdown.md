# Showdown (DK Captain Mode)

Read this only when the Showdown path misbehaves or Ben asks about its internals.
The normal route is `scripts/build_slate.py`, which detects Showdown and handles
all of it.

**Construction changed 2026-07-25.** `run_showdown` now builds from the game-state
thesis ladder in `mlb_engine/optimize/showdown_theses.py` whenever the pool basis
is `declared_starters` with both orders posted. `build_showdown_bank`, documented
below, is the fallback for an unposted slate. Two portfolio controls are enforced
in the solver on both paths: `max_shared_players=4` (overlap counts the player,
not the role) and `max_cpt_exposure_pct=0.33`. They relax before they truncate,
overlap first and the captain cap last, and every relaxation is counted in the
brief under `diversity` and `captain_exposure`.

## Status, stated plainly

`mlb_engine/optimize/showdown.py` is `VERSION = "0.3-review"`, and
`docs/2026-07-18_implementation_guide.md` lists Phase 3 (Showdown) as not started.
The strategic brief recommends the correlation model ahead of it, on the reasoning
that a new archetype series splits thin ledger data across two contest types and
slows both ownership gates.

So Showdown works, has tests, and produces a legal file, but it does not carry the
Classic three-gate certification. The build script labels its output
`review_grade_build` for that reason. Pass the label through. Calling a Showdown
file "certified" or "upload-ready" in the Classic sense is exactly the kind of
inflated claim the truthful-labels rule exists to prevent.

## The contract

From `mlb_engine/optimize/roster_contracts.SHOWDOWN`:

- Roster: 1 CPT + 5 UTIL, six players
- CPT scores 1.5x and uses the CPT row's own salary and draftable ID
- No player in both roles
- At least one player from each team
- Salary cap 50,000
- Export header: `Entry ID, Contest Name, Contest ID, Entry Fee, CPT, UTIL x5, "", Instructions`
- Roster cells start at column index 4

Scoring is identical to Classic, so projections transfer untouched. With no richer
projection supplied, the module uses the salary file's AvgPointsPerGame as a
labeled deterministic Base proxy. That is a prior, not a projection, and it is
weaker than what Classic gets.

## The path

```python
from mlb_engine.optimize import showdown as sd

df = sd.melt_showdown_salary_csv(salary_csv)      # one row per player-role
reserved = sd.read_showdown_reserved_rows(entries_csv)
blank = [r for r in reserved["reserved"] if not r["is_complete"]]

bank = sd.build_showdown_bank(df, n=len(blank))   # caps: 0.33 cpt, 4 shared
certs = [sd.certify_showdown(lineup, df) for lineup in bank]

assignments = [
    {"entry_id": row["entry_id"], "roster_ids": list(lineup["roster_ids"])}
    for row, lineup in zip(blank, bank)
]
sd.write_showdown_entries(entries_csv, out_path, assignments)
sd.verify_template_preserved(entries_csv, out_path)
```

Three things that will bite:

**`roster_ids`, not the lineup object.** `write_showdown_entries` wants a flat list
of six draftable IDs (CPT first). Passing the lineup dict silently assigns nothing
and the output file never gets written, which surfaces later as a confusing
FileNotFoundError from the verifier.

**Only blank reserved rows are fillable.** A complete row is immutable. Filter on
`is_complete` before zipping against the bank, or the assignment count will not
line up with the rows that actually need filling.

**The template must be preserved.** `write_showdown_entries` refuses to write over
the template, and `verify_template_preserved` confirms every non-roster cell came
through unchanged. Never edit the uploaded entries file in place.

## Solver

`scipy.optimize.milp` only, mirroring `optimizer_v3`. `build_showdown_lineup`
takes `locks`, `excludes`, `cpt_lock`, `forbidden_sets`, and a `time_limit`
(default 20s). `build_showdown_bank` wraps it and passes kwargs through, using
`forbidden_sets` to keep each lineup distinct.

Showdown archetypes never pool with Classic in the ledger or in the ownership
work. Keep them separate when archiving results.
