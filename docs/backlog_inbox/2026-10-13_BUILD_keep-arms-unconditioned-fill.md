# Kept relievers are unconditioned UTIL fill on the thesis ladder

Filed by BUILD, 2026-10-13, ALCS G2 CLE@TB Showdown (2000_1g_sd).

## What happened

`build_slate.py --odds <packet> --keep-arm` for seven high-leverage relievers on the
two active postseason rosters (CLE: Cade Smith, Hunter Gaddis, Erik Sabrowski, Tim
Herrin; TB: Bryan Baker, Kevin Kelly, Cam Booser). The build (sha256 `296c5f8b...`,
superseded, never delivered) put kept arms in 20 of 162 slots. CLE closer Cade Smith
landed in 10 of 27 lineups, and 8 of those 10 were TB-win rosters (4 or 5 TB players).
That's the game state where a closer is least likely to get a save situation.
Delivered instead: the same build without `--keep-arm` (`8049dfbe...`).

## Why

`references/showdown.md` says it directly: "A kept arm is UTIL fill on the thesis
ladder. No template names him captain." The solver picks him by Base per dollar
against the cheapest posted bats (Hedges $3,400, Halpin $4,000), with no link to the
thesis's winning side. A reliever's DK value in a playoff game comes mostly from the
win (+4) and from leverage innings, and both track his own side winning close.

## Proposed

A kept reliever is eligible only on theses where his side wins or the game stays close
(`win_close`, `pitchers_duel`, his side's `win_*`), or he gets a side-conditioned
per-thesis Base. Until then, `references/showdown.md` "When to use it" should say
that on a non-elimination postseason game the widening adds anti-correlated filler.

## Premise to verify (dfs-premise)

- `mlb_engine/optimize/showdown_theses.py`: checked at filing. Lines 670-675 drop a kept arm from starter selection and 3374-3379 from the declared-arm count; grep for `KEPT_ARM_PARTICIPATION` finds no side or thesis condition, so kept arms enter every template's
  candidate set unconditioned.
- Reproduce on `data/slates/2026-10-13/` with the seven `--keep-arm` ids above and
  count Cade Smith's side-split.
