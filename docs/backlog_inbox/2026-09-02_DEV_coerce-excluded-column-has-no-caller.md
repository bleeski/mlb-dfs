# `optimizer_v3.coerce_excluded_column` has no caller anywhere (P3, XS)

DEV, 2026-09-02 ET. Found while enumerating the `Excluded` class for R291;
out of that item's scope, filed rather than fixed.

**What.** `mlb_engine/optimize/optimizer_v3.py:700-707` defines
`coerce_excluded_column(projections_df)`, documented as "Return a copy whose
Excluded column is real booleans, plus the report". Measured at HEAD:

    grep -rn "coerce_excluded_column" mlb_engine tools skills tests --include=*.py
    mlb_engine/optimize/optimizer_v3.py:700:def coerce_excluded_column(projections_df):

One hit, the definition. No production caller, no test, and an AST walk of the
same tree for the name finds nothing the grep did not.

**Why it is worth a line.** It is a third exported entry point into the one
reading of the column, beside `read_excluded_cell` (the scalar) and
`excluded_flags` (the frame). R291 had to decide, at four sites, which reader to
use, and a same-named third option with no caller is exactly the kind of choice
that gets made wrong once. It also has a live-looking bug shape a caller would
hit: `out['Excluded'] = flags if report['column_present'] else False` writes a
scalar False on a frame with no column, which is fine for pandas but means the
"real booleans" promise is met two different ways.

**Fix, either direction, and the decision is which.** Delete it (R273's
dead-site treatment), or give it the caller it was written for: `_drop_excluded_rows`
and the two bank-stamp sites at `execution_pipeline.py:3446-3449` and
`:4823-4826` each open-code a piece of what it does. Deleting is the cheaper and
more honest of the two unless someone remembers the intended caller.

**Not R303.** It could ride R303's Tier 5 solver list, but that list is long and
this one sits inside the class two P0s have now been filed against, so it is
worth its own line until R291's class is quiet.
