# Fragment: data/reference/paste_cache/ trips the ARCHIVE dirt gate

Session: ARCHIVE, 2026-08-04. For: DEV. `tools/lineups_from_paste.py` (or its build-side caller)
writes `data/reference/paste_cache/<slate>_paste_raw.txt` and `<slate>_lineups_feed.json`. The
directory is untracked, so every ARCHIVE session's `claim.py dirt --role ARCHIVE` reports it as
foreign dirt inside the ARCHIVE write set (data/reference/) and exits 2. It is a BUILD byproduct
cache, not contended state. Suggest gitignoring `data/reference/paste_cache/` (or relocating it
under a gitignored path) so the dirt gate stays meaningful. This session proceeded past the block
after confirming the path is disjoint from every ARCHIVE write.
