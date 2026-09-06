# Showdown (DK Captain Mode)

Read this only when the Showdown path misbehaves or Ben asks about its internals.
The normal route is `scripts/build_slate.py`, which detects Showdown and handles
all of it.

**Construction changed 2026-07-25.** `run_showdown` now builds from the game-state
thesis ladder in `mlb_engine/optimize/showdown_theses.py` whenever the pool basis
is `declared_starters` with both orders posted. `build_showdown_bank`, documented
below, is the fallback for an unposted slate.

**THREE portfolio controls are enforced in the solver on both paths, not two,
and the captain cap is 0.25 and not 0.33 (R153, Ben 2026-08-19).** This section
said "two portfolio controls ... `max_cpt_exposure_pct=0.33`" until 2026-09-06,
which is a money-boundary defect: a session reading it would have believed a cap
50% looser than the one the solver holds, and would not have known the third
control existed at all. The defaults live in `mlb_engine/optimize/showdown.py`
and are the citation:

| control | default | counts |
|---|---|---|
| `max_shared_players` | `DEFAULT_MAX_SHARED_PLAYERS = 4` (of 6) | the PLAYER, not the role |
| `max_cpt_exposure_pct` | `DEFAULT_MAX_CPT_EXPOSURE_PCT = 0.25` | no captain above a quarter of the entered set |
| `max_player_exposure_pct` | `DEFAULT_MAX_PLAYER_EXPOSURE_PCT = 0.50` | no PLAYER in ANY role above half of it |

The third one is the portfolio-level washout axis the dual objective names and
the module did not have: on the 2026-08-19 ARI@BOS build the overlap bound was
clean, the captain cap was clean, and one cheap leadoff bat was in 12 of 19
entries.

Every cap count is a `floor()` of pct * entries, so realized exposure lands at
or below the requested pct at every entry count; the one escape is `pct * n < 1`,
where the count clamps to 1 rather than forbidding everyone.

**They relax before they truncate, in the order overlap, then player exposure,
then captain lock, then thesis** — a short bank leaves a blank reserved row and a
blank row blocks certification. Player exposure sits second because relaxing it
puts one more entry on a player already at half the set, a washout cost spread
thin, where relaxing the captain lock concentrates the single highest-leverage
slot. Both caps bind against the REALIZED set and not against an apportionment.
A capped player coming off a thesis's captain slot or locks BEFORE the solve is
not a relaxation and is not counted as one; it is named in
`player_exposure.cap_reassignments` and `.locks_dropped`. Every relaxation is
counted in the brief. **A portfolio is not clean because the gates passed; it is
clean when the relaxation counts are zero.** Override all three through
`--controls-override`, which reads them from one dict. CLAUDE.md's `## Showdown`
section is the authority for all of this.

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

bank = sd.build_showdown_bank(df, n=len(blank))   # caps: 0.25 cpt, 0.50 player, 4 shared
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
