# An explicit wrong --salary that joins 0.0% still archives as coverage "full"

2026-08-08, ARCHIVE. Five 1910_4g contests were first mined with
`--salary data/slates/2026-08-06/DKSalaries.csv` (the 1235_5g early-slate
file). Salary join rate 0.0%, every stack_pattern empty, salary_left null —
and the record archived with `coverage: "full"`, exit 0. The wrong-salary
protection (exit 4) apparently guards the --auto-salary scoring path;
an explicit --salary is trusted even at a 0% join. A 0% (or near-0%) join on
an explicit salary file should either exit 4 or downgrade the record to
`standings_only`, because "full" with no joined salary is the misleading
middle: downstream shape/salary aggregation silently reads empty patterns as
an 'other' bucket. Found because the 2026-08-08 tranche analysis noticed five
winners with empty stack patterns; re-mined to standings_only via
--auto-salary (which correctly declined). Contests: 193297994, 193297995,
193303619, 193344230, 193344231.
