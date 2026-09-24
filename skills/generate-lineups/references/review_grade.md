# The review-grade lifecycle: an S/P-only refusal still delivers (R388(d), R124(a), R268)

**What lands.** A Classic build whose only failing gates are S or P
(`MLB_Classic.md` §2; `mlb_engine/entries/gate_classes.py`) is still refused:
exit 3, `status: not_certified`, `errors[]` unchanged, the run `blocked`, and
no `runs/<id>/final/DKEntries.csv`. Its legal file now lands at
`outputs/<date>/DKEntries_<tag>_UNCERTIFIED_<run_id>.csv`. The upload
manifest row carries `certification: review_grade_uncertified` and
`failing_gates`. The brief's `review_grade_export` names the path, the sha256
and the gates. Once `verify_classic` re-reads the file clean, a `FILE` line
prints before the gate narrative. A file still at its `DO_NOT_UPLOAD_` name is
named but never presented. It is NOT certified and never upload-ready. Preflight says
`review_ready`, exit 0, and names the failing gates. Upload stays Ben's call,
as for any review-grade file.

**Which failures qualify.** Every failing check must be S or P, and the file
must be essential-valid on its own bytes (Session 08's rule):
- `odds_gate_passed`, `optimizer_gate_passed` and `allocation_method` are P;
- `portfolio_caps_passed` is S, unless the breached cap is `--never-relax`;
- `selection_certified` has no V fact.

Everything else keeps the file at `runs/<id>/candidate/DO_NOT_UPLOAD_DKEntries.csv`,
and the brief says why under `review_grade_withheld`. That covers:
- any V gate;
- the wrong-draftgroup "entries file" errors;
- a MIXED gate with a V fact (weather, lineup, pitcher audit, projection
  schema, roster legality, hash binding). The engine cannot say which of its
  facts failed until R388(c) (Session 13) splits them.

**Never over a better file.** If a live delivery for the same slate tag passed
its gates (`certified`, or a deadline or downgrade label), the UNCERTIFIED file
is not mirrored. The brief names the live file under
`review_grade_export.not_mirrored`: it stays the delivery, and refinements go
through late swap. A later certified build supersedes an UNCERTIFIED row as
usual.

**Late swap off it.** `tools/late_swap.py` finds the parent by the file's own
bytes (R268(b)). The parent can be:
- the latest promoted run;
- an earlier promoted one;
- a certified run that never promoted;
- an UNCERTIFIED build.

Pass the delivered file; no `--allow-parent-mismatch` is needed. The flag is
now only for a file matching no run (hand-edited, repaired, or re-downloaded),
and without it that file is refused at exit 3 before any bank slice.

The swap inherits the portfolio controls the parent recorded (R268(a)).
`--rederive-controls` re-derives them from postures and floors, the old
behaviour. A swap's label is never better than its parent's: a refinement of
an UNCERTIFIED file is UNCERTIFIED, and a refinement of a deadline build keeps
its deadline label. A P-only parent swaps cleanly. An S-failing parent swaps
only when the authorized rows hold the excess, because its frozen rows already
breach the inherited cap.

**What it is not.** A swap whose own failures are S or P is refused and not
mirrored (a rider on R414, Session 101). `--deliver-always` is R124(b),
Session 21.
