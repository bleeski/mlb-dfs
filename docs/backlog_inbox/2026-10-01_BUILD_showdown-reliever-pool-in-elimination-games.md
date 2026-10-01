# 2026-10-01 BUILD (2000_1g_sd, PHI @ ATL wild card game 3): Showdown intake drops every reliever on a fully-posted side

**Observed.** `melt_showdown_salary_csv(starters_only=True)` (the only call is `build_slate.run_showdown`) removes every pitcher that is not a DK `SP`/`P`/`PLR`/`PO` tag once a side's 1-9 is posted: 71 of 92 persons, all 41 pitchers but three. In a winner-take-all game with "all hands on deck" (PHI: Wheeler on 3 days' rest, Luzardo, Painter, Duran available; ATL: a bullpen game, Kerr `PO` then Holmes `PLR`) the `Starting` column says nothing about the arms who will pitch most of the innings.

**What the session did.** A scratch wrapper (`tools/_scratch_po_g3/run_wide.py`, gitignored) patched the melt to `starters_only=False`, then dropped bench hitters (unfiltered, they enter as pitchers do: no batting order, so `apply_base_prior` leaves them on raw APPG, Arraez included while off the series roster). Arms were priced through `--projections` (labeled operator priors). Two arms the pool would have lacked (Duran, Iglesias) were rostered as cheap hedge fillers; both needed `--declare-pitcher` or the preflight fails them as absent.

**Candidate item.** An operator flag on the Showdown door (for example `--keep-arms`) that keeps every non-OUT pitcher, never bench hitters, records `pool.operator_widening` in the brief, and defaults arms without a supplied Base to a labeled low prior rather than raw APPG. The unfiltered melt's bench-hitter leak is the trap to pin in a test.

**Second finding.** `--captain-sleeve` designates the FIRST N reserved rows, and the ladder deals favorite-side templates to those rows first, so a sleeve naming an underdog-side bat lands him as captain of a "PHI win big" roster as its one filler (seen with Harris II; one counted captain-cap relaxation). One designated entry on a favorite-side captain was clean.

Nothing here is a lift, an edge, an ROI or a win rate.
