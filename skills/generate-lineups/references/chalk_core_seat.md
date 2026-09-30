# The chalk-core seat (R469)

Read this when a brief's `chalk-core seat:` line shows a relaxation, when a feasibility
check named `consensus_pair_seat_capacity` fails, or when a late swap refuses on it.

## The rule (Ben, 2026-09-30)

Every Classic contest with two or more entries seats at least one lineup on the
projection's consensus SP pair, differentiated through its bats. On 1400_4g the Opener
held no Sale + Schlittler lineup: both arms sat at the 0.43 pitcher cap and the objective
spent the seats elsewhere. A construction rule over labeled priors, never a claim about
what the pair scores.

- **The pair.** The top two rostered-legal SPs by `Base_Projection` (ties by Ceiling, then
  id), not opponents of each other: when the top two face each other, #1 pairs with the
  next arm who does not. Computed once by `run_slate`'s feasibility inputs and carried in
  the controls (`consensus_sp_pair`), so the run record holds it and a late swap inherits it.
- **The count.** `min_consensus_pair_entries_per_contest`, per contest from its posture:
  1 on `large_gpp`, `wta_satellite`, `small_gpp`, `mme`; 0 on `single_entry`, `cash`; 0 for
  a contest with fewer than two rows. A cash contest in a mixed file does not switch it off
  for the others. An override sets every multi-entry contest; it is a whole number and the
  units gate refuses anything else at exit 4.
- **The caps.** The pitcher, player and pair caps are floored UP to the seats required, on
  the ordinary floor path (`derived_floor` provenance). A `--never-relax` cap is not moved:
  the advisory check `consensus_pair_seat_capacity` names the shortfall and the allocator
  relaxes the seat.
- **The bank.** Every door runs a pinned-pair slice (`build_consensus_pair_jobs`: P1 and P2
  pinned, stack jobs for the bats) sized to twice the seats, and the allocator's prefilter
  reserves the pair's lineups. Search effort only.
- **Relaxation.** A contest whose bank holds no compatible pair lineup is relaxed and
  counted; a proven-infeasible joint solve steps the seat after the five-stack quota and
  before the primary-stack floor. Never a refusal: an S control never costs the file.
  `--never-relax min_consensus_pair_entries_per_contest` is refused by name for that reason.

```bash
python skills/generate-lineups/scripts/build_slate.py ...     --controls-override '{"min_consensus_pair_entries_per_contest": 0}'   # off for one build
```

Where to read it: the brief's `exposure.consensus_pair` (the pair and names, what each
contest owed and seated, every relaxation, the bank slice's `jobs`) and the
`chalk-core seat:` line, `A 1/1` meaning contest A seated 1 of the 1 it owed.

## Late swap

The swap refuses at exit 3 when it would leave a contest with no pair lineup that its
parent held, naming the parent entries; `--accept-downgrade` takes it and the file ships
review-grade. A seat that moves to another entry of the same contest is not lost. A hand
edit never passes through the swap: the rule for that path is R472's printed verdict.
