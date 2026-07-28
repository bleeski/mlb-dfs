# Contests awaiting standings — regenerated 2026-07-28

Scan: every contest ID on a filled entry row in `outputs/*/DKEntries*.csv`, minus
the archived set and the recorded unrecoverable. Regenerate by rerunning that
scan; do not hand-maintain this list.

Pull each while logged in to DraftKings, **check the file size is non-zero**, and
drop it in `data/standings/inbox/`. A zero-byte export is a failed pull, not a
pulled file. The inbox is flat; the miner reads Classic vs Showdown off the
lineup cells and resolves the salary file itself (`--auto-salary`).

## Status as of 2026-07-28

**Nothing is open.** The 2026-07-28 backfill pulled and mined 59 contests across
seven slate dates, archived as A-013 through A-026. Every contest that has ever
appeared on a delivered entry row is now either archived or recorded
unrecoverable.

The age rule widened as a result: exports from 2026-07-17 still returned
populated on a 2026-07-28 pull, so eleven days is not a hard cutoff. Age raises
the failure rate rather than setting a cliff. Keep pulling the night of, but a
missed pull is still worth attempting.

**Open gap, not a pull problem:** every contest in A-008 through A-026 is missing
entry fee, payout structure, paid places, and cash line, because the contest-page
trio was never captured manually. `python tools/net_to_date.py` therefore reports
76 contests and 241 entries with a zero money column. That data is not
recoverable from the standings export and is not recoverable late; it has to be
captured on the contest page at entry time. Until it is, there is no net line.

---

## Archived, do not re-pull

A-001 191787184, 191787186, 191823035 · A-002 192464820 ·
A-003 192413146, 192413147, 192444379 ·
A-004 191506958, 191506960, 191507209, 191507213, 191507220 ·
A-005 191488360, 191488366 ·
A-006 192657349, 192657350, 192658268, 192667458 ·
A-007 192701222, 192701224, 192701225, 192705822, 192709106, 192712196 ·
A-008 192657334, 192657335, 192667460 ·
A-009 192630776, 192652559, 192652560, 192652561 ·
A-010 192623314, 192623315, 192656508 ·
A-011 192591926, 192591927, 192627933 ·
A-012 192591443, 192591459, 192591504, 192593054 ·
A-013 192784475, 192784476, 192784479, 192798445, 192851120 ·
A-014 192784653, 192784672, 192784673, 192784674, 192798437, 192842358,
      192853093, 192853339 ·
A-015 192708093, 192708094, 192708096, 192708097, 192754543 ·
A-016 192708059, 192708060, 192708062, 192708063 ·
A-017 192707612, 192710507, 192744091, 192746313, 192747269, 192747982,
      192748828, 192753671 ·
A-018 192707473, 192707481, 192707519, 192707520, 192707521, 192707522,
      192707523, 192710479, 192738861, 192740560, 192741308 ·
A-019 192529275 ·
A-020 192442890, 192500593 ·
A-021 192464310, 192464354, 192464355 ·
A-022 192443599, 192443606, 192454586 ·
A-023 192413131, 192413132 ·
A-024 192344519, 192344520 ·
A-025 192344257, 192344259, 192369212 ·
A-026 191020573, 191020574

## Recorded unrecoverable, do not re-pull

191489664, 191513240, 191520890, 191521489, 191542451 (2026-06 tranche) ·
191047506, 192345441, 192419758, 192420813 (zero-byte on the 2026-07-28 pull)
