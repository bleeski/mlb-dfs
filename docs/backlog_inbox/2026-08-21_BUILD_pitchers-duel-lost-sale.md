# "Pitchers duel" thesis delivered without one of its two named starters

Slate `slate_2026-08-21_atlmil_sd` (1610_1g_sd), entry 5225725107 / contest
194119101. Thesis `pitchers_duel`, label "Pitchers duel - both starters
rostered," rationale "Neither offense gets going. Both arms on the card carry
the score." The delivered roster is CPT Jacob Misiorowski + UTIL Matt Olson,
Jackson Chourio, Cooper Pratt, Mauricio Dubon, Joey Ortiz -- no Chris Sale,
verified against `roster_ids` in the brief's `assignment_log` (Sale's CPT id
43897908 and UTIL id 43897818 are both absent).

Cause, per the brief's own caution text: the overlap bound (`max_shared_players`)
made no feasible lineup exist with Sale captaining this thesis, so the captain
LOCK relaxed and substituted Misiorowski. That substitution replaced Sale in
the roster entirely rather than keeping both pitchers and only changing who
captains -- so the delivered lineup no longer matches its own thesis name or
rationale text. Confirmed this is the only `pitchers_duel` slot in the ladder
(`construction.allocation.pitchers_duel: 1`), so there is no sibling lineup
that does carry both.

Worth DEV's attention: when a captain-lock relaxation fires on a thesis whose
definition requires a specific SECOND player (not just the captain), either
(a) constrain the substitute search to keep that second player rostered and
only swap the captain slot, or (b) relabel/flag the thesis text when the
substitution drops a defining player, so the brief doesn't describe a roster
that isn't the one delivered. Related to the general "relaxation visibility"
gap already filed same day in
`2026-08-21_BUILD_showdown-tool-gaps.md`, but this is a construction-behavior
question rather than a reporting-tool gap.
