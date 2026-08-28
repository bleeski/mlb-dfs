# Intelligent Leverage and Dual-Objective Portfolio Optimization

**Greenfield design and current-process correction**  
**Repository reviewed:** `mlb-dfs`  
**Review date:** 2026-08-28  
**Reviewed commit:** `0a83caca9a0d85ef44b40afe7346e7e2eb57df1b`  
**Scope:** DraftKings MLB Classic and Showdown; data-driven leverage discovery; contest-level top-tail probability; slate-level washout control  
**Status:** implementation specification, not a claim that the current engine estimates EV, win probability, cash probability, or ROI

---

## Executive decision

The engine should stop treating leverage as a synonym for low ownership and stop treating diversification as a collection of exposure caps. The greenfield target is a **joint decision engine** that answers four different questions without collapsing them into one heuristic score:

1. **Salary edge:** has DraftKings underpriced the player's full outcome distribution given information available after salary release?
2. **Field edge:** has the field underreacted to that information, by contest and roster role?
3. **Combination edge:** is the complete lineup less common than its component ownership suggests, and how many copies should it have if it succeeds?
4. **Portfolio edge:** which additional lineup covers valuable slate outcomes that the already-selected entries do not?

The most decision-relevant definition of player leverage is therefore not “good xwOBA at low ownership.” It is:

> The player is more likely to occupy a required role in a top-performing legal lineup than the field is likely to roster that player in that same role, after accounting for salary, contest type, duplication, uncertainty, and the rest of our portfolio.

The current repository cannot compute that quantity. Its Classic selection score is a deterministic blend of projected ceiling, stack heuristics, salary usage, meta-lineup overlap, and cumulative structural ownership. Its current “washout” calculation zeroes a game's hitters from lineup ceilings. Both are useful review diagnostics, but neither is a probability. Showdown adds fixed thesis weights and fixed exposure caps, not a calibrated joint game distribution.

The correct end state is:

- a time-valid feature and market snapshot;
- a probabilistic player/game outcome engine;
- a contest-conditioned field-construction model;
- exact contest settlement with ties and duplicates;
- scenario-driven candidate generation;
- a multiobjective portfolio optimizer that constructs a Pareto frontier rather than hiding the tradeoff inside arbitrary weights; and
- independent, prospective grading of every probability and every promoted signal.

The fastest safe route is not to build all of that at once. A **joint conditional threshold model** can estimate top-1% and washout coverage before the full opponent-lineup simulator exists. It must sample the contest threshold inside the same game scenario as our lineups. A standalone scalar p99 forecast is not sufficient.

---

## 1. What the current process gets right—and where it stops

### 1.1 Existing assets worth preserving

The greenfield design should reuse these assets:

- exact DraftKings identity, roster, salary, and export contracts;
- immutable input hashes and truthful status labels;
- archived full-field standings, including lineup strings, ownership, score, rank, and duplicates;
- contest-shape and field-size classification;
- pre-lock ownership prediction followed by post-slate grading;
- a candidate-bank/entry-allocation separation;
- deterministic failure diagnostics and final-byte validation;
- an explicit rule that ungraded priors must not masquerade as probabilities.

Those are difficult operational foundations. They are not yet a quantitative edge engine, but they make one possible.

### 1.2 Current decision surfaces

| Surface | Current implementation | What it actually measures | Missing decision quantity |
|---|---|---|---|
| Classic candidate score | `mlb_engine/optimize/optimizer_v3.py:3432-3568` | Ceiling/floor proxy, stack bonus, batting-order cluster, salary-band uniqueness, meta-lineup overlap, cumulative structural ownership | Probability of top-1%, expected prize share, calibrated duplication, marginal scenario coverage |
| Ownership prior | `mlb_engine/field/ownership_prior.py:1-52` | A Classic structural rank prior; first grade showed useful ordering but unusable magnitude | Contest- and role-calibrated player share, stack share, exact-lineup likelihood |
| Ownership constraints | `mlb_engine/optimize/optimizer_v3.py:889-918` | Optional cumulative-ownership cap and low-owned-hitter floor | No production caller; constraints are blunt even after activation |
| Portfolio frontier | `mlb_engine/pipeline/execution_pipeline.py:1752-1952` | Ceiling sums and a counterfactual that zeroes hitters from one game | Probability distribution, prize outcomes, joint contest settlement, true washout probability |
| QA panel | `tools/qa_portfolio.py:1-43` | Honest review-only diagnostics | Automatic selection or calibrated decision rule |
| Showdown projections | `mlb_engine/optimize/showdown.py:1-16` | DK APPG when no richer projection is supplied | Player event distribution, plate appearances/batters faced, game-state dependence |
| Showdown diversification | `mlb_engine/optimize/showdown.py:34-76` | Flat 25% Captain cap, 50% person cap, maximum four shared players | Script-conditioned optimal exposure and marginal portfolio coverage |
| Showdown scripts | `mlb_engine/optimize/showdown_theses.py:223-277` | Hand-authored templates with fixed weights | Graded probabilities, uncertainty, and outcome-generated scripts |

The current code is commendably explicit about these limitations. The problem is not false labeling inside these modules; it is that the operational selection process still has no calibrated replacement.

### 1.3 Assessment of the newly filed R251–R262 roadmap

The roadmap is directionally strong but should not be implemented literally.

| Item | Decision | Required correction |
|---|---|---|
| R251 input freeze | **Keep and make first** | Store every snapshot with both `observed_at` and `valid_for`, content hash, source, schema version, and availability status. Preserve salary-post, first-market, lineup-confirmation, and final-lock states rather than only “morning” and “build.” |
| R252 one mispricing score | **Replace the scalar with a vector** | Preserve salary edge, field edge, duplication edge, model uncertainty, and marginal portfolio coverage separately. A single number hides whether the edge comes from performance or merely low attention. |
| R253 park × hand/profile | **Keep, but change the model** | Do not create a noisy “xwOBA in this park” split. Transform the batter's shrunk exit-velocity/launch-angle/spray profile through the venue and expected weather, then compare it with a neutral venue. |
| R254 Captain screen | **Major revision** | Compare simulated Captain optimality share with projected Captain share. Multiplying a generic skill score by low Captain ownership is not enough. |
| R255 BUY/FADE grading | **Major revision** | Mean realized FPTS by a selected bucket is confounded and tail-blind. Grade complete distributions and incremental tail skill versus salary/market baselines on rolling-origin holdouts. |
| R256 arsenal-vs-profile | **Keep its gate** | Use hierarchical shrinkage and synthetic comparable matchups, never raw BvP or unshrunk pitch-type splits. Promote only if it explains held-out residual tail error. |
| R257 kill matrix | **Keep as a diagnostic** | Team-cold, pitcher-blowup, and Showdown-script rows are useful failure-domain tests, but must remain clearly separate from estimated probability. |
| R258 scalar threshold model | **Correct before implementation** | A threshold forecast must be a conditional distribution sampled with the same game scenario as our score. An independently predicted p99 point breaks the score/threshold dependence. |
| R259 marginal distributions | **Keep, deepen** | Model opportunities first—lineup slot, plate appearances, starter batters faced, bullpen role—then scoring events. Bucketed FPTS alone is an interim baseline. |
| R260 correlation table | **Use only as an interim model** | Add hierarchical shrinkage, game/team factors, pitcher-versus-opponent negative dependence, batting-order distance, and bootstrap uncertainty. The endpoint should be event-driven simulation. |
| R261 own-outcome bank | **Keep with stricter separation** | Use DESIGN, SELECT, and REFEREE banks; shared slate scenarios across every contest; weighted rare-event sampling; model ensembles; and a jointly sampled threshold. |
| R262 weighted coverage MILP | **Replace the weighted sum** | Build a Pareto frontier or epsilon-constrained/lexicographic solve. Arbitrary top-versus-floor weights conceal the exact tradeoff the user wants to control. |

