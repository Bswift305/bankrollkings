# Change-First Lookup — Product Specification (design only, no code)

**Status: SPECIFICATION ONLY. No code, no UI, no model tuning, no production selection logic.** Returns
for approval before any implementation. Builds on the Decision Journal (built, dark —
`docs/decision_journal_review_spec.md`), the dataset-level legal register
(`docs/legal_register_v2.md`), and the queued Sport × Market × Angle Model Registry
(`docs/` — pending). Date: 2026-10-16.

## 0. Frozen doctrine
> **Facts may create visibility. Only validated, governed models may affect ordering or selection.**

A change, a mismatch, or a contradiction can make a player/team/game **visible** (surface it, flag it,
let the user investigate). None of them may change **ranking, confidence, selection, or
recommendation** unless a corresponding Sport × Market × Angle model has passed governance
(status = Qualified). Lookup is a **research workflow**, not a statistical encyclopedia and not a
picks page.

---

## 1. Shared architecture — Player, Team, Matchup
Every Player, Team and Matchup page renders the **same ordered sequence**; modules are omitted (not
faked) when their data isn't cleared or present:

1. **What's Changed?** — objective changes between defined snapshots.
2. **New Since You Last Looked** — the user's unread qualifying changes since their last recorded view.
3. **Facts** — logs, markets, availability, raw splits.
4. **Context** — trends, distributions, stability, environment.
5. **Matchup / Mismatch Detector** — factual archetype × opponent-channel alignments (visibility only).
6. **Contradictions** — material facts pointing in different directions (no hidden score).
7. **Research** — governed angle models with explicit status + explanation.
8. **Decision Journal** — the user's decision, thesis and result (the existing system, not a new one).

The three page types share one engine and one change-event store; they differ only in the **entity**
(player / team / game) and which modules apply.

---

## 2. Canonical change-event schema
One row = one observed change to one field of one entity, between two observations. **Three clocks are
stored and never treated as interchangeable** (the distinction the market-only correction established):

| Field | Meaning |
|---|---|
| `entity_type` / `entity_id` | player / team / game (stable id; names are display only) |
| `field` | the changed datum (e.g., `market_line`, `injury_status`, `designed_run_rate`, `minutes`, `opp_channel_rank`, `weather_wind`, `expected_lineup`) |
| `prior_value` / `current_value` | before/after values (typed; unknown stays unknown) |
| **`source_updated_at`** | when the **source/book** reported the datum updated (e.g., Odds API bookmaker `last_update`) |
| **`bk_captured_at`** | when **Bankroll Kings actually ingested** the observation |
| **`displayed_at`** | when the **user viewed** it (per-view, not stored on the event) |
| `effective_time` | the best available time the underlying fact changed (source-reported where present) |
| `occurred_after_market_quote` | boolean — did this change post-date the market quote currently displayed on the page |
| `reliability_state` | `confirmed` / `preliminary` (e.g., official ruling vs beat-report) |
| `dataset` / `source` | the dataset lineage of the field (links to §9; drives whether it may be shown) |
| `comparison_window` | the two snapshots compared (e.g., "yesterday 18:00 → now", "last 3 games") |
| `explanation` | one honest user-facing sentence stating what changed, with window + source |

Every change item shown to a user displays its **comparison window, source, both timestamps
(`source_updated_at`, `bk_captured_at`), whether confirmed or preliminary, and whether it occurred
after the displayed market quote.** A change with no valid timestamps is not shown as a timed change.

---

## 3. "What's Changed?" vs "New Since You Last Looked"
- **What's Changed?** — **objective, global** changes between defined snapshots (e.g., open → now; last
  game → this game). Same for every viewer. Example items: "Line moved 63.5 → 67.5 (source X, 2h ago)";
  "Starting RB ruled out (confirmed, 40m ago)"; "Designed-run rate 12% → 19% over last 3 games";
  "Opponent went from strong to weak vs this channel."
- **New Since You Last Looked** — the **user-specific** subset of qualifying change events with
  `effective_time > user.last_viewed_at(entity)`. It is a *filter over the same change events*, not a
  second tracking system. It shows only what the user hasn't seen.

---

## 4. Per-user last-viewed state + privacy
- **Minimal state only:** `(user_id, entity_type, entity_id, last_viewed_at)` — one row per user per
  entity, updated on view. **No behavioral surveillance**, no event-by-event clickstream, **not
  cookie-only** (server-side, tied to the authenticated account).
