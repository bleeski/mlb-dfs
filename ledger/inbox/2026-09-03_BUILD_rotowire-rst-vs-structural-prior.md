# 2026-09-03 BUILD — RotoWire RST% contradicts the structural ownership prior on 2140_2g

Slate 2140_2g (ATH@SEA, STL@LAD), delivered sha256 635cc0b52e73...

First slate where an EXTERNAL ownership projection was pulled alongside the repo's
own `ownership_pred` prior. They disagree in direction, and the disagreement is the
finding.

- `qa_portfolio.py` section 4, using `ownership_pred_2140_2g.json`, scored every one
  of the six contests chalk-POSITIVE (+37.4 to +57.4 pp vs its own field mean) and
  reported low-owned carry 0 in 5 of 9 entries.
- RotoWire DraftKings RST% (pulled 21:14 ET, saved at
  `data/slates/2026-09-03/rotowire_rst_2140_2g.csv`) says the portfolio is chalk-positive
  on the two arms and the LAD/SEA core, and carries DEEP leverage on STL and ATH bats:
  Ivan Herrera 56% mine vs 0.04% field, Zack Gelof 56% vs 0.67%, Jose Fermin 44% vs 0.47%,
  Jordan Walker 33% vs 0.56%, Thomas Saggese 33% vs 0.82%.
- The prior's own grade record (R135) is a mean signed error of -10.44 points, i.e. it
  under-concentrates. That is consistent with it failing to see near-zero tails.

Caveat on the RotoWire pull: it is the ALL-GAMES view, not the 2-game night draftgroup.
Ordering should survive; levels will not. Whether RotoWire publishes a per-draftgroup
RST% is unresolved and worth checking before the next late slate.

Suggested for ARCHIVE: when the standings for these six contests land, grade BOTH the
structural prior and this RotoWire snapshot against realized %Drafted. That is the first
head-to-head this project has had, and it is the input R10's fitted prior needs.
