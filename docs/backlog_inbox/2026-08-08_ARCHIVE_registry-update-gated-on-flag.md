# update_registry only runs when --registry is passed; the runbook says omit it

2026-08-08, ARCHIVE. `docs/cowork_archival_runbook.md` Job 1 says "Do not pass
--registry. It defaults to data/reference/field_opponent_registry.json" — but
`field_miner.main` gates the call on the flag (`if args.registry:
update_registry(...)`), and `update_registry`'s internal default
(`registry_path or default_registry_path()`) is only reachable when the flag
was passed with some value. Net effect: a runbook-compliant mine never touches
the registry. All 31 mines of the 2026-08-08 tranche skipped accumulation
silently; caught by comparing registry contests_mined (236) against
own_results (267). Either main calls update_registry unconditionally with
`args.registry or None`, or the runbook says to pass the flag. Interim: full
`tools/rebuild_registry.py` rebuild started 2026-08-08, resumable state in
`.field_opponent_registry.json.rebuild`, ~13s/contest on the mount.
