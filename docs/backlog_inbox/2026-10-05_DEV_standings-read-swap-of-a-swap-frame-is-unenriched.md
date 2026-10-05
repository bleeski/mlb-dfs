# 2026-10-05 DEV (Session 141, R472): a swap whose parent run is itself a `late_swap` run reads ceilings from an unenriched frame

**Observed.** `tools/standings_read.frame_for_run` is ONE hop: it reads `runs/<id>/final/projections.csv` of the run `late_swap` resolved by the delivered file's bytes (R268(b)). A swap run writes `final/projections.csv` too, but its frame is the swap's own `emergency_proxy` frame with no Savant, F1/F4/F5 or FanGraphs input (R428), so when the file being refined is itself a swap's output the verdict's remaining-slot ceilings are APPG-derived. The report names it (`ceiling frame: parent run <id> (mode late_swap); unenriched swap frame: its ceilings are APPG-derived (R428)`); the verdict still computes.

**Why it is filed and not fixed in Session 141.** The fix is a walk up the run manifests' `parent_run_id` (cycle-safe, bounded) to the nearest non-`late_swap` run, with the swap frame filling only the players the build never carried. Session 115 (R428) makes a swap reuse its parent's enrichment, which makes the walk moot, so the walk was cut from R472's plan after the advisor review.

**Candidate item.** After Session 115 lands, confirm a swap run's `final/projections.csv` carries the parent's enriched `Ceiling`; if it does, delete the `late_swap` note in `frame_for_run` and the `test_the_frame_is_one_hop_and_names_the_run_and_its_mode` assertion on it. If it does not, add the walk. XS.

Nothing here is a lift, an edge, an ROI or a win rate.