- **Privacy/retention:** store only the latest `last_viewed_at` per (user, entity); no view history;
  purge on account deletion; covered by the product privacy policy (`docs/legal_register_v2.md` §7/§9).
  `displayed_at` is computed at render time and is **not** persisted as a tracking log.

---

## 5. Module boundaries (what each may and may not do)
- **Facts** — logs, markets, availability, raw splits. Display only; no scoring.
- **Context** — trends, **descriptive distributions** (percentiles, median, variance, sample size — not
  an unexplained "consistency score"), **floor/median/ceiling** as a descriptive historical
  distribution (explicitly **not a projection** unless a governed model owns it), rotation/role
  stability, schedule stress (rest/travel/workload where reliable sources exist). No verdicts.
- **Mismatch Detector** — factual **archetype × opponent production-channel** alignment (e.g., mobile QB
  vs a defense that allows QB rushing). **Creates visibility only.** It may surface/flag; it may **not**
  rank, score, boost, or recommend. Every mismatch maps to a Sport × Market × Angle model id; it only
  **affects ordering/selection** once that model is Qualified (§13 governance).
- **Contradictions** — lists **material opposing facts** in two columns ("Supports higher…" /
  "Pushes the other way…") with no forced verdict and **no hidden score**. Example (QB rushing):
  supports = designed runs up + opponent allows QB rushing; against = line moved 38.5 → 45.5 + starting
  LT out + severe wind. The user weighs it.
- **Research** — governed angle models with an explicit **status** (Discovery / Under Review / Qualified
  / Failed / Retired) and an **explanation contract** (which inputs raised, lowered, or left the
  assessment unchanged). Failed/Retired never act as live signals; a page may *link* "why we don't use
  X here."
- **Decision Journal** — the existing built system. Lookup **integrates** it (log a decision + thesis
  from the page); it does **not** add a second notebook.

---

## 6. Environment Stability (explainable, no hidden score)
A plain label — **Stable / Mixed / Unstable** — whose **deterministic rules are published** and whose
**every contributing event is visible**. No meter, no opaque number. Example:

> Environment: **Unstable**
> Changed: new starter · two injury-designation changes · market moved 4 yards · role sample is 2 games

