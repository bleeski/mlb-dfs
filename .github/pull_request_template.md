<!--
The repo's landing discipline, as a PR body. `.claude/rules/board.md` sets the
shape of a CHANGELOG entry; this mirrors it so the two do not drift, and so a
reviewer reading the PR sees what the changelog will say.

Delete any section that genuinely does not apply, and say why in one line
rather than leaving it blank. "Not applicable" with no reason is the shape a
skipped step takes.
-->

## R-numbers

<!-- R###, one line each, matching the CHANGELOG entry and the commit subject. -->

## Scope

<!--
Every file touched, including docs, skills, `.claude/` and CLAUDE.md. This is
the same list that went to `git add` and `git commit`; if it is not, one of
them is wrong.
-->

## What was wrong

<!--
Verified against the tree, not against the backlog entry. The filed diagnosis
has been wrong about the mechanism more often than right
(`.claude/rules/engine.md`), so say what you reproduced and what it printed.
-->

## What shipped

## Declined or deferred

<!-- Parts of the item not built, each with its reason. A partial landing is normal. -->

## Evidence

**Gate:** <!-- `PASS  v2.26.0  40 modules  <N> tests`, from the real tree, in full. -->

**Golden histogram:** <!-- unmoved, or before/after plus why a re-freeze was deliberate. -->

**Mutation checks:** <!-- each new test reverted against its fix, expected red, restored. -->

## Truthful labels

<!--
Tick only what the change actually did. CLAUDE.md's non-negotiable: everything
here is a deterministic review proxy or a labeled prior.
-->

- [ ] No ROI, profitability, win rate, cash rate, edge or probability claimed anywhere in this diff
- [ ] "Upload-ready" used only for a certified Classic export
- [ ] Any Showdown output still labeled review-grade
