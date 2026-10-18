# Sport × Market × Angle Model Registry — Specification (design only, no code)

**Status: REGISTRY FOUNDATION IMPLEMENTED DARK; no weight or production selection-logic changes.**
The metadata registry and its governance firewall were authorized and implemented on 2026-10-18 in
`services/model_registry.py`. The inventory and prioritized roadmap remain documentation work before
any model validation or authority change. Builds on the change-first Lookup (`docs/lookup_change_first_spec.md`), the matchup
product contract (`docs/matchup_page_product_contract.md`), and the market-efficiency discipline
(out-of-sample or it does not count). Date: 2026-10-16.

## 0. The principle
A **model system for every sport and every meaningful betting angle** — not one generic score forced
across everything, and not scattered undocumented bonuses. Architecture:

```
Sport
└── Market
    └── Angle
        └── Governed model
```

Examples: NFL QB rushing yds = mobile-QB profile × defense-vs-QB-rushing; NFL WR rec yds = target role ×
coverage/channel allowed; NFL RB rush yds = workload × run defense × game state; NBA assists =
ball-handling role × opponent assist allowance × teammate availability; NBA rebounds = minutes/position
× opponent shot profile × rebound chances; CFB ATS = active cover wave × price movement × coaching/team
context. **A shared framework orchestrates the models, but the underlying logic stays sport- and
angle-specific.** A QB-rushing model must **never** borrow a generic rushing-defense adjustment designed
for running backs.

## 1. The governed-model contract (every angle model specifies all nine)
1. **Eligible universe** — which players/teams/markets it applies to (and who it abstains on).
2. **Inputs** — the factual variables, each with **source (dataset lineage) + freshness budget**.
3. **Interaction logic** — not "Dallas is weak" and "the QB runs" separately, but whether those facts
   become **meaningful together** (the angle), stated explicitly and testably.
4. **Output** — an expected range/probability **or** a contextual alignment, **depending on what the
   evidence supports** (never a number the evidence can't carry).
5. **Market comparison** — line and price evaluated **separately** from player/team performance.
6. **Explanation contract** — exactly which facts **raised**, **lowered**, or **left unchanged** the
   assessment.
7. **Validation** — **historical** fit, **holdout** test, and **prospective** tracking; out-of-sample
   or it does not count.
8. **Governance status** — **Discovery / Under Review / Qualified / Failed / Retired** (mirrors the
   matchup contract and Lookup Research module).
9. **Abstention** — if required data is **stale or absent**, the model **abstains** (no score invented).

Each model is a registry **entry** with a stable `model_id`, a `version`, its nine fields, its
validation record, and its current status. Entries are developed, tested, explained, and retired
**independently**.

## 2. Shared framework, not shared logic
The registry is one orchestration layer that: resolves which entries apply to a market, runs each
entry's own logic, records status + explanation, and enforces governance. **The orchestration is
shared; the reasoning is per-entry.** The framework explicitly forbids:
- a **universal 1–100 score** or cross-sport "best bets" ranking (already on the do-not-build list);
- **sharing an adjustment across markets** (e.g., one rushing-defense term for both RB and QB rushing);
- any **undocumented "boost"** — every input that moves an assessment is a named, versioned,
  validated part of an entry, or it does not move anything.

## 3. Governance firewall (how it connects to Lookup + matchup)
> **Facts may create visibility. Only a Qualified model may affect ordering or selection.**

- A factual **mismatch / change / contradiction** (Lookup) may make an entity visible and feed an
  entry's **discovery + explanation** — it may **not** change ranking, confidence, or selection.
- An entry affects **ordering/selection/confidence/recommendation only at status = Qualified**, with
  its validation record attached. **Discovery / Under Review** entries are visible context only;
  **Failed / Retired** never act as live signals (a page may *link* "why we don't use X here").
- The Lookup Mismatch Detector maps each output to a `model_id`; the Lookup materiality/stability
  contracts are **owned by registry entries** and abstain until the entry exists.
- **Factual boards keep factual membership.** Where a board's membership is itself a factual rule (not a
  model), a model may **never suppress** a qualifying row. The canonical case is the **Active ATS Wave**
  (`docs/ats_wave_contract.md`, FROZEN): membership = a team's **current consecutive graded ATS-cover
  streak ≥ 3** (not undefeated start, not cover%); byes/ungraded games are ignored, a push pauses (shown
  separately) and is not a cover, an ATS loss resets. Objective sorting by **current streak length** is
  allowed and labeled; any angle model (e.g., `cfb_ats` = cover wave × price movement × coaching) is an
  **overlay beside each row** and controls neither membership nor the factual sort.