---

## 2. Intelligent leverage from first principles

### 2.1 Four quantities that must not be conflated

Let `I_t` be all information legitimately available at decision time `t`, `Y_p` the player's DraftKings score, `r` the roster role, and `c` the contest.

#### Salary edge

The salary file implies a baseline outcome distribution conditional on format, position/role, slate size, and salary:

\[
F^{salary}_{p}(y)=P(Y_p \le y \mid salary_p, role_p, format, slate\ context)
\]

The model produces `F_model`. Salary edge is the incremental change relative to that baseline, reported at more than the mean:

\[
\Delta^{mean}_p=E_{model}[Y_p]-E_{salary}[Y_p]
\]

\[
\Delta^{tail}_{p,q}=P_{model}(Y_p \ge q)-P_{salary}(Y_p \ge q)
\]

The tail threshold `q` should be salary/role-conditioned or slate-conditioned, not a universal FPTS number.

#### Field edge

In each simulated slate outcome, solve the legal top lineup or top `M` near-optimal lineups. Define `q_{p,r}` as the weighted share of scenarios in which player `p` is required in role `r` by at least one of those lineups. Let `o_{p,r,c}` be projected field usage in that same role and contest.

\[
L^{field}_{p,r,c}=\operatorname{logit}(\tilde q_{p,r})-
                  \operatorname{logit}(\tilde o_{p,r,c})
\]

Both probabilities are shrunk away from 0 and 1. This produces a comparable scale and makes Showdown Captain leverage structurally different from Utility leverage.

#### Combination edge

For legal lineup `l`, estimate joint field probability `f_{l,c}` from a lineup-construction model—not the product of player ownership. Then:

\[
E[D_{l,c}] \approx (N_c-n^{ours}_c) f_{l,c}
\]

where `D` is the number of opposing copies. A lineup can contain popular players and remain structurally unusual; it can also contain two low-owned players yet duplicate because the salary/stack construction is obvious.

#### Marginal portfolio edge

Given already selected portfolio `P`, lineup `l` adds:

\[
\Delta A(l\mid P)=\sum_s w_s\,
  1\{l\text{ clears the large-prize line in }s\}\,
  1\{P\text{ does not}\}
\]

This is the best operational meaning of “different”: it covers valuable outcomes not already covered. Player exposure and lineup overlap are guardrails, not substitutes for this quantity.

### 2.2 A player is not intelligent leverage unless both markets are considered

Use this decision matrix:

| Performance versus salary | Field reaction | Classification | Action |
|---|---|---|---|
| Positive | Field has not reacted | **Intelligent leverage** | Generate scenario-conditioned candidates; allow optimizer to choose by marginal coverage |
| Positive | Field has fully reacted | Good value, little leverage | Use when needed for raw tail probability; seek uniqueness elsewhere |
| Neutral/negative | Field is low | Unpopular, not leverage | Do not force exposure |
| Negative | Field remains high | Fade candidate | Prefer alternatives when the portfolio retains required scripts |

This prevents the common error of rewarding low ownership regardless of performance.

### 2.3 Correct treatment of the xwOBA/park example

MLB defines xwOBA from exit velocity, launch angle, Sprint Speed on some batted balls, and actual walks/strikeouts. It is an expected-results metric for comparable batted balls; it is not, by itself, a causal forecast that a hitter's xwOBA will improve in one park. [MLB Statcast glossary](https://www.mlb.com/glossary/statcast)

