# Bankroll Kings — Development Doctrine

> **Last updated: 2026-10-10** (§10 now four questions: discovery → mechanism → market → validation). This is the *why* behind the product — the stable philosophy
> every feature is checked against. Read it alongside [`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md)
> (the *how it's wired*) and [`CLAUDE.md`](CLAUDE.md) (the enforced session rules; §10 is the
> honesty/guardrail rulebook this doctrine is the reasoning for). Internal doctrine — **not**
> marketing copy. When a feature idea comes up, it is judged against the two filters in §6, not
> re-debated from scratch. When this doc and the code disagree, fix whichever is wrong on purpose.

---

## 1. What Bankroll Kings is

**A bettor decision-support platform.** It helps users gather evidence, build tickets, and
evaluate their own decision-making honestly. Its business is **improving decision quality**, not
predicting outcomes.

The defining sentence:

> **Bankroll Kings helps bettors build a repeatable, defensible process — combining context,
> market information, and risk awareness — then measures those decisions honestly after the fact.**

That one sentence explains why Track Record, CLV, Ticket Check, Risk Radar, and Market Movers all
exist, why we document failed theories, and why we reject locks and composite scores.

## 2. What Bankroll Kings is NOT

- Not a picks site ("here are today's winners").
- Not "trust our model."
- Not "we found the lock."
- Not "we'll tell you how much to bet."
- Not a sportsbook — it accepts no wagers and custodies no funds. 21+.

A picks site says *"here's the play."* Bankroll Kings says *"here's the play — now let's look for
the reasons it could be wrong."* That evaluation step is the whole difference.

## 3. The central lesson (what a good user learns)

> **Good decisions and good outcomes are not the same thing.** A good bet can lose; a bad bet can
> win. A user who internalizes that — who judges a month by the *quality and defensibility of the
> process* (good numbers, managed exposure, discipline, CLV) rather than by the scoreboard — is a
> user the platform succeeded with.

This is also the retention model: people stay with an honest analyst through a cold streak; they
rage-quit a "picks guy" the first week he's wrong. **The learning is the moat.**

## 4. The user loop

```
Discover → Evaluate → Build → Save → Track → Learn
```

| Step | What the user does | Tools |
|---|---|---|
| **Discover** | find ideas across the slate (options, not one pick) | Menu, Daily Card, Featured Players, Wave/Floor Boards, Trends |
| **Evaluate** | challenge the idea — "what am I missing?" | Ticket Check, Risk Radar, Game Context, Injury Report, Best Lines |
| **Build** | assemble the ticket, by eye or from the auto card | The Menu, Today's Cards |
| **Save** | keep the ticket | card image / saved ticket |
| **Track** | log what was actually bet, at the price taken | Bet Tracker |
| **Learn** | measure the process honestly | CLV, Track Record, personal results |

One destination (the ticket), fed by a research engine, backed by a record. Every surface serves a
step. "Discover without Evaluate" is a picks site; "Track without Learn" is a spreadsheet. The loop
is the product.

## 5. The four-layer architecture

| Layer | Purpose | Surfaces |
|---|---|---|
| **Research Engine** | generate ideas | Featured Players, Floor Boards, Wave Boards, matchup/current-form, Game Context, Best Lines |
| **Evaluation Layer** | challenge ideas (look for why the play is wrong) | Ticket Check, Risk Radar, Injury Report, Game Context |
| **Destination** | build the ticket (the action layer) | Daily Card, The Menu, My View |
| **Truth Layer** | measure reality; keep the rest honest | Bet Tracker, CLV, Track Record, candidate/prop-line archives |

Without the Truth Layer, everything above it becomes marketing. That layer is non-negotiable.

## 6. The two development filters

Every feature idea must pass **both**:

1. **Which step of the loop does this improve?** (Discover / Evaluate / Build / Save / Track /
   Learn.) If the honest answer is "none," it's noise — don't build it.
2. **Does it make a claim we cannot prove out-of-sample?** If yes, don't build it — no matter how
   marketable, how good the demo, or how much a competitor has it.

These two questions replace re-debating the philosophy every time.

## 7. The explicit do-not-build list

Filter #2 rules these out by construction. They are **deliberately unbuilt, by standing direction:**

- A universal 1–100 / composite "confidence" or "risk" **score** (sports don't share equivalent
  evidence — report counts and context **by type**, never one number).
- A cross-sport **"best bets" ranking**.
- A **sharp-money / steam tracker**, or any "sharp"/"steam" labeling.
- A **"lock."**
- An **auto-EV list.**
- **Kelly / automated stake-sizing** that implies an edge. Kelly needs an edge estimate; our own
  research says the edge is ~the vig. Sizing against an edge we can't prove is "the lock in a new
  costume." (Risk management here means surfacing **exposure, longshot overs, single-book,
  all-over, prefer-under** — the avoidance signals the graded record supports — **not** telling a
  user how much to stake.)

## 8. The beliefs (evidence & honesty)

1. **Markets are usually efficient.** Every predictive factor we've tested — streak depth,
   opponent defense, venue, rest, line movement, expected PAs — moves the hit rate *and* the
   market's implied probability moves with it. The edge sits at roughly the vig.
2. **Out-of-sample or it does not count.** Four streak-parlay rules looked bulletproof in-sample
   (lower CI bounds +8.3 to +17.8) and every one reversed to significantly negative out-of-sample.
   A 3-leg parlay showed +63% ROI at n=21 and −29% at n=2,861.
3. **Context is useful; context is not edge.** Injury, weather, park, matchup, pace improve
   *decision quality and avoidance* — they are already in the price as an *edge.*
4. **Streaks are information, not predictions.** They're real (NBA streak ≥3 continues +15.1 pts
   above base over 122,888 obs) — and the market knows. We never sell streak depth as an edge.
5. **Winning bets do not prove good decisions. Losing bets do not prove bad decisions.** Judge the
   process.
6. **CLV measures process, not profitability** — and it needs a real sample; a hot handful of bets
   with good CLV proves nothing.
7. **We report honest, separated signals** — counts and context by type — **never a composite
   score** that implies different sports share equivalent evidence. Cross-sport is "lower
   shared-event concentration," **not** "uncorrelated." Combined parlay probability is always
   labeled "assumes independence."
8. **Missing data is labeled, never defaulted to neutral.** Availability states
   (Verified / Partial / Pending / Stale / Unavailable) exist so an absence of context never reads
   as a green light.
9. **Risk management matters more than chasing winners** — as *avoidance and exposure awareness*,
   not stake sizing (see §7).
10. **Transparency beats certainty.** Documenting what doesn't work is the asset, not a liability.
11. **If a feature implies an edge we cannot prove, we do not build it.**

## 9. What actually survives (so "we avoid, we don't predict" isn't empty)

Backtested on **171,476 graded MLB + WNBA props** at real lines and prices. The only things that
hold up are *avoidance* rules, and they are enforced in code:

- **`LONGSHOT OVER` guardrail** — overs under ~25% implied; OVER ROI by implied band is monotonic
  (`<15% → −40.9%`, `15–25% → −20.4%`, `70%+ → −6.5%`). Built for MLB and football.
- **All-over parlay warning** — all-over tickets ran −22% (2 legs) to −61% (5 legs) out-of-sample.
- **`SINGLE BOOK` → CONFLICTED** — 1 book returns −15.2% vs −3.9% at 5 books.
- **Prefer UNDER** — −0.6% vs −6.3% on identical streak logic.

Full study and caveats: `docs/` + the market-efficiency research notes.

## 10. The research method — four questions

The two filters (§6) decide *what to build*. The beliefs (§8) say *what we hold true.* This is
*how we discover* — the repeatable method behind every recent breakthrough. It is first-class
doctrine, not a one-off exercise. It is **four questions**, in order: discover a signal, test
that it's an independent mechanism, map it to a real market, then prove it actually helped.

> **Q1 — discovery:** ### "What context is this average hiding?"
> **Q2 — independence:** ### "What mechanism creates this outcome?"
> **Q3 — market:** ### "What role / channel creates the production?"
> **Q4 — validation:** ### "Did this lens actually help — forward, out-of-sample?"

### Question 1 finds the signal

An average collapses a distribution to a single number, and **the signal is almost always in
what got collapsed.** Every recent advance came from this move — not new math:

| Breakthrough | The average it broke open |
|---|---|
| Opportunity vs production | "yards/game" hid *role and usage* |
| Buy Low / Sell High | "record" hid *performance vs opponent-adjusted level* |
| 1Q/1H behavior | "31 PPG" hid *when* the points happen |
| CLV vs win rate | "win %" hid *whether you beat the number* |
| Process vs outcome | "did it hit?" hid *whether the decision was sound* |

**An average hides one of five things** — the checklist to run against any metric: **WHEN**
(within-game time), **CONDITION** (game-state / script), **WHO** (concentration), **VS WHOM**
(opponent / venue), **HOW RELIABLY** (the shape, not the mean).

### Question 2 decides if it's a real lens

Discovery alone over-expands — every new metric *looks* like a new angle. The second question
is the filter: **a lens is independent if and only if it draws on a distinct causal mechanism.**
Two metrics that trace back to the same mechanism are one lens wearing two hats, no matter how
different the numbers look. So before a finding earns a seat at the convergence table, ask what
*mechanism* produces it — and whether that mechanism is already represented.

Worked both ways:
- **QB rushing yards** *looked* like a new family. Mechanism check: it's produced by Game
  Identity (trailing → scramble) × Matchup (weak pass rush/contain) × Opportunity (designed-run
  role) — three families we already have. **Not a lens; a market** those lenses should reach.
- **Situational usage** ("usage while trailing") is Opportunity × Game-Identity — an
  *interaction* of two families, not a third. Not a lens.
- **Role stability** (the *variance* of a player's role, not its level) traces to a mechanism
  nothing else measures — coaching/personnel *trust* producing stable deployment. **A real new
  lens**, and the missing half of a floor (high opportunity **+** stable role).

The test's job is to **filter, not expand**: it should collapse a six-idea list to one new lens,
two deepenings, a market, and an interaction — the way "four metrics, one lens" collapsed before.
Done right, the lens set grows slowly and every member is genuinely its own argument.

### Question 3 maps it to a market

You don't bet positions, you bet **production channels** — rush yds, rec yds, receptions, TDs.
So a surviving lens still has to answer: *which market does it actually serve?* An RB's rushing
and receiving are different defenses to beat; a WR can carry it; a QB can run. (This is why
"Defense vs Position" became "Defense vs Channel.") Market applicability is uneven and must be
*labeled*: Channel Dependency is a floor / anytime-TD read, **not** a yardage-prop signal — say
so, don't slap a score on every market.

### Question 4 proves it helped — the part that outranks invention

A lens that survives Q1–Q3 is *plausible*, not *proven*. Q4 is the standard the others answer to:
**did this lens actually help — forward, out-of-sample, captured, and graded?** Not in the
backtest it was born in; on real plays it appeared on afterward. This is why the Lens Attribution
harness exists — every Green Light play is captured *with the lenses that fired on it*, then graded
as games resolve, so we can eventually say "Opportunity hit X% at Y ROI; Opportunity + Role
Stability beat Opportunity alone" — or that a lens we loved added nothing. **We grade evidence,
not bets.** Once a validated set exists, *measuring which lenses contribute is worth more than
inventing a seventh* — and a lens that fails Q4 loses its seat no matter how good its story was.

Five disciplines keep the method honest — each a scar, not a theory:

1. **De-averaging trades bias for variance.** Slice finely enough and the sample vanishes; a
   conditional point estimate on a handful of plays is a mirage (§8.2). Stop when the context
   appears, and trust *direction and shape* over a precise conditional number.
2. **It usually reveals correctness, not edge.** The market prices most context (§8.1), so
   de-averaging most often removes a *misleading* number rather than uncovering money — and that
   is still worth doing (A3 de-blended a phantom `AvgLine` that fed the score off fiction).
3. **Volume hides context: prefer rate over counting.** A per-game / total / win-count stat
   embeds volume driven by game-script, pace, games played, or price. Rate stats (per-play,
   per-opportunity, per-possession, ROI) divide it back out. (`docs/rate_over_counting.md`.)
4. **Correlated signals are not independent votes.** Before counting that several factors "agree,"
   confirm they aren't one argument wearing many hats (Target Share, Air Yards, Targets/Game are
   one lens, not three). Convergence of correlated lenses is false conviction.
5. **Deterministic is not correct.** A consistent answer can still be wrong — our attribution
   grader returned the *same* result every time while grading the *wrong player* (a display-name
   collision). When you validate a lens, challenge its **correctness**, not just its
   **consistency**: "does it repeat?" is easy; "is what it repeats true?" is the one that matters.
   (`docs/lens_governance_constitution.md`.)

The method is auditable and ongoing: `docs/averaging_audit.md` (the grounded inventory and the
A1/A2/A3 findings), `docs/rate_over_counting.md` (the counting→rate migration), and
`docs/wisdomism_lens_families.md` (the independent-lens map it produced). A recurring product of
this method is a cleaner, smaller set of genuinely independent signals — which is what the
ranking engine is allowed to treat as separate evidence.

> This may be the most durable thing we build: a discovery engine a competitor can't copy, because
> it requires the graded history *and* the willingness to disprove our own narrative. Every future
> idea gets tested against it.

---

*This doctrine is stable on purpose. Features change; the two filters, the beliefs, and the
research method do not, unless new out-of-sample evidence forces a documented change here.*
