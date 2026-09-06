> **RETAINED — DO NOT DELETE ON AN INBOX SWEEP.** Merged as **R317** on
> 2026-09-06 and KEPT on the 2026-08-09 precedent: `docs/backlog.md` names this
> file as the sole carrier of the step-0 staleness checker, the roster-grid
> extraction script, the per-team HTML synthesis and the `reference`-claim
> sequence, none of which exist anywhere else, and a session needs them TODAY
> because R317(a) and (c) are not built. It is consumed and deleted in the
> commit that ships R317(c), at which point the refresh is one command.
> **Caveat 1 below is DEAD** — superseded by
> `2026-09-06_DEV_fangraphs-reachable-by-curl-not-urllib.md` (merged into
> R317(a)): the block is a urllib client fingerprint, not a proxy gate, and
> `curl` returns 200 from this VM. Read R317 before running any of this.

# How to refresh the FanGraphs platoon reference when it is stale

Recorded by a BUILD session on the 1810_3g slate, 2026-09-04, at Ben's request.
This is a PROCEDURE a future session can follow with no context, plus the code
change that would make it one command. It supersedes
`2026-09-04_BUILD_fangraphs-platoon-browser-path-works.md`, which said the same
things as a findings report; DEV should merge this one and drop that one.

The file in question is `data/reference/fangraphs_platoon_lineups.json`. It
supplies the projected batting order for any team that has NOT posted a lineup,
via `live_data_adapters.build_slate_pool`. On a slate with a TBD team it decides
which nine bats are in the pool and what F2 batting-order weight each gets, so a
stale file is not a cosmetic problem: it seeds the pool with players who are no
longer in the order. Measured on this slate, at the bottom.

## Step 0. Decide whether it is actually stale

Do NOT trust the top-level `collected_date`. A partial refresh sets it to today
even when most teams are months old (see Caveat 3). Run this instead; it reports
the OLDEST TEAM, which is the number that matters:

```bash
cd $REPO && python3 - <<'PY'
import json, datetime, pathlib
d=json.loads(pathlib.Path('data/reference/fangraphs_platoon_lineups.json').read_text())
today=datetime.date.today()
age=lambda s:(today-datetime.date.fromisoformat(s)).days if s else None
ages={t['abbrev']:age(t.get('carried_forward_from') or t.get('page_updated') or d['collected_date'])
      for t in d['teams']}
oldest=max(ages.values())
print(f"top-level collected_date : {d['collected_date']} ({age(d['collected_date'])}d)")
print(f"OLDEST TEAM in the file  : {oldest}d ({', '.join(a for a,v in sorted(ages.items()) if v==oldest)})")
print(f"teams over 7d            : {sorted(a for a,v in ages.items() if v>7) or 'none'}")
print("VERDICT:", "FRESH" if oldest<=7 else f"STALE -- refresh (oldest team {oldest}d)")
PY
```

Verified output on this slate after the full refresh: `OLDEST TEAM 0d`,
`teams over 7d: none`, `VERDICT: FRESH`.

The 7-day bar is the engine's own (`stale_platoon_policy`), and it ages against
the SLATE, not the file's collection date. Two shortcuts before you refresh
anything: a slate where every team has POSTED reads no platoon reference at all,
and a team you can source from DK's `Starting` column never touches it either
(R143). So the only teams that matter are the TBD ones on tonight's slate. If
those are fresh, ship and refresh later.

## Step 1. Two URLs carry all thirty teams (Ben, 2026-09-04)

    https://www.fangraphs.com/roster-resource/roster-grid?platoon=vsr
    https://www.fangraphs.com/roster-resource/roster-grid?platoon=vsl

This is the important finding. `fetch_fangraphs_platoon.py` walks its 30-entry
`TEAMS` table and loads `/roster-resource/platoon-lineups/<slug>` once per team,
so a full refresh is 30 page loads. The roster-grid pages do it in TWO. Both
were verified this session: each returns all 30 teams at nine slots each, and
the `platoon` parameter genuinely switches the order (PIT leads Horwitz on
`vsr`, Griffin on `vsl`).

## Step 2. Load each page in the built-in browser and extract

