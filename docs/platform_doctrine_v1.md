# Bankroll Kings — Platform Doctrine v1

| Field | Value |
|---|---|
| Version | **v1** (`PLATFORM-DOCTRINE-1`) |
| Approved | Owner, 2026-11-09, as the final platform vision |
| Status | **Documentation only. Authorizes no implementation.** |
| Pin | File SHA-256 and commit recorded in `docs/platform_doctrine_versions.md`. A file whose hash does not match its recorded version has been edited without approval. |
| Change rule | Any revision requires a documented, owner-approved version change (v1 → v1.1 / v2) with a new pin record. No edits in place. |

## 0. What this document is and is not

- It records the platform vision the owner approved on 2026-11-09. It is the yardstick future releases are
  reviewed against.
- It creates **no** product branch, implementation release, milestone or roadmap position.
- It does **not** expand A0.2, Green Light Release 1A, NCAAB, or any active build. Nothing derived from it enters
  1A. Order and scope stay in `docs/PROGRAM_TABLE.md`.
- It is **separate from the frozen `DIC-1.0`** (`docs/decision_integrity_constitution.md`). It neither amends
  nor reinterprets it; any later incorporation uses the DIC amendment process.
- The larger capabilities it describes (full odds tooling, a universal market explorer, BK Milestones, user
  thresholds, decision memory, other parity capabilities) were already assigned to future releases. Recording
  them here does not schedule them.

## 1. Product positioning

> **Everything you need to research the market. The King's Way to understand the opportunity.**

Bankroll Kings is a transparent sports-market research and decision-intelligence platform. Its Trust Layer
establishes what can be relied upon. Its Accountability Layer explains and proves why the platform behaved as it
did. Its Market Research Foundation provides the complete tools users expect. Its Comparative Layer explains
alignment, disagreement, and change. The King's Way organizes opportunities into understandable evidence, and its
Learning Layer helps users improve their process over time. BK explains what is known, unknown, conflicting,
actionable, unavailable, and changed. The user makes the final decision.

## 2. Platform architecture

1. **Trust Layer** — identity, provenance, rights, freshness, applicability, same-offer binding, executability,
   and atomic publication.
2. **Accountability and Audit Layer** — why something appeared, disappeared, changed state, became unavailable, or
   failed publication, and the durable evidence proving why.
3. **Market Research Foundation** — governed competitive coverage: odds, props, best lines, alternate lines,
   movement, trends, injuries, weather, results, tracking, and research.
4. **Comparative Layer** — what history, current usage, context, and markets show; where they agree, disagree, or
   share one underlying cause.
5. **The King's Way** — identity before evidence; reality before market; trend and threshold discovery; context;
   support, contradiction, unknowns, limitations, and transparent BK perspectives.
6. **Learning Layer** — what the user knew, chose, and why; what happened; and whether the reasoning and the
   outcome were independently sound.
7. **Opportunity Lifecycle** — Observed → Discovered → Investigated → Evaluated → Decided → Recorded → Resolved →
   Reviewed → Learned.

## 3. Governing invariants

1. Evidence quantity does not prove evidence independence.
2. Availability is not endorsement.
3. Visibility is not recommendation.
4. Outcome quality is not process quality.
5. Eligibility controls actionability, not visibility.
6. Simplify presentation without concealing material evidence.
7. BK may offer transparent perspectives and recommendations, but they cannot control access to the governed
   market universe.
8. The user makes the final decision.

## 4. Blind-spot review framework

Every future release's acceptance package classifies **each** of the thirteen questions below as exactly one of:

- **Addressed** (cite the evidence);
- **Deferred with destination** (name the release or ledger item that owns it);
- **Not applicable with reason**;
- **Open contradiction** (the release conflicts with this doctrine; blocks acceptance until the owner rules).

The thirteen topics are the owner-approved list. The one-sentence wording of each question below was written
when this document was recorded. If it differs from the owner's own wording, the correction is a version change
(v1.1), not an in-place edit.

| # | Topic | Question |
|---|---|---|
| Q1 | Identity | Is every item bound to a verified identity (sport, competition, event, team or player, opponent, event time) before any evidence or offer is attached, and does an unresolved identity abstain rather than fall back? |
| Q2 | Temporal provenance | Does every value carry its own source time and observed time, kept separate and never substituted or derived from another clock? |
| Q3 | Applicability | Is each piece of evidence shown only where it applies (right event, season, role, market, and current state), with non-applicable evidence labelled rather than silently used? |
| Q4 | Evidence states | Are supporting, contradicting, missing, unknown, conflicting, disqualifying, and not-applicable evidence kept as distinct states and never collapsed into neutral? |
| Q5 | Shared root causes | When several signals agree, does BK show whether they share one underlying cause instead of counting them as independent confirmation? |
| Q6 | Market independence | Are the market's own price and BK's evidence kept separate, so the market is never restated as independent support for itself? |
| Q7 | Directional symmetry | Are over, under, and push (and both sides of every market) discovered and displayed on equal terms, with a missing price affecting executability only? |
| Q8 | Why an item appeared | Can BK state, with durable evidence, why each item appeared, disappeared, changed state, or became unavailable? |
| Q9 | Discovery versus recommendation | Is it clear which items were merely discovered and which carry a BK perspective or recommendation, and does no recommendation gate access to the governed universe? |
| Q10 | Decision-time reconstruction | Can the exact information, prices, and states the user saw at decision time be reconstructed later? |
| Q11 | User reasoning | Does BK capture what the user knew, chose, and why, without manufacturing precision the user did not provide? |
| Q12 | Research-candidate lifecycle | Does each research candidate move through governed, recorded states, with no hindsight substitution and no promotion without out-of-sample evidence? |
| Q13 | Human-readable explanations | Is every state, exclusion, warning, and limitation explained in plain language a user can act on? |

## 5. Relationship to existing documents

- **`docs/platform_product_doctrine_20261108.md`** (owner, 2026-11-08) remains in force. It is the detailed
  decision flow and identity-binding requirement for the research path. Platform Doctrine v1 is the
  platform-wide architecture that contains it. Read together: the 2026-11-08 line "BK does not determine what the
  user should bet" and v1 invariant 7, "BK may offer transparent perspectives and recommendations", are
  consistent, because a perspective informs and the user decides (invariant 8). This reading is recorded for
  owner confirmation, not as a new rule.
- **`BANKROLL_KINGS_DOCTRINE.md`** and CLAUDE.md §10 remain binding. That includes the do-not-build list (no
  universal score, cross-sport best-bets ranking, sharp-money tracker, lock, auto-EV list or Kelly) and the
  out-of-sample rule. A BK perspective under invariant 7 is still subject to them.
- **`DIC-1.0`** — separate and frozen (see §0).

## 6. How releases use this document

- Each acceptance package carries the doctrine-reference field from `docs/acceptance_package_template.md`: the
  doctrine version and pin it was reviewed against, plus the Q1–Q13 classification.
- A release may *reference* this doctrine. It may not *cite it as authority* to add scope. Scope comes only from
  `docs/PROGRAM_TABLE.md` and the owner.
