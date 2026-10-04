# The Averaging Audit — Bankroll Kings

> **One question, asked of every number on the site:**
> ### "What context does this average hide?"
>
> **Status (2026-10-03):** methodology written; grounded inventory being populated from a
> codebase sweep. This is not a feature spec — it's the research method behind the next
> round of features. Pairs with `BANKROLL_KINGS_DOCTRINE.md` and feeds
> `docs/kings_wisdomism_engine.md` (every audit finding is a candidate Wisdomism *lens*).

---

## 1. Why this is the thread to pull

Every recent breakthrough came from the same move — not new math, but **refusing to let an
average hide context:**

| Breakthrough | The average it broke open |
|---|---|
| Opportunity vs production | "points/yards per game" hid *role and usage* |
| Buy Low / Sell High | "record" hid *performance vs opponent-adjusted level* |
| CLV vs win rate | "win %" hid *whether you beat the closing number* |
| Process vs outcome | "did it hit?" hid *whether the decision was sound* |
| 1Q/1H vs full game | "31 PPG" hid *when* those points happen |

That's a pattern, not a coincidence. An average collapses a distribution to a single
number, and **the signal is almost always in what got collapsed.** The audit
systematically hunts for the next one.

CoCo's framing, which we're adopting: this may be less a feature pipeline than **the
Bankroll Kings research methodology** — and it reframes the whole Wisdomism project.
Wisdomism's real job is not "find the best plays." It's **"assemble the strongest
convergence of independent context the market may not have fully captured."** Evidence
assembly, not scoring.

---

## 2. The five ways an average hides context

Every aggregate on the site collapses at least one of these. Tagging each number by *which*
tells us where a conditional version would reveal something.

| Dimension | The average collapses… | Example of what's hidden |
|---|---|---|
| **WHEN** | within-game time | 1Q/1H scoring; fast vs slow starters; finishers vs faders |
| **CONDITION** | game state | pass rate when trailing vs run rate when leading (*script identity*) |
| **WHO** | distribution across players | who actually gets the red-zone touches / targets (*concentration*) |
| **VS WHOM** | opponent / venue quality | strength of schedule; home vs road |
| **HOW RELIABLY** | the shape of the distribution | the *floor*, not the mean; volatility; consistency |

**VS WHOM** is largely handled already (SRS / opponent-adjusted form). **WHEN** and **HOW
RELIABLY** are started (CFB period board; hit profiles). The two wide-open frontiers are
**CONDITION** (game-script identity) and **WHO** (concentration) — and not by accident:
those are the two that directly *manufacture player props*.

---

## 3. The lens-independence test (the part that makes a finding usable)

CoCo's sharpest point, and the acceptance test for everything the audit produces:

> **A group of metrics is ONE lens wearing many hats if knowing one lets you predict the
> others. It's several independent lenses only if each is a genuinely different argument.**

His example says it perfectly:

**One argument, four hats** (do *not* count as 4 lenses):
```
Target Share · Air Yard Share · Targets/Game · Receiving Opportunity
```
All four are the **Opportunity** signal restated.

**Four actual arguments** (genuinely independent):
```
Opportunity · Game Script · Market Movement · Quarter/Half Behavior
```

This matters because **Kings Wisdomism ranks by convergence**, and convergence of
correlated lenses is false conviction — the three-Gibbs-cards trap one level up. So every
audit finding gets tagged with its **lens-family**, and we track which families are
actually independent of each other.

**How we'll decide independence:**
- *By mechanism (now):* do two metrics draw on the same underlying cause (team strength,
  game volume, the price)? If yes, suspect one lens.
- *By measurement (once coded):* correlate the two metrics' per-play signals across the
  historical play universe. High correlation → collapse them into one lens.

---

## 4. Candidate lens-families (independent arguments) + their market exposure

The convergence model needs a small set of *independent* families. Starting hypothesis —
to be confirmed by the independence test — plus whether the market likely already prices
each (the "un-priced gate" from the Wisdomism brief):

| Lens-family | Captures | Likely already priced? |
|---|---|---|
| **Opportunity / Usage** | volume, role, snaps, touches, targets | partly — stars are priced, role *changes* less so |
| **Game-script identity** | conditional behavior by game state | **under-priced** (frontier) |
| **Coaching / structural** | 4th-down, pace, RZ philosophy | **least priced** — market prices the QB, not the OC |
| **Concentration** | who gets the RZ/goal-line/target share | **under-priced** (esp. anytime-TD) |
| **Time-sliced behavior** | quarter/half, starts/finishes | partly — 1H/1Q lines exist and are priced |
| **Matchup / opponent quality** | form, SRS, def ranks | **priced** — the line already knows team strength |
| **Market context** | line, movement, line-delta, CLV | *is* the price — by definition reflects consensus |
| **Reliability / shape** | floor, consistency, variance | partly — floors erode as the line is bumped |

> ⚠️ **Suspected correlations to resolve:** Matchup quality ↔ Market context ↔ Opportunity
> may all be partly the same "this team/player is good, and the line knows it" signal. The
> independence test has to settle this before convergence counting is trustworthy. The
> genuinely *orthogonal* trio looks like **what a team/player DOES (script + concentration)
> × how MUCH (opportunity) × what the market MISSED (line-delta)** — but that's a
> hypothesis to verify, not a conclusion.

---

## 5. How to read the inventory (next section)

Each row of the grounded inventory is tagged:

| Column | Meaning |
|---|---|
| **Metric** | the average/rate/ranking as the site computes it |
| **Where** | file:function — so it's actionable, not theoretical |
| **Window** | season / last-N / all-resolved / career |
| **Collapses** | which of the 5 dimensions it washes out |
| **Lens-family** | which independent argument it belongs to (§4) |
| **Conditional buildable?** | can we split it with data we already hold? |
| **Priced?** | does the market likely already see the split (§4 exposure) |

The payoff column is the last two: a metric that **collapses a frontier dimension**, is
**buildable from data we have**, and is **not already priced** is a candidate for the next
breakthrough — and the next Wisdomism lens.

---

## 6. Grounded inventory

> *Populated from the codebase sweep now running (game/team, player, market-trends-truth).
> Filled in below when the sweep lands.*

### 6a. Game / Team level
*(pending sweep)*

### 6b. Player level
*(pending sweep)*

### 6c. Market / Trends / Truth
*(pending sweep)*

---

## 7. Output of the audit

Two deliverables, in order:

1. **The hidden-context shortlist** — ranked by (collapses a frontier dimension) ×
   (buildable now) × (not already priced). This is where the next insight is most likely
   sitting.
2. **The Wisdomism lens catalog** — the subset of findings that are genuinely *independent*
   lenses, which the Evidence Assembly engine ranks convergence over. The audit is what
   earns Wisdomism the right to rank by agreement at all.

---

*Written 2026-10-03 after the strategy brainstorm with Darrel + CoCo. The method is the
product: keep asking what the average hides, keep the lens-independence test honest, and
let the findings — not another board — decide what gets built next.*