`--fetch` does not work from the sandbox (Caveat 1), so the pages are read in
the Cowork built-in browser. Navigate, wait ~8s for the tables to render, then
run this in the page. It returns every team's nine slots as JSON:

```js
function grid(){const out={};
 for(const t of [...document.querySelectorAll('table')].filter(x=>x.rows.length>50)){
  const rows=[...t.rows].map(r=>[...r.cells].map(c=>c.textContent.replace(/\s+/g,' ').trim()));
  const abbr=rows.find(r=>r.length>=5&&r.every(c=>/^[A-Z]{2,3}$/.test(c)));
  if(!abbr) continue;
  const si=rows.findIndex(r=>r.length===1&&/^Starting Lineup$/i.test(r[0]));
  if(si<0) continue;
  const slots=[];
  for(let i=si+1;i<rows.length&&slots.length<9;i++){
   const r=rows[i];
   if(r.length<abbr.length*4) break;
   if(!/^[1-9]$/.test(r[0])) break;
   slots.push(r);
  }
  abbr.forEach((ab,k)=>{out[ab]=slots.map(r=>[+r[k*4],r[k*4+1],r[k*4+2],r[k*4+3]]);});
 }
 return out;}
JSON.stringify(grid())
```

Why it is shaped that way, so it can be repaired when FanGraphs moves something.
Six tables with more than 50 rows, one per division. Inside each: a row of five
team abbreviations, a repeated `Role | Pos | Name | B/T` header, a single-cell
`Starting Lineup` section marker, then the nine slot rows. **Teams sit SIDE BY
SIDE**, four columns each, so a slot row holds 5 x 4 = 20 cells and team `k`
occupies `[k*4 .. k*4+3]`. Bench, Rotation and Bullpen follow below in the same
shape, which is why the loop stops at the first row whose first cell is not 1-9.

## Step 3. Write per-team HTML and run the existing parser

No code change is needed today: the parser already accepts saved pages via
`--from-dir`, and it only needs the vsR/vsL heading phrase plus a table whose
first four cells are slot, position, name, bats. So synthesize one minimal file
per team and let the real tool do the parsing, merging and schema work.

```python
# slug map comes from the tool itself, so it cannot drift:
#   from tools/fetch_fangraphs_platoon.py import TEAMS  ->  (slug, name, abbrev, league, div)
# vsr / vsl are the two JSON blobs from Step 2, keyed by FANGRAPHS abbrev.
import html, pathlib
XW={'CHW':'CWS','KCR':'KC','SDP':'SD','SFG':'SF','TBR':'TB','WSN':'WSH'}  # FG -> DK
slug_by_dk={a:s for s,_n,a,_l,_d in TEAMS}
out=pathlib.Path('data/slates/<date>/fangraphs_pages'); out.mkdir(parents=True, exist_ok=True)
for fg_ab in vsr:
    dk=XW.get(fg_ab, fg_ab)
    parts=[f"<html><body><p>Updated: {page_updated}</p>"]
    for side, blob in (("R", vsr), ("L", vsl)):
        rows=blob[fg_ab]
        assert [r[0] for r in rows]==list(range(1,10)), (fg_ab, side)
        parts.append(f"<h3>Go-To Starting Lineup vs{side}</h3><table>")
        for s,pos,nm,bt in rows:
            bats=bt.split('/')[0].strip()          # the grid ships "B/T"; the page shipped bats alone
            parts.append("<tr>"+"".join(f"<td>{html.escape(str(x))}</td>" for x in (s,pos,nm,bats))+"</tr>")
        parts.append("</table>")
    (out/f"{slug_by_dk[dk]}.html").write_text("".join(parts)+"</body></html>", encoding='utf-8')
```

Then, holding the `reference` claim, because `data/reference/` is ARCHIVE's
write set and this file is a one-writer surface:

```bash
python tools/claim.py take reference --role ARCHIVE
cat data/reference/fangraphs_platoon_lineups.json > data/reference/_backup_fangraphs_platoon_lineups_<olddate>.json
python tools/fetch_fangraphs_platoon.py --from-dir data/slates/<date>/fangraphs_pages --check --json   # dry run first
python tools/fetch_fangraphs_platoon.py --from-dir data/slates/<date>/fangraphs_pages --json
python tools/claim.py release reference
```