The rule set (e.g., "Unstable if ≥N material changes in the window, or a confirmed starter change, or a
role sample < M games") is shown on the page or one click away. The label is **context, not a score**,
and never alters ordering/selection.

---

## 7. Unavailable Production (not "Missing")
Named **Unavailable Production**. Always declares the **window and sample size**, and **explicitly
prohibits implied redistribution** — it states observed unavailable production and **does not claim**
how it will be reabsorbed:

> In the last 5 games, unavailable players accounted for 58 pts / 19 reb / 11 ast per game. This does
> not establish how that production will be redistributed.

No downstream module may infer that remaining players "inherit" it.

---

## 8. Dataset-level lineage & licensing for every displayed field
Every field on every module declares its **dataset** (per `docs/legal_register_v2.md`). A field renders
**only if its dataset's classification permits display**:
- **Owned/Licensed** or **Factual Reference** → may display (with any required attribution).
- **Permission Required / Unknown / Prohibited Until Cleared** → **withheld**; the module shows its
  honest unavailable state and, where useful, links "why this isn't shown."
- Concretely today: Odds API market facts display; **NBA.com-derived statistics are withheld** (the
  `BK_NBA_STATS_ENABLED` gate), so NBA Lookup Facts/Context/Mismatch built on NBA.com stats are
  unavailable until cleared, while the **market facts** still render. This spec must not design the NBA
  flagship around data that cannot legally support it — a field with un-cleared lineage simply does not
  appear.
- **Timestamp lineage:** every time shown is labeled (Book Updated / Feed Captured / Displayed At) and
  carries timezone info, or is marked "tz unknown" (never silently interpreted).

---

## 9. Freshness, missing data, abstention
- Each module declares a **freshness budget** per dataset; past it, the datum is **Stale** (shown as
  such, never as live).
- **Availability states** (Verified / Partial / Pending / Stale / Unavailable) so a gap never reads as
  neutral.
- **Abstention is mandatory:** if a module's required data is **stale, absent, or un-cleared**, the
  module **abstains** (honest unavailable state) rather than inventing a value, a projection, or a
  score. A governed model with insufficient/stale inputs abstains rather than emitting a number.

---

## 10. Sport-specific examples
**NBA — Assists (player page)**
- What's Changed: minutes 28 → 35 (last 3); usage up after a teammate's injury (confirmed); line 6.5 →
  7.5 (book, 1h ago). *(NBA.com-derived items appear only once the stats gate is cleared; the line
  change is Odds API and shows now.)*
- Context: assist distribution (median/percentiles/variance, n); rotation stability.
- Mismatch: ball-handling role × opponent assist allowance × teammate availability → visibility.
- Contradictions: supports (usage up, pace up) vs against (line moved, backup PG returning).
- Research: NBA-assists angle model, status shown; affects order only if Qualified.

**NFL — QB rushing yards (player page)** *(the concrete first model-registry gap)*
- What's Changed: designed-run rate 12% → 19% (last 3, source); opponent QB-rushing allowance strong →
  weak; line 38.5 → 45.5 (book, 2h ago); weather wind worsened.
- Context: QB rush-yd distribution (floor/median/ceiling, descriptive); role stability.
- Mismatch: mobile-QB archetype × defense-allows-QB-rushing → **visibility only**. The existing
  Defense-vs-Channel evidence connects here for **discovery + explanation**; it does **not** change
  ranking or add a boost until the **QB-rushing angle model** is validated out-of-sample.
- Contradictions: as in §5.
- Research: NFL QB-rushing model (Discovery → … → Qualified); only a Qualified model orders/selects.

---

## 11. Phased build order (each phase returns for approval)
1. **Change-event store + schema** (the three clocks), read-only population from already-cleared
   datasets (Odds API market changes first). No UI ordering impact.
2. **What's Changed? + New Since You Last Looked** modules + the minimal per-user last-viewed state.
3. **Facts + Context** (descriptive distributions, stability, Unavailable Production) — cleared datasets
   only; NBA.com-derived withheld behind the gate.
4. **Contradictions** (two-column, no score).
5. **Mismatch Detector** (visibility only) + mapping each output to a model-registry angle id.
6. **Research** surface reading governed model status (no ordering change until a model is Qualified).
7. **Decision Journal integration** on the page (uses the built system).
Data/validation-gated items (CLV, performance-by-line-range, market-movement, referee, weather, Similar
Games) wait on their prerequisites (captured market observations, licensed sources, frozen similarity
definition) and are **not** built in these phases.

## 12. Acceptance tests (per phase)
- **Timestamps:** every change item carries source_updated_at + bk_captured_at (+ displayed_at at
  render), each labeled with timezone or "tz unknown"; the three are never conflated.
- **Visibility ≠ ordering:** a mismatch/change/contradiction surfaces an entity but does **not** alter
  the ranking or add a score; ordering only changes when a Qualified model drives it (asserted against a
  fixture where no model is Qualified → order unchanged).
- **Lineage gating:** a field whose dataset is Prohibited/Permission-Required/Unknown is **not
  rendered**; NBA.com-derived modules are withheld while `BK_NBA_STATS_ENABLED=0`, while Odds API market
  facts still render.
- **Abstention:** stale/absent/un-cleared inputs → the module shows an honest unavailable state, never a
  fabricated value or projection.
- **New-Since correctness:** only events with `effective_time > last_viewed_at` appear; the per-user
  state stores exactly one `last_viewed_at` per (user, entity) and nothing else.
- **Contradictions / Environment Stability:** no hidden score; every contributing event is listed and
  the deterministic rules are reachable.
- **Unavailable Production:** declares window + sample and never implies redistribution.
- **Decision Journal:** logging from a Lookup page uses the existing store; no second notebook.

## 13. Governance (the visibility/ordering firewall)
- Mismatch Detector, What's Changed, Contradictions, Environment Stability, Unavailable Production, and
  all descriptive distributions are **visibility/context**: they may surface, flag, and explain.
- **Only a Sport × Market × Angle model with status = Qualified** (its own governance record, validated
  out-of-sample) may affect **ordering, selection, confidence, or recommendation.** A factual mismatch
  may be shown before validation; it must not become a "boost" until the angle model demonstrates
  incremental value.
- Every ordering/selection claim traces to a governed model id + status; none are introduced by this
  spec. Implementation of any ordering impact is a separate, separately-approved gate.

## 14. Out of scope here
No code, no UI, no model tuning, no production selection logic, no new notebook, and no field whose
dataset lineage is not cleared. This is the product contract + event schema + data-requirements + phased
build order to review before any Lookup implementation gate opens.
