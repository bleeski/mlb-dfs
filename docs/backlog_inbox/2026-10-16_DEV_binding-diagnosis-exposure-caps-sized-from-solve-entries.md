# The infeasibility diagnosis sizes the exposure caps from the solve's entries on a late swap

Filed by DEV, 2026-10-16 (Session 65, R166), found while giving the diagnosis's reuse line its headroom.

`contest_allocator._diagnose_binding_constraints(E, ...)` is called with `entries_count = E` at both sites
(`select_and_assign_entries`, the `errors[]` call and the `binding_constraints` report call), and resolves
`max_primary_stack_exposure_pct` (and the sibling counting checks) as `_cap_count(E, pct)` against `E` entries. Since
R61 the solve resolves those caps over `total = E + fixed_rows` and subtracts what the untouchable rows hold. On a
proven-infeasible late swap the diagnosis therefore states a cap count and a capacity the solve never used: a stack
cap of floor(0.35 x 12) = 4 with 2 held in the fixed rows is diagnosed as floor(0.35 x 2) = 1 with nothing held.
Session 65 fixed only the reuse line (its R166 control). The diagnosis is advisory, so nothing ships wrong; an operator
reading the refusal is pointed at the wrong number.

Ask: pass `total` and the R61 offsets to the diagnosis and state each counting check as headroom over E, the way the
reuse line now does. Check: a swap fixture whose stack cap binds, asserting the finding's numbers match the solve's.
