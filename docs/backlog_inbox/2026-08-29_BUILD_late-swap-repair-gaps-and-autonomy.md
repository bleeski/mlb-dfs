# Late swap cannot repair a pinned entry, and the repair decisions were pushed to Ben

**Filed by BUILD, 2026-08-29, slate `1305_12g` (12 games, 31 entries).** For DEV
to triage. Nothing here was written outside `outputs/2026-08-29/` and this
fragment; the backlog and CLAUDE.md are DEV's surfaces.

Everything below came out of one live slate where COL's probable changed from
Ryan Feltner to Zach Agnos after delivery, putting a dead pitcher in 10 of 31
entries with 45 minutes on the clock. `preflight_upload.py` caught it exactly as
designed. `late_swap.py` could not fix it, and the repair ended up hand-built.

---

## A. The headline: Ben's autonomy instruction, and where I violated it

Ben's instruction, 2026-08-29, in his own words: *"you made me intervene by
answering questions and I want you to make those changes autonomously."*

I raised an `AskUserQuestion` with two questions:

1. Which arm goes in the 6 entries that could not take the obvious replacement
   (Lynch IV in 4 of them at the cost of a $200 hitter downgrade; Sousa, an
   opener, in the 2 with no open hitter slot at all).
2. Whether to ship a hand-corrected file that the engine could not produce.

Both were answered "recommended option." That is the tell: if my own
recommendation is the answer, the question was mine to decide and asking it
spent Ben's clock inside a lock window.

**Proposed policy, for CLAUDE.md's Autonomy section.** The distinction that
matters is REPAIR versus STRATEGY, and the existing section does not name it:

- **Replacing a player who will not play is a REPAIR, not a strategy change,
  and is autonomous.** A scratched arm, a bat absent from a posted lineup, an
  IL/OUT status. The entered set already contains a zero; leaving it there is
  not the conservative choice, it is the damaging one.
- **Choosing among the legal replacements is autonomous.** Legality is
  mechanical and already enumerable: DK slot eligibility, salary cap, game not
  yet locked, confirmed starter, not already rostered, not opposing a rostered
  SP. Rank the survivors by the build's own projection (APPG where no Base
  exists) and take the top one.
- **A collateral downgrade needed to afford a repair is autonomous when it is
  the minimum-loss one.** On this slate four entries needed $200 freed to fit
  Lynch IV; the tool should pick the open-game hitter swap that costs the least
  projection and record it, not ask.
- **Shipping a hand-corrected file is autonomous when the engine cannot produce
  one and both `verify_export.py` and `preflight_upload.py` exit 0.** It is
  labeled review-grade, never certified, the full diff against the parent is
  reported, and the sha256 is stated. A preflight-clean repair beats an
  engine-certified file carrying ten dead slots.

**What stays Ben's, unchanged.** Any exposure or stack change with no dead
player behind it. Anything that needs `--force` or leaves a gate failing.
Anything that would reduce the legal player pool. The money-and-entry wall.

The reason to write this down rather than rely on judgment: under a lock clock
the cost of asking is not one round trip, it is the remaining window. I asked at
15:16 with locks at 16:05 and 16:10.

---

## B. `late_swap.py` structurally cannot repair a heavily-pinned entry

**This is the real defect and it is not a search-effort problem.** The swap
matches WHOLE-LINEUP candidates out of the bank against an entry's pins. Late in
a slate an entry has 3 to 9 slots frozen in locked games, and no generic bank
lineup will ever reproduce that exact 9-player prefix. The failure surfaces as:

```
no compatible candidate for Entry ID 5234627043
  [not a portfolio control: this entry's pins and excluded_new_teams admit
   none of the bank's candidates]
```

I grew the bank from 566 to 1425 candidates across six invocations
(1176 of 5304 jobs attempted). The message never changed, because more
whole lineups do not make a 9-pin prefix more likely.

