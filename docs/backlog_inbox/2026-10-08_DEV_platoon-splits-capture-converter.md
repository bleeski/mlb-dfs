# 2026-10-08 DEV (Session 33): `--platoon-splits` reads a CSV the session has to hand-convert from StatsAPI `statSplits`

**Context.** `--platoon-splits <csv>` (R122, solver half) reads `name,team,ops_overall,pa_vs_L,ops_vs_L,pa_vs_R,ops_vs_R`. The session captures the numbers with its web tool (StatsAPI `/people/<id>/stats?stats=statSplits&sitCodes=vl,vr&group=hitting`, ~20 s for 18 bats per R122's rider) and nothing turns the JSON into that CSV, so each Showdown slate re-rolls a converter in a scratch dir: R332's shape again, one input over.

**Overlap to resolve first.** R402(a) (Session 34) defines the capture contract (`data/slates/<date>/captures/` with a url / fetched_utc / sha256 / tool sidecar, `tools/capture.py`). The converter belongs to that contract: it reads a captured `statSplits` JSON and writes the CSV with the sidecar, and `--platoon-splits` then defaults to the captured path. Session 33 deliberately gave the flag no default path for that reason.

**Fix shape.** `tools/capture.py`'s `splits` verb (or a sibling) parsing the StatsAPI split objects (`vl` / `vr` stat lines: `plateAppearances`, `ops`; the season line for `ops_overall`), joining the person to DK by the accent-folded name and team the engine already uses, and naming a hitter with no sample (a blank cell, which the reader accepts: that hand keeps the flat factor).
