# DEV 2026-09-06 — FanGraphs answers `curl` 200 and python `urllib` 403 on the same URL, so `--fetch` is one client swap from working and the browser path is optional

Filed while correcting R316's network claims. This SUPERSEDES caveat 1 of
`2026-09-04_BUILD_fangraphs-platoon-refresh-procedure.md` ("there is no route to
fangraphs.com: Tunnel connection failed: 403 Forbidden on CONNECT"). The rest of
that fragment — the roster-grid two-page finding, the cell-block arithmetic, the
FG->DK crosswalk, the partial-refresh staleness trap, the step-0 checker — is
unaffected and still worth merging.

## The measurement, device VM, 2026-09-06

Same URL, same minute, `https://www.fangraphs.com/roster-resource/platoon-lineups/pirates`:

| client | result |
|---|---|
| `curl` (default UA) | **200**, 155,942 bytes, `Go-To Starting Lineup vsR` / `vsL` both present |
| `curl -A "python-urllib/3.10"` | **200** |
| `urllib.request` + `User-Agent: Mozilla/5.0` | **403 Forbidden** |
| `urllib.request` + full browser header set (UA, Accept, Accept-Language, Accept-Encoding: identity) | **403 Forbidden** |

So it is not the proxy and it is not the User-Agent: a UA that names python gets
through under curl, and a UA that names Chrome does not get through under
urllib. That is TLS/HTTP2 client fingerprinting on FanGraphs' edge. The proxy
gate the 09-04 fragment inferred does not exist on this VM — `curl` also
returned 200 from `statsapi.mlb.com`, `baseballsavant.mlb.com`, `pypi.org` and
`api.github.com`, and 200 from `api.the-odds-api.com` with the repo key.

## The existing tool already parses what curl fetches

No code change was needed to prove it. `tools/fetch_fangraphs_platoon.py`'s
`--from-dir` path accepts saved pages, so three teams curl'd into a scratch
directory ran straight through:

```
blue-jays 200 165625
orioles   200 165890
pirates   200 155942
python tools/fetch_fangraphs_platoon.py --from-dir /tmp/fgtest --check
  ->  parsed 3 team(s), 27 failure(s)
```

The 27 failures are `no saved page in /tmp/fgtest` for the teams that were not
downloaded, i.e. exactly the expected shape. `--check` writes nothing.

## What / Why / Fix

- **What.** `fetch_page` at `tools/fetch_fangraphs_platoon.py:271` builds a
  `urllib.request.Request` with `_UA` and calls `urlopen`. That client is 403'd
  by FanGraphs from this VM while `curl` on the identical URL is not, so
  `--fetch` is documented as "expected to work from Ben's machine" and is unusable
  from a session, which is what forced both the 30-page browser procedure and the
  roster-grid workaround.
- **Why it matters.** A stale platoon reference seeds the pool for every TBD
  team; the 09-04 fragment measured the cost on 1810_3g (three players in the
  projected PIT order no longer in it, three missing, apex review proxy
  1056.83 -> 1085.38 after the refresh). The refresh is currently a
  browser-and-hand-assembly procedure nobody will run under a clock. One command
  changes that.
- **Fix (S).** Give `fetch_page` a curl transport — `subprocess` to `curl
  --fail --silent --show-error --max-time N` where curl exists, falling back to
  the current `urlopen`, with the transport that answered named in the tool's
  own JSON so a session can tell which one served the page. A 403 then means the
  site declined, which is what the module's own comment at line 25 already
  claims it means. Keep `--from-dir`: it is the only path that works when
  neither client can reach the host, and it is what made this measurement
  possible with no code change.
- **Bound worth stating.** The parser is still verified against RENDERED table
  structure and, now, against curl'd server HTML for three teams. That is a
  stronger position than the 09-04 fragment's caveat 2 recorded, and the file's
  VERIFICATION STATUS paragraph should say so with the count.
- **Do not encode "there is network" either.** R316's whole point is that egress
  is a per-session measurement. The curl transport should be tried and its
  failure classified (no route / declined / unknown, R147's shape), never
  assumed.
