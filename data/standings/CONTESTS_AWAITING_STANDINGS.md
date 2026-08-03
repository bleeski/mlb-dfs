# Contests awaiting standings — regenerated 2026-08-03

Scan: every contest ID on a filled entry row in `outputs/*/DKEntries*.csv`, minus
the archived set (`data/archive/`), what's already sitting in
`data/standings/inbox/`, and the recorded unrecoverable below. Regenerate by
rerunning that scan; do not hand-maintain this list. No dedicated tool runs this
scan yet, so it is still a manual pass; a `tools/awaiting_standings.py` is filed
in `docs/backlog_inbox/` for DEV, since this is the third session to write the
scan by hand.

Pull each while logged in to DraftKings, **check the file size is non-zero**, and
drop it in `data/standings/inbox/`. A zero-byte export is a failed pull, not a
pulled file. A `.zip` is fine; `python tools/extract_inbox_zips.py` unpacks it.
The inbox is flat; the miner reads Classic vs Showdown off the lineup cells and
resolves the salary file itself (`--auto-salary`, restricted with `--salary-dir`).

## Status as of 2026-08-03: 91 contests open across 4 slate dates

Prioritize oldest first. The 2026-07-25 ledger note found DK's export ages out
after some days, so 07-28 and 07-29 are the ones at risk; 08-01 will keep longer.

**2026-08-01** (17 contests):

- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (STL @ TOR)](https://www.draftkings.com/contest/exportfullstandingscsv/193034903) — `193034903`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (STL @ TOR)](https://www.draftkings.com/contest/exportfullstandingscsv/193034904) — `193034904`
- [MLB Satellite to $2 MLB Pocket Cup MEGA Qualifier (Turbo)](https://www.draftkings.com/contest/exportfullstandingscsv/193034935) — `193034935`
- [MLB Satellite to $2 MLB Pocket Cup MEGA Qualifier (Turbo)](https://www.draftkings.com/contest/exportfullstandingscsv/193034936) — `193034936`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Turbo)](https://www.draftkings.com/contest/exportfullstandingscsv/193034938) — `193034938`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Turbo)](https://www.draftkings.com/contest/exportfullstandingscsv/193034939) — `193034939`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Turbo)](https://www.draftkings.com/contest/exportfullstandingscsv/193034940) — `193034940`
- [MLB $2.5K Solo Shot (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/193035787) — `193035787`
- [MLB $1K Solo Shot (Turbo)](https://www.draftkings.com/contest/exportfullstandingscsv/193035792) — `193035792`
- [MLB $6K mini-MAX [150 Entry Max] (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/193035795) — `193035795`
- [MLB Showdown $250 Solo Shot (STL @ TOR)](https://www.draftkings.com/contest/exportfullstandingscsv/193076001) — `193076001`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/193077888) — `193077888`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/193078052) — `193078052`
- [MLB SUPERSatellite to NFL 9-13 $5 Fantasy Football Millionaire [5x]](https://www.draftkings.com/contest/exportfullstandingscsv/193091132) — `193091132`
- [MLB Satellite to NFL Best Ball $25 Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/193095032) — `193095032`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/193096516) — `193096516`
- [MLB $350 Solo Shot](https://www.draftkings.com/contest/exportfullstandingscsv/193096806) — `193096806`

**2026-07-30** (32 contests):

- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192937435) — `192937435`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192937436) — `192937436`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192937438) — `192937438`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192937440) — `192937440`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192937454) — `192937454`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192937456) — `192937456`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192937459) — `192937459`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192937461) — `192937461`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192937463) — `192937463`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192937533) — `192937533`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192937534) — `192937534`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192937538) — `192937538`
- [MLB Satellite to $15 Relay Throw](https://www.draftkings.com/contest/exportfullstandingscsv/192938622) — `192938622`
- [MLB Satellite to $15 Relay Throw](https://www.draftkings.com/contest/exportfullstandingscsv/192938623) — `192938623`
- [MLB Satellite to NFL Best Ball $25 Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192938629) — `192938629`
- [MLB $15K mini-MAX [150 Entry Max]](https://www.draftkings.com/contest/exportfullstandingscsv/192944793) — `192944793`
- [MLB $500 Daily Dollar [Single Entry] (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192944831) — `192944831`
- [MLB Showdown $350 Solo Shot (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192972500) — `192972500`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192972876) — `192972876`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192972999) — `192972999`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192973000) — `192973000`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192973047) — `192973047`
- [MLB Showdown $200 Solo Shot (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192976860) — `192976860`
- [MLB Showdown $20 Quarter Jukebox [Just $0.25!] (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192977444) — `192977444`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192979294) — `192979294`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192979424) — `192979424`
- [MLB $400 Solo Shot (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192994189) — `192994189`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192996806) — `192996806`
- [MLB Showdown $300 Solo Shot (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192997189) — `192997189`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192997656) — `192997656`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192998674) — `192998674`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192999777) — `192999777`

