---
paths:
  - "docs/backlog.md"
  - "docs/backlog_inbox/**"
  - "CHANGELOG.md"
---
# The board and the changelog (DEV writes both; loads when you open one)

- **Never read `docs/backlog.md` whole.** It is about 12,700 lines and 1.1MB. Grep for anchors: `^# What do we tackle next`, `^## Execution roadmap` (the heading carries `NEXT:`), `^## Workstream`, `^### R<number>`. Read the roadmap row for the Session ID on the NEXT pointer, then the `### R` entries it names, and nothing else until you need it. The same holds for `CHANGELOG.md` (1.3MB): grep `^## ` for the entry you want.
- **Edit by anchor-splice, never by rewriting the file.** Write the new text to a scratch file, then a script that asserts each anchor matches exactly once, writes a `.bak` beside the target, and splices. Riders go directly under the entry heading, newest first; new entries directly under the workstream heading; the roadmap row edits in place.
- **A completed item.** Its entry MIGRATES to `CHANGELOG.md` in the completing commit (the CHANGELOG gets the full text; the board keeps a one-paragraph closed stub with the gate line and the commit); the roadmap row says DONE with the date and the gate line; the NEXT pointer in the `## Execution roadmap` heading advances. Land part by part when an item has lettered parts: rewrite the entry to hold only the open remainder, reprice it if the severe half landed, and record each declined part in the CHANGELOG under its own heading with the reason.
- **Verify a fragment's premise with grep before filing it.** Grep the tree for the control, factor, or field the fragment says is missing; trace who WRITES what it needs; name the code path its measurement ran on and check whether the missing term is absent by design there (Showdown skips F1-F5). Two of three fragments on 2026-09-08 had a false or unscoped premise; R333 was a DEAD control, not a missing one. Keep the fragment's measurement, file the corrected mechanism, and say which part was corrected.
- **Consumed fragments** are `git rm --cached` when tracked and `mv -n` into `docs/backlog_inbox/_to_delete/` (gitignored). Committed fragments are invisible to `git status`; list the directory.
- **R-numbers** are allocated at COMMIT time from both files: `grep -oh "R[0-9]\{3\}" docs/backlog.md CHANGELOG.md | sort -u | tail -3`; take the next, never reuse one. A review landed later than it ran is re-adjudicated at the landing HEAD: renumber from the current max and re-reproduce the sharpest findings.
- **CHANGELOG entry shape.** `## <date> — <title carrying the R-numbers>`, then `**Scope.**` listing every file touched (the DEV write set includes docs, skills, `.claude/`, and CLAUDE.md), what was wrong, what shipped, the R233 grep with its hit list, the gate line, and the golden histogram before and after if it moved. One entry per shipped change, newest first, no "lessons" section. A `Decided` entry records a call made and not yet built.
- **Commit subjects are at most 100 characters** and carry the R-numbers (R301); the entry title can be long, the subject cannot. The body says what moved and why in a sentence and points at the entry.
