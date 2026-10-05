# 2026-10-05 BUILD (1700_2g): after a re-promote, the preflight takes an undelivered intermediate as the parent and FAILs a file that matches what was uploaded

**Observed.** 1700_2g, outputs/2026-10-05/upload_manifest.json. Three promotions in about two minutes under one slate tag:

1. run `20261005T203207Z_f1417bc3`, sha `9b1f6a98`, delivered at `outputs/2026-10-05/DKEntries_1700_2g.csv`.
2. run `20261005T203228Z_c44fc975`, sha `12e3bbb0` (a caps-0.625 experiment, never handed over), written to the same path. Row 1 goes `superseded`, `superseded_by` that path.
3. `promote_run --run-id 20261005T203207Z_f1417bc3`, which writes `DKEntries_1700_2g_f1417bc3.csv` with sha `9b1f6a98` (status `upload_ready`). Row 2 goes `superseded`, `superseded_by` the new file.

Ben uploaded `9b1f6a98`. At 18:56 ET, with CWS@CLE in progress, the standard command `preflight_upload.py --entries outputs/2026-10-05/DKEntries_1700_2g_f1417bc3.csv --salary ... --feed <fresh> --declare-pitcher 44387117=viable_bulk_or_alt_sp` exited **2**. Its four FAIL lines say entries 5284476093 and 5284476268 "introduced" and "replaced" CWS players "from an already-started game". The chain walk found row 2 (`12e3bbb0`) as the parent. That file swaps exactly those two entries' lineups relative to `9b1f6a98`. The uploaded bytes are identical to the file under test, so nothing moved. With `--parent outputs/2026-10-05/DKEntries_1700_2g_f1417bc3.csv` the same command exits 0.

**Mechanism, read at 531658b.** The parent comes from the supersession-chain walk in `tools/preflight_upload.py:1768-1785`. It takes the first record whose `superseded_by` names this file and reads that record's `delivered_file`. Row 2's `delivered_file` is `DKEntries_1700_2g.csv`, which holds `12e3bbb0` on disk. Row 1 names the same path, so by now it would also resolve to `12e3bbb0`. Two rows sharing one delivered path is the latent half: the bytes on disk belong to whichever promotion wrote last.

**Why it matters.** Before a late swap, the preflight is the last independent look. Here it would have told Ben not to upload, or pushed a session toward `--force`, over a diff against bytes nobody uploaded. This is a different bug from `2026-10-04_DEV_preflight-chain-walk-reads-runs-final-by-run-id.md`: in that one, the parent row's bytes are wrong; in this one, the bytes are right but the row is the wrong parent.

**Candidate item.** In the supersession-chain walk, when the file under test has the same sha256 as a row further up its own chain, the rows in between were never uploaded at those bytes. Two options: take the earliest row with the same sha as the parent, or treat the parent as ambiguous. Either way, WARN and name every candidate rather than FAIL; `--parent` stays the operator's override. Test: the three-row shape above, where locked-slot preservation passes, plus the inverse case where the intermediate was uploaded, which needs `--parent` to state that.

Observed outcomes and a tool check only; nothing here is an edge, ROI, win rate or probability.
