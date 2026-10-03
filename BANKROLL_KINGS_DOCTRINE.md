# Bankroll Kings — Development Doctrine

> **Last updated: 2026-10-02.** This is the *why* behind the product — the stable philosophy
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

---

*This doctrine is stable on purpose. Features change; the two filters and the beliefs do not,
unless new out-of-sample evidence forces a documented change here.*
