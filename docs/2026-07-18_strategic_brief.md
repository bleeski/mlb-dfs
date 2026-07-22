# Strategic Brief: The Evidence-Bound Engine

Date: 2026-07-18
Author: review pass over engine v2.26.0 / layout v3.0.0-pre
Status: proposal for discussion, not approved, changes no bytes in the tracked engine
Predecessor: the 2026-07-04 waterfall brief (approved; lives in `posture_allocator.py`)

---

## 0. The thesis in one paragraph

This project does not need a greenfield rebuild. It needs to cross one
threshold. The binding constraint on winning more is not optimizer
sophistication, lineup count, or compute. It is graded evidence. Almost every
capability the mandate asks for already exists in scaffolded, review-only form
(`posture_allocator`, `ownership_prior`, `field_miner`, `tail_candidate_scanner`,
the parked `slate_sim`), and every one of them is inert or uncalibrated for the
same reason: the archive holds roughly one to two conditioned slates, and the
gate to turn them on is eight to fifteen. The macro strategy is therefore to
industrialize the evidence loop until the gate opens, promote the three
companions from reports into wired components as their evidence lands, and add
exactly one genuinely new capability, an adversarial pre-lock research loop,
in the one architectural slot that is built to accept it: outside the certified
core. Everything else in this brief serves that spine.

---

## 1. A correction I have to make before anything else

The mandate is written in the vocabulary the project forbids: "more winning
lineups," "maximize our probability of taking down prizes," "success rates and
total winnings," "true mathematical upside." I am not raising this to be
pedantic about house style. I am raising it because the truthful-labels rule is
not house style. It is the load-bearing wall of the whole design, and the reason
half the codebase is deliberately parked.

The system cannot optimize for win rate because it cannot yet measure win rate.
With one to two archived slates there is no way to grade whether any change made
you win more. `slate_sim.py`, `calibration_engine.py`, and
`contest_results_tracker.py` are parked precisely because at this volume they
"add no signal" and would manufacture false confidence. If I hand you a brief
that promises more winning lineups, I have handed you the exact failure the
ledger was built to prevent: overfitting to the last result and dressing a proxy
as a probability.

So I am going to restate the mandate in terms the engine can actually pursue,
and then pursue them hard:

- Not "win more," but "reduce the two known leaks, and make the system
  falsifiable faster so a real win-rate claim becomes possible at all."
- Not "maximize probability of a top prize," but "maximize decorrelated ceiling
  exposure per unit of expected duplication, under labeled priors, graded every
  slate."
- Not "protect capital with a floor," but "buy breadth in fee allocation, where
  the only real floor lives, and stop pretending a lineup-level floor exists in
  top-heavy contests."

That last one is not my invention. It is already written into
`posture_allocator.py`, verbatim, and the mandate's Puzzle 1 contradicts it. I
side with the module. More on this in Section 4.

This is the one place I am going to push back hard and then move on. The rest of
the brief takes the ambition of the mandate completely seriously. I just refuse
to relabel proxies as probabilities to do it, because that trade loses money the
moment the sample is large enough to notice.

---

## 2. What is actually true about the system today

A first-principles review has to start from an honest map, or the "burn it down"
instinct torches the wrong things. Here is the state, without flattery.

**The spine is excellent and should never be touched by this effort.** The
certification chain (immutable run provenance, re-read-the-exact-export
reconciliation, the three-gate upload-ready contract, fail-closed late swap) is
the reason you stopped missing locks and stopped uploading broken files. It is
the most valuable asset in the repository and it is invisible to the mandate
because it does not generate lineups, it prevents disasters. Any macro strategy
that adds an autonomous agent has to route around this wall, never through it.

**The "empty portfolio" problem the mandate names is already mostly solved.** Two
releases closed it. v2.25.0's `build_diverse_candidate_bank` fixed the thin-slate
collapse where overlap-repulsion halted on the first infeasible lineup and the
bank clustered on two SP pairs. v2.26.0's pool contract plus slate clock fixed
the missed-lock and full-CSV-waste incidents. The residual is not emptiness. It
is that the portfolio is not yet shaped by an explicit tier policy at build time.
That residual is the waterfall, and it is Section 4.

**The projection stack is mature and correctly humble.** `Base x F1..F5` with the
xwOBA base correction, xISO and K-rate ceiling multipliers, deterministic F4, the
value-sanity guard. The engineering here is careful (the v2.23.0 xwOBA no-op bug
and its wiring-test class is a model of how to catch silent failures). The honest
gaps are stated in the backlog: F3 skill is still 1.0, pitcher F4 is still 1.0,
and every multiplier is a labeled prior, not a fitted value.

