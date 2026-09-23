# The Classic bank cannot grow past 12 candidates per entry on any host (R349 follow-on)

Slate 2026-09-23 1905_10g, cloud container (call budget 630s). Ben asked to
expand the bank with time left before lock. It cannot be expanded without a code
change:

- `skills/generate-lineups/scripts/build_slate.py:3045` sets
  `_total_max = max(n_entries * 12, 60)`, which is 384 for 32 entries.
- `mlb_engine/optimize/bank_cache.py:953` stops `extend_bank` when
  `len(cache) >= max_candidates`. That count is the TOTAL cache, so re-running
  the same command never adds a candidate once the cache holds 384.

Measured on four builds tonight: every one stopped at exactly 384 candidates
after 17.9-19.2 s of bank time, with 439-440 of 7,200 jobs attempted (6%) and
`job_list_exhausted: false`. The bank's time budget was 24-29 s against a 630 s
host call budget.

SKILL.md's "exit 10 is normal, run it again and the bank grows" is true only
where TIME binds, as on Cowork's 130 s budget. On the cloud host the cap binds
first, so CLAUDE.md's delegated "grow the bank, always" has no lever there.

Proposed for DEV:
- Scale `_total_max` with the host's call budget (`repo_env.host_profile()`),
  or take `--bank-max-candidates` / a `controls_override` key recorded in the
  brief.
- Name the binding limit in the brief ("bank stopped at the candidate cap" vs
  "stopped at the time budget"), so a session can tell which lever it holds.
