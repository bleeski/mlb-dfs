# R39 gains a measured payoff: the captain anatomy the miner cannot see

2026-08-08, ARCHIVE. The 3.18 review worked around R39 (miner drops the CPT
marker) by re-parsing 64 archived showdown standings CSVs directly. What that
one-off found is the argument for landing R39 properly:

- Winner CPT %Drafted median 14.8 vs field median 13.0 — at-share, the
  showdown twin of the Classic SP-pair result.
- The top-owned captain won 22/85 in the sample (26%).
- Tranche: winners captained at 9.1 median own, 0/8 top-owned, while our own
  tranche captains ran 15.4 median — chalkier than the winners that week.

Once `captain_norm` lands per entry (R39's fix), this becomes a standing
per-contest table instead of a session-sized re-parse, and a captain-selection
spread policy (how far off the consensus CPT the bank should sit) becomes a
decidable question with data behind it. Observed distributions only; no
probability claims; conditioning per ledger Section 2.
