# Bankroll Kings — Betting Intelligence Playbook

The vocabulary, principles, and best practices that a serious analytics platform must
speak fluently — mapped to what Bankroll Kings already does (**HAVE**) and what it should
add (**GAP**). This is the "do we know what we're doing in totality" checklist. Every
claim here is consistent with our own record: **178k graded MLB+WNBA props, and the NFL
PropScore backtest.**

The one-line thesis we never abandon: **almost everything predictive is already in the
price.** Streak depth, defense, rest, weather, line movement — every factor moves the hit
rate *and* moves the market's implied probability with it, leaving the edge near the vig.
So we sell **avoidance, discipline, and honest context**, not "locks." What survives that
test is the whole product.

---

## 1. The Math (the foundation — non-negotiable)

| Term | What it means | Us |
|---|---|---|
| **Implied probability** | Convert odds → the break-even win % they price (-110 = 52.38%). | **HAVE** — market view / implied prob throughout. |
| **Vig / juice / hold** | The book's built-in margin; the sum of both sides' implied % > 100%. | **HAVE** — de-vig before comparing. |
| **No-vig / fair odds** | Strip the juice to get the market's true probability. Methods: multiplicative, additive, **power**, **Shin**. | **HAVE** (de-vig) · **GAP**: we don't state *which* method or expose it. |
| **Expected value (EV)** | (win prob × win) − (loss prob × stake). The only thing that matters long-term. | **HAVE** — EvPct in the archive. |
| **Closing Line Value (CLV)** | Did you beat the closing number? The single best proxy for skill — beating the close correlates with long-term profit better than W/L does. | **HAVE the data** (ClvLine, ClvPricePct) · **GAP**: not shown to users as "you beat the close by X". Biggest quick win. |
| **Break-even %** | 52.38% at -110. You must clear the vig, not just win >50%. | **HAVE** — floors reflect this. |
| **Kelly Criterion** | Optimal stake as a fraction of bankroll = edge/odds. Most pros bet **¼–½ Kelly** for lower variance. | **GAP** — we never advise stake size. A "unit sizing" guide is a credibility add. |
| **Variance / drawdown / risk of ruin** | Even a +EV bettor has long losing streaks; bankroll survives variance only if staked correctly. | **HAVE** (honesty about variance) · **GAP**: no bankroll/ruin calculator. |
| **ROI vs Win% vs Units** | Win% is misleading (juice + odds vary). ROI and units-won are the real scoreboard. | **HAVE** — we report ROI, not win%. |
| **Sample size / significance** | A 3-leg parlay at +63% ROI on n=21 went −29% at n=2,861. Small samples lie. | **HAVE** — hard-earned; enforced in guardrails. |

---

## 2. The Market (respect it — it's the sharpest opponent)

| Term | What it means | Us |
|---|---|---|
| **Efficient market** | Major markets (NFL sides/totals) price nearly all public info. Edges are thin and shrink fast. | **HAVE** — this is our doctrine. |
| **Sharp vs square / public** | Sharp = disciplined, model/CLV-driven; square = casual, narrative-driven. | **HAVE the concept** · we deliberately **don't** label plays "sharp/steam" (unprovable). |
| **Market makers vs retail** | Origination books (Pinnacle, Circa) set the true line; retail (DK/FD) copy + shade for the public. | **GAP** — we don't distinguish book *types*; worth noting Pinnacle/Circa as the "truth" reference. |
| **Line movement / steam / RLM** | Movement = new info or money. **Reverse line movement** (line moves against the public %) is the classic sharp tell. | **HAVE** — Market Movers, line-open→now capture. **GAP**: no public-% feed, so no true RLM. |
| **Key numbers** | NFL margins cluster on **3 and 7**; a spread of 2.5 vs 3.5 is worlds apart. Half-points around key numbers have real value. | **GAP** — we don't flag key-number spreads or price the half-point. High-value, low-effort add. |
| **Number / line shopping** | The same bet is priced differently across books; always take the best number. | **HAVE** — best-book / best-line surfaced. |
| **Middling / scalping / arbitrage** | Bet both sides at different numbers for a guaranteed or free-roll win (a "middle"). | **HAVE** — Middle Watch on the game-lines board. |
| **Hold % by market** | Sides ~4–5% hold; parlays/props/futures far higher. **Props and alt-lines are the *least* efficient** (thin markets) — that's where beatable edges actually live. | **HAVE** — our validated edge is in props (PropScore), exactly per theory. |
| **Correlated parlays / SGP** | Same-game legs aren't independent (QB pass yds ↔ WR rec yds). Books price the correlation; naive combined odds are wrong. | **HAVE** — we label combined odds "assumes independence" and warn all-over SGPs. |
| **Futures hold** | Season futures carry 20–30%+ hold — entertainment, not value. | **GAP** — worth a one-line honesty flag on the futures pages. |

---

## 3. Handicapping & Modeling (where our engine lives)

