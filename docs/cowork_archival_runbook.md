# Cowork Archival and Acquisition Runbook — MLB Classic DFS

Untracked companion. Last updated: 2026-07-04. Status: operational runbook for
Claude Cowork on Ben's machine. The engine stays in the claude.ai project where
certification lives; Cowork owns data acquisition, post-slate archival, and the
T-minus watch. Nothing in this runbook builds lineups or touches tracked engine
files.

## Guardrails (read first, every session)

1. Never log, echo, or write API keys. `THE_ODDS_API_KEY` stays in the
   environment; if a command fails for a missing key, report the failure, not
   the key.
2. Never edit tracked engine files. The only files Cowork edits are the
   untracked companions: `MLB_Classic_Calibration_Ledger.md`,
   `MLB_Classic_Backlog.md`, and `field_opponent_registry.json`.
3. Ledger edits are edit-in-place and append-only in the archive. Never drop an
   invariant section. Diff the structure before saving; if a section
   disappears, the commit note must say why.
4. All outputs that the claude.ai project session needs (updated ledger, updated
   registry, mined JSON, the slate bundle) get returned to that session for
   upload. Cowork is the hands; the project is the record.
5. Labels are non-negotiable: everything captured here is an observed outcome or
   a deterministic descriptive statistic, never a win-rate, ROI, or probability
   claim.
6. Multi-session: this runbook is the ARCHIVE role (CLAUDE.md,
   multi-session contract). Before Job 1, take the claims:
   `python tools/claim.py take ledger --role ARCHIVE` and
   `python tools/claim.py take inbox --role ARCHIVE` (the tool adds the
   UTC date). A held claim exits nonzero and prints the owner: stop.
   When the archival session is done, release both:
   `python tools/claim.py release ledger` and
   `python tools/claim.py release inbox`. Never run Job 1 during a live
   build window, and never edit the ledger without holding its claim.

## Job 1: Post-slate archival (highest value; run after every slate)

Run once per contest entered. This is the direct accelerant for the B-8 gating
dependency (eight to fifteen archived slates activate the ownership model).

Per contest:

1. Download the contest standings export from DraftKings (Contest page, Export
   Lineups CSV). Save the raw file untrimmed:
   `archive/<slate_date>/standings_<contest_id>.csv`. Do not open-and-resave in
   a spreadsheet app; that strips the BOM contract and can mangle names.
2. Capture the contest-page trio plus seats into
   `archive/<slate_date>/contest_<contest_id>.json`:

   ```json
   {
     "contest_id": "191787184",
     "slate_date": "2026-06-29",
     "name": "MLB $3 Pocket Cup",
     "entry_fee": 3.0,
     "field_size": 222,
     "paid_places": 30,
     "cash_line_points": 121.5,
     "payout_structure": [{"place": "1", "prize": 100.0}],
     "seats": null,
     "max_entries_per_user": 4
   }
   ```

   The standings export omits every one of these fields (ledger 3.1). `seats`
   is required for satellites; `paid_places` is required for the posture
   allocator (an UNRESOLVED tier blocks allocation).
3. Save the slate salary CSV used that day:
   `archive/<slate_date>/DKSalaries_<slate_date>.csv`. The salary file is
   authoritative for salary and team; the miner joins on it. If the salary CSV
   for a past slate is missing, check for the slate's DKEntries upload file
   first; it embeds the full salary block and restores full coverage. If
   neither exists, run the miner without `--salary` (the `standings_only`
   degraded tier): duplication, winner copies, chalk scores, SP pairs, and the
   registry still land; salary and stack tables report unavailable and the
   archive block carries the coverage tag.
4. Record Ben's own Entry IDs for the contest in the contest JSON or a sidecar,
   for the self-vs-winner decomposition.
5. Run the miner from the project working copy:

   ```
   python -m mlb_engine.field.field_miner \
     --standings data/standings/inbox/contest-standings-<contest_id>.csv \
     --auto-salary \
     --contest-id <contest_id> --slate-date <slate_date> \
     --json data/archive/<slate_date>/mined_<contest_id>.json \
     --emit-ledger
   ```

   Do not pass `--registry`. It defaults to
   `data/reference/field_opponent_registry.json`, which is the one registry.
   Passing a bare relative path is what forked it into two diverging copies in
   the first place, and the runbook telling you to do that is what kept it
   forked. Accumulation is now idempotent per contest, so re-running a mine
   changes nothing.

   **R94, fixed 2026-08-08: this sentence is now true.** Until then the miner
   gated the registry update on the flag, so a runbook-compliant mine never
   touched the registry and said nothing about it — 31 mines of the 2026-08-08
   tranche skipped accumulation silently. Every mine now prints either
   `registry updated: <path>` or a `NOTICE: registry NOT updated` line naming
   the reason. **If you do not see one of those two lines, the mine did not do
   what this step says.** A mine with no `--contest-id` and no winning entry id
   is the one case that legitimately declines (R74(a)); it is non-fatal and the
   rest of the mine is still good.

   The structural gate is fail-closed and blocks: exit 4 wrong salary file,
   5 zero entries parsed, 6 unparsed share over tolerance, 3 other structural
   failure. Nothing is written on a block, so there is nothing to undo. `--force`
   archives anyway and records the override as line 2 of the emitted block.
   Never use it to make a red run look green; use it only when you have read the
   note and know the check is wrong.

   To rebuild the registry from scratch (it is derived data, and the archive is
   the source): `python tools/rebuild_registry.py`. Add `--max-seconds 35` if
   you are running inside a sandbox with a call timeout; it exits 10 with
   progress kept and finishes across several runs.

   **Capture the money at mining time, not later.** Add `--entry-fee <fee>` and
   `--winnings <won>` for the contests Ben entered. Entry IDs are harvested from
   `outputs/<slate_date>/upload_manifest.json` automatically; `--my-entry-ids`
   overrides that. This writes a self-vs-field block into the ledger entry and
   appends the contest to `ledger/own_results.json`, which
   `python tools/net_to_date.py` turns into one cumulative table.

   Do this on the day. DK exports age out and five contests are already
   unrecoverable; anything not captured at mining time is captured never. The
   number this produces is the input to the open stakes decision, and that
   decision cannot be made without it.

