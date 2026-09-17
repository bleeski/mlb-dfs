# Showdown: with `even_split_no_market_input`, the "favorite" label is an alphabetical tiebreak but the allocation is still asymmetric

**For DEV.** Filed from a BUILD session (2026-09-17, MIN@LAA Showdown,
slate tag `2138_1g_sd`). Nothing in `mlb_engine/` was touched.

## What was observed

On a Showdown build with no moneyline reachable, the brief read:

```
construction.win_share_basis = "even_split_no_market_input"
construction.favorite        = "LAA"
construction.win_share       = {"LAA": 0.5, "MIN": 0.5}
```

`build_game_shape` in `mlb_engine/optimize/showdown_theses.py` falls back to
`share = {t: 0.5 for t in teams}` and then picks
`fav = max(teams, key=lambda t: share[t])`. With both shares equal, `max` over
`teams = sorted(df["Team"].unique())` returns the FIRST element, so the
favorite is decided by alphabetical order. The comment directly above that
fallback is explicit that the code declines to invent a favorite from salary,
which is right; the `max` on the line below reinstates one anyway, from the
team name.

That label is not cosmetic. `_template_specs` tags one side `favorite` and the
other `underdog`, and the realized allocation on this 16-entry build was:

```
favorite  (LAA): win_big 2, win_big_no_sp 1, win_close 2, shootout 1, bottom_order 1  = 7
underdog  (MIN): win_big 2, win_big_no_sp 1, win_close 1, shootout 1, bottom_order 1  = 6
neutral        : pitchers_duel 1, both_explode 1, ace_loses 1                         = 3
```

The favorite draws one extra `win_close` entry. Measured on the delivered
bytes, the team lean came out LAA-heavy 8, MIN-heavy 6, balanced 2. So an
alphabetical tiebreak moved one entry of sixteen onto a side the build had no
market evidence for. (Unattributed web search that day had MIN as the modest
road favorite, which would make the tilt backwards, but no per-book price was
obtainable and none was fed in.)

## Why it is worth a row

The even-split path exists precisely for the case where the market is unknown,
and it currently resolves that unknown twice: once honestly (0.5/0.5) and once
arbitrarily (`favorite = alphabetically first`). The second one is invisible
unless you read `win_share` and notice the shares are equal, because
`construction.favorite` reads like a finding.

## Options DEV might weigh

1. Make the allocation symmetric when `win_share_basis` is
   `even_split_no_market_input`: split the odd entry to a neutral template, or
   alternate the extra `win_close` between the sides, so no side is favored by
   name ordering.
2. Set `favorite`/`underdog` to `null` on an even split and have
   `_template_specs` branch on that, rather than always having a favorite.
3. Leave the behavior and make it legible: have the brief state
   `favorite_basis: "alphabetical_tiebreak_no_market_input"` alongside the
   label, so a reader is not misled by a `favorite` field that carries no
   information.

(3) is the cheapest and closes the reporting half of it on its own. (1) or (2)
closes the allocation half.

## Provenance

Build was clean otherwise: `pool.basis: declared_starters` (both 1-9 posted),
`construction.mode: thesis_ladder`, `counted_relaxations.clean: true`, all 16
rosters unique, `preflight_upload.py` and `verify_export.py` both exit 0.
