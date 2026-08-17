# Next-session prompts

Rewritten 2026-08-10 by DEV during the board reorganization. Delete each once
used; this file is scratch, not a contract. The previous Prompt B (ARCHIVE,
2026-07-31) was stale — its pending-work list had been done for a week — and
is replaced below. Authority for what any prompt asks lives in the backlog
entry it names, never in this file; if a prompt and the backlog disagree, the
backlog wins.

---

## Prompt A — DEV, the Showdown intake-and-bookkeeping batch (queue position 1)

```
Role: DEV. Read CLAUDE.md and run session start first. Take the engine claim
before touching code (claim.py take engine --role DEV, scope: "Showdown batch
R104+R45+R105+R54"); a claim you cannot take stops the session. Check claims/
for lit slate beacons — builds re-import modules between steps, so never edit
engine paths while one is lit.

The work is queue position 1 in docs/backlog.md, Workstream 1:
four items, one session, all S. Read each entry in full before starting; the
entries carry line cites, live burn records, and the agreed fix shapes.

1. R104 — DK Starting token policy. PO becomes non-rosterable everywhere
   (new role, not a reuse of viable_bulk_or_alt_sp; out of _is_declared and
   Is_Declared_Starter in showdown.py). PLR is surfaced, never auto-resolved:
   named soft blocker per arm plus the new repeatable
   --declare-pitcher <id>[=<role>] flag on build_slate.py, plumbed to the
   declared_pitchers mapping the engine already accepts. The brief records
   any declaration verbatim. Ben's policy is quoted in the entry; the
   web-search confirm step stays an operator act outside the build.
2. R45 — lineups_from_paste.py resolves Showdown salary files: dedupe
   candidate rows by DK identity before the ambiguity test, resolve probables
   off the Starting column when the file is Showdown, and add the Showdown
   salary fixture test the entry names (CPT/UTIL double rows, both probables).
3. R105 — the Showdown manifest record writes 'candidate', never the
   preflight verdict string; verdict and status stay separate facts; pin the
   delivered-status vocabulary by test. Record which exit code verify_export
   really returns on the vocabulary failure (the two fragments disagreed, 2
   vs 3) and pin that too.
4. R54 — the four counted-relaxation lies: count the overlap-relaxed solve,
   add the both-relaxed ladder rung (counted), surface ignored_locks, share
   one OUT-status constant with preflight. Counter-VALUE asserts, not
   key-presence (that gap is what let this survive — R79(c)).

If the session has room, R85 (preflight contest-type vs Contest ID
cross-check) is the named rider: preflight-native, no network, S.

Rules that bind this session: scipy.optimize.milp only; determinism
(stable_union, PYTHONHASHSEED); truthful labels — Showdown stays
review-grade, "certified" and "upload-ready" do not enter Showdown vocabulary
here (that is R41, a separate decision-first item); never trim the player
pool to fit anything; the audit must print its PASS line before and after.

Closing contract, not optional: every completed item's entry MIGRATES from
the backlog into CHANGELOG.md in the completing commit, with rationale, keyed
to its R-number; the changelog entry rides the SAME commit as the code;
update the queue and Workstream 1 so the backlog holds open work only; if
anything new is found, the next free R-number comes from scanning BOTH the
backlog and CHANGELOG.md (the R102/R103 lesson). git add by explicit path,
never -A. Release the engine claim with claim.py release.
```

## Prompt B — ARCHIVE, execute Ben's curated-archetypes decision and bring the ledger current

```
Role: ARCHIVE. Take the ledger and inbox claims first; a claim you cannot
take turns this run into a report, never a write. Never run this during a
live build: check claims/ for a lit slate beacon and check its age before
trusting it.

1. Execute Ben's 2026-08-09 decision in
   docs/backlog_inbox/2026-08-09_DEV_ben-decision-curated-satellite-archetypes.md:
   the nine ledger-3.14 satellite families enter
   data/reference/dk_contest_archetypes.csv with observed ticket_count
   values. Honor all four cautions in the fragment — multi-valued families
   are not written single-valued, the SUPERSat matching gap, check
   competing-pattern shadowing on the bench, and the two GOLF-only rows are
   observed history only. Delete the fragment once executed; it is consumed.
2. Merge ledger/inbox/2026-08-10_DEV_quick-card-test-pin-moved-to-792.md into
   the Quick Card. Note the pin has since moved again: tools/audit.py's
   EXPECTED_TEST_COUNT is the source of truth and reads 810 as of the R102
   sync commit. Carry the fragment's two riders (stale chunk boundaries;
   the off-machine 783-vs-pin sandbox caveat, which is R62's evidence).
3. Regenerate the awaiting-standings list
   (python tools/awaiting_standings.py scan) and mine anything Ben has
   dropped in data/standings/inbox/. The inbox stays FLAT; the miner reads
   Classic vs Showdown off the lineup cells.

Labels: everything you write is observed history or a deterministic count;
nothing is a win rate, ROI, or probability claim. Ownership and outcome
counts stay conditioned on archetype and field size, never pooled.

You do not edit the backlog or CHANGELOG.md; those are DEV's. If this run
finds something DEV should file, drop one fragment per finding in
docs/backlog_inbox/. Ledger edits are in place; the archive is append-only.
Commit with a descriptive message when tracked files change.
```

## Prompt C — DEV, R10: the satellite ownership and duplication prior (queue position 3)

```
Role: DEV. Session start, then take the engine claim (scope: "R10 satellite
prior"). Run this AFTER the Showdown batch (Prompt A) unless Ben reorders.

Authority: the R10 entry in docs/backlog.md Workstream 2, in
full — the gate decision (2026-07-31), the satellite-only scope limit, and
the grading bar are all binding. The short form, which does not replace the
entry: fit per (satellite family, field-size bucket) from the mined archive
with thin buckets left unmodeled, never pooled; write versioned
data/reference/ownership_prior_<archetype>.json artifacts; load them in
_assemble_projection_frame; persist each slate's prediction file BEFORE lock;
grade with grade_against_actuals into the ledger against the flat-12
baseline, on ownership error AND the duplication distribution
(own_lineups_duplicated_by_field is populated); surface meta_lineup_status.
Every other archetype stays on flat-12. No production column flips until the
prior beats flat-12 across the gate count in that cell, graded in the ledger.
Label everything a prior; duplication reads "unmodeled" where ownership is
absent, never silently substituted.

R48 (the per-contest leverage table) is this item's grading target and an
ARCHIVE-side emission; if it has not landed, grade against what exists and
say so rather than blocking.

Closing contract: same as every DEV session — completed entries migrate to
CHANGELOG.md in the completing commit, rationale included; the changelog
entry rides the same commit; update the queue and Workstream 2; new numbers
come from scanning both files; explicit-path git add; release the claim.
```
