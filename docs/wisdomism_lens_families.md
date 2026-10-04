# Wisdomism Lens Families — Alignment Draft

> **The deliverable of the one lens-family session.** Not metrics — *families.* Convergence
> ranking only means something if the families are independent; otherwise Target Share + Air
> Yards + Targets/Game count as three votes for one thing, "and that's how every bad model gets
> built" (CoCo). This is a **draft for Darrel + CoCo to ratify or redline** — it fills the
> whiteboard so the meeting decides, rather than starts cold.
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

## The three decisions for the meeting

1. **Do we accept Market as the gate rather than a sixth voting lens?** (Changes convergence from
   6-way agreement to 5-way agreement + an un-priced check.)
2. **Coaching vs Game Identity boundary:** decisions vs outcomes — does pace/tempo live under
   Coaching (as a choice) and realized rhythm under Game Identity? Ratify or redraw.
3. **Concentration's scope:** scoring markets only, or do we try to make it vote on yardage too
   (risking a double-count with Opportunity)?

Lock those three and the family set is final.

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
