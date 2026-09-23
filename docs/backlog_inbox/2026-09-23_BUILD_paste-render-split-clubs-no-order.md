# mlb.com paste: a third render the parser reads as zero games (R32)

Slate 2026-09-23 1905_10g. Ben pasted https://www.mlb.com/starting-lineups as
plain text (no markdown links), and `tools/lineups_from_paste.py` printed
`0 game(s) parsed` and exited 0 having written an empty feed. The render differs
from the two the parser knows in three ways:

1. The matchup is three lines, `Twins` / `@` / `Giants`, not `Twins@Giants`, so
   `_club_names` never fires and no game opens.
2. Hitter lines carry no order prefix: `B Rice (L) DH`, not `1. B Rice (L) DH`,
   so `_HITTER` never matches.
3. An unposted side is a bare `TBD` under the two `<TEAM> Lineup` headers, not
   `1. TBD`, so it is read as a probable's name slot. The parser then warns
   "found 4 probable pitcher line(s) for the 2 headers" and attaches neither
   probable.

The BUILD session normalized a copy mechanically: it joined the 14 split
matchups, numbered each nine-hitter block 1-9 in paste order, and rewrote the 4
lineup-section `TBD` lines as `1. TBD`. The raw paste is kept beside it in
`data/slates/2026-09-23/`. The result resolved 164 names (16 confirmed sides,
20 probables with hands), and 135/135 of the numbered orders matched DK's
`Starting` column slot for slot.

The silent part is the defect: zero games parsed on a paste that plainly holds
14 exits 0 and writes a feed. Proposed for DEV: accept this render in
`parse_paste` (all three shapes above), and make "0 games parsed on a non-empty
paste" a non-zero exit. The data points are this paste and the 135/135 DK
order match.