6. The miner writes the emitted block to `ledger/inbox/` as a fragment and no
   longer prints it, so a block cannot be pasted twice (R23). Merge each
   fragment into the ledger archive under the slate's `A-NNN` entry, newest
   first, then delete the consumed fragment (step 8). Reconcile the living
   sections the same session: if the slate contradicts a provisional rule,
   adjust the rule's grade and note the contest ID. A successful mine also
   moves its standings CSV from the inbox to `data/archive/<slate_date>/`
   itself; `--no-archive-move` opts out.
7. Verification checklist before closing the contest:
   - File read cleanly with the BOM (`utf-8-sig`); header matched the ledger
     3.1 schema.
   - Salary join rate reported and unmatched names investigated (full tier
     only; call-ups and suffix variants are the usual causes). At the
     `standings_only` tier, confirm the coverage tag is in the archive block.
   - Ownership recompute self-check within 1.5 points of `%Drafted`
     (ledger 3.7). If it fails, the parse is wrong; fix before archiving.
   - Duplication table present: distinct lineups, share duplicated, max
     copies, winner copies.
   - Contest JSON complete: fee, paid places, cash line, seats where
     applicable, own Entry IDs.
8. Merge any fragments waiting in `ledger/inbox/`: apply each note to the
   ledger in place or under the slate's `A-NNN` entry, then delete the
   consumed fragment file. Fragments are create-only for every other
   role; ARCHIVE is the only merger.

After all contests on the slate: return the updated ledger, the updated
registry, and the mined JSON files to the claude.ai project session.

## Job 2: Pre-slate acquisition (run the morning of a slate)

1. Run `python fetch_slate_bundle.py` with `THE_ODDS_API_KEY` set. Output is
   `slate_bundle.json` (MLB Stats API lineups, DK and FD totals, per-venue
   weather). Retractable-roof venues are flagged for the manual roof rule.
2. Save the FanGraphs RosterResource platoon-lineups JSON for the slate (the
   TBD-lineup fallback input for `platoon_order_adapter`).
3. Weekly, on the slow-state cadence: refresh the two Baseball Savant
   expected-stats CSVs (`expected_stats_batting.csv`,
   `expected_stats_pitching.csv`). They carry a BOM; leave them as downloaded.
4. Deliver `slate_bundle.json`, the platoon JSON, the DK salary CSV, and the
   DKEntries reserved template to the claude.ai project session before the
   build.

## Job 3: T-minus watch (ledger 3.8)

Run the clock against the earliest game's first pitch. Every finding maps to an
engine action; never a vibe adjustment.

| Time | Check | Engine action on a hit |
| --- | --- | --- |
| T-24h | Tail scanner review; platoon projected orders | F1 review flag; `platoon_order_by_player_id` input |
| T-90m | Diff posted lineups vs projected orders; scratch flags | `refresh_confirmed_lineups`; excludes for scratches |
| T-45m | Verify every declared SP (opener risk, pushed starts) | `pitcher_roles` reassignment; exposure cap |
| T-20m | Weather and roof refresh on flagged venues | `compute_f5_factor` recompute |
| Post-lock | Authorized late-swap window only | `run_late_swap` with `authorized_entry_ids` |

Kill-list template (state it at the pre-build checkpoint, three entries, per
ledger 3.8):

```
KILL LIST — slate <date>
1. Assumption: <the thing that most damages the portfolio if wrong>
   Verify: <specific check>   Deadline: <T-minus time>
2. ...
3. ...
Override discipline: any discretionary variance injection names its
non-consensus source and timestamp, or it does not happen.
```

## File inventory returned to the project session

- `MLB_Classic_Calibration_Ledger.md` (updated, archive appended)
- `field_opponent_registry.json` (updated)
- `archive/<slate_date>/mined_<contest_id>.json` (per contest)
- `slate_bundle.json` and the platoon JSON (pre-slate)
- Raw standings exports and contest JSONs stay in the local archive tree,
  retained untrimmed.
