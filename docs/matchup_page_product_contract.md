# Matchup Page Product Contract

**Status: FREEZE CANDIDATE — awaiting review.** This defines *what a completed Bankroll Kings
matchup page promises the user*. It is a contract, not a plan. It does **not** define
architecture, schemas, storage, implementation, UI layout, or engineering tasks; it does not open
Audit #3, propose lenses, or authorize any build. Once reviewed and frozen it governs those later
decisions. Pairs with `docs/matchup_page_product_map.md` and `BANKROLL_KINGS_DOCTRINE.md` §11.

> **Revision for final freeze (2026-10-09, consolidated review):** removes the suppression
> exception — **every** predictive suppressor (including the graded-record guardrails) needs a
> documented governance record (§3); replaces the "authority increases" wording (§2); adds
> "Qualified does not mean correct" (§3); fixes Failed / Retired / Data-Gated placement (§2);
> makes Green Light & Daily Card conditional and names them currently nonconforming (§6); and
> protects governance from My View personalization and Track & Learn hindsight (§8).

---

## 1. Page Promise

> **We show the table. We show what has earned trust. We show what has not. You decide.**

A completed matchup page gives the user, for one game: the objective facts, the analytical context
that might explain them, an honest label on how much each idea has earned trust, Bankroll Kings'
governed assessment (which may be "no qualified edge"), the controls to weigh it their way, and the
record to measure the decision afterward. It is **decision support, not a pick.** It never
substitutes its judgment for the user's, and it never presents an untested idea as a claim.

## 2. Layer Definitions

| Layer | Belongs here | Does NOT belong here |
|---|---|---|
| **Market Facts** | Objective, current, verifiable: line/total/books, injuries, weather, schedule, records, line movement, scores — each with a fact-status. | Any prediction, interpretation, or edge claim. |
| **Analytical Context** | Ideas that *might* explain the game: form, strength, pace, matchup splits, market behavior. Multiple viewpoints, allowed to disagree. | Authority. Context explains; it does not rule. |
| **Research Status** | The governed label on each contextual idea (Qualified / Baseline / Under Review / Failed / Data-Gated / Legacy / Retired). | A second, page-local status system. Status comes only from the single governance source. |
| **King's View** | Bankroll Kings' governed assessment, built only from Qualified inputs, plus governed suppression. May be "no qualified edge — here is the market and context." | Any Legacy, Under Review, Failed, or Fact-as-prediction input acting as a vote. |
| **My View** | The user's emphasis, filters, slip building, notes. | Anything the platform forces. This layer is the user's. |
| **Track & Learn** | What the user actually bet, at the price taken, and the honest after-the-fact measure (CLV, results). | Marketing of hypothetical results. |

As the page moves from facts to analytical context to King's View, the **source and limits of
evidentiary authority become explicit.** My View then preserves user agency, and Track & Learn
records the decision **without changing the authority** of the evidence that preceded it. Nothing
below Research Status may present an unaudited idea as a claim.