**Three capabilities the mandate asks for already exist as review-only
companions, all gated on the same missing evidence.** The waterfall
(`posture_allocator`, F/A/V tiers). The anti-chalk model (`ownership_prior`
predict-then-grade, plus `field_miner` duplication and the opponent registry).
The correlation engine that actually powers "ceiling" (`slate_sim`, parked). None
of them drives a build. All of them are waiting on the archive.

**The optimizer is deterministic MILP, and there is no LLM anywhere in the
certified build path.** This matters enormously for Puzzle 2, and I will return
to it, because it means the "AI chalk trap" is mostly a misdiagnosis of where the
chalk risk actually sits.

The one-sentence version: you have built a superb certification spine and a
mature projection stack, wrapped around a portfolio brain whose three most
important lobes are switched off waiting for data.

---

## 3. The reframed efficiency paradox (Puzzle 4 first, because it reorders everything)

The mandate calls it a paradox: cut generation time while raising accuracy. It is
only a paradox if you try to buy accuracy inside the T-5 window. You cannot, and
you should stop trying.

Separate the two compute budgets that the architecture already implies but never
names:

**The hot path (inside the slate clock).** Intake, bank construction, the joint
MILP, certification. This must be fast and deterministic and it is already nearly
optimal. The MILP is cheap. The candidate bank is the real cost, and it is
correctly sized to unique demand, not raw entries. The only accuracy that belongs
here is accuracy that is already compiled into priors and constants.

**The cold path (between slates, offline, no deadline).** Archival, ownership
grading, correlation fitting, venue residuals, opponent modeling. This is where
accuracy is actually manufactured. It has no time budget and it never touches a
certified export.

The resolution of the paradox: accuracy is a cold-path product, cached into the
hot path as labeled priors. You raise accuracy by making the cold loop turn
faster and more often, and you cut hot-path time by refusing to do any evidence
work under the clock. The two goals stop competing the instant you stop
conflating the two budgets.

This reframing has a sharp consequence for the "generate more lineups" instinct:
more lineups is a hot-path cost that does not convert to accuracy. Past the point
where the bank covers the viable SP pairs and the tier archetypes, additional
near-duplicate lineups add solve time and duplication risk while adding no
decorrelated ceiling. The `bank_coverage_report` already measures the point of
diminishing returns (the roughly 5% gap rule). The efficient move is to spend the
saved compute on the cold loop, not on a bigger bank.

So the honest efficiency answer to the mandate is counterintuitive: to win more,
generate fewer, better-covered lineups faster, and pour the reclaimed time into
the evidence loop that is the actual bottleneck.

---

## 4. The waterfall, promoted from report to driver (Puzzle 1)

The three-tiered waterfall is not a new idea to design. It is a shipped, approved
policy (`posture_allocator.py`, from the 2026-07-04 brief) that classifies every
contest on the menu into Floor, Apex, or Volume by payout breadth, and emits a
fee-share policy plus a paste-ready `contest_postures` dict. Today it is a report
Ben reads and pastes. The upgrade is to make the tier a first-class input to
portfolio construction. But two corrections come first, because the mandate's
mental model of the waterfall is wrong in a way that would cost money.

**Correction 1: the floor is bought with dollars, not roster slots.** The mandate
says "protect our capital first by preventing a total wash (Floor Protection),"
which imagines a lineup that cannot bust. In top-heavy contests that lineup does
not exist, and the module says so in its header: "no lineup-level floor exists in
top-heavy contests and this module does not pretend one does." The floor is a
bankroll construct. It is the share of fees you route into broad-payout shapes
(breadth >= 0.20) and multi-seat satellites, where a modest score still returns
something and a won ticket is a convertible asset. Floor Protection is an
allocation decision at the contest-menu level, executed before a single lineup is
built. Treating it as a lineup objective is the classic beginner error of playing
cash-game lineups in tournaments and losing both.

**Correction 2: Apex "controlled overlap" is already the DU and SP-pair
machinery, and it is under-fed, not under-built.** The optimizer already does
decorrelated ceiling: overlap-repulsion presets, `du_distance` on unit
signatures, SP-pair repetition caps, per-tier ceiling and floor weights
(`CONTEST_SHAPE_PROFILE_WEIGHTS`, WTA at ceiling_weight 1.00). What is missing is
not diversity mechanics. It is that "different" is currently defined by player
overlap, not by outcome correlation. Two lineups with five different players can
still rise and fall together if they share a game environment. Real apex
decorrelation needs the correlation model (Section 7), which is parked.

