# BUILD 2026-08-24 main (1940_7g) -- the odds API is unreachable in a cloud session, and F1 is not cosmetic

Ben's instruction, verbatim, after seeing the rebuild: "if using action network is
easier let's either update what we need to or add a fragment or item to the
backlog." This is that fragment. Filed by a BUILD session, so it does not touch
`docs/backlog.md`.

## 1. A certified file shipped with F1 fully neutral, and nothing refused

`api.the-odds-api.com` is proxy-gated in the cloud Cowork container exactly as
`statsapi.mlb.com` is. Measured tonight:

    odds: odds fetch failed (<urlopen error Tunnel connection failed: 403 Forbidden>); F1 stays neutral

The first delivered portfolio (run `20260824T231347Z_13db8508`, sha
`2c6c4e044899`) certified on all three gates and passed
`preflight_upload.py` at exit 0 while carrying:

    f1_non_neutral: 0
    f1_games_priced: 0

Both gates and the preflight are silent about this by design -- F1 neutrality is
not a legality fault. `enrichment.signal_applied` was `true`, because five other
factors did move rows, so the one summary field a hurried session is told to read
said the build was enriched. The specific reading that matters,
`counts.f1_non_neutral: 0`, is one level down. **The skill's own guidance ("Read
`enrichment.signal_applied` before you present anything") is therefore not
sufficient on its own to catch a dead F1.** Worth a line in
`skills/generate-lineups/SKILL.md`, and possibly a named entry in the brief's
`factors_inert` list -- note that `factors_inert` printed `none inert: every
computed factor moved at least one row`, which is TRUE and still misleading here,
because F1 never computed at all rather than computing to neutral. An
uncomputed factor and a computed-neutral factor are different facts and the
inert list currently conflates them by omission.

## 2. The delta is large enough that this is a quality bug, not a footnote

Same salary file, same entries file, same controls, same posture, same bank
policy. Only `--odds` differs. Rebuild is run `20260824T232032Z_5b42af75`, sha
`42aadd285f93`.

    4+ stacks   F1 neutral                    F1 live
                MIN 5, CHC 4, CIN 3, CLE 2    CWS 4, CHC 3, TEX 3, ATH 3
                PIT 1, TEX 1, SEA 1, ATH 1    CLE 2, MIN 2, CIN 1, ARI 1

    apex mean   144.0                         149.48
    apex total  2592.0                        2690.67

CIN went 3 stacks to 1. CIN@SF priced at a 7.0 total with CIN implied 3.75
against a slate mean of 4.071, so the neutral build was stacking one of the two
weakest environments on the board. Derived implied team totals ran ATH 5.32 and
MIN 5.68 at the top against SEA 3.21 and SF 3.25 at the bottom -- a 1.77x spread
that F1 could not see at all in the first build.

The frontier proxy also moved in the direction that matters to the dual
objective, and not favourably: washout on MIN@ATH went from "retains 86.4% of
portfolio ceiling with 8/18 entries untouched" to "78.9% with 2/18 untouched."
F1 correctly concentrated into the only double-digit total on the slate, which
is the same concentration that loses a satellite portfolio at once. Not a
defect -- it is the frontier behaving as documented -- but it is the first case
I have on record where turning a factor ON measurably worsened the washout end,
and it argues that F1 and the washout axis should be read together rather than
in sequence.

## 3. Action Network works, and here is exactly what it costs

`https://www.actionnetwork.com/mlb/odds` is reachable and carries moneyline and
total for every game. Four facts a future session should not have to rediscover:

- **`web_fetch` returns an EMPTY body.** The page is client-rendered. This is
  the "escalate to Chrome" case, not a blocked-domain case.
- **`__NEXT_DATA__` does NOT carry the odds.** `props.pageProps.scoreboardResponse`
  has every game with correct ids, start times and status, and `oddsRows: 0` on
  all of them. Odds arrive from a later client fetch and exist only in the DOM.
  Do not spend a call parsing `__NEXT_DATA__` for prices.
- **The market selector is the SECOND `<select>` on the page.** The first is the
  sport picker (`mlb`). The second is `spread|total|ml|combined`. Setting
  `.value` directly does not re-render; use the native value setter plus a
  bubbling `change` event, then wait ~3s and re-read the page text.
