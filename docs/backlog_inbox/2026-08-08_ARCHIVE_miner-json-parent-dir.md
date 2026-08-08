# field_miner does not create the --json parent directory

2026-08-08, ARCHIVE. First mine into a fresh archive date fails at the very
end: `--json data/archive/2026-08-05/mined_<id>.json` raises FileNotFoundError
at the `open(args.json_out, "w")` in `main` when `data/archive/2026-08-05/`
does not exist yet. All 30 mines of the 08-05/08-06 tranche failed this way
until a manual `mkdir -p`; everything upstream of the write (own-results
append, fragment write) had already run, so the failure lands after side
effects. `os.makedirs(dirname, exist_ok=True)` before the open, or fail before
side effects. Repro: any mine whose slate date has no archive folder yet.
