# The 1910_4g delivery is invisible to every manifest-driven tool

2026-08-08, ARCHIVE. `outputs/2026-08-06/DKEntries_1910_4g.csv` exists with
filled, entered rows (standings prove entry), but: no delivery record in
`outputs/2026-08-06/upload_manifest.json`, no `runs/` directory in the
1910-window, and no staged salary in `data/slates/2026-08-06/` (the saved
DKEntries template there is the early slate's, without a salary block). This
is the Classic sibling of the Showdown manifest-status fragments from
2026-08-05/06. Consequences hit ARCHIVE: own-entry harvest fails silently for
those contests (needed explicit --my-entry-ids), and the five contests can
only ever be `standings_only` because no salary source exists. Whatever path
produced that delivery bypassed the manifest write; worth finding, because a
delivery outside the manifest also sits outside supersession tracking and the
sha256-at-upload check. Contests: 193297994, 193297995, 193303619, 193344230,
193344231.
