# Delivery note: 2000_1g_sd (ALCS G4, TB @ CLE), FINAL_r2, after two QA rounds

- Delivered file: `outputs/2026-10-16/DKEntries_showdown_2000_1g_sd_FINAL_r2.csv`
- sha256: `d5c3f2acb6a9382eaa5504cf8630016267cbdafd5c12f8cd7afb208d25b26c8f`
- Label: review-grade. Showdown is never certified and never upload-ready.
- This note, not the engine's build brief, describes the delivered file. The brief (`build_brief_2000_1g_sd_try3.json`) names the engine's own file (sha256 `90741b99b4ea...`); the delivered file differs by the hand edits below.

## Entries

| Entry | Contest | CPT | UTIL | Salary |
|---|---|---|---|---|
| 5297787277 | MLB Showdown $15K mini-MAX [150 Entry Max] | Brayan Rocchio | Jo Adell, Chase DeLauter, Jonathan Aranda, Travis Bazzana, Steven Kwan | 49,200 |
| 5297791132 | MLB Showdown $1.5K Quarter Jukebox [Just $0.25!] | Joey Cantillo | Jose Ramirez, Travis Bazzana, Steven Kwan, Nathaniel Lowe, Bryan Baker | 49,700 |
| 5297791150 | MLB Showdown $1.5K Quarter Jukebox [Just $0.25!] | Junior Caminero | Yandy Diaz, Jonathan Aranda, Liam Hicks, Chandler Simpson, Cade Smith | 49,400 |
| 5297791271 | MLB Showdown $1K Daily Dollar [Single Entry] | Jonny DeLuca | Nick Martinez, Yandy Diaz, Liam Hicks, Steven Kwan, Chandler Simpson | 50,000 |
| 5297786712 | MLB Showdown Satellite to $15 Relay Throw | Jose Ramirez | Jo Adell, Chase DeLauter, Steven Kwan, Nathaniel Lowe, Richie Palacios | 49,800 |
| 5297791398 | MLB Showdown Satellite to $15 Relay Throw | Nick Martinez | Jonathan Aranda, Liam Hicks, Steven Kwan, Chandler Simpson, Cade Smith | 49,300 |
| 5297786753 | MLB Showdown Satellite to NBA 10-20 $20 Opening Tip Off | Jose Ramirez | Chase DeLauter, Travis Bazzana, Steven Kwan, Chandler Simpson, Nathaniel Lowe | 48,800 |
| 5297791476 | MLB Showdown Satellite to NBA 10-20 $20 Opening Tip Off | Tanner Bibee | Nick Martinez, Jonathan Aranda, Chandler Simpson, Richie Palacios, Petey Halpin | 49,900 |
| 5297786881 | MLB Showdown Satellite to $20 NFL Fantasy Football Millionaire | Nick Martinez | Chase DeLauter, Travis Bazzana, Brayan Rocchio, Nathaniel Lowe, Patrick Bailey | 48,500 |
| 5297786907 | MLB Showdown Satellite to $20 NFL Fantasy Football Millionaire | Junior Caminero | Jose Ramirez, Chase DeLauter, Chandler Simpson, Nathaniel Lowe, Richie Palacios | 49,600 |
| 5297786291 | MLB Showdown $100 Dime Time [Just $0.10!] | Junior Caminero | Yandy Diaz, Jonathan Aranda, Liam Hicks, Nathaniel Lowe, Taylor Walls | 49,600 |
| 5297791094 | MLB Showdown $100 Dime Time [Just $0.10!] | Tanner Bibee | Jose Ramirez, Chase DeLauter, Chandler Simpson, Nathaniel Lowe, Taylor Walls | 49,700 |
| 5297791198 | MLB Showdown $150 Quarter Jukebox [Just $0.25!] | Jonathan Aranda | Nick Martinez, Yandy Diaz, Liam Hicks, Richie Palacios, Cade Smith | 48,900 |
| 5297791234 | MLB Showdown $150 Quarter Jukebox [Just $0.25!] | Nick Martinez | Joey Cantillo, Jonathan Aranda, Victor Mesa Jr., Petey Halpin, Cade Smith | 49,900 |

Captains: {'Junior Caminero': 3, 'Nick Martinez': 3, 'Jose Ramirez': 2, 'Tanner Bibee': 2, 'Brayan Rocchio': 1, 'Joey Cantillo': 1, 'Jonny DeLuca': 1, 'Jonathan Aranda': 1}
Player counts, top: [('Jonathan Aranda', 7), ('Nathaniel Lowe', 7), ('Chandler Simpson', 7), ('Chase DeLauter', 6), ('Steven Kwan', 6), ('Nick Martinez', 6), ('Jose Ramirez', 5), ('Liam Hicks', 5), ('Travis Bazzana', 4), ('Yandy Diaz', 4)]

## How this file was made

1. Engine thesis ladder (`build_slate.py`, Showdown, review-grade), pool = 18 posted hitters + Martinez, Armstrong, Bibee (DK tags) + 16 active-roster arms named with `--keep-arm` (TB Seymour, Booser, Kelly, Sulser, Baker, Hopkins, Matz; CLE Cantillo, Cecconi, Griffin, C. Smith, Espino, Sabrowski, Gaddis, Festa, Herrin). No hitter removed. Engine file sha256 `90741b99b4ea95c3557c7cac0df71d6c53710e5643caf0bcff322c2045a337b6`, brief `build_brief_2000_1g_sd_try3.json`.
2. Labeled operator arm priors (`--projections`, 19 arms, hitters on the engine's own priors): Martinez 10.5, Bibee 7.0, Cantillo 4.8, Cecconi 3.5, Griffin 2.2, Armstrong 2.9, C. Smith 3.2, Espino 1.8, Sabrowski 2.0, Gaddis 1.8, Festa 1.2, Herrin 1.2, Seymour 2.8, Booser 2.0, Kelly 1.8, Sulser 1.5, Baker 2.6, Hopkins 0.8, Matz 2.2. These are the session's own judgment from rest, usage and pitch counts, not data.
3. Hand re-deal (two rows), then QA round 1 edits (Cantillo split in, Relay and $1.5K Jukebox lineups swapped, Kwan to Rocchio in 5297791094), then QA round 2 edit (lineups of 5297786881 and 5297791094 swapped). Each step was advised by an Opus advisor after an Opus dfs-qa review, validated against: $50,000 cap, both teams, delivered pool only, any two lineups share at most 4 players, no captain above 3, no player above 7, distinct lineups and captains per contest. `tools/preflight_upload.py` exits 0 on every file, no `--force`.
4. Parent shas: engine 90741b99b4ea; re-deal 63265c3aa5a1; FINAL_r1 b09c4631c2a2; FINAL_r2 (delivered) d5c3f2acb6a9.

## Liveness, 7:36 PM ET

Both nines unchanged since the 6:53 PM pull (the feed now spells "Victor Mesa", same player and slot). Probables Martinez and Armstrong. Every rostered player is on his ALCS active roster. MLB game status at 7:36 PM ET: Delayed Start, reason Inclement Weather, scheduled start still 8:00 PM ET. NWS forecast (23:01Z): 53F at 8 PM, 18 mph from the north, 51% showers, showers likely through 11 PM.

## Gaps

Contest sizes and satellite ticket counts unknown. No moneyline reached the build (even win split). Reference data (Savant, season pitching) 17 days old. Weather and delay handling on DK's side not verified. The audit gate was started at session start and its result was never read.
