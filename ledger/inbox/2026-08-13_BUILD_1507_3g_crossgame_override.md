# 2026-08-13 1507_3g — operator override of the same-game SP-pair exclusion

Ben directed removal of `cross_game_only` for this slate after being shown the
anti-correlation rationale. Applied as a run-scoped patch,
`tools/_operator_patch_20260813_crossgame.py`, run via
`tools/_run_patched_build.py`. **No file under `mlb_engine/` was edited**; the
committed defaults are unchanged. The patch file is kept, not reverted, so the
artifact has a readable cause.

Delivered: `outputs/2026-08-13/DKEntries_1507_3g.csv`
sha256 `b8a3ef7c605baffffbc2f64cbe2cbd0e1cde97b11903b965df06db0322eccefe`
(supersedes `91738762e397...`, the cross-game-only build). Certified, preflight PASS.

## The ask was not fully met, and the reason is structural

Ben asked for all 6 SP pairs at >= 2. Result: 5 of 6 used, min 0.

| pair | n |
|---|---|
| Scherzer + Tolle (same game, newly admitted) | 6 |
| Cavalli + Tolle | 6 |
| Gausman + Tolle | 4 |
| Gausman + Scherzer | 2 |
| Cavalli + Scherzer | 1 |
| **Cavalli + Gausman (same game)** | **0** |

`max_sp_pair_repetition` is a **ceiling, not a floor**. Admitting a pair into the
enumeration makes it legal; nothing obliges the allocator to spend entries on it,
and no exposed control expresses "at least N entries per SP pair." The bank
almost certainly held no Cavalli+Gausman candidate at all, in which case no
allocation could have used it regardless of caps.

Second-order cost, which Ben should weigh against the coverage he gained:
Tolle went from 52.6% to **84.2%** exposure and Brady House to 63.2%. Trading a
pair-coverage floor for single-pitcher concentration on a 2-game slate is a real
exchange, not a free one.

## Backlog candidates
1. A `min_sp_pair_representation` control, enforced in the allocator as a floor
   with a pre-solve arithmetic check (`distinct_bank_pairs >= pairs_required`).
   Without it, "represent every pair" is not expressible.
2. Expose `cross_game_only` as a documented control on `build_slate.py` so this
   override needs no patch file next time.
3. The bank's breadth-before-depth loop should report per-pair candidate counts
   in the brief. "5/6 pairs used" was only discoverable by parsing the output CSV.
