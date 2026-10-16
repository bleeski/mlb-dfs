# `MLB SUPERSat to ...` satellites match no archetype row and block as unresolved

Filed by DEV for ARCHIVE (owner of `data/reference/dk_contest_archetypes.csv`), 2026-10-16 (Session 133, R464).

Measured on the 2,006 distinct MLB titles in both DK contest-entry histories and every entries CSV in the tree:
`MLB SUPERSat to TEN $20 French Slam (5-26) [2x] (1/2)` and `(2/2)` match no row. DK abbreviates "SUPERSatellite"
to "SUPERSat" here, and the `Satellite` row cannot match a word that does not contain it, so a Classic build with
such a contest refuses it as unresolved (`unresolved_contest_blockers`) until an operator passes
`--postures <id>=wta_satellite`.

R464 (Session 133) made every pattern meet a word edge on its right, so a new row must be the whole word DK writes:
a `SUPERSat` row matches `SUPERSat to ...` and not `SUPERSatellite` (which `Satellite` already covers). Suggested
row, to verify against the next such contest's payout: `SUPERSat,,satellite,,ticket_line,inferred_medium,...,0.22,ticket_line,`.
Incidence: one MLB Classic contest in Ben's own entry history (190634687, 2026-05-20, two $0.50 entries, a
satellite to a tennis contest); the same abbreviation also appears on NFL and soccer (`WC SUPERSat to ...`) rows.
