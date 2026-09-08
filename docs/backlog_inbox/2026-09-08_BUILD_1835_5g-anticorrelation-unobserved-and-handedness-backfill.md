# BUILD fragment, 2026-09-08 1835_5g (5g Classic, 9 entries, certified)

Run `20260908T204935Z_5f3e248f`, delivered sha256 `34c74a365298...`, gates all
three true, zero relaxations. Two items, one a reporting defect and one a path
that worked and is currently improvised.

## (a) `anti_correlation` reads UNKNOWN on the direct path, and one field reads FALSE

On this build `solve.strategy` is `direct` and `solve.bank` is null. The brief's
`anti_correlation` block then reads:

    requested: null      applied: null       applied_source: "unobserved"
    observed: []         solves_observed: 0  engine_default: 0
    agrees_with_request: false

R293 made `applied` a MEASUREMENT off the bank's own solves rather than a restatement
of the flag, which is right. But the direct path builds no bank, so there are no solves
to measure and the block cannot say whether the convention held. That is a defensible
absence. `agrees_with_request: false` is NOT: nothing was requested (`requested: null`),
so there is nothing to agree or disagree with, and a bare `false` on a line about
anti-correlation is exactly the shape a session reads under a lock clock as "the
constraint did not hold."

It did hold. Verified independently off the delivered bytes: 0 of 9 entries roster a
hitter facing a rostered SP. Each entry's two arms come from two games and neither
game's opposing bats appear in it.

The lineups the measurement wants already exist on this path -- they are the delivered
portfolio. Two candidate fixes, either is enough: measure `applied` from the delivered
lineups when no bank was built, or keep `applied_source: "unobserved"` and make
`agrees_with_request` **null** whenever `requested` is null. The second is the smaller
change and removes the false reading on its own.

Same class as R167/R215 -- a control whose REPORTED state and actual state disagree in
silence -- arriving through the reporting field rather than through the units.

## (b) the handedness backfill that closes `f4_platoon_applied: 0` is improvised per slate

DK posted a complete 1-9 plus SP for all ten sides here, so R143's zero-fetch path
applied: `dk_order_coverage` reported 10/10, `sides_left_to_feed: []`. The documented
cost is that DK ships no handedness, so F4's platoon half goes neutral and
`f4_handedness_unavailable` names every side.

Both shells were egress-gated this session (`statsapi.mlb.com` and
`api.the-odds-api.com` both 403 from the device VM AND the container; the device VM
reached only `api.github.com`), so `--lineups` had no feed to fetch. The route that
worked, and it is worth making first-class:

1. `WebFetch` on `statsapi.mlb.com/api/v1/teams/<id>/roster?rosterType=40Man&hydrate=person&fields=...batSide,pitchHand...`, one call per team, 10 calls. WebFetch is served Anthropic-side and is not subject to the container's egress proxy.
2. Generate an mlb.com-shaped paste whose NAMES and BATTING ORDER come from the DKSalaries file itself (so DK stays authoritative and no disagreement can be minted) and whose only added column is the bat side.
3. `tools/lineups_from_paste.py` -> ordinary feed -> `build_slate.py --lineups`.

Result: `f4_platoon_applied` 0 -> **90 of 90**, `f4_handedness_unavailable: []`,
`disagreements: []`, zero blockers, zero `--resolve` needed.

It also changed the portfolio rather than decorating it. LAA came back with the
slate's HIGHEST mean F4 (1.063) on eight righty bats against LHP Sandoval, while
carrying the slate's LOWEST F1 (0.924) -- and took 2 of 9 primary stacks. BOS came back
with the LOWEST mean F4 (0.909), lefty-leaning into LHP Detmers, and took 1. Neither
ordering is visible with the platoon term neutral, so on a fully DK-covered slate the
zero-fetch build is not merely "missing half of F4," it is blind to the one axis that
separated the two sides of this slate's only LHP-vs-LHP game pair.

The generator lives in `tools/_scratch_1835_5g/gen_paste.py` (gitignored, slate-scoped,
sweep on slate close). Suggest a real tool: `tools/handedness_paste.py --salary <csv>`,
which takes a bat-side map on stdin or a cached league handedness file and emits the
paste, so the next DK-covered slate does not hand-roll the map. Handedness is a stable
player attribute, so a cached `data/reference/handedness.csv` refreshed like the Savant
files would remove the 10 fetches entirely.

Filed by BUILD; not merged into docs/backlog.md by this session (DEV owns that file).