`--check` prints `parsed N, failed 0` and writes nothing. Refresh ALL THIRTY
whenever you refresh at all (`--only` exists but see Caveat 3). Back up by `cat`,
not `cp`: this mount grants create and truncate but not unlink (R109).

## Step 4. Verify, and know which check you have left

`parsed 30, failed 0` proves the parse ran, not that the numbers are right. The
real check is that the two FanGraphs views agree. This session pulled all 30
teams the slow per-team way, then pulled both grid pages, and diffed:

    vs_RHP identical: 30/30   mismatched: 0   not-found: 0
    vs_LHP identical: 30/30   mismatched: 0

That is 540 slots, position and name, in slot order, from two independently
rendered views. **Note what changes once you SOURCE from the grid: the grid is
no longer an independent check, and the per-team pages become the cross-check.**
Spot-check two or three teams against `/platoon-lineups/<slug>` after a grid
refresh rather than claiming corroboration you did not run.

## Caveats

1. **`--fetch` cannot run from the sandbox, and the reason is not FanGraphs.**
   There is no route to fangraphs.com: `Tunnel connection failed: 403 Forbidden`
   on CONNECT, the same proxy gate that blocks `statsapi.mlb.com` and
   `api.the-odds-api.com`. That is R147's lesson in a new place -- report "no
   network", not "check the site". The built-in browser reaches it fine.
2. **The parser is verified against RENDERED table structure, three times now,
   and still not against raw server-rendered FanGraphs HTML,** which is what
   `--fetch` from Ben's Windows machine would feed it. That distinction belongs
   in the file's VERIFICATION STATUS paragraph, which currently claims neither.
3. **A partial refresh silences the staleness check for all thirty.**
   `merge_preserving` correctly stamps each carried-forward team with
   `carried_forward_from`, but the top-level `collected_date` still becomes
   today, and `build_slate.py`'s 7-day check reads the top-level stamp. Six teams
   were refreshed on this slate at 17:03 and the warning went quiet for the 24
   that were a month old. Harmless here (the one TBD team was among the six) and
   not harmless on a slate whose TBD team is one of the 24: the build would seed
   a projected nine from month-old data with nothing printed. Candidate fix: age
   the check per team against `carried_forward_from` where present, or carry a
   second top-level stamp naming the oldest team in the file. Until then, refresh
   all thirty, and use the Step 0 checker rather than the warning.
4. **Abbreviations and handedness differ between the two sources.** The grid uses
   FanGraphs abbrevs (CHW, KCR, SDP, SFG, TBR, WSN) against DK's (CWS, KC, SD,
   SF, TB, WSH), and ships a combined `B/T` column where the per-team page shipped
   bats alone. Both are handled above; both are silent corruption if missed.
5. **Only a COMPLETE 1-9 counts.** Assert the slot sequence per team per side, as
   Step 3 does. A short side is a projection, not a posted order, and it must fall
   through rather than arrive looking complete.

## The code change worth making

Add `--from-grid <vsr.json> <vsl.json>` (or have the tool drive the browser
itself) so a refresh is two page loads and one command instead of thirty loads
and a hand-assembly step. Everything it needs is in Steps 2-3: the cell-block
arithmetic, the FG->DK crosswalk, the `B/T` split, and the 1-9 assertion. Keep
`--from-dir` -- it is what made this session possible with no code change at all,
and it is the only path that works while the sandbox has no network.

## Why this matters, measured on this slate

PIT was the one unposted side on 1810_3g. The reference file was 30 days old
(collected 2026-08-05). Its projected order vs RHP held three players no longer
in it (Endy Rodriguez, Jacob Gonzalez, Ronny Simon) and was missing three now in
it (Konnor Griffin, Oneil Cruz, Rafael Flores Jr.); only slots 2 and 3 were
unchanged. Rebuilding on the refreshed file at identical controls moved the apex
review proxy 1056.83 -> 1085.38, the worst entry 134.03 -> 147.37, and
worst-triple concentration 4/7 -> 3/7. PIT went from one primary stack to two and
CIN from zero to one, which fits the market: PIT's 4.58 implied total was second
on the slate and was being under-stacked because half its projected order was
players who no longer bat there. Same three gates, same single control override.
Both are deterministic review proxies, not probability claims.
