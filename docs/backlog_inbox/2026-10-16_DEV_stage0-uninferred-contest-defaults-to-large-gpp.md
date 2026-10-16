# Stage 0: an uninferred contest still builds as `large_gpp`, contradicting `infer_shape`'s docstring

Filed by DEV, 2026-10-16 (Session 133, R464), found while porting `mlb_engine/production/contracts.infer_shape`.

`infer_shape` says "An unknown title never becomes a GPP by default" and returns None for a title it cannot read.
`workflow.py:136-142` then adds no `ContestSpec` for that contest, and `portfolio.py:172` reads
`specs[entry.contest_id].shape if entry.contest_id in specs else "large_gpp"`, so the contest is built as a
large-field GPP anyway, silently. The engine's build path refuses the same case by name
(`execution_pipeline.unresolved_contest_blockers`). Stage 0 is R302's strangler, off the build path, so nothing
delivered was affected.

Ask: decide whether stage 0 refuses an unidentified contest the way the engine does, or labels the fallback on the
manifest (`title_inferred_contests` records only the inferred ones today). Either way the docstring and the
behavior should say the same thing.