## 4. Inventory method (read-only)
Catalog every existing NFL/NBA/CFB/MLB mechanism that affects selection/ranking/confidence/score or
supplies decision context, mapping each to **market × angle**, and classify as:
- **(a) Generic shortcut** — a one-size adjustment or universal score reused across markets.
- **(b) Disconnected context** — contextual data that exists but is not wired to selection/explanation.
- **(c) Real model** — a market/angle-specific mechanism (candidate registry entry).
- **(d) Missing** — a meaningful market/angle with no model.

*(Inventory results are being gathered read-only and will populate §6 + §7 below. No mechanism is
changed by this spec.)*

## 5. First entry — NFL QB rushing (the concrete gap)
- **Entry:** `nfl_qb_rushing_yards` — Market: QB rushing yards. Angle: **QB-rushing archetype ×
  opponent QB-rushing allowance.**
- **Eligible universe:** quarterbacks with an established designed-run/scramble profile; abstain on
  pocket passers and on thin samples.
- **Inputs:** QB designed-run rate / rush attempts / scramble rate (source + freshness); opponent
  **QB-rushing allowance specifically** (NOT a generic rushing-defense number); game-state/script;
  line + price (compared separately).
- **Interaction logic:** a mobile QB **against a defense that specifically allows QB rushing** — the
  two facts meaningful **together**, not each alone.
- **Explicit guardrail:** the existing **Defense-vs-Channel** evidence connects to **discovery +
  explanation only**. It must **not** change ranking or add a "boost" until this entry's **incremental
  value is validated out-of-sample.** No generic RB rushing-defense term may stand in for the opponent
  QB-rushing allowance.
- **Output:** contextual alignment at Discovery; a range/probability only if validation supports it.
- **Validation:** historical + holdout + prospective on QB-rushing results at real lines/prices.
- **Status:** **Discovery** (visible context + explanation; zero ordering/selection impact).
- **Abstention:** stale/absent QB-rushing or opponent-allowance inputs → abstain.

## 6. Inventory — existing mechanisms by sport

Completed in `docs/model_registry_inventory.md`. The highest-risk finding is cross-sport live
calibration and promotion helpers that mutate scores without any Qualified entry. Factual systems
(Active ATS Wave, market prices, observed usage and historical distributions) remain facts; Green
Light and Defense-vs-Channel remain context; PropScore v1 remains contained/failed. NBA/WNBA
statistical candidates remain behind the data-rights gate.

## 7. Prioritized roadmap

The detailed sequence is frozen in `docs/model_registry_inventory.md` §7–§8. Start with NFL QB
rushing; then NFL WR receiving yards/receptions, RB rushing yards/attempts, and passing markets;
CFB spread continuation; market-specific MLB entries; NBA/WNBA only after cleared inputs exist.
Before those builds, characterize and contain unauthorized cross-sport calibration/promotion score
mutation, sport by sport. **No weight or production-selection change is authorized until an entry
reaches Qualified out-of-sample.**

## 8. Out of scope here
No model computation, weight changes, production selection logic, universal score, or undocumented
boost. The implemented code is registry metadata + the governance firewall only; the inventory and
prioritized roadmap precede any model validation or authority change.

## 9. Implementation receipt (2026-10-18)

The registry foundation now encodes `nfl_qb_rushing_yards` at **Discovery** and exposes it on the dark
NFL Player Check Research module only when the player is a QB with a live rushing-yards market. The
single `has_authority()` firewall requires both `status=Qualified` and passing historical, holdout, and
prospective validation; the current entry therefore has **zero** ordering, selection, confidence, or
recommendation authority. `qc_model_registry.py` proves the governance firewall and sport × market ×
position isolation. No model computation, weight, production ordering, or public flag changed.

The prospective shadow-record foundation is implemented separately in
`services/model_observations.py`: immutable pre-event snapshots, exact market line/price, input and
dataset lineage, model version/status-at-capture, idempotency, and later settlement with explicit
push/void/DNP/ungraded states. It has no production writer, schedule, UI, or authority.
