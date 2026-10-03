# 2026-10-03 BUILD (1830_1g_sd, NYY @ TB ALDS game 1): the Showdown handedness map misses accented names

**Observed.** `showdown_handedness` reported `hitters_with_side: 16` of 18 posted hitters on a fully confirmed feed. The two misses were `Luis García Jr.` (feed) against `Luis Garcia Jr.` (DK salary file) and `Yandy Díaz` against `Yandy Diaz`. `apply_base_prior` looks the side up by `row["Name"]`, so both took the flat 1.00 platoon factor with `teams_without_hand: []` and nothing in the brief naming them. Reproduced offline: `bat_side.get("Luis Garcia Jr.")` is empty and `bat_side.get("Luis García Jr.")` is `L`.

**What the session did.** The build supplied every hitter's Base through `--projections`, so it applied the engine's own platoon convention (opposite hand 1.04, same hand 0.94) to those two by hand and recorded it in `1830_1g_sd_operator_priors_notes.csv`.

**Candidate item.** Key the handedness join on the DK player id or on an accent-folded name (`unicodedata.normalize("NFKD")`), and name any posted hitter left without a side in `handedness` as a list, not a count. `slate_intake_manager.normalize_name` (line 159) already folds accents and strips suffixes for Classic's intake; `showdown_handedness` does not call it: `build_slate.py` line 5240 stores `bat_side[str(hitter["name"])]` and line 5244 counts `hitters_with_side` by exact string against `df["Name"]`. Verified by grep on 2026-10-03; the fix is to route both through that normalizer.

**Second observation.** The Showdown intake keeps no relievers on a fully posted side (the 2026-10-01 fragment). On this slate the DK file lists 47 arms, 23 of them on the two ALDS active rosters (StatsAPI, 2026-10-03) and 24 not, 17 of those with a blank Status (for example Hopkins, Legumina and M. Rodriguez were cut from the Rays' series roster). A widened pool needs a roster allowlist as well as the arm filter, or 17 healthy-looking arms who cannot play enter it.

Nothing here is a lift, an edge, an ROI or a win rate.
