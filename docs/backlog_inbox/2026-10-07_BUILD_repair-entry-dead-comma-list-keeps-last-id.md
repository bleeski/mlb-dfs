# 2026-10-07 BUILD (1600_4g late swap): `repair_entry.py --dead a,b` silently repairs only `b`

**Observed.** `python tools/repair_entry.py ... --dead 44418125,44418175 --mode repair --dry-run --json` reported `"dead_player_ids": ["44418175"]` and repaired only Chandler Simpson's two entries; Jazz Chisholm Jr.'s five (44418125, absent from NYY's confirmed nine) were left untouched with no warning and no refusal. Re-run as `--dead 44418125 --dead 44418175` it found all seven, matching `--dead-from-feed`.

**Mechanism (read, not inferred).** `--dead` is `action="append"` (`tools/repair_entry.py` L649), one token per flag. `resolve_dead_players` (L155) passes each whole token to `_digits`, which returns the LAST `\d{4,}` run in the string, so a comma list resolves to its final id and the rest vanish. The "unresolved token" refusal (L796) never fires because the token did resolve, to the wrong subset.

**Candidate item.** Split each `--dead` token on commas and whitespace before resolving, or refuse a token holding more than one digit run, naming it. A test: `--dead 1,2` against a two-dead fixture repairs both (or exits 3 naming the token). Effort XS. Under a lock clock this is the dangerous shape: the tool prints a clean repair of a subset.

Nothing here is a lift, an edge, an ROI or a win rate.
