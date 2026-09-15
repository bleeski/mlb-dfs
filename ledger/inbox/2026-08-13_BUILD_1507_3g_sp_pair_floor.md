# 2026-08-13 1507_3g — SP-pair repetition was the binding floor, not exposure

Run `20260813T184756Z_9db289df`, 19 entries, certified, sha256
`91738762e397446aba2fce6e35ea0439ef31c3c928a581e40689a92057dab888`.

4-team slate (BOS/TOR/CHC/WSH; CIN@CWS carried `Game Info: -` and was absent
from the pool, per operator instruction and unparsed game info). Bank exhausted
structurally at **8 unique candidates, 16/16 jobs, `budget_floored: false`** —
growing `--max-seconds` did not add candidates. Only 4 SPs exist on the slate,
so the candidate bank held too few distinct SP pairs to cover 19 entries at
`max_sp_pair_repetition=5`.

Relaxation ladder observed, each attempt refused identically:
1. defaults → infeasible
2. pitcher/player exposure 0.75 → infeasible
3. exposure 0.85 + primary stack 0.50 → infeasible
4. **`max_sp_pair_repetition: 10`** (+ exposure 0.85, stack 0.55, shared 9) → certified

Realized top exposure came in at **52.6%**, i.e. the default 0.5263 cap, so the
exposure relaxations were never what bound. Only the SP-pair term was. The
refusal string ("no single control is arithmetically binding ... the interaction
is") did not distinguish these, and three calls went to bisecting it under a
T-20 clock.

Candidate for the backlog: when `job_list_exhausted` is true and
`distinct_sp_pairs * max_sp_pair_repetition < entries`, name that inequality in
the refusal. It is a closed-form arithmetic check available before the MILP runs.

Consequence to record against outcomes: 19 entries drawn from 8 unique lineups
means **7 duplicate lineup groups**; preflight reports overlap 10 on 23 pairs.
Not a defect on WTA satellites, but this portfolio is not 19 distinct shots.
