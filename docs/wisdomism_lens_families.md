# Wisdomism Lens Families — RATIFIED

> **✅ Ratified 2026-10-04 (Darrel + CoCo).** The lens-family session is done. The audit,
> migrations, doctrine, truth layer, and lens cleanup did their job; the lenses are purified
> enough that evidence convergence can mean something. Research hands the baton to
> implementation. **The locked set is below; the rest of this doc is the reasoning that got us
> there.** Not metrics — *families.*
>
> **Voting lenses (5):** Opportunity · Game Identity · Matchup · Concentration · Coaching.
> **Non-voting gate (1):** Market — the referee, not a vote.
>
> Pairs with `docs/averaging_audit.md`, `docs/rate_over_counting.md`, feeds
> `docs/kings_wisdomism_engine.md`.

---

## CoCo's proposed six

Opportunity · Game Identity · Matchup · Market · Concentration · Coaching.

It's a strong set. Running it through the independence test surfaces **three overlaps** that
have to be resolved before the families are truly orthogonal — plus one structural reframe.

---

## Independence pressure-test — the three overlaps

**(a) Opportunity ⟂ Game Identity.** A1 proved usage is partly *created by* game-script. So
raw Opportunity and Game Identity are the same signal until Opportunity is measured on
**neutral script** (the rate-migration work). *Resolution:* Opportunity only counts as its own
lens once it's neutral-script conditioned; until then it double-counts with Game Identity.

**(b) Matchup ⟂ Market — the deep one.** The line already encodes the matchup; the market knows
the opponent. A good matchup the market sees is *priced*. So Matchup is only independent in its
**un-priced residual.** This is the same realization as the convergence model's un-priced gate —
which means **Market isn't a co-equal lens, it's the benchmark the others are checked against**
(see reframe below).

**(c) Coaching ⟂ Game Identity.** Pace/tempo appears in *both* of CoCo's definitions ("tempo
decisions" under Coaching, "pace" under Game Identity). *Resolution:* split by cause vs effect —
**Coaching = the decisions** (4th-down aggression, run/pass tendency, tempo *choice*);
**Game Identity = how the game actually unfolds** (fast/slow start, realized script tendency).

---

## The structural reframe: Market is the gate, not a vote

The other families are **arguments** about a play. Market is the **aggregate of what everyone
already believes** about all of them. If you let it vote alongside the others, you double-count:
the market's number already contains the matchup, the opportunity, the heat. So Market plays a
special role —

> **Convergence = agreement among the independent *argument* lenses. Market is the gate that
> asks: has the number already priced that agreement in?**

High convergence **+ market hasn't moved** = the real flag. High convergence **+ market agrees**
= context, not opportunity. That's cleaner than "six lenses vote," and it's exactly the
un-priced gate from the Wisdomism brief, now given its proper place.

---

## Proposed resolved set — 5 voting lenses + Market as the gate

| Family | What it measures | Member metrics (examples) | Independent because… | Priced? | Build now (NFL)? |
|---|---|---|---|---|---|
| **Opportunity** | access to volume | target/rush/air share, pass attempts — *neutral-script* | it's *how much*, once script is divided out | partly | ✅ PBP (rate #3) |
| **Game Identity** | how the team actually plays | fast/slow start, realized script tendency, pace | it's *how the game unfolds*, not who's in it | under-priced | ✅ PBP (A1 + quarters) |
| **Matchup** | opponent interaction | neutral per-dropback/per-rush rates, opp adjust | it's *the other side* — but only its un-priced residual | **mostly priced** | ✅ PBP (A2, rate #1) |
| **Concentration** | where production lands | red-zone/goal-line share, target concentration | *where*, not *how much* — orthogonal to Opportunity **for scoring markets** | under-priced | ✅ PBP (yardline_100, TDs) |
| **Coaching** | structural decisions | 4th-down aggression, run/pass tendency, tempo choice | roster-stable *decisions*; the market prices the QB, not the OC | **least priced** | ✅ PBP (down/play-type) |
| *Market* *(gate)* | what the number is doing | line delta, movement, CLV, shopping | — it's the benchmark, not an argument | *is* the price | ✅ already live |

Two scope notes baked into the table:
- **Concentration is independent of Opportunity only for scoring/TD markets.** For yardage props,
  where-production-lands ≈ how-much-volume, so it collapses back into Opportunity. The engine
  should let Concentration vote on anytime-TD and goal-line props, not on yardage.
- **Player script-dependence (from A1) is a modifier, not a family.** It decides *whether* the
  Game Identity lens is allowed to vote for a given player (fires for the ~10% who flip; silent
  for the stable 90%, where it'd double-count Opportunity).

---

## Buildability

All five NFL argument lenses are buildable **now** from the PBP we already hold plus live market
data — nothing blocked. The **CFB** versions of Matchup/Game Identity (per-possession, pace) are
blocked on the CFBD `/drives` fetch; player per-snap/route refinements of Opportunity are blocked
on nflverse participation. So NFL can carry the first honest convergence engine; CFB follows once
the feeds exist. (See `docs/rate_over_counting.md` data-gaps.)

---

## The three decisions — RESOLVED

1. **Market as gate, not a vote** — ✅ **ratified.** Convergence = agreement among the 5 argument
   lenses; Market is the referee that checks whether the agreement is already priced. ("4 lenses
   agree → Market checks → eligible," never a 5th vote.)
2. **Coaching vs Game Identity** — ✅ **kept separate.** Game Identity = *what happens* (fast
   starts, trailing tendencies, pace). Coaching = *why it keeps happening* (coordinator
   preference, 4th-down behavior, personnel/tempo choice). Observations vs cause.
3. **Concentration's scope** — ✅ **ratified as a distinct family, scoring markets.** It asks a
   question none of the others do: *when scoring happens, who gets it?* Votes on anytime-TD /
   goal-line, not yardage (where it would collapse into Opportunity).

The family set is final.

## Implementation readiness (what exists vs what's left to build)

The research is done; here's the honest state of each voting lens as code:

| Lens | Status |
|---|---|
| **Opportunity** | ✅ built + cleaned — share-based, script-decoupled (rate migration #3) |
| **Matchup** | ✅ built + cleaned — per-dropback / per-carry efficiency (migration #1) |
| **Game Identity** | ◑ partial — A1 script-dependence + CFB period board; NFL team-identity to round out |
| **Concentration** | ⬜ **net-new** — RZ / goal-line / target & TD share, buildable from PBP (yardline_100, TD) |
| **Coaching** | ⬜ **net-new** — 4th-down aggression, pace, run/pass tendency, buildable from PBP (down, play_type) |
| *Market (gate)* | ✅ live — line, movement, CLV, line-delta |

So "build Wisdomism" = build the two net-new lenses (Concentration, Coaching), round out Game
Identity, then the convergence **assembly** engine + page. A 3-lens v1 (Opportunity + Matchup +
Game Identity, Market-gated) is a legitimate first cut while the last two land.

---

## Why this locks Wisdomism

Once the families are ratified, the convergence model is well-defined: count agreement among the
five independent arguments (each one a thing the audit confirmed the market *averages away*),
gate it against the market, and rank by how many *independent* lenses converge on an un-priced
read. No composite score, no profit claim — just "N independent arguments agree, and the number
hasn't caught up yet." That's the engine, and the audit is what earned the right to build it.

---

*Written 2026-10-04 as the lens-family alignment draft. CoCo's call stands: we're done auditing —
ratify the families here, then implement the rate-over-counting migration in order (def ranks
per-dropback, ROI beside every hit-rate, usage per-opportunity). The research method — "what
context is this average hiding?" — outlasts any single feature.*