| Term | What it means | Us |
|---|---|---|
| **Power ratings** | A single team-strength number (Elo / SRS / Massey / Sagarin) → a projected margin. | **HAVE** — Elo power ratings + SRS current-form (opponent-adjusted). |
| **Opponent adjustment / SoS** | Rate performance relative to who it came against, not raw. | **HAVE** — iterative SRS, prior-blended. |
| **Regression to the mean** | Records built on **turnover margin, one-score games, red-zone %** aren't sticky — they regress. Phil-Steele-style luck. | **HAVE** — CFB Regression Watch, MLB xwOBA-vs-wOBA luck. |
| **Expected / advanced stats** | EPA, success rate, DVOA, xG, xwOBA — process over results; predictive where raw box scores aren't. | **PARTIAL** — Statcast luck (MLB), NGS modifiers. **GAP**: no EPA/success-rate layer for football. |
| **Pace / possessions** | Totals live and die on pace; normalize per-play/per-possession. | **PARTIAL** — totals model uses scoring environment; **GAP**: no explicit pace/plays metric. |
| **Situational spots** | Rest, travel, lookahead, letdown, revenge, short week, altitude. **Mostly myth/priced** — the research graveyard. | **HAVE** — we test these and refuse to sell the priced ones (openers, big-favorite trends studied honestly). |
| **Injuries / QB value / backup tier** | QB is worth ~6–10 pts; *who* the backup is matters (gunslinger vs game-manager). | **HAVE** — QB-out veto + backup-quality weighting + production-share skill injuries. |
| **Weather** | Wind on passing/totals is the one weather edge with real ROI (+10–22% on high-wind unders). | **HAVE** — validated wind-under flag. |
| **Calibration** | Do your 60% calls hit 60%? Overconfidence at the top of the range is the silent killer. | **HAVE** — model_calibration; known overconfidence-at-the-top still being worked. |
| **Base rates** | Start from the population rate (e.g., dogs win SU ~28% of games) before adjusting. | **HAVE (new)** — season upset tracker; more base-rate context is a good direction. |
| **Backtesting hygiene** | **Out-of-sample / walk-forward** only. Beware **overfitting, data-mining, survivorship bias.** In-sample +8–18% lower-CI rules all reversed OOS. | **HAVE** — the most expensive lesson we've paid for; baked into every guardrail. |
| **Monte Carlo simulation** | Simulate outcome distributions rather than point estimates. | **HAVE** — SimProb in the prop archive. |

---

## 4. Bet Types & Structures (speak all of them)

- **Sides (spread), moneyline, totals, team totals, props, alt lines** — **HAVE** across boards.
- **Period markets (1H / 1Q / halves)** — **HAVE** (Period Board). **GAP**: no 1H *player* props (feed cost).
- **Parlays** — compound the vig; even validated legs aren't +EV stacked. **HAVE** — honest warnings.
- **Teasers / Wong teasers** — moving NFL spreads **through 3 and 7** (e.g., +1.5→+7.5) is the one teaser with historical value. **GAP** — not built; a natural, credible add.
- **Round robins** — parlay combinations; same vig caveat.
- **Live / in-game betting** — the fastest-growing, least-efficient market; also the biggest trap for tilt.
- **Hedging / cash-out** — cash-out is almost always −EV (the book's hold on your own bet). **GAP**: a one-line "cash-out is a bad deal" honesty note.
- **Futures / season win totals** — high hold; long-hold capital. **HAVE** (season markets) · **GAP**: hold warning.

---

## 5. Discipline & Psychology (where most bettors actually lose)

- **Bankroll management / flat unit sizing** — 1–3% of roll per play; never scale to chase.
- **Chasing / tilt / steaming** — increasing stakes after losses is the #1 bankroll killer.
- **Record-keeping + CLV tracking** — track every bet and whether you beat the close. **HAVE the data; GAP the surfacing.**
- **Cognitive traps** — recency bias, gambler's fallacy, **hot-hand fallacy** (proven priced in our data), confirmation/narrative bias, results-oriented thinking (**process > outcome**).
- **Bet-to-your-edge discipline** — no edge, no bet. "Best available option, it doesn't matter what it is" — but only when one clears the bar.

> **GAP — the single most credibility-building feature we don't have:** a **personal bet
> tracker** (log a bet → we grade it + show your **CLV** and ROI over time). We already
> compute CLV; giving the *user* their closing-line-value scoreboard is what separates a
> "picks site" from an intelligence terminal.

---

## 6. Our Honesty Doctrine (the moat — say it out loud)

- **No universal 1–100 score.** Sports don't share equivalent evidence; report **counts by type**, not a composite.
- **Validated edge vs model lean vs situational spot** — every play is tiered by *how much evidence backs it*, never presented flat.
- **"Assumes independence"** on every combined-probability number.
- **Availability states** (Verified / Partial / Pending / Stale / Unavailable) so missing context never reads as neutral.
- **No "sharp" / "steam" / "lock" language.** We don't claim to see money we can't.
- **Out-of-sample or it doesn't count.** Full stop.

---

## 7. The Gap List — what to close to be "complete" (ranked)

1. **Surface CLV to the user** — we store it; show "you beat the close +2.1%." Highest credibility-per-effort.
2. **Personal bet tracker + CLV/ROI scoreboard** — turns the terminal into a system of record.
3. **Key-number awareness (NFL 3 & 7)** — flag spreads on/around key numbers + half-point value.
4. **Unit-sizing / bankroll guide (fractional Kelly)** — advise *how much*, honestly, without picking for them.
5. **Devig transparency** — state the method (multiplicative vs power vs Shin) and let it be inspected.
6. **Teaser tool (Wong teasers through 3/7)** — a real, literature-backed structure we don't offer.
7. **Hold/efficiency honesty on props/futures/parlays** — name where the house edge is biggest.
8. **Cash-out / live-betting honesty notes** — flag the −EV traps.
9. **EPA / success-rate layer for football** — the modern advanced-stat baseline we're light on.
10. **Market-maker reference (Pinnacle/Circa as "truth")** — anchor our lines to the sharp origination number.

Closing these, on top of what we already do, is what lets us say — honestly — that we
know what we're doing in totality.