**Placement.** Failed and Retired mechanisms do **not** appear as live matchup signals — they
remain visible only through the Research Ledger or an educational link ("why we don't use this
here"). **Data-Gated** status may appear only to explain a meaningful evidence *absence*, never as
a signal.

## 3. Authority Rules

- **Qualified does not mean correct.** It means a mechanism earned authority under the *current*
  governance process, and it remains subject to probation, retirement, and future evidence.
- **May influence King's View (affirmative):** only **Qualified** research. (Today: none documented.)
- **May provide context only (no vote):** **Facts**, **Baseline** (e.g. opponent-adjusted strength),
  **Legacy** (unaudited inheritances), **Under Review** (shown, not voting), **Data-Gated** (shown
  as a stated absence).
- **May suppress conclusions — suppression is decision authority.** **Any predictive suppression**
  (an "avoid"/"fade" resting on expected performance) **requires a documented governance status
  authorizing suppression for its applicable sport, market, population, and version.** A Legacy,
  Under Review, or Failed mechanism may not suppress a wager, and neither may any predictive signal
  lacking such a record. Suppression allowed **without** predictive qualification is limited to the
  non-predictive kinds: **correctness failures** (bad parlay math, duplicate leg), **missing data /
  source conflict** (§5), and explicit **user-set bankroll guardrails**.
- **The graded-record avoidance guardrails** (longshot-over, single-book, all-over, prefer-under)
  are **predictive and therefore not exempt.** They may ultimately *earn* suppressive authority —
  they are strong candidates as out-of-sample survivors of doctrine §10 — but only once a
  governance record documents their status, version, tested population, supported claim, permitted
  suppressive use, applicable sports/markets, and review conditions. **Until that record exists
  they do not influence King's View. No undocumented predictive suppressors.**
- **Never a vote (affirmative or suppressive):** Fact-as-prediction; any **Failed** or **Legacy**
  signal dressed as an edge; and everything on the doctrine §7 do-not-build list (composite score,
  lock, sharp/steam, cross-sport best-bets, auto-EV, Kelly staking).

## 4. Facts vs Research

Three distinct things, never conflated: a **factual observation** (what is / happened), **analytical
context** (a lens that might explain it), and a **governed mechanism** (a tested claim with earned
authority). A fact becomes a prediction *only* through an audited mechanism.

- **Injuries** — show who is in/out (fact). Not "X out → take the under" as a vote unless a
  with/without impact mechanism is Qualified.
- **Recent results / records** — show the record (fact). Not "won 4 straight → will cover"
  (streak-continuation is priced and unaudited here → context).
- **Line movement** — show open→now (fact/market behavior). Not "sharp money"/"steam", not "moved
  toward X → bet X" as a vote.
- **Rankings / power ratings** — show the number (context). Not an affirmative edge — opponent-
  adjusted strength is **Baseline** (no demonstrated ATS edge).

The page may *inform* with facts and context; only Qualified research may *claim*.

## 5. Missing Data Behavior

| Fact status | Display | As context | Into King's View |
|---|---|---|---|
| **Verified** | Yes | Yes | Yes (as fact, not a vote) |
| **Partial** | Yes, flagged | Yes, caveated | Caveated |
| **Pending** | Yes, "updating" | Limited | No |
| **Stale** | Yes, timestamped | Limited, caveated | No |
| **Unavailable** | Show the absence | No | No — may suppress a conclusion that needs it |
| **Source conflict** | Show the conflict | No | No — never silently pick one |

Missing or old data reads as *missing*, never as neutral or zero.

## 6. Green Light and Daily Card

- **Green Light** — *What it is:* an assembly that counts independent NFL lenses that agree, with
  the market as a gate. *Current authority:* **none earned** — its lenses are Under Review
  (attribution still accruing) and none are Qualified. *Framing until governance advances:* a
  **research-in-progress** view; its tier language ("conviction") must not read as a governed pick.
- **Daily Card** — *What it is:* a user-convenience assembly of cards from the board pools by an
  explicit rule. *Current authority:* **none** — no Qualified selection mechanism exists. *Framing
  until governance advances:* cards **assembled by a stated rule**, not "best"; "best" implies
  governed selection authority the product does not yet have.

Neither is a recommendation engine. Both may remain visible **only when framed honestly according
to their current governance status.** As they read today (authoritative "conviction" tiers; "best"
cards), they are **nonconforming** with this contract and are **not** examples of the completed
governed experience — the honest framing above is required, not optional.

## 7. No Qualified Edge

When no Qualified mechanism applies to a game — the current and expected state — the page says so
plainly: *"No qualified edge here. Here is the market, the context, and what each idea has earned."*
This is a **normal, honest outcome, not an error**. The page's value in that case is the table and
the honest status, not a manufactured pick. The product never invents authority to fill the space.

## 8. User Agency

These remain **entirely the user's**, always: **My View** (which lenses to emphasize), the **Menu**
(the whole board), **ticket construction** (build any slip by eye or from an assembly), **notes**,
and **tracking** (what they bet, at their price). The platform shows the table and labels the
dishes; the user chooses what to eat. Bankroll Kings informs and governs its own claims — it does
not decide for the user.

Two protections keep agency and governance from corrupting each other:

- **My View** may change what the user *emphasizes*, but it may **not** change research status, fact
  status, or Bankroll Kings' governed assessment. Personalization reorders; it never relabels.
- **Track & Learn** preserves the wager, price, available evidence, and governed assessment **as
  they existed at decision time**; later outcomes do not rewrite the original record. No hindsight.

---

*Once frozen, this contract governs the later decision of which implementation gate opens first
(Governance Source / Research Ledger / Matchup Assembly). That decision comes after approval.*