With those corrections, the promotion is concrete and stageable:

1. **Now (no new evidence needed).** Wire the `posture_allocator` output into the
   `run_slate` checkpoint as a first-class block, so tier, breadth, fee-share
   policy checks, and the paste-ready postures appear in the pre-build review
   automatically instead of as a side script. This is plumbing, not modeling, and
   it removes a manual paste from the T-10 crunch. It changes no certified logic.

2. **Now.** Make tier drive the bank composition target, not just the posture
   string. Tier A entries demand SP-pair spread scaled to entry count (ledger
   3.5) and a duplication screen on every candidate. Tier F entries demand the
   top-script, highest-median construction and tolerate shared cores. Tier V
   follows the concentration rule (duplicate the top lineup across independent
   linear-payout contests, diversify within satellite families). The
   `build_diverse_candidate_bank` breadth-and-depth forcing already exists. Point
   it at tier-specific targets.

3. **After the gate opens.** Replace the fee-share policy priors (floor_min 0.25,
   apex band 0.40 to 0.60) with graded values once enough conditioned slates exist
   to say whether those bands earned their keep. Until then they stay labeled
   policy, adjustable per slate, exactly as the module already insists.

The waterfall is the highest-certainty win in this brief because it is the one
major capability that needs no new data to become real. It is sitting in the
repository as a printed report. Wire it in.

---

## 5. The AI chalk trap is mostly a misdiagnosis, and the real anti-chalk lever is already honest (Puzzle 2)

The mandate worries that "LLMs inherently gravitate toward consensus" and asks
for a programmatic way to inject smart variance. This needs to be taken apart,
because the diagnosis points at the wrong organ.

**There is no LLM in the build.** The certified path is `scipy.optimize.milp`. It
does not gravitate anywhere. It solves. Whatever contrarian or chalky character a
lineup has comes from its inputs (projections, ceiling multipliers, ownership
tiers) and from the objective weights, not from a language model's taste. So
"LLM chalk" cannot enter where lineups are made. Good. Keep it that way.

**Where an LLM does enter is exactly where its consensus bias is dangerous: the
research and QA loop.** When I read beat writers, summarize weather, or judge an
opener report, I will drift toward the consensus read. That is a real risk, and
Section 6 designs against it explicitly. But it is a QA-loop risk, not a
lineup-generation risk, and conflating the two sends you looking for the problem
in the solver where it does not live.

**The real chalk risk is the shared-inputs problem.** You, and every sharp
opponent in your small fields, price off the same Savant, the same odds, the same
public projections. That correlation of inputs is what makes fields converge, and
no amount of solver cleverness escapes it if the inputs are shared. The
programmatic escape has two levers, and their honesty differs sharply, which
dictates the sequence.

**Lever A, available and honest today: duplication avoidance.** Exact-lineup
duplication is the one anti-chalk signal that is structurally sound before any
calibration, because it is counted from standings, not predicted.
`field_miner`'s duplication screen and the `field_opponent_registry.json` give
you a real, non-probabilistic measure of how crowded a construction is in the
populations you actually play. Minimizing expected duplication is a legitimate,
label-clean edge you can pursue this slate. It does not need the ownership model.

**Lever B, the calibrated upgrade: ownership leverage.** Leverage in the DFS
sense is projection edge per unit of predicted ownership, and it is the sharpest
lever there is, but it is a claim about a number you cannot yet predict well.
`ownership_prior.py` exists to start the predict-then-grade loop on slate one so
that this lever becomes real as fast as possible. Until it has been graded across
eight to fifteen conditioned slates, its temperatures are labeled priors, and
leverage computed from them is a prior, not an edge. The module says this in its
header and it is right.

The correct anti-chalk macro strategy, then, is not "be contrarian." The mandate
itself warns against "being different for the sake of it," and the engine already
encodes that warning: variance is only bought where projection supports it. The
strategy is:

- This slate and every slate: run `ownership_prior.predict_ownership`, archive
  the standings, run `grade_against_actuals`, reconcile the error into the ledger.
  This is the loop that turns Lever B on. It is worth doing now even though it
  moves nothing yet, because the only path to the graded model is graded slates.
- This slate: use the duplication screen (Lever A) as the live anti-chalk input,
  because it is honest today.
- After the gate: fold graded ownership leverage into the Apex candidate score,
  screened by duplication, as a single combined "decorrelated ceiling per unit
  duplication" objective term. That is the mandate's "high-leverage variance
  backed by true mathematical upside," rebuilt on a foundation that will actually
  hold weight.

