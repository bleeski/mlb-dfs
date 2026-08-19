# "Apex" means leverage-adjusted, not points-max, and the engine has every piece but the pipe

**Found:** 2026-08-19, BUILD session, slate `1235_4g`, contest 194022265
(MLB $100K Relay Throw, 7,833 entries, $25K to 1st). Ben stated the objective
directly: apex is p(first), so a 2%-owned player at the same projection is
worth more than a 30%-owned one. This note grades that against the archived
standings and proposes the change.

## The first graded ownership prediction (R135's whole purpose)

`outputs/2026-08-19/ownership_pred_1235_4g.json` was emitted pre-lock with all
four features applied. The standings export gives realized `%Drafted` for 112
priced players. Joining them, per archetype:

| archetype | Spearman | MAE | mean signed | pred sum | real sum |
|---|---:|---:|---:|---:|---:|
| cash | +0.660 | 4.96 | -1.30 | 763 | 909 |
| single_entry_gpp | +0.649 | 5.13 | -2.02 | 683 | 909 |
| wta_satellite | +0.641 | 5.23 | -2.17 | 666 | 909 |
| small_gpp | +0.620 | 5.44 | -2.44 | 636 | 909 |
| **large_field_gpp** | **+0.581** | **5.71** | **-2.67** | **610** | 909 |
| mme | +0.505 | 5.96 | -2.87 | 588 | 909 |

Read the two columns separately, because they say opposite things. The LEVEL
is badly calibrated: every archetype under-predicts, `large_field_gpp` by a
third. Rescaling to the known slot total does NOT fix it (MAE 5.71 -> 5.92),
so it is not a simple normalization error. But the ORDERING is usable at
+0.58 to +0.66, and ordering is the only thing a leverage objective needs. You
do not need to know a player will be owned 30%; you need to know he will be
owned more than the alternative.

R10's bar is a fitted prior that beats flat-12. Flat-12 carries ZERO rank
information by construction, so +0.581 clears it on this cell. That is one
slate and one contest, and the grade belongs in the ledger, which is ARCHIVE's
write, not this session's.

## What the delivered entry actually did

Cumulative predicted-vs-realized ownership across all 7,822 parsed lineups,
by finish band:

| band | n | realized cum-own | sub-10% bats | points |
|---|---:|---:|---:|---:|
| 1st | 1 | 167.0% | 4.00 | 123.65 |
| top 10 | 10 | 160.1% | 4.50 | 117.02 |
| top 75 | 75 | 160.8% | 4.32 | 110.04 |
| top 235 | 238 | 166.9% | 4.10 | 102.95 |
| cashed (1-1710) | 1,724 | 177.9% | 3.62 | 87.61 |
| missed | 6,098 | 190.3% | 3.25 | 58.28 |
| whole field | 7,822 | 187.5% | 3.33 | 64.74 |
| **our entry** | 1 | **254.7%** | **2** | **56.35** (rank 5287) |

Monotone across every band, and our entry sat at the **95.6th percentile of
chalkiness** in a field of 7,833.

**The pre-lock file already knew.** Scored on the prediction alone, our entry
was the **97.6th percentile** chalkiest, and the predicted band means track the
realized ones: 1st 63, top 10 70, top 235 66, field 71, ours 90.
`qa_portfolio.py` even printed it as "+37.6 pp chalk-positive". The number was
computed, written to disk, and displayed. Nothing in the objective consumed it.

## The gap is one column

- `optimizer_v3._ownership_pct_for_row` already READS
  `Projected_Ownership_Pct`, falling back to `DEFAULT_OWNERSHIP_PCT_BY_TIER`
  and a flat 12.0.
- `_lineup_projected_ownership_sum` and `_low_owned_hitter_count` already
  EXIST as post-solve diagnostics.
- `add_constraint(coefs, lb, ub)` takes arbitrary linear coefficients over the
  assignment variables.
- `tools/ownership_pred.py` already WRITES per-archetype ownership keyed by
  `Player_ID`.

Nothing connects the writer to the reader. The engine has both ends of the
pipe and no pipe.

## STATUS: A and B SHIPPED as R154 the same day. C is what remains.

Ben approved A and B and they landed in R154 (see CHANGELOG.md). What is left
for the backlog owner is C, plus one thing R154 deliberately did not do:
**nothing calls `attach_projected_ownership` on the production path yet**, so
no build changes until a caller sets values. Wiring it into `run_slate` with
per-contest-shape numbers is the next item and is smaller than C.

## Proposal, in sequence

**A. Wire it (mechanical, no behaviour change).** Populate
`Projected_Ownership_Pct` on the projections frame from the archetype block
matching each contest's resolved shape. Behaviour is unchanged until B or C
lands; this only makes the number reachable and makes the diagnostics real
rather than flat-12.

**B. Two linear constraints (the fast win, do this next).** Cumulative
ownership is a linear function of the roster indicators, so both drop into the
existing MILP with no objective surgery and no re-derivation:

- `max_cumulative_ownership_pct`, a per-lineup cap
- `min_low_owned_hitters`, a floor on bottom-tier bats

Target band from this contest: roughly 160-170% cumulative and at least 4
low-owned bats for a top-heavy large field. State that as a TARGET BAND
DERIVED FROM ONE CONTEST, never a calibration.

Constraints before an objective term is deliberate. A constraint is auditable,
testable against a measured band, and cannot silently re-rank every player the
way a mis-weighted objective coefficient can.

**C. Replace the leverage proxy in the objective (the real change, later).**
`salary_uniqueness_weight` (0.62 on `large_field_gpp`) is the engine's current
stand-in for uniqueness, and on this slate it measured nothing: the delivered
entry spent exactly $50,000 and was the 97.6th percentile chalkiest lineup in
the field. Salary uniqueness is not ownership uniqueness. The replacement is
Ben's own formulation, a leverage-adjusted value term weighted by contest
shape, zero for cash and largest for a top-heavy large field.

Do C after 3-5 more graded slates. One contest cannot size a coefficient that
changes what every player is worth.

## What this note does NOT claim

Our entry finished 5287th and scored 56.35 against a field mean of 64.74, so
it lost on POINTS as well as on leverage, and the two cannot be separated from
one result. Four rostered players scored zero and Skenes returned 8.95 at
53.2% owned.

On this slate the chalk busted, which is what makes the ownership/finish
relationship look so clean. On a slate where chalk hits, the ordering inside
the cashing bands inverts. The structural case for leverage does not rest on
chalk busting; it rests on duplication splitting a top-heavy prize. But the
MAGNITUDE above is one observation and is not a calibration.
