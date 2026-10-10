# 2026-10-10 BUILD (2000_1g_sd): `qa_portfolio.py` prints "F1 NEUTRAL" on a Showdown build whose brief applied F1

**Observed.** `python tools/qa_portfolio.py --entries outputs/2026-10-10/DKEntries_G5_startersonly_d37283d6f91d.csv --brief outputs/2026-10-10/build_brief_G5_startersonly_d37283d6f91d.json` section 1 printed `F1 NEUTRAL: no implied totals reached the projections`. The same brief carries `f1.prior.applied: true`, `non_neutral_f1: 18`, `factor_by_team: {CLE: 1.0373, CWS: 0.9627}` from an `--odds` file.

**Likely mechanism (not traced).** Section 1 reads the Classic enrichment self-report (`enrichment.f1_league_mean_implied_total` and friends), which a Showdown brief does not carry, and reads its absence as neutral. The skill tells a session to read that section first and believe it, so on Showdown it states the opposite of what the build did.

**Candidate item.** Have section 1 read `brief["f1"]["prior"]` when `contest_type == "showdown"`, and say "not reported" rather than NEUTRAL when neither shape is present. Effort XS.

Nothing here is a lift, an edge, an ROI or a win rate.