The creative core of Puzzle 2 is not a cleverer contrarian heuristic. It is
recognizing that duplication is measurable now and ownership is not, and
sequencing the two so you are never claiming an edge you cannot yet grade.

---

## 6. The adversarial pre-lock research loop (Puzzle 3, the one genuinely new build)

This is the mandate's best idea and the only puzzle that calls for building
something that does not already exist in scaffold. It also fits the architecture
cleanly, because the engine already has the correct seam for it: all live data
enters as pre-fetched JSON through `live_data_adapters`, and there is already a
manual version of exactly this loop (the ledger 3.8 "kill list" protocol and the
Cowork archival runbook's T-minus watch cadence). The job is to automate the
watch, not to invent a new entry point.

Design principles, in priority order, because the guardrails are non-negotiable:

**It lives entirely in the cold-adjacent pre-lock window, never in the certified
core.** It produces explicit, reviewable override proposals that enter through the
existing `approve=False` checkpoint. It never mutates a projection, a cap, or an
export directly. This is the same doctrine that keeps live fetching out of the
audited engine, applied to an agent instead of a fetcher. A red-team that can
silently change the certified build is not a red-team, it is an unaudited code
path.

**Every finding maps to a pre-existing engine action.** The runbook already
defines this mapping and the engine already exposes the levers. A confirmed
scratch removes a player from the pool. A surprise opener or bulk arm sets the
pitcher role flag and the F1 game override. A wind or roof change flips the
deterministic F5 inputs. A rising rainout risk triggers the medium-postponement
25% game-exposure cap, which is already an allocator control. The agent's output
is a diff against the current checkpoint, expressed in levers the operator
already trusts, with a source and a timestamp on every claim.

**It is adversarial against the optimizer's own assumptions, and against its own
consensus bias.** Two safeguards. First, the agent's job is framed as
falsification: find the three assumptions this build is most exposed to and
attack them with real-world context, rather than confirm the build. Second, to
counter the LLM consensus drift from Section 5, it must cite primary sources
(beat writer, official injury report, the actual weather packet) and surface the
raw source, so the operator grades the evidence rather than the agent's summary.
A confidence-tagged claim with no source is discarded, not shown.

**It respects the money wall absolutely.** No authenticated DraftKings actions,
no scripted standings pulls, no browser session holding a login. Research reads
public context. Money moves only at Ben's manual upload. This is already in
CLAUDE.md and it constrains the agent's tool access by construction.

What this buys, stated honestly: it does not raise win rate, because nothing can
claim that yet. It reduces the frequency of building on a stale assumption (a
scratched leadoff bat, an unannounced opener, a wind flip) that the deterministic
pipeline cannot see because those facts arrive after the feeds are pulled. It is a
latency-of-truth hedge, and it is worth building because the missed-lock history
shows that late-breaking reality is a repeated, material source of blown builds.
Label it as that, not as an edge engine.

Concretely, the first version is small: a scheduled pre-lock task that ingests the
lineups feed, the odds packet, the weather packet, and a short list of beat-writer
and injury sources, then emits a checkpoint-shaped override proposal with sourced
findings and the kill list. It is the runbook's watch cadence, run by an agent,
delivering into the review the operator already does by hand. That is a real
capability and a modest, guardrail-respecting build.

---

## 7. The blind spots, and what I would actually challenge

A first-principles review is worth more for what it questions than for what it
endorses. Four challenges, roughly in order of leverage.

**The correlation model is the parked crown jewel, and it, not ownership, may be
the faster path to ceiling.** `slate_sim.py` is the only component that
actually distinguishes ceiling from mean at the portfolio level, through its
Gaussian factor loadings (team, top-of-order, game). "Apex, high-variance,
decorrelated" is a statement about outcome covariance, and the sim is the only
thing that models it. It is parked with the ownership apparatus, but its gating
condition is different and softer. Correlation structure is grounded in baseball
(stacking, batting-order adjacency, bring-backs, game totals), and much of it can
be specified from structure and validated against realized scores without needing
the ownership archive at all. I would challenge the decision to keep the sim
parked at the same threshold as ownership. Fitting and validating the correlation
marginals against realized FPTS is plausibly the highest-ceiling cold-path project
available right now, and its output feeds the Apex objective directly. The one
named piece of future work in the sim, pairwise batting-order adjacency, is
exactly the mechanism through which MLB ceiling is actually produced. That is not
a footnote. It is arguably the most valuable single model in the roadmap.

**The opponent registry is a moat that your format makes uniquely buildable, and
almost nobody else can build it.** Everyone models ownership as a marginal (per
player). Almost nobody models the joint field (which full lineups recur, which
sharp opponents repeat, how field construction correlates). In large MME fields
that is hopeless because the population is huge and anonymous. Your fields are
small (40 to 50 player pools, small entrant counts) and the same opponents recur,
which `field_opponent_registry.json` is already capturing. That is a rare setting
where an empirical opponent model is actually estimable from a few dozen slates.
The strategic reframe: "beat the field" is not an ownership-guessing problem for
you, it is an opponent-modeling problem, and you are already sitting on the data
asset. I would treat the registry as the crown-jewel long-term asset and design
collection around it deliberately, not as a byproduct of `field_miner`.

**You cannot yet measure whether any of this works, so guard against building
cleverness you cannot grade.** This is the discipline the ledger already enforces,
and the greenfield framing is a direct threat to it. Every proposal in this brief
that is not "wire in the waterfall" or "run the grading loop" should be held to
the same gate the rest of the project uses: labeled prior until conditioned
evidence promotes it. The failure mode of an ambitious rebuild is a pile of
plausible mechanisms, none falsifiable, that feel like progress and cannot be
told apart from noise. Resist it.

**Small slates are a small-sample machine, and the cross-sectional path is slow.**
The backlog is candid that with 40-to-50-player pools you accumulate the
player-level rows that calibrate projections faster than you accumulate the
slate-level events that calibrate ownership and winning shape. That asymmetry
should shape sequencing: projection-accuracy calibration and correlation fitting
are reachable sooner, winning-lineup-shape memory stays record-only longest, and
the ownership model sits in between. Do not sequence the work as if all three
arrive together. They do not.

---

## 8. The macro strategy, sequenced

One sentence: close the loop, wire the waterfall, fit correlation before
ownership, add the red-team outside the wall, and refuse every win-rate claim
until the archive can grade one.

**Horizon 0, this slate and every slate, no new code required.** Run the full
evidence loop as ritual: `predict_ownership` before lock, archive the standings
after, `grade_against_actuals`, reconcile into the ledger, capture the three
contest-page fields the standings export omits. This is the single most important
recurring action in the entire project, because it is the only thing that moves
the gate. Use the `field_miner` duplication screen as the live anti-chalk input.
Read the `posture_allocator` report at the menu.

**Horizon 1, plumbing, no new evidence needed, changes surface not certified
logic.** Wire the waterfall tier and fee-share block into the `run_slate`
checkpoint. Point `build_diverse_candidate_bank` at tier-specific coverage
targets. Ship the first version of the pre-lock research agent as a scheduled
watch that emits a sourced override proposal plus kill list into the checkpoint,
strictly outside the certified core.

**Horizon 2, cold-path modeling, gated on evidence but partly reachable now.**
Un-park and validate the correlation marginals against realized FPTS, starting
with batting-order adjacency, because it is the real ceiling mechanism and its
gate is softer than ownership's. Continue accumulating toward the eight-to-fifteen
conditioned slates that turn the ownership model on.

**Horizon 3, the calibrated engine, after the gate.** Fit the ownership model into
one of the two reserved tracked slots (B-8). Fold graded ownership leverage,
screened by duplication and weighted by the correlation model, into a single Apex
objective term. Replace the fee-share policy priors with graded bands. Begin
building the empirical opponent model on the registry. Only here does a genuine,
gradeable statement about winning become possible, and only here should the
project start using that language.

---

## 9. What not to burn down

The greenfield mandate invites demolition, so the most useful thing I can do is
name the load-bearing walls the instinct would wrongly torch.

- **The certification spine.** Immutable runs, re-read reconciliation, the
  three-gate contract, fail-closed late swap. This is the asset. Route around it,
  never through it.
- **The truthful-labels discipline.** It is the reason you have not fooled
  yourself yet. It is not friction to optimize away. It is the thing that will
  still be true when the sample is large enough to embarrass a lesser process.
- **`scipy.optimize.milp` as the only solver, and no LLM in the build.** Keep the
  generation deterministic and auditable. Put all agent intelligence in the
  research and review loop, outside the wall.
- **The compact-bank philosophy.** More lineups is not more winning. The bank is
  sized to unique demand on purpose. Do not let a "generate thousands" instinct
  reintroduce the cost the design already removed.
- **The parked apparatus.** Parked is not abandoned. It is correctly waiting for
  the sample that makes it honest. The strategy is to reach that sample faster,
  not to un-park it early and pretend.

The single highest-leverage sentence in this brief: the bottleneck is evidence,
not compute, and the entire macro strategy is the discipline of spending the
project's energy where that constraint actually binds.
