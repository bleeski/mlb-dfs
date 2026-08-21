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

**Ben's follow-up (2026-08-21, same session): the real fix is upstream of the
relaxation, in `showdown_theses.py`'s allocation table.** `pitchers_duel` got
`allocation: 1` while six other templates (`favorite_win_big`,
`favorite_win_big_no_sp`, `favorite_win_close`, and their `underdog_*`
counterparts) each got `2`, specifically so a second variant can hedge which
player captains. A "both starters rostered" game state is exactly the case
that wants that hedge: one lineup with Sale captaining and Misiorowski at
UTIL, one with Misiorowski captaining and Sale at UTIL, four hitters varied
enough between them to clear `max_shared_players=4`. Allocation at 1 is why
there was no sibling slot for the relaxation to fall back to, and it produced
a single lineup missing a starter instead of two lineups each carrying both.

This fits inside the existing 25% captain cap (`cap_count=4`), it does not
need a relaxation: in the delivered file Sale captained 3 of 19, so he has one
free captain slot; Misiorowski captained 4 of 19 (already at cap), so his half
of the hedge would need to come from reassigning one of his other three
captaincies to this thesis rather than adding a fifth. Both pitchers'
UTIL-side player exposure (Sale 5/19, Misiorowski 7/19) has headroom under the
50% cap either way. Recommend `pitchers_duel` move to `allocation: 2` (one
slot funded by trimming a less load-bearing template, e.g. `ace_loses` or
`both_explode`), each variant captained by a different starter with the
existing variant-2 hitter-diversification logic already used elsewhere in the
ladder.
