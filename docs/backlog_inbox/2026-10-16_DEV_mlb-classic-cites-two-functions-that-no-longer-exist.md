# `MLB_Classic.md` cites `winning_threshold` and `classify_contest_type`, which no longer exist

Filed by DEV, 2026-10-16 (Session 133, R464), found while correcting `MLB_Classic.md:527`.

`MLB_Classic.md` line ~597 says `winning_threshold` "now also filters by `field_size_band` and `contest_type`" and
that `classify_contest_type(contest_name, archetypes)` "infers the type from `dk_contest_archetypes.csv` by
longest-pattern match". Neither function, nor `field_size_band`, is defined anywhere under `mlb_engine/`, `tools/`
or `skills/` at HEAD (`grep -rn "def winning_threshold\|def classify_contest_type\|def field_size_band" mlb_engine
tools skills --include=*.py` returns nothing). The contest-type reader the build uses is
`dk_entries_manager.infer_contest_archetype`, and it has ranked by type precedence, not pattern length, since R17.

Ask: find where the winning-threshold query went (or whether it was retired) and rewrite or delete the paragraph.
Docs only; nothing reads it.
