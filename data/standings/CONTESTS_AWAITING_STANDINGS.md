# Contests awaiting standings — generated 2026-07-25

Derived by hand this session: every contest ID in a delivered `outputs/*/DKEntries*.csv`
that has no archive entry. The five 07-19 exports recorded as unrecoverable are
excluded. This is the check the review proposed as item 3.3 and that does not
exist yet; regenerate it by rerunning that scan until it does.

Pull each while logged in to DraftKings, **check the file size is non-zero**, and
drop it in `data/standings/inbox/`. A zero-byte export is a failed pull, not a
pulled file. Showdown contests archive separately from Classic and never pool
with them.

---

## Tranche 1 — the aging test (pull these first, alone)

2026-07-24 night slate, 16 entries. If these come back populated, the export ages
out and the rule is a same-night pull. If they come back empty, the export path
itself is broken and timing was never the issue. Either result goes in the ledger
before pulling anything else, because it decides whether tranches 3 and 4 are
worth your time.

```
https://www.draftkings.com/contest/exportfullstandingscsv/192657350
https://www.draftkings.com/contest/exportfullstandingscsv/192657349
https://www.draftkings.com/contest/exportfullstandingscsv/192667458
https://www.draftkings.com/contest/exportfullstandingscsv/192658268
```

## Tranche 2 — rest of 2026-07-24 (pull if tranche 1 worked)

Main slate, 9 entries:

```
https://www.draftkings.com/contest/exportfullstandingscsv/192701222
https://www.draftkings.com/contest/exportfullstandingscsv/192701224
https://www.draftkings.com/contest/exportfullstandingscsv/192701225
https://www.draftkings.com/contest/exportfullstandingscsv/192705822
https://www.draftkings.com/contest/exportfullstandingscsv/192709106
https://www.draftkings.com/contest/exportfullstandingscsv/192712196
```

Showdown, 15 entries:

```
https://www.draftkings.com/contest/exportfullstandingscsv/192657334
https://www.draftkings.com/contest/exportfullstandingscsv/192657335
https://www.draftkings.com/contest/exportfullstandingscsv/192667460
```

## Tranche 3 — 2026-07-23 and 2026-07-22

Still recent enough to be plausible. 07-23 Classic (12 entries):

```
https://www.draftkings.com/contest/exportfullstandingscsv/192623314
https://www.draftkings.com/contest/exportfullstandingscsv/192623315
https://www.draftkings.com/contest/exportfullstandingscsv/192656508
```

07-23 Showdown (8 entries):

```
https://www.draftkings.com/contest/exportfullstandingscsv/192630776
https://www.draftkings.com/contest/exportfullstandingscsv/192652559
https://www.draftkings.com/contest/exportfullstandingscsv/192652560
https://www.draftkings.com/contest/exportfullstandingscsv/192652561
```

07-22 (15 entries):

```
https://www.draftkings.com/contest/exportfullstandingscsv/192591926
https://www.draftkings.com/contest/exportfullstandingscsv/192591927
https://www.draftkings.com/contest/exportfullstandingscsv/192627933
```

07-22 second upload (10 entries):

```
https://www.draftkings.com/contest/exportfullstandingscsv/192591443
https://www.draftkings.com/contest/exportfullstandingscsv/192591459
https://www.draftkings.com/contest/exportfullstandingscsv/192591504
https://www.draftkings.com/contest/exportfullstandingscsv/192593054
```

## Tranche 4 — 2026-07-21 and older (probably already gone)

These are past the age at which the five known-dead exports failed. Do not spend
time here until tranche 1 says whether age is the mechanism. If it is, treat this
list as lost and record it.

2026-07-21:

```
https://www.draftkings.com/contest/exportfullstandingscsv/192529275
```

2026-07-19 (192464820 already archived as A-002):

```
https://www.draftkings.com/contest/exportfullstandingscsv/192442890
https://www.draftkings.com/contest/exportfullstandingscsv/192500593
https://www.draftkings.com/contest/exportfullstandingscsv/192443599
https://www.draftkings.com/contest/exportfullstandingscsv/192443606
https://www.draftkings.com/contest/exportfullstandingscsv/192454586
https://www.draftkings.com/contest/exportfullstandingscsv/192464310
https://www.draftkings.com/contest/exportfullstandingscsv/192464354
https://www.draftkings.com/contest/exportfullstandingscsv/192464355
```

2026-07-18 (192413146, 192413147, 192444379 already archived as A-003):

```
https://www.draftkings.com/contest/exportfullstandingscsv/192413131
https://www.draftkings.com/contest/exportfullstandingscsv/192413132
```

2026-07-17:

```
https://www.draftkings.com/contest/exportfullstandingscsv/192344257
https://www.draftkings.com/contest/exportfullstandingscsv/192344259
https://www.draftkings.com/contest/exportfullstandingscsv/192345441
https://www.draftkings.com/contest/exportfullstandingscsv/192369212
https://www.draftkings.com/contest/exportfullstandingscsv/192419758
https://www.draftkings.com/contest/exportfullstandingscsv/192344519
https://www.draftkings.com/contest/exportfullstandingscsv/192344520
https://www.draftkings.com/contest/exportfullstandingscsv/192420813
```

2026-06-03 (also re-delivered under 2026-07-17):

```
https://www.draftkings.com/contest/exportfullstandingscsv/191020573
https://www.draftkings.com/contest/exportfullstandingscsv/191020574
https://www.draftkings.com/contest/exportfullstandingscsv/191047506
```

---

## Already archived, do not re-pull

A-001 191787184, 191787186, 191823035 · A-002 192464820 ·
A-003 192413146, 192413147, 192444379 ·
A-004 191506958, 191506960, 191507209, 191507213, 191507220 ·
A-005 191488360, 191488366

## Recorded unrecoverable, do not re-pull

191489664, 191513240, 191520890, 191521489, 191542451
