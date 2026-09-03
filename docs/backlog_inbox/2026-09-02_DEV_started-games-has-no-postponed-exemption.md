# R287 rider: `check_started_games` has no postponed-game exemption, and it is now in BOTH referees

Filed by the DEV session that shipped R292, 2026-09-02. Found while deciding
where (d)'s call belonged; deliberately not fixed in that batch.

## The condition

`preflight_upload.check_started_games` (`:818`) reads the salary file's
`Game Info` and nothing else, and R287's docstring gives the reason: it must run
at 19:56 on a night with no feed, and `Game Info` is in the file the operator is
already passing. The cost of that choice is that a POSTPONED game's scheduled
start has passed while its players are still swappable, and the salary CSV cannot
tell the two apart -- `verify_export.derive_locked_teams` says so in its own
docstring ("It cannot tell a postponed game from a game in progress").

So a file legitimately holding players from a postponed game hard-fails at the
money boundary, and the only way past is `--force`, which exits 4. CLAUDE.md's
R272 clause requires both referees to exit **0** before a hand-corrected file
ships, so on a postponed-game slate that clause cannot be satisfied at all.

## Why R292 left it

R292(d) put the same check in `verify_export` on its no-parent branch, so the
false positive is now in both tools rather than one. That is the CONSISTENT
state, and it is the reason not to fix it here: two implementations of one rule
that disagree is this repo's named no-op failure class, and exempting in one tool
only would create exactly that. The rule has one owner and the exemption belongs
to the owner.

## The input already exists and is thrown away

`derive_locked_teams_from_feed` (`verify_export.py:177`) returns
`(locked, note, not_locked)`, where `not_locked` is precisely the teams in games
the feed reports postponed, cancelled or suspended -- an affirmative "has not
locked", not merely an absence. `resolve_locked_teams` (`:240`) consumes it,
subtracts it, and does not return it. So the fix is:

* `check_started_games(entries, salary, as_of, rep, exempt_teams=())` -- an
  optional set, default empty, so `preflight_upload`'s own call (which has no
  feed at that point) behaves exactly as today;
* `resolve_locked_teams` returns `not_locked` as a fourth value (two callers:
  `verify_export.py:536` and `test_upload_integrity.py:2580`'s `_resolve`
  helper, which unpacks three);
* `verify_export` passes it; the exemption is NAMED in the report rather than
  silently applied, on R237's rule that an absence and an observation are not the
  same fact.

Preflight can reach the same evidence when it resolves a feed (`:2144`), but that
happens AFTER `check_started_games` at `:2105`, and R287 put the check early on
purpose ("a started game makes every other verdict about that entry moot"), so
moving it is a separate decision.

## Not verified

Whether DK actually keeps a postponed game's slots editable in a bulk CSV upload.
The engine treats postponed as not-locked throughout (`excluded_game_ids`), and
the swap path has behaved that way since R29, but nobody has watched DK accept a
post-scheduled-start upload for a postponed game. That is the fact worth having
before spending the change.
