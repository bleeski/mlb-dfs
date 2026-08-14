# Next implementation run (paste this into a fresh Cowork session on the mlb-dfs folder)

You are DEV for this session. Read CLAUDE.md and follow the session-start
protocol exactly (git status with the foreign-dirt rule; the audit gate —
note the one-call macro exceeds the sandbox call ceiling, use the Quick
Card's per-suite fallback and verify every suite at its pin; read the ledger
Quick Card section 0). Glob claims/engine* and read owner.json on anything
held; then take the engine claim via `python tools/claim.py take
engine_<utc-date>_r114 --role DEV`. Run with `TMPDIR=/tmp` and
`PYTHONPATH=.pylibs`.

## Task: land the head of Tier 1 — the preflight-evidence batch (R114 + R67)

Work from the entries in `docs/2026-07-27_backlog_v2.md` (Workstream 5, R114;
Workstream 5, R67). If a live slate beacon is lit, stop and report instead of
editing engine paths. If R114+R67 have already migrated to CHANGELOG.md,
take the next eligible queue item instead (current order: false-signal batch
R113+R112+R103+R99+R92+R71+R119, then R116) and apply this same procedure.

Scope, per the entries:

1. `tools/preflight_upload.py` and `tools/verify_export.py` learn to read
   `declared_pitchers` from the run's brief/diagnostics (and accept an
   explicit passthrough flag for the no-run case). A rostered pitcher who is
   declared (`viable_bulk_or_alt_sp` or any R104 role) reports as an
   acknowledged WARN naming the declaration and role — never FAIL. An
   undeclared missing arm still exits 2. Never weaken any other check; the
   money-and-entry wall and exit-code contract (0/2/3/4) are unchanged.
2. R67 in the same pass: a confirmed team with a null probable (bullpen
   game) evidences bats only — do not fail a pitcher-position player against
   a posted batting lineup.
3. Tests, in the audited suites: replay the archived 2210_2g shape (declared
   bulk arm → exit 0 with named WARN; same file, declaration removed →
   exit 2); the bullpen-game null-probable case; pin the WARN text by value
   (R91's lesson: no key-presence-only asserts). Update
   `EXPECTED_SUITE_COUNTS` in tools/audit.py for genuine growth only, and
   re-run the per-suite gate to green at the new pins.
4. Documentation: SKILL.md's preflight section if it names the failure mode;
   CLAUDE.md only if a sentence became false (unlikely; the preflight
   sentence is behavior-neutral here).
5. CHANGELOG.md: one entry for this change (What/Why/landing record, keyed
   R114+R67), migrating both entries out of the backlog per the contract.
   Also write the entry the 2026-08-14 audit session deliberately deferred:
   "2026-08-14 portfolio-edge audit — R114-R120 filed, three BUILD fragments
   merged (diagnoses corrected in tree), ed4 adjudicated (R119 adopted,
   sim-gate variance precondition added), tiers reordered R118→R48+R83→R10;
   record in .audit/AUDIT.md." That clears the changelog debt the audit
   commit knowingly created.
6. Backlog: remove the R114 and R67 entries (they migrate to the changelog),
   update the Tier 1 list head, and add the session note per house style.
   While holding the claim, sweep the three consumed
   `docs/backlog_inbox/2026-08-1*` fragments (request the Cowork delete
   grant; else `mv` into `_to_delete/backlog_inbox_consumed_<date>/` per
   R109).
7. Commit by explicit path only (never `-A`): the changed tools, tests,
   audit pins, CHANGELOG.md, the backlog, this file's checkbox below. Check
   for a stale `.git/index.lock` first (mv aside with a timestamped suffix
   if dead). Then `python tools/claim.py release engine_<utc-date>_r114`.

Acceptance gate (all required before commit): per-suite audit green at the
new pins; the 2210_2g replay pair behaves as specified; preflight on the
newest delivered file in outputs/ still exits 0; no new dependency, no
network in the gate path, no owner action.

Constraints, absolute: no DraftKings fetching or automation; no uploads; no
edits outside the DEV write set; truthful labels everywhere (WARN text names
the declaration source, never claims verification it does not have).

- [ ] Landed by session ____ on ____ (fill at completion)

## Queue after this run (do not start these; recorded for continuity)

1. False-signal batch (R113+R112+R103+R99+R92+R71+R119) — one session, WS4.
2. R116 (production reuse-cap default + distinct_lineups in brief) — S.
3. R118 (FPTS retention + replay_portfolio) — the Tier 2 head; its
   acceptance gate includes the 2207_2g reuse A/B with exact duplication
   counts against the archived field.