- **The table includes games that are not on the slate**, including in-progress
  ones (BOS@MIA, TB@DET, COL@WSH tonight). Any parser must filter against the
  salary file's game set, and F18's doubleheader-leg resolution still applies.

## 4. Proposal: `tools/odds_from_paste.py`, mirroring `lineups_from_paste.py`

The repo already has the right pattern for a source that cannot be fetched:
R32's paste path. Same shape here. Input is the Action Network odds table text,
output is an ordinary the-odds-api v4 events list written into
`data/slates/<date>/`.

Nothing downstream needs to change, and that is verified rather than assumed. I
hand-built a v4 payload tonight and `normalize_odds_payload` accepted it as
`raw_events_list`; `parse_the_odds_api_totals` returned all 7 games with
moneylines; and all 14 team names on the slate resolved through
`team_name_to_dk_abbrev`, `Athletics` and `Oakland Athletics` both mapping to
`ATH`.

Blockers behave like the paste tool's: an unresolved team name or a game in the
salary file with no priced row should refuse rather than emit a partial packet,
because a half-priced slate reaches F1 looking like a slate where some teams
genuinely have no market.

## 5. The sharp part: what I did tonight is R205's bug, executed by hand

**A paste tool must not average across book columns, and neither should a human.**

I read the Action Network table across roughly seven book columns and averaged
the moneylines BY EYE to a "consensus" before writing the file. That is exactly
the arithmetic R205 forbids: American odds are discontinuous at ±100, and a
near-pick'em straddling the boundary is where the fabrication is worst. TEX@CWS
tonight was TEX +110/+116/+120/+122 across books -- all same-sign, so my read is
probably not badly wrong there -- but the method is unsound and would have been
wrong on any game where one book posted +100 and another -104. I have no
per-book record of what I collapsed, so the delivered file's prices cannot be
audited back to a book. That is the honest status of run `20260824T232032Z_5b42af75`:
its F1 is materially better than neutral and its inputs are not reproducible.

Two consequences for whoever builds this:

- **Emit ONE book, named, or land R205 first.** If the tool emits N book entries
  per event, `parse_the_odds_api_totals` will average them and reintroduce R205
  through a new door. Tonight's file sidesteps that only by accident: it carries
  a single synthetic `consensus` book, and a median over one value is that
  value, so the parser is clean and the contamination sits entirely upstream in
  my hand-averaging. Relocating a bug is not fixing it.
- **Prefer a single named book column** (the tool should let the caller pick, and
  should record which one in the packet) until R205's de-vig-each-book-then-
  average-probabilities fix ships. After R205 lands, emitting all books becomes
  the better option and this tool gets more accurate for free.

Cross-reference: R205 (`docs/backlog.md`), and the `mlb-game-odds` key residual
on the Do-not-build list, which is the same class -- blocked on a hand step
rather than on a decision.

## 6. Suggested acceptance

- `tools/odds_from_paste.py` emits a v4 events list; round-trips through
  `normalize_odds_payload` -> `parse_the_odds_api_totals` to the same prices the
  paste stated, pinned by a fixture built from tonight's captured table text.
- Refuses on an unresolved team, on a game in the salary file with no priced
  row, and on a book column the caller did not name.
- Filters to the salary file's game set and resolves doubleheader legs by start
  time, same as `load_odds_packet` already does.
- `skills/generate-lineups/SKILL.md` gains: the odds API is proxy-gated in cloud
  sessions, `signal_applied: true` does not mean F1 ran, read
  `counts.f1_games_priced` directly, and the Action Network fallback path.
- Consider having `factors_inert` distinguish "computed to neutral" from "never
  computed" so a dead F1 names itself in the one line the brief already prints.

## 7. Artifacts on disk

- `data/slates/2026-08-24/odds_actionnetwork_1940_7g.json` -- tonight's packet,
  single `consensus` book, hand-read. Usable as a shape reference; NOT usable as
  a price fixture, per section 5.
- Delivered: `outputs/2026-08-24/DKEntries_1940_7g.csv`, sha `42aadd285f93`,
  run `20260824T232032Z_5b42af75`. Supersedes sha `2c6c4e044899` at the same path.
