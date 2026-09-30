# DEV to ARCHIVE, 2026-09-30: `dk_contest_archetypes.csv` has no row for the Showdown "Triple Up" title

Found by Session 52 (R238) while checking which Showdown contest titles name inference covers. Over every distinct contest name in the 13 Showdown delivery manifests under `data/deliveries/2026-09-*/` (31 names), 30 match a row of `data/reference/dk_contest_archetypes.csv`. The one that does not:

`MLB Showdown $1 Triple Up [Top 9 Win $3] (SD @ LAD)` resolves `inferred_type: unknown`.

Since Session 52 a Showdown build names such a contest in `brief["contests"]` (`posture_source: unresolved`, `contest_shape: null`, the resolver's fall-through kept as `fallback_shape`) and `qa_portfolio` section 4 prints `archetype UNRESOLVED` for it. It is not defaulted and the build is not refused. A row here, or `--postures <contest_id>=<posture>` at build time, labels it.

What only ARCHIVE or Ben can supply: the posture and payout shape of a "Top 9 Win $3" contest (a fixed count of winners at 3x the entry fee reads as a cash-like line, not a top-heavy one), and whether the `Triple Up` family carries a field-size cap in its title. The file is ARCHIVE's (`data/reference/`), so this is a fragment and no row was added.