Statcast park factors measure observed venue effects, normalized to 100, by comparing the same players across parks while controlling for handedness. They are useful, but an aggregate park factor is still not a batter-specific counterfactual. [Statcast Park Factors](https://baseballsavant.mlb.com/leaderboard/statcast-park-factors?category=5842)

The correct chain is:

1. Estimate a shrunk **batter contact distribution**: strikeout, walk, contact, exit velocity, launch angle, spray/attack direction, barrels/blasts, and running value.
2. Estimate the opposing starter's **contact and miss distribution**: pitch mix, location, velocity, movement, release, handedness, whiff/contact allowed, expected batters faced, and times-through-order risk.
3. Blend batter and pitcher with hierarchical partial pooling. Direct batter-versus-pitcher history is allowed only as tiny incremental evidence after shrinkage. The SEAM research starts from the same problem: individual matchup samples are too small and require synthetic comparable batters and pitchers. [SEAM methodology](https://arxiv.org/abs/2005.07742)
4. Route each simulated batted ball through a **venue transform** based on handedness, launch direction, fence geometry/observed park effects, roof state, air density, wind, and temperature.
5. Convert the resulting plate-appearance events into DraftKings points.
6. Compare the new distribution with both the salary baseline and the field's projected reaction.

The player-specific park contribution should be reported as a counterfactual:

\[
\Delta HR^{park}_p=
P(HR\mid profile_p, opponent, venue_{tonight}, weather)-
P(HR\mid profile_p, opponent, neutral\ venue)
\]

Also report the change in the full score tail, because a park can alter doubles/triples and run/RBI context without producing the same home-run effect.

#### Avoid double counting

Sportsbook team totals already encode much of the public run environment. The model should decompose information in this order:

- market total/spread anchors team-level scoring mean;
- player and lineup roles allocate opportunities within the team;
- park/contact/arsenal features alter player allocation and tail shape;
- only validated residual skill beyond the market anchor earns additional weight.

If the park term simply adds to a projection already moved by the team total, it can count the same information twice and create fake edge.

### 2.4 High-value signal families

All signal families begin as registered hypotheses. None enters production selection until its incremental held-out benefit is demonstrated.

| Priority | Signal | Mechanism | Especially valuable in | Main failure mode |
|---|---|---|---|---|
| 0 | Confirmed lineup and batting-order promotion | More expected plate appearances; stale salary/APPG | Both; Showdown lower salaries | Late or conflicting lineup evidence |
| 0 | Starter role, leash, opener/bulk designation | Changes batters-faced and win/quality-start tails | Showdown | Treating “probable” as confirmed |
| 0 | Market movement since salary release | New public information not in salary | Both | No timestamped salary-era market snapshot |
| 0 | Park × hand × contact geometry | Converts pull/air-contact profile into venue-specific power tail | Showdown | Small park splits and double-counted totals |
| 0 | Bullpen availability/fatigue and handed composition | Changes late-PA quality and correlated stack tail | Showdown | Uncertain reliever availability |
| 1 | Batter profile × pitcher arsenal | Contact/whiff quality against tonight's pitch mix | Showdown | Unshrunk pitch-type splits |
| 1 | Stolen-base opportunity | Runner speed/tendency × pitcher/catcher control | Showdown punts and lower-order speed | Opportunity depends on reaching base/game state |
| 1 | Bat-tracking change | Bat speed, squared-up rate, attack direction may lead results | Both | New metric drift and small recent samples |
| 1 | Plate-appearance distribution | Batting order, home/away ninth inning, pinch-hit risk, weather interruption | Showdown | Using a fixed PA count |
| 1 | Starter degradation and times-through-order | Fatigue changes opposing stack tail | Both | Recency/noise and managerial behavior |
| 2 | Defense/outfield conversion | Changes hit/XBH outcomes conditional on contact | Large slates | Small DFS effect after market anchor |
| 2 | Confirmed umpire effects | K/BB/contact environment | Pitcher-heavy Showdown | Assignment timing and unstable effects |
| 2 | Public-attention residual | Name value, recency, nationally visible narratives | Showdown | Easy to overfit and difficult to source cleanly |

Statcast exposes pitch-type outcome tables, including xwOBA, whiff rate, hard-hit rate, and usage, and defines run value at the pitch level. Those fields support a shrunk arsenal model but do not license direct use of raw leaderboard splits. [Statcast Pitch Arsenal Stats](https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?type=pitcher)

Statcast also exposes swing-path, attack-direction, pitch movement, and release variables in its CSV contract. [Statcast CSV documentation](https://baseballsavant.mlb.com/csv-docs)

For speed leverage, the opportunity must include both sides of the matchup. Statcast's basestealing model conditions opportunities on the pitcher and catcher, while its pop-time definition explicitly notes runner speed and pitcher delivery as contributors. [Statcast Basestealing Run Value](https://baseballsavant.mlb.com/leaderboard/basestealing-run-value?game_type=Regular), [MLB Pop Time glossary](https://www.mlb.com/glossary/statcast/pop-time)

### 2.5 The signal factory

Every proposed signal should pass through the same automated lifecycle.

#### REGISTER

Create a machine-readable hypothesis before inspecting its target-period results:

```yaml
signal_id: park_contact_hr_v1
decision_time: final_prelock
population: mlb_hitters
formats: [classic, showdown]
features:
  - batter_ev_la_spray_shrunk
  - opponent_contact_profile
  - park_hand_factor_3y
  - roof_weather_state
baseline: salary_market_distribution_v1
primary_metric: incremental_tail_log_score
secondary_metrics: [crps, top_lineup_inclusion_brier]
minimum_evidence: power_and_ci_rule
multiple_testing_family: batter_tail_signals_2026
```

#### SNAPSHOT

Persist exactly what was knowable at the declared decision time. Each observation requires:

- `source` and rights/collection method;
- `observed_at_utc`;
- `valid_for_utc` or game identifier;
- `effective_from`/`effective_to` if the source changes;
- raw-byte SHA-256;
- normalized schema version;
- identity join status;
- `PASS`, `UNKNOWN`, `STALE`, or `CONFLICTED` state.

For retrospective work, query date-bounded season-to-date data. Never join a June slate to a mutable August season aggregate.

#### FIT

Use rolling-origin training. All examples in a validation period must occur after the training period. Hierarchical partial pooling should borrow strength across players, handedness, parks, pitch classes, and roles while retaining uncertainty for sparse cells.

Start simple:

1. salary/role baseline distribution;
2. market and lineup opportunity model;
3. park/hand/contact model;
4. arsenal model only if residuals justify it;
5. higher-dimensional bat-tracking interactions only after the lower layers grade.

#### PREDICT

Persist the entire predictive distribution or a reproducible parameterization—not just a point projection. Each output carries model version, snapshot hashes, training cutoff, uncertainty, and abstention reason.

#### GRADE

Use metrics matched to the claim:

- mean/median: MAE or pinball loss;
- full player distribution: CRPS, PIT/rank histograms, interval coverage;
- exceedance probabilities: Brier and log score;
- top-performing-player discovery: precision/recall and NDCG at a predeclared tail cutoff;
- scenario-optimal role share: Brier/reliability by predicted band;
- ownership: MAE, signed error, rank correlation, and calibration by share band;
- exact-lineup duplication: predicted versus observed copy-count distribution;
- portfolio outcomes: prospective top-1%, positive-payout, near-washout, and exact-net settlement calibration.

Proper scoring rules reward honest predictive distributions and jointly evaluate calibration and sharpness; they are a stronger gate than checking whether a BUY bucket happened to score more points. [Gneiting and Raftery, *Strictly Proper Scoring Rules, Prediction, and Estimation*](https://doi.org/10.1198/016214506000001437)

#### PROMOTE OR RETIRE

Promotion requires all of the following:

- incremental improvement versus salary-only and salary-plus-market baselines;
- prospective rolling-origin holdout results;
- a confidence interval or predeclared power rule, not an improvised slate count;
- no material degradation in tail calibration;
- stability across the format/role cells in which it will be enabled;
- an ablation showing the result is not duplicate information already present in market totals or lineup position;
- independent referee-bank decision improvement after transaction costs/duplication are included.

A signal that does not graduate should be retired or remain research-only. Do not accumulate dozens of weak factors inside one projection multiplier.

---

## 3. Showdown should be a separate quantitative product

### 3.1 Why Showdown is different

Showdown has one shared real game, extreme player-score dependence, role-specific salary and ownership, a 1.5x Captain score, and a much higher chance of exact lineup duplication. The same player outcome must drive both the Captain and Utility rows; only role salary, score multiplier, and field share differ.

Consequences:

- all entries live or die on a small number of game scripts;
- Captain selection dominates top-tail geometry;
- a cheap lineup-enabling player can create more ownership than his standalone projection warrants;
- fixed person/captain caps may delete the best portfolio when one script is genuinely dominant;
- “different players” can still represent the same game bet;
- uniqueness must be estimated at the complete-lineup level.

### 3.2 Replace fixed thesis weights with a scenario lattice

The current weights at `showdown_theses.py:273-277`—0.26, 0.22, 0.24, 0.16, 0.12 for each side's templates—are useful labels, not estimated probabilities. Retain the labels for human-readable attribution, but generate their probability from the game model.

Each scenario should include at least:

- favorite/underdog result;
- close/blowout margin;
- low/normal/high total runs;
- starter quality and exit inning/batters faced;
- bullpen quality/availability realization;
- each team's lineup-turnover count;
- home ninth-inning opportunity;
- extra innings;
- run-scoring topology: concentrated home runs, distributed singles, steals, pitcher dominance;
- weather delay/short-start state when materially possible.

Use stratified sampling so low-frequency but contest-winning scripts receive enough DESIGN scenarios. Retain likelihood weights so estimates remain unbiased.

### 3.3 Captain optimality, not Captain value

For every scenario:

1. score all players once;
2. apply 1.5x only when a player is placed at Captain;
3. solve the legal optimal and top-`M` near-optimal Showdown lineups;
4. record Captain and Utility inclusion shares;
5. compare those shares with projected field role shares.

Recommended Captain diagnostic:

\[
CaptainEdge_{p,c}=\operatorname{logit}(q^{optimal}_{p,CPT})-
                  \operatorname{logit}(o^{field}_{p,CPT,c})
\]

Also report:

- `captain_optimal_share`;
- `captain_field_share`;
- `captain_edge_logit`;
- `captain_top1_contribution`;
- `captain_expected_duplicates_when_top`;
- `captain_model_uncertainty`;
- scripts in which Captain use is optimal;
- marginal scripts added to the selected portfolio.

A 2%-owned Captain is not leverage if he almost never captains a top-performing legal lineup. A 20%-owned Captain can be leverage if he is optimal in 35% of calibrated scenarios and the resulting lineups are not duplicated.

### 3.4 Candidate generation for Showdown

Do not produce a bank by repeatedly perturbing one mean-optimal solution. Generate columns from the scenario space:

- optimal and top-`M` lineups per stratified game scenario;
- lineups within `epsilon` points of scenario optimum but materially more unique;
- one or more lineups per Captain/script cell;
- candidates conditioned on starter failure, team shutout, bottom-order production, steal events, and late bullpen scoring;
- duplication-resistant variants that preserve the same high-value script;
- fallback candidates for uncertain lineup/role states, activated automatically only if that state becomes valid.

For each candidate, retain its exact scenario-hit bitmap. Portfolio selection can then value the outcomes it adds rather than the surface-level player difference.

### 3.5 Showdown field model

Model these separately by contest archetype and field-size band:

- Captain share;
- Utility inclusion share;
- team split (5-1, 4-2, 3-3);
- salary-left distribution;
- starter/both-starter inclusion;
- lineup-order and cheap-player behavior;
- Captain-Utility conditional pairs;
- exact-lineup duplication;
- entrant segment if supported by evidence: single-entry behavior versus MME construction.

The current Classic ownership budget cannot be repurposed for Showdown rows. Showdown salary files duplicate persons across role-specific IDs and the field's Captain and Utility budgets are different objects.

---

## 4. The dual objective, stated exactly

### 4.1 Contest-level large-prize probability

For contest `c` with field size `F_c`, define:

\[
K_c=\max(1,\lceil 0.01 F_c\rceil)
\]

For a package of our entries `P_c`:

\[
A_c(P_c)=P\left(\min_{l\in P_c} Rank_{l,c}\le K_c\right)
\]

This is the probability that at least one of our entries reaches the top 1% in that contest. Always report alongside it:

- per-entry probability;
- probability any entry reaches top `K_c`;
- expected count of our entries in top `K_c`;
- expected large-prize gross and net return;
- tie/duplication-adjusted prize share once the full field model exists.

For a 15-entry contest, top 1% means one entry. For a 50,000-entry contest, it means 500. The implementation must compute `K_c` from exact field size rather than using a universal p99 percentile interpolation.

### 4.2 Define “total washout” before optimizing it

The system should calculate three related events and optimize one policy-selected definition:

1. **Literal zero-return washout**

   \[
   W_0=P(\text{total gross payout}=0)
   \]

2. **Near-total capital loss**

   \[
   W_{\rho}=P(\text{total net return}\le -\rho\times\text{total fees})
   \]

3. **No meaningful contest success**

   \[
   W_{floor}=P(\text{no entry clears its contest-specific cash/ticket floor})
   \]

`W0` most literally matches “total washout.” `Wρ` is usually the better bankroll-risk metric because a token min-cash can coexist with an almost complete loss. The report should always show all three. The zero-touch policy config selects the primary constraint once; it must not be changed interactively slate by slate.

### 4.3 Why an independently predicted p99 threshold is wrong

The equality

\[
P(top\ 1\%)=P(our\ score\ge realized\ top\text{-}1\%\ threshold)
\]

is true by definition, subject to ranks/ties. But replacing the realized threshold with an independently sampled or point-predicted threshold is generally biased.

On a high-scoring slate:

- our hitters score more;
- the opponent field scores more;
- the top-1% line rises.

On a pitchers' duel Showdown:

- our pitcher-heavy lineups rise relative to other constructions;
- the absolute top threshold may fall;
- duplicate patterns change.

Those values co-move because they arise from the same player outcomes. The interim threshold engine must therefore estimate:

\[
T_{s,c}\sim P(T_c\mid X_c, Z_s)
\]

where `X_c` is pre-lock contest/slate context and `Z_s` contains features computed from the same simulated game scenario, such as perfect-lineup score, chalk-lineup score, total runs, starter outcomes, and optimal-score concentration. Our lineup score and `T_{s,c}` are then compared inside scenario `s`.

The threshold model should output a conditional distribution, not a point. Historical standings supply the realized target. This is a cost-effective bridge to top-1% probability, but it cannot estimate exact prize sharing or ROI without a field/duplication model.

### 4.4 Do not bury the tradeoff in one weighted score

The top-1% and washout objectives conflict. Concentration can improve an entry's best-case rank while making every entry fail together. A weighted sum such as:

\[
\lambda A + (1-\lambda)(1-W)
\]

has arbitrary units and can select a qualitatively different portfolio after a small, opaque change in `lambda`.

Use a Pareto/epsilon policy:

1. For each contest independently, find its best achievable contest package and record `A*_c`.
2. Define normalized apex retention:

   \[
   R_c(P)=A_c(P_c)/A^*_c
   \]

3. For a grid of `rho`, solve:

   \[
   \min_P W(P)
   \]

   subject to:

   \[
   R_c(P)\ge \rho \quad \forall c
   \]

   plus legality, entry assignment, exposure guardrails, and any bankroll policy.
4. Produce the nondominated frontier of apex retention versus washout.
5. Choose the operating point using a frozen, backtested policy—not a human mid-run judgment.
6. Within the chosen tolerances, maximize expected net return and then minimize adverse-tail loss/model fragility.

If `A*_c` is numerically zero on the REFEREE bank, do not divide by it. Expand the scenario bank; if it remains unresolved, mark that contest's probability `UNKNOWN` and block probability-based production selection for it rather than inventing a normalized score.

An alternative first stage is to maximize the minimum `R_c`, which prevents a global portfolio from sacrificing one contest to improve another.

### 4.5 Scenario-coverage MILP

Let:

- `e` index reserved entries;
- `c(e)` be entry `e`'s contest;
- `l` index legal candidates;
- `s` index common slate scenarios;
- `z[e,l]` be 1 if lineup `l` is assigned to entry `e`;
- `H_top[s,c,l]` be 1 if lineup `l` clears contest `c`'s top-1% threshold in scenario `s`;
- `H_floor[s,c,l]` be 1 if it clears the configured payout/ticket floor;
- `w_s` be the scenario likelihood weight.

Assignment:

\[
\sum_l z_{e,l}=1 \quad \forall e
\]

Introduce binary `a[s,c]` for any of our entries hitting the top threshold and `g[s]` for any entry avoiding the portfolio washout condition. Linear OR constraints connect those variables to `z` and the constant hit matrices.

For example, for every `s,c`:

\[
a_{s,c}\le \sum_{e:c(e)=c}\sum_l H^{top}_{s,c,l}z_{e,l}
\]

and for every `e,l` in contest `c`:

\[
a_{s,c}\ge H^{top}_{s,c,l}z_{e,l}
\]

The analogous pair using `H_floor` defines `g_s` across all contests. These constraints make the binary exactly equal to the logical OR, independent of objective direction.

Then:

\[
A_c=\sum_s w_s a_{s,c}
\]

\[
W_{floor}=\sum_s w_s(1-g_s)
\]

When exact payout settlement is available, use scenario/contest/lineup net returns `R[s,c,l]`, add the contest's entries jointly, and model literal/near-total washout from total portfolio return. Own entries must settle together; independently scoring each entry overstates diversification and can mishandle our own duplicate lineups.

For scalability, enumerate complete contest packages first and choose one package per contest. This turns thousands of entry-lineup variables into a smaller package-selection MILP while preserving within-contest interaction.

### 4.6 Robust optimization, not faith in one fitted model

Repeat the scenario/optimization evaluation over model ensemble `m`:

- projection parameter bootstraps;
- alternative reasonable correlation structures;
- threshold-model residual bootstraps;
- field-ownership/duplication parameter draws;
- weather and lineup uncertainty states.

The production policy should maximize lower-confidence or worst-reasonable-model apex retention subject to a worst-reasonable-model washout limit. A lineup that is optimal only under one fragile pitch-matchup estimate should lose to a slightly lower central estimate that survives the model ensemble.

Use CVaR only as a tertiary severity measure after directly controlling the washout probability. CVaR is useful because scenario losses, including discrete contest outcomes, can be optimized with linear auxiliary variables. [Rockafellar and Uryasev, *Conditional Value-at-Risk for General Loss Distributions*](https://www.sciencedirect.com/science/article/pii/S0378426602002716)

### 4.7 Contest routing is an optional outer optimization

If contest choice and entry counts are not already fixed by reservations, add an outer layer that chooses `n_c` subject to bankroll, contest capacity, max-entry rules, and desired liquidity. A lineup package should not be evaluated without the field size, payout curve, entry fee, and number of our entries it will occupy.

This outer layer can identify cases where the same lineup portfolio has a better large-prize/washout frontier in a smaller single-entry contest than in a large MME contest. Once reserved entries exist, they are not fungible: the optimizer must honor their exact contest IDs and only optimize their lineup assignments.

### 4.8 Late swap is a recourse problem

Classic late swap should re-solve the same objectives conditional on what has already happened:

\[
P(top\ K\mid observed\ scores, locked\ players, remaining\ games)
\]

and

\[
P(washout\mid observed\ portfolio\ state)
\]

Treat original lineup construction as the first-stage decision and legal swaps as recourse. Re-simulate only unresolved games, hold every locked player and observed point total fixed, update available lineup/role/weather evidence, and optimize all swappable entries jointly. Entries currently far ahead may prefer robust, lower-duplication completion paths; entries far behind may need narrower high-tail scripts. That change must emerge from conditional prize and coverage probabilities, not a hard-coded “ahead equals chalk, behind equals contrarian” rule.

The swap engine must preserve exact player IDs, start-time locks, salary, positional eligibility, and every contest assignment. Its output passes the same evidence, legality, referee, and final-byte gates as the original build.

Before lock, compute **recourse option value**: the number and quality of legal future swap states a lineup preserves after early games lock. If two portfolios have indistinguishable apex/washout estimates, prefer the one with better conditional recovery paths. This is especially valuable when late lineups, storms, or uncertain starters sit in later games.

---

## 5. Joint outcome simulation

### 5.1 Recommended modeling ladder

#### Level 0: empirical joint factors

Use this only as the first shippable probabilistic baseline:

- role/salary/lineup-slot empirical player distributions;
- team offense latent factor;
- game run-environment factor;
- same-team batting-order-distance effects;
- pitcher versus opposing-hitter negative dependence;
- pitcher win/quality-start and team-run dependence;
- hierarchical shrinkage and block-bootstrap uncertainty.

The archive's current number of dates is more important than its raw player-row count. Thousands of player rows do not create thousands of independent team/game outcomes.

#### Level 1: opportunity-plus-event model

Model:

- hitter plate appearances;
- starter batters faced/innings and exit hazard;
- relief role probability;
- PA outcomes: BB/HBP/K/ball in play;
- batted-ball outcomes conditional on batter, pitcher, venue, defense, weather;
- steals conditional on reaching base and game state;
- runs/RBIs generated from the shared sequence.

This naturally creates most of the correlations that static covariance tables attempt to approximate.

#### Level 2: field and settlement

For each scenario:

1. sample opposing legal lineups from the contest-conditioned field model;
2. score all field and own lineups on the same player outcomes;
3. rank exactly;
4. apply the actual payout/ticket structure;
5. split tied prizes according to the contest rules represented by the settlement contract;
6. record duplicates, gross, net, top-`K`, cash/ticket, and portfolio loss.

Research on DFS portfolio optimization supports optimizing the probability that at least one entry succeeds and emphasizes joint distributions/correlation, while later work explicitly models opponent behavior and expected reward in top-heavy contests. Those principles support this scenario-settlement design, but their Gaussian and historical contest assumptions should not be copied blindly into MLB. [Hunter, Vielma, and Zaman](https://arxiv.org/abs/1604.01455), [Haugh and Singal](https://pubsonline.informs.org/doi/pdf/10.1287/mnsc.2019.3528)

### 5.2 Rare-event efficiency

For a true per-entry probability near 1%, naive Monte Carlo with 100,000 independent draws has standard error:

\[
\sqrt{0.01(0.99)/100000}\approx 0.000315
\]

That is roughly 3.1% relative error before model uncertainty, candidate selection, or repeated comparisons. Tail ranking among similar lineups can remain noisy.

Use:

- stratification by team run totals and Showdown game scripts;
- importance sampling that deliberately visits high-scoring and unusual scripts;
- stored likelihood weights;
- effective sample size and Monte Carlo error on every probability;
- sequential scenario expansion when candidates are statistically indistinguishable;
- common random numbers when comparing candidates, so differences are less noisy.

Importance sampling must retain likelihood-ratio weights; oversampling home-run scripts without reweighting creates a different, optimistic model. Rare-event simulation literature exists precisely because standard Monte Carlo can be inefficient in tail regions. [Beck and Zuev, *Rare Event Simulation*](https://arxiv.org/abs/1508.05047)

### 5.3 Three immutable banks

| Bank | Purpose | May affect selection? | Reused later? |
|---|---|---:|---:|
| DESIGN | Feature/model development, scenario strata, candidate-generation rules | Indirectly, before model freeze | Never as final evidence |
| SELECT | Optimize the live portfolio after all model versions are frozen | Yes | Stored for reproducibility |
| REFEREE | Estimate the chosen portfolio and alternatives without selection reuse | No | Used for go/no-go and later prospective grade |

Different numeric seeds are insufficient if all banks share tuned outcomes. They need separate draws and, for model evaluation, separate time periods or bootstrap blocks.

---

## 6. Field behavior and duplication

### 6.1 The field model is a lineup model

Projected player ownership is necessary but not sufficient. The model must reproduce:

- roster legality;
- stack sizes and team combinations;
- pitcher pairs and pitcher-versus-batter avoidance;
- salary-left distribution;
- batting-order construction;
- value-chalk combinations;
- Captain/Utility conditional choices;
- contest-specific entry behavior;
- exact-lineup duplication counts.

Possible implementations, in increasing complexity:

1. hierarchical discrete-choice model with explicit stack and salary features;
2. sequential conditional sampler: construction shape → team stack → pitchers/Captain → remaining players;
3. energy-based model over complete legal lineups fit with negative sampling;
4. mixture model for entrant segments, if the archive supports stable segments.

The promotion gate is posterior predictive fit to observed construction distributions and duplicates—not player-ownership MAE alone.

### 6.2 Exact duplication beats ownership products

Never compute lineup probability as `Π player_ownership`. Player selections are constrained and strongly dependent. Instead estimate `P(lineup | contest, salary file, public information)` directly from the legal construction model.

Validation should include:

- player and role ownership;
- pairwise and stack conditional frequencies;
- salary left;
- team split and stack shape;
- exact lineup frequency/duplicate count;
- top-lineup duplicate count;
- calibration by predicted duplicate band.

### 6.3 Full prize-share objective

When the field model is ready, the definitive objective is not a leverage score. It is expected utility from exact settlement:

\[
E[U(P)]=\sum_s w_s\,U\left(\sum_c payout_{s,c}(P)-fees(P)\right)
\]

The requested top-1% and washout metrics remain explicit constraints/reports. Expected net return becomes a tie-breaker or a third frontier dimension. This avoids optimizing a proxy after the ingredients for the true contest outcome exist.

---

## 7. Candidate generation and selection

### 7.1 Generate from scenarios, not projection perturbations

For each DESIGN scenario or stratum:

1. solve the legal best lineup;
2. enumerate top-`M` lineups or all lineups within an `epsilon` score gap;
3. solve a uniqueness-aware variant;
4. retain scenario, script, team, Captain, and failure-domain labels;
5. deduplicate exact rosters;
6. retain only candidates that are nondominated on tail coverage, uniqueness, salary, or robustness.

This is a column-generation loop: if the current portfolio leaves a high-weight scenario uncovered, ask the lineup solver for a legal lineup that performs well specifically in that scenario.

### 7.2 Candidate metrics

Every candidate should carry:

```text
identity
  candidate_id, format, player_ids, role_ids, salary, source_scenarios

performance
  mean, median, p75, p90, p95, p99
  P(top1_threshold), P(cash_or_ticket_threshold)
  top1_monte_carlo_se, model_uncertainty_interval

field
  expected_duplicates, P(unique), lineup_field_probability
  player/stack/role ownership diagnostics

portfolio
  marginal_top1_coverage
  marginal_floor_coverage
  failure_domains_added/duplicated
  robustness_across_models

provenance
  snapshot_hashes, model_versions, scenario_bank_id, created_at
```

### 7.3 Exposure controls become safeguards

Keep hard caps only for:

- operator-declared catastrophic concentration limits;
- model uncertainty or missing information;
- illegal/conflicting roles;
- severe numerical instability;
- preventing exact duplicate assignments when not intended.

Do not use flat 25% Captain and 50% person caps as the main portfolio optimizer. A calibrated scenario solution may rationally exceed or stay far below those values. The system should report when a guardrail binds and quantify the loss in top-tail coverage caused by it.

---

## 8. Target software architecture

### 8.1 Module boundaries

```text
mlb_engine/
  contracts/
    evidence.py             # timestamp, validity, hash, status
    contest.py              # field, payout, entry and roster contracts
    prediction.py           # distribution and uncertainty contracts

  features/
    snapshot_store.py       # immutable raw and normalized snapshots
    salary_baseline.py
    opportunity.py          # PA/BF/role distributions
    park_contact.py
    arsenal_matchup.py
    running_game.py
    market_residual.py

  models/
    player_outcomes.py
    joint_game.py
    threshold.py
    field_construction.py
    showdown_roles.py

  simulate/
    scenario_bank.py
    rare_event.py
    field_sampler.py
    settlement.py

  candidates/
    scenario_columns.py
    dominance_filter.py
    metrics.py

  portfolio/
    contest_packages.py
    pareto_optimizer.py
    robustness.py

  evaluate/
    signal_grades.py
    calibration.py
    prospective_replay.py
    policy_gate.py

  pipeline/
    zero_touch_run.py
```

The existing artificial tracked-file/module cap should be removed. Architecture should be governed by cohesive ownership, typed interfaces, tests, and runtime budgets—not by a file count.

### 8.2 Core immutable contracts

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

EvidenceStatus = Literal[
    "PASS", "FAIL", "UNKNOWN", "STALE", "CONFLICTED", "NOT_APPLICABLE"
]
Role = Literal["CLASSIC_HITTER", "CLASSIC_PITCHER", "CPT", "UTIL"]

@dataclass(frozen=True)
class EvidenceRef:
    source: str
    observed_at_utc: datetime
    valid_for_utc: datetime
    sha256: str
    schema_version: str
    status: EvidenceStatus

@dataclass(frozen=True)
class PlayerDistribution:
    player_id: str
    role: Role
    scenario_scores: Sequence[float]
    scenario_weights: Sequence[float]
    model_version: str
    evidence: Sequence[EvidenceRef]

@dataclass(frozen=True)
class LeverageVector:
    player_id: str
    role: Role
    salary_mean_delta: float
    salary_tail_delta: float
    optimal_role_share: float
    projected_field_share: float
    field_edge_logit: float
    model_uncertainty: float
    component_attribution: Mapping[str, float]

@dataclass(frozen=True)
class ScenarioBankRef:
    bank_id: str
    purpose: Literal["DESIGN", "SELECT", "REFEREE"]
    seed: int
    model_versions: Mapping[str, str]
    scenario_count: int
    effective_sample_size: float
    sha256: str
```

Production code should store large scenario arrays in a columnar/binary format with a manifest rather than embedding them in JSON. The dataclasses define the semantic boundary.

### 8.3 Required persisted artifacts

| Artifact | Grain | Purpose |
|---|---|---|
| `slate_information_set` | slate × decision time | Reconstruct what was knowable |
| `player_feature_snapshot` | player × slate × decision time | Leakage-safe model input |
| `salary_baseline_prediction` | player × role × slate | Minimum benchmark |
| `player_distribution_prediction` | player × role × slate | Mean/tail/opportunity model |
| `field_prediction` | player/role/stack/lineup × contest | Ownership and duplication |
| `contest_threshold_prediction` | contest × scenario | Joint conditional threshold |
| `scenario_bank_manifest` | bank | Reproducibility and independence |
| `candidate_bank` | candidate | Legal lineup plus hit bitmap/metrics |
| `portfolio_frontier` | solution point | Apex/washout/return tradeoff |
| `portfolio_decision` | slate | Frozen selected policy point and reason |
| `exact_settlement` | entry × contest | Ground truth after slate |
| `calibration_grade` | model/signal × time window | Promotion/rollback evidence |

### 8.4 Zero-touch flow

```text
Salary + entries + contests arrive
        ↓
Freeze salary-era information set and hashes
        ↓
Resolve identities, contest rules, field sizes, payouts, roles
        ↓
Collect/refresh time-valid lineups, odds, weather, Statcast references
        ↓
Critical evidence gate
        ↓
Build opportunity, player, joint-game, threshold, and field predictions
        ↓
Generate stratified DESIGN candidates
        ↓
Score candidates on independent SELECT scenarios
        ↓
Build contest packages and Pareto frontier
        ↓
Apply frozen risk policy automatically
        ↓
Re-evaluate chosen package on REFEREE scenarios
        ↓
Legality + evidence + numerical-stability + final-byte gates
        ↓
Emit DK file, manifest, decision report, and monitor state
        ↓
At settlement: exact results, calibration, signal promotion/rollback
```

The LLM has no place in score simulation, probability calculation, lineup construction, exposure accounting, CSV generation, settlement, or gating. It can help research a new unstructured source, explain anomalies, or draft a hypothesis; deterministic code must convert any approved source into a versioned adapter before production use.

### 8.5 Failure and latency policy

The live path must have no training and no unbounded retry loops.

- Precompute slowly changing park/player reference features off the live path.
- Cache model artifacts by version and information cutoff.
- Use explicit per-source and per-solver timeouts.
- Retry only bounded, idempotent operations with jitter and a deadline earlier than the lineup lock.
- Critical missing identity, contest, salary, lineup, or roster-role evidence results in `DO_NOT_UPLOAD`.
- Optional signal failure results in a declared abstention and reversion to the last validated lower-complexity model, never a silent zero.
- If referee results materially contradict selection estimates beyond a predeclared Monte Carlo tolerance, reject the portfolio or fall back to the validated baseline policy.
- Every fallback is recorded in the manifest and graded later.

### 8.6 Computational design

The probabilistic engine does not require slow per-lineup Python simulation.

- Store player scores as a weighted `scenario × player` NumPy array.
- Store Classic lineup membership as a sparse `lineup × player` incidence matrix; calculate all lineup scores with matrix multiplication.
- Store Showdown Captain and Utility incidence separately so the same underlying player outcome is used once and the 1.5x multiplier is applied exactly once.
- Bit-pack top/floor scenario-hit vectors; marginal coverage becomes fast bit operations and weighted reductions.
- Cache scenario banks, predictions, and candidate matrices by complete input/model hash.
- Use column generation to avoid enumerating the full legal-lineup universe.
- Give every solver an explicit wall-clock limit, relative MIP-gap target, deterministic tie-break, and incumbent-validation path.
- Keep the optimizer's sparse matrix construction deterministic; do not build dense scenario-by-candidate constraint matrices when a package or coverage-column representation is available.
- Expand the scenario bank adaptively only when Monte Carlo uncertainty can change the decision.

The result should make the expensive work batch-oriented and local. Network calls collect evidence before the deadline; live selection consumes frozen arrays and model artifacts.

---

## 9. Evaluation and promotion gates

### 9.1 Model gates

| Layer | Required prospective evidence |
|---|---|
| Opportunity | PA/BF interval coverage and proper score beat simple role averages |
| Player distribution | CRPS/log score beat salary and existing projection baselines; calibrated tail exceedances |
| Joint outcomes | Held-out team/game totals, stack co-hit rates, pitcher/opponent dependence, multivariate rank/variogram diagnostics |
| Threshold | Conditional quantile coverage and pinball/log score beat archetype median and environment-only baselines |
| Field | Role ownership, construction marginals, pair/stack frequencies, salary-left, duplicate-count calibration |
| Portfolio | Prospective top-1%, washout, and payout predictions calibrated; SELECT-versus-REFEREE optimizer regret within tolerance |

Do not set acceptance thresholds after seeing the result. Predeclare a statistical power/confidence rule appropriate to the available slate count. Report uncertainty when the sample cannot distinguish models.

### 9.2 Decision-policy backtest

Replay each historical slate as it would have been known at lock:

1. train only on earlier slates;
2. load the historical information set;
3. generate candidates and the frontier without future data;
4. select the operating point with the frozen policy;
5. settle against the actual contest;
6. compare with named baselines using paired slate blocks.

Required baselines:

- current production heuristic;
- maximum mean/ceiling lineup bank;
- ownership-cap heuristic;
- scenario optimizer without intelligent-leverage features;
- scenario optimizer with each signal family added separately;
- oracle diagnostic using realized outcomes, labeled unreachable, to measure remaining headroom.

Primary evaluation metrics:

- per-contest `P(any top K)` prediction and realization;
- portfolio literal and near-total washout prediction and realization;
- expected and realized net return with confidence intervals;
- large-prize frequency and prize share;
- maximum drawdown and loss-tail severity;
- model/selection regret;
- incremental value of each signal family;
- runtime, memory, and failure rate.

The archive must be split by slate date, not by player row or contest row, because all players and contests on one slate share the same underlying outcomes.

### 9.3 Anti-overfitting controls

- register signal hypotheses and primary metrics;
- control the false-discovery family or reserve untouched confirmation periods;
- use hierarchical shrinkage for sparse interactions;
- tune only on DESIGN periods/banks;
- keep REFEREE outcomes untouched until the decision is frozen;
- report all attempted signals, including failures;
- require an ablation and a simpler baseline;
- decay or retire features when their prospective skill deteriorates;
- never promote based on one memorable Showdown result.

---

## 10. Implementation sequence

### Phase 0 — Preserve future evidence immediately

Deliver first because missed snapshots cannot be recreated perfectly.

- implement R251's salary-post/pre-lock snapshot chain;
- add bitemporal timestamps and content hashes;
- freeze current expected-stat, odds, lineup, weather/roof, contest, and salary inputs;
- record a complete model/input manifest on every build;
- create leakage-safe historical reconstruction tooling.

**Production selection change:** none.

### Phase 1 — Salary baseline and signal grading

- fit role/format/slate-conditioned salary baseline distributions;
- create `LeverageVector`, retaining components rather than one score;
- implement market/lineup/park-hand features first;
- replace R255's bucket-mean grade with proper distributional and tail metrics;
- ship reports only.

**Production selection change:** none.

### Phase 2 — Conditional threshold bridge

- mine exact rank, top-`K`, cash/ticket, tie, and duplicate thresholds from archived standings;
- fit conditional threshold distributions by format, archetype, field size, and scenario-derived slate state;
- prove that the joint conditional model beats both a historical-median threshold and an independently sampled threshold;
- grade prospectively.

**Production selection change:** none.

### Phase 3 — Joint outcomes and scenario candidates

- implement empirical hierarchical joint factors;
- add opportunity distributions;
- create weighted DESIGN/SELECT/REFEREE scenario banks;
- generate scenario-optimal candidate columns;
- implement Showdown role-optimality and script coverage;
- report candidate and current-portfolio top/floor coverage in shadow mode.

**Production selection change:** none.

### Phase 4 — Pareto portfolio optimizer in shadow

- build contest packages and the epsilon-constrained frontier;
- report per-contest apex retention, all washout definitions, and binding constraints;
- compare chosen current portfolio with the shadow frontier on REFEREE scenarios;
- measure the opportunity cost of flat exposure caps.

**Production selection change:** none until the prospective gate passes and the operating policy is approved once.

### Phase 5 — Field model and exact settlement

- fit role ownership and construction distributions;
- sample legal opposing fields;
- calibrate exact duplication;
- add exact payout, tie, and ticket settlement;
- replace threshold-only expected-return approximations with exact scenario settlement;
- run controlled historical and low-stakes prospective evaluation.

### Phase 6 — Controlled production promotion

Promote by layer, with automatic rollback:

1. scenario-driven candidate generation;
2. Showdown Captain/Utility role model;
3. Pareto selection under the approved risk policy;
4. exact field/payout objective;
5. advanced arsenal, bat-tracking, running, or defense signals only after their own gates pass.

---

## 11. Concrete changes to the current process

### Stop doing

- calling a low-owned player leverage without measuring his scenario-optimal role share;
- using raw xwOBA-minus-wOBA or raw BvP as matchup truth;
- summing projected ownership as a complete duplication model;
- generating most candidates around one point projection;
- treating maximum overlap or exposure caps as portfolio optimization;
- treating a game-zero ceiling test as washout probability;
- using fixed Showdown thesis weights as probabilities;
- grading a skill signal only by average realized FPTS of BUY/FADE buckets;
- sampling a predicted contest threshold independently of player outcomes;
- combining apex and washout with an arbitrary weighted score;
- fitting or tuning anything in the live pre-lock path.

### Start doing

- snapshot every decision-time information set;
- model opportunities and full outcome distributions;
- calculate salary, field, combination, and marginal portfolio edge separately;
- generate candidates from stratified scenarios;
- measure Captain and Utility optimality separately;
- sample contest thresholds jointly with the same slate outcome;
- optimize contest packages over a Pareto frontier;
- report literal washout, near-total loss, and no-floor-hit probabilities;
- use common scenarios across all contests on the slate;
- use DESIGN/SELECT/REFEREE separation and model uncertainty;
- settle ranks, ties, duplicates, and payouts exactly;
- promote only prospective, incremental, calibrated improvements.

---

## 12. Recommended first build tickets

These are deliberately smaller and better ordered than implementing R251–R262 verbatim.

1. **Information-set manifest v2**  
   Freeze salary-post, lineup-confirmation, and final-lock snapshots with bitemporal metadata and hashes.

2. **Salary-distribution baseline**  
   Produce empirical/parametric FPTS distributions by Classic hitter, Classic pitcher, and Showdown person at Utility; derive Captain scores from the same person outcome with the exact Captain salary and 1.5x rule—conditioned on salary, slate size, batting slot/role, and market environment.

3. **Prospective distribution grader**  
   CRPS, PIT, interval coverage, tail Brier/log score, rolling-origin split, paired baseline comparison.

4. **Park-contact counterfactual v1**  
   Three-year shrunk park × hand factor plus batter EV/LA/spray bins, neutral-versus-tonight delta, no raw park xwOBA split.

5. **Conditional threshold miner and baseline**  
   Exact `K`, ranks, ties, top/floor/ticket thresholds; historical-median and environment-only baselines.

6. **Joint threshold proof**  
   Demonstrate on held-out slates that threshold residuals depend on realized/simulated optimal-score and run-state features; implement `T[s,c]` rather than one `T[c]`.

7. **Empirical joint scenario bank v1**  
   Team/game/pitcher factors with shrinkage, weights, uncertainty, and three bank purposes.

8. **Scenario column generator**  
   Top-`M` legal candidates per scenario plus dominance filtering and hit bitmaps.

9. **Showdown Captain optimality report**  
   Captain/Utility optimal shares, projected role shares, edge, duplicates, scripts, and marginal coverage.

10. **Pareto optimizer in shadow**  
    Per-contest `A*_c`, normalized apex retention, three washout measures, binding guardrails, independent referee evaluation.

11. **Field-construction model v1**  
    Contest-conditioned legal lineup sampler graded on roles, stacks, salary, pairs, and exact duplicates.

12. **Exact settlement and policy replay**  
    Payout/tie/ticket logic, prospective archive replay, promotion/rollback gate.

---

## 13. What success looks like

The engine is ready to claim intelligent leverage only when it can show, before lock and from immutable inputs:

- why a player's distribution moved relative to the salary baseline;
- whether the field moved by the same amount;
- the scenarios and roster role in which the player matters;
- the uncertainty in that assessment;
- the duplication implication of the complete lineup;
- the new top-tail outcomes a candidate adds to the current portfolio;
- prospective evidence that this signal improves calibrated tail forecasts.

The portfolio engine is ready to claim the dual objective only when it can show:

- exact per-contest `P(any top K)` for the selected package, with Monte Carlo and model uncertainty;
- the standalone best achievable value and retained fraction for every contest;
- literal washout, near-total loss, and no-floor-hit probabilities across the whole slate;
- the nondominated frontier and the frozen policy used to choose one point;
- exact, joint settlement of all own entries;
- independent REFEREE-bank confirmation;
- prospective calibration and policy results against the current heuristic.

Until those conditions hold, the existing ceiling, field-pressure, kill-matrix, and thesis outputs remain useful diagnostics and should retain their current truthful labels. They should not be described as EV, top-1% probability, washout probability, or portfolio-optimal.

The core strategic change is simple even though the implementation is substantial:

> Build lineups to own mispriced outcomes, not merely mispriced players; then choose the portfolio that covers the most valuable distinct outcomes while preserving an explicit, measured floor on each contest's large-prize probability.