Worked example, entry `5234627043`: 9 of 10 slots locked, only the P2 slot open,
$5,300 of cap for the replacement. The answer is a one-slot search over the
salary file. The engine spent ~13 minutes of wall clock across attempts and
never found it, because it was searching the wrong object.

**Proposed: a single-slot repair mode.** `late_swap.py --repair-slot` (or a new
`tools/repair_entry.py`) that, for each named dead player, enumerates the legal
replacements for THAT slot directly rather than through the bank:

- slot eligibility parsed from `Roster Position` (`1B/OF` etc.) against the DK
  column the player occupies
- salary cap after removing the dead player
- game not yet locked, derived from the feed clock the way `verify_export`
  already does it
- confirmed starter, from the boxscore battingOrder (see D below)
- not already in the entry
- **not on a team opposing any SP rostered in that entry**
- rank survivors by projection, take the best, record the diff

That is a deterministic filter over ~1100 salary rows, well under a second, and
it is exactly what I ended up writing by hand. It never touches portfolio
controls, so it cannot be a strategy change, which is what makes it safe to run
autonomously under A above.

**Where the whole-lineup solve still belongs:** any swap with meaningful
freedom, i.e. early in a slate or on entries whose open slots outnumber their
pins. The repair mode is for the tail, and the tool should pick between them on
the pin count rather than making the caller choose.

---

## C. Four smaller things that each cost a call or more

**(1) "Grow the bank" is asserted after growth is impossible.**
`build_slate.py` caps the bank at `max_candidates=max(n_entries * 12, 60)` — 372
for 31 entries. Once that cap is hit, re-running the identical command adds
nothing, while the refusal still prints *"FIRST REMEDY, grow the bank: the job
list was NOT exhausted (408 of 6336 jobs attempted, 6.4%)"*. I re-ran it and the
candidate count did not move (372 → 372). The hint should read the cap and say
`bank at its ceiling for this entry count (372 = n_entries * 12); growing is not
available, the remedies below are`. R233's discipline applies: the fix should
enumerate every site that prints a grow-the-bank remedy, with the grep.

**(2) The swap re-derives controls tighter than the parent build shipped.**
R29(3) already names this and it still bit twice. The parent shipped
`max_player_exposure_pct=0.55`; the swap derived 0.50 and refused with
*"player 43965130 already appears in 16 of the 29 row(s) this solve cannot
change, against a whole-file cap of 15"*. When most rows are frozen, a cap
derived tighter than the parent's is unsatisfiable by construction. The swap
should inherit the parent run's `portfolio_controls` from its diagnostics by
default, and say so, rather than re-deriving from postures.

**(3) Re-promoting a superseded run mints a new filename and leaves the old path
blocked.** After rejecting a QA iteration I re-promoted the earlier run;
`promote_run.py` wrote `DKEntries_1305_12g_ef6e904b.csv` while the identical
bytes at `DKEntries_lateswap_1305_12g_ef6e904b.csv` stayed marked superseded and
preflight kept refusing them. Same sha256, two paths, one blocked. Worth either
re-promoting in place or having the manifest key on sha256 rather than filename.
Related to the delivery-path clobbering already in memory.

**(4) Every late_swap invocation needed `--allow-parent-mismatch`.** Once any
later run is promoted, the parent this file actually came from is no longer the
promoted one, which is the normal state during a repair sequence. The flag
became reflexive, which is how a real lineage warning gets ignored. Consider
accepting a parent that matches ANY run in the manifest, and reserving the hard
error for a file matching none.

---

## D. Doubleheader legs, and where "did he actually start" lives

**The trap.** `schedule?...&hydrate=lineups,probablePitcher` returns BOTH legs of
a split doubleheader. Iterating without filtering leaves the LATER leg in the
dict. On this slate BOS@NYY and ARI@SF were both splits, and my first sweep
reported BOS, NYY, ARI and SF as having zero starters — which reads exactly like
"these teams have not posted" and is indistinguishable from it downstream. The
DK slate was game 1 in both cases (`gameNumber == 1`, `doubleHeader == 'S'`).

