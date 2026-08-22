# Solo Shot archetype gap, 3rd occurrence

Raised by a BUILD session, slate 2026-08-22 tag `1335_3g` (3-game early Classic,
9 entries across 7 contests). Create-only fragment; the owning role merges and
deletes it.

Same gap as `2026-08-19_BUILD_solo-shot-archetype.md` and
`2026-08-20_BUILD_solo-shot-archetype-recurred.md`, still unmerged.
`preflight_upload.py` warned:

    WARN  1 contest name(s) match no row in dk_contest_archetypes.csv:
    ['MLB $2.5K Solo Shot (Early)']

Supplied `--postures 194183875=single_entry` by hand, per both existing
fragments' proposed fix, and the build certified. Nothing here blocked
delivery. Third time paying the same one-line tax: adding the `Solo Shot`
family to `data/reference/dk_contest_archetypes.csv` (posture `single_entry`,
shape `single_entry_gpp`, pattern likely just `Solo Shot`) closes all three.
