# Fragment: proposal — the miner should emit the leverage table it took a bespoke pass to compute

Session: ARCHIVE, 2026-08-04. For: DEV. New small item, pairs with the R30 miner batch and R39.

The 3.17 leverage measurement (in 104 of 116 Classic contests >=40 entries, at least one player
finished top-5 in contest FPTS under 10% drafted; winners carried >=1 in 51% vs a 13% field base
rate) was computed in a one-off analysis pass over the mined JSONs. Nothing persists it per
contest, so the next regrade re-derives it from scratch and no build-time surface can ever cite it.

Proposal: `field_miner` emits a small `leverage` block per contest — the sub-10% top-5-FPTS players
(name, %drafted, FPTS), plus carry rates for winner / top decile / field — into the mined JSON and
the ledger fragment. Deterministic descriptive statistics only, same labels as the rest of the
block. Retroactive backfill is a re-mine of the archive (idempotent, ~10 min in the cloud
container per the 2026-08-04 registry rebuild pattern).

Why it earns a slot: it operationalizes the one differentiation channel the archive shows paying
(low-owned pieces inside chalk-positive lineups), it becomes the natural grading target for R10's
satellite ownership prior (a prior that cannot rank tomorrow's sub-10% top-scorers adds nothing),
and it costs one table in a module that already computes both inputs. R39 is the Showdown half of
the same blindness: captain choice is invisible in the mined record, so the 2026-08-04 pass could
not measure captain chalk or captain leverage at all.
