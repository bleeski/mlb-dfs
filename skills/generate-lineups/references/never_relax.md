# `--never-relax`: a control that holds under every deadline (R388(b))

A value typed in `--controls-override` is a relaxable preference: the
deadline governor's `open_controls` rung (SKILL.md, `--deliver-by`) opens it, and the brief's `control_provenance` calls it
`operator_relaxable`. Only `--never-relax <control>[,<control>...]` (comma-separated
or repeated) makes one `operator_never_relax`. The rung leaves it closed and
lists it under `held`, a feasibility floor does not raise it, and
`tools/autobuild.py` (which forwards the flag) stops and names it rather than
floor it. R407's input-confidence tightening still applies, and never loosens a
held cap. Distinct lineups per contest (F-3) is held on every build without the
flag. The build refuses at exit 4, before staging, a name it cannot hold at
every relaxer: the allocator's own ladders and sleeve fallback
(`classic_sleeves`, `max_candidate_reuse`, the stack floor and five-stack
quota) and all four Showdown controls, whose solver relaxes them per slot
(R391 wires those). A late swap re-derives the floors, so restate the flag on
`tools/late_swap.py --never-relax`; it refuses the consensus-cluster cap, which
a swap does not enforce. Use it only for a restriction Ben stated for this
slate. `brief.control_provenance.by_control` gives every resolved control's
value and provenance; a row a rung moved carries `relaxed` with its before
value.