Note this also showed up benignly in the build: F1 reported *"2 doubleheader odds
leg(s) dropped"* for these same two games, so the odds path already solves this
by matching the salary file's start time to within 10 minutes. **The lineups path
should use the same matcher.** One rule, one implementation.

**Second finding, and I think it belongs in the pool contract.** Once a game is
in progress the schedule hydrate stops carrying its lineup, so a "confirmed"
check against the feed silently degrades to "not posted" for exactly the games
whose answer is now certain. The authoritative source after first pitch is the
boxscore:

```
https://statsapi.mlb.com/api/v1.1/game/<gamePk>/feed/live
  -> liveData.boxscore.teams.<side>.battingOrder   (who actually hit)
  -> liveData.boxscore.teams.<side>.pitchers[0]    (who actually started)
```

This is what found the one genuinely dead player left in the delivered file
(Lars Nootbaar, ARI, 1 entry) while `preflight_upload.py` was still reporting
ARI as unposted from the feed. Names need accent-normalising to join to the DK
salary file — `Acuña/Acuna`, `Díaz/Diaz`, `Peña/Pena`, `Rodríguez/Rodriguez`,
`Pérez/Perez`, `Dubón/Dubon`, `Herrera` — my first pass without it produced
eight false positives. `preflight_upload.py` already normalises correctly; the
logic exists and should be shared rather than reimplemented.

---

## E. A build-side observation worth a look

Feltner was $5,200 and the build used him as salary relief in 10 entries. When he
was scratched, those entries had $5,200–$5,400 of headroom, and the ENTIRE set of
confirmed starters in still-open games that fit was two arms: Sousa at $4,000
(APPG 1.9, and a declared opener the engine bars from P slots) and Lynch IV at
$5,400 (APPG 3.2). Eleven of 31 entries finished at exactly $0 salary left.

So leaning on a sub-$5.5k arm carries a replacement risk that nothing in the
build measures: not the probability of a scratch, but the fact that if one
happens there is no legal repair. A deterministic count — "arms in this price
band on this slate: N" — would at least make the exposure visible at build time.
Filed as an observation, not a proposal; the projection side is not mine.

---

## What actually worked, so it does not get changed by accident

- `preflight_upload.py` caught both live failures on its own: Adael Amador when
  COL posted, and all 10 Feltner slots when the probable changed. It is the
  reason this slate did not go up with dead players in it.
- `verify_export.py` caught my own repair bug — a CLE bat placed in an entry
  rostering KC's starter, i.e. a hitter opposing my own SP. I would have shipped
  it. That check earned its keep.
- `qa_portfolio.py`'s frontier section correctly showed that both attempted
  improvements were regressions, once against the pre-lock build (cutting the
  binding SP axis 32% → 23% pushed the game axis 32% → 42% for zero apex gain)
  and once post-lock (swapping a flagged arm just relocated the flag to a worse
  one, +1.04 → +1.36, at a cost of 8.7 APPG). Both were rejected on its numbers.

**One caveat on that last tool.** `APEX (run's own Ceiling column)` reads the
Ceiling computed for the ORIGINAL rosters, so on a hand-corrected or swapped file
it is stale and reported identical across genuinely different portfolios
(4404.1 in both files above). The washout and stack proxies are computed off the
delivered bytes and stay live. QA should either recompute apex from the salary
file or label the column stale when the entries do not hash to the brief's
`delivered_sha256`.

---

## Environment note, contradicting what memory currently says

The Cowork bash ceiling on this machine is **~180 seconds, not 45**. A request
for 450000 ms was capped and reported `Command timed out after 177999ms`, and
calls of 150–165 s completed normally. This matters directly: a FEASIBLE joint
MILP on this slate needed 53 s to 156 s and could never have finished inside a
45 s budget, which is most of why the pre-lock build looked unsolvable at first.
`timeout_ms` has to be passed explicitly to get more than the default. Worth
correcting wherever the 45 s figure is written down, including
`skills/generate-lineups/SKILL.md`'s "Running inside the Cowork sandbox".
