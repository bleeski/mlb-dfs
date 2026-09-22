# autobuild misses bank_exploration on the SLICED path too; refusal records are untagged

BUILD, 2026-09-22, slate 1905_10g (10 games, 34 Classic entries, delivered run
20260922T214742Z_a02e9e31, sha256 d4a2a080636d). Two findings. Everything else
this slate hit is already filed and only gets a sighting line at the end.

## 1. The backlog's "works on the sliced bank" is false: the reader misses both paths

`docs/backlog.md` (the autobuild bank-exhaustion entry, "The real mechanism: the
fact is written in prose and read as a key") says the `autobuild.py` grow branch
"works on the sliced bank and not on the direct one". This slate's first
autobuild attempt ran SLICED (the cache at
`runs/bank_cache_2026-09-22_b41177b517.json` holds 462 attempted jobs and 408
candidates from that attempt). Its refusal brief carried:

- `bank_exploration: {"jobs_attempted": 462, "jobs_total": 3240, "job_list_exhausted": false, "total_candidates": 408, "budget_floored": false}` at TOP LEVEL
- no `solve` key at all

`autobuild.py` tests `(brief.get("solve", {}) or {}).get("bank", {})`, so it read
`{}`, skipped the grow branch, and stopped with "refused with no remedy this
supervisor may take" (`outputs/2026-09-22/autobuild_decisions.json`, attempt 1).
The sliced refusal writes the fact under `bank_exploration` and the supervisor
reads it under `solve.bank`, so the read fails on both paths. The filed fix
(one extractor reading `solve.bank`, then `bank_exploration`, then
`bank_diagnostics`) covers this. The correction is to the claim that sliced
works, because that claim prioritizes the item as direct-path-only.

## 2. Refusal records never carry the slate tag or the reason

`build_slate.py` `_main_recording_refusals` calls
`write_refusal_record(..., slate_tag="", refusal={"argv": argv, "note": ...})`.
On this slate that produced eleven records named
`data/deliveries/2026-09-22/untagged_<utc>.json`, each with `slate_tag: ""` and
nothing but argv, while every matching refusal brief carried
`slate.tag: "1905_10g"` and the error text. So a refusal record cannot be joined
to its slate by tag, and it cannot say why the build refused (pool block,
interaction infeasibility, BANK-LIMITED SP pairs) without re-running the argv.
SKILL.md says "a night that shipped nothing is the night the record is worth
most", and on that night this record is the only thing that survives.

Fix: have the refusal path hand `_main_recording_refusals` the tag and the
payload's `refusal`, `refusal_class`, `errors[:3]`, and failing
`feasibility.checks`, for example through a module-level holder set at each
`REFUSAL_SITES` exit. Test: a refusal-exit fixture whose record carries a
non-empty `slate_tag` and the error text.

## Sightings of filed items (no new mechanism)

- R204 rider (grow hint after the candidate cap): `max(34 * 12, 60) = 408` was
  reached at 462 of 3240 jobs. Seven more sliced re-runs added zero candidates,
  and each refusal still printed "FIRST REMEDY, grow the bank ... 14.3%".
- ed6 rider (direct/sliced flip): `--max-seconds 540` and `250` each chose
  DIRECT and wrote `solve.bank: null`. The 250s direct bank sampled 26 of 162
  viable SP pairs and refused BANK-LIMITED, and nothing persisted. About 16
  minutes went to calls that could not grow the persistent bank.
- `build_slate.py --help` crash: already in
  `2026-09-22_BUILD_showdown-1915-small-defects.md` section 1.

## What the build did, for the record

The R157 rescue opened ONE cap. A sanity build at 1.0/1.0/1.0 certified: max
player 24/34 (Baldwin, Vargas), max SP 9/34, max primary stack 4/34. Only the
player cap was binding. A step-down on the full sliced bank certified at 0.70,
0.60, 0.55, 0.50, 0.45, 0.40, and 0.37, and refused at 0.35. Delivered at
`max_player_exposure_pct` 0.35 -> 0.37 (11 -> 12 of 34), with
`max_pitcher_exposure_pct` 0.43 and `max_primary_stack_exposure_pct` 0.35 left
at posture defaults.