**2026-07-29** (41 contests):

- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192896238) — `192896238`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192896240) — `192896240`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192896242) — `192896242`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192896255) — `192896255`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192896256) — `192896256`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192896258) — `192896258`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192896259) — `192896259`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192896260) — `192896260`
- [MLB Satellite to $2 MLB Pocket Cup MEGA Qualifier (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192896273) — `192896273`
- [MLB Satellite to $2 MLB Pocket Cup MEGA Qualifier (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192896274) — `192896274`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192896278) — `192896278`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192896291) — `192896291`
- [MLB Showdown Satellite to $2 MLB Pocket Cup MEGA Qualifier (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192896292) — `192896292`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192896296) — `192896296`
- [MLB $15K mini-MAX [150 Entry Max]](https://www.draftkings.com/contest/exportfullstandingscsv/192897439) — `192897439`
- [MLB Showdown $1K Solo Shot (CHC @ STL)](https://www.draftkings.com/contest/exportfullstandingscsv/192897471) — `192897471`
- [MLB Showdown $1.5K Solo Shot [20 Entry Max] (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192897496) — `192897496`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192921685) — `192921685`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192921728) — `192921728`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192921742) — `192921742`
- [MLB $1.25K Solo Shot (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192921966) — `192921966`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Early)](https://www.draftkings.com/contest/exportfullstandingscsv/192922983) — `192922983`
- [MLB Showdown $30 Quarter Jukebox [Just $0.25!] (ATL @ NYM)](https://www.draftkings.com/contest/exportfullstandingscsv/192923620) — `192923620`
- [MLB Showdown $150 Solo Shot (ATL @ NYM)](https://www.draftkings.com/contest/exportfullstandingscsv/192924379) — `192924379`
- [MLB SUPERSatellite to NFL 9-13 $5 Fantasy Football Millionaire [2x]](https://www.draftkings.com/contest/exportfullstandingscsv/192932671) — `192932671`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192933802) — `192933802`
- [MLB Showdown $20 Quarter Jukebox [Just $0.25!] (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192934735) — `192934735`
- [MLB Showdown $250 Solo Shot (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192935418) — `192935418`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192935801) — `192935801`
- [MLB SUPERSatellite to NFL 9-13 $5 Fantasy Football Millionaire [2x]](https://www.draftkings.com/contest/exportfullstandingscsv/192935802) — `192935802`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192936209) — `192936209`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192936649) — `192936649`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (TEX @ TB)](https://www.draftkings.com/contest/exportfullstandingscsv/192938854) — `192938854`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192938900) — `192938900`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192939787) — `192939787`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire](https://www.draftkings.com/contest/exportfullstandingscsv/192939862) — `192939862`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192943882) — `192943882`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192947686) — `192947686`
- [MLB Showdown Satellite to NFL 9-13 $5 Fantasy Football Millionaire (SEA @ LAD)](https://www.draftkings.com/contest/exportfullstandingscsv/192948724) — `192948724`
- [MLB $250 Solo Shot (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192948814) — `192948814`
- [MLB Satellite to NFL 9-13 $5 Fantasy Football Millionaire (Night)](https://www.draftkings.com/contest/exportfullstandingscsv/192949357) — `192949357`

**2026-07-28** (1 contests):

- [MLB Satellite to $15 Relay Throw](https://www.draftkings.com/contest/exportfullstandingscsv/192892126) — `192892126`

## Not on this list — do not pull

- **Archived** (145 contests) — already mined into `data/archive/`;
  see the ledger's A-NNN entries for the per-contest mapping.
- **199000001** (`MLB $100K Relay Throw [$25K to 1st]`) — synthetic/placeholder
  entry ID (9900000001) in `DKEntries_1210_4g.csv` / `DKEntries_apex_relay.csv`, not
  a real DK contest ID. If Relay Throw was actually entered, the real ID has to
  come from DK's entry history, not this scan.
- **Contest ID `0`** (`Showdown Manual - KC @ DET`, 2026-07-25) and **`900`**
  (`Test WTA`, 2026-06-11) — not DK contest IDs. Both sit on filled entry rows in
  `outputs/`, so a scan that accepts any non-empty Contest ID emits a dead
  `.../exportfullstandingscsv/0` URL for them. Filter the scan to 9-digit IDs.
- **Recorded unrecoverable** — landed at 0 bytes and stayed at 0 bytes on re-pull;
  do not re-attempt:
  - 191489664, 191513240, 191520890, 191521489, 191542451 (2026-06 tranche)
  - 191047506, 192345441, 192419758, 192420813 (zero-byte on the 2026-07-28 pull)
