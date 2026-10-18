# Change-First Lookup — Product Specification and Phase Status

**Status: REVISION 3 APPROVED. PHASE 1 IMPLEMENTED LOCALLY FOR REVIEW; PHASE 2+ NOT AUTHORIZED.**
Phase 1 is dark service/storage code only: no UI, model tuning, production selection logic, or live
production database. It returns for approval before Phase 2. Builds on the Decision Journal (built, dark —
`docs/decision_journal_review_spec.md`), the dataset-level legal register
(`docs/legal_register_v2.md`), and the queued Sport × Market × Angle Model Registry
(`docs/` — pending). Date: 2026-10-16. **Revision 3** (five frozen product refinements — see §16:
"What's Changed?" is the default opener with New / Newly-Significant sub-divisions; "Why This Is
Interesting" attention layer; Mismatch stays descriptive; consistency scores replaced by distributions;
"What Did I Miss?" is the user-facing change view. Builds on Revision 2's nine implementation-readiness
corrections — §15.)

## 0. Frozen doctrine
> **Facts create visibility. Research creates hypotheses. Qualified models may create authority. The
> Decision Journal creates learning.**

The shorter rule still holds: **facts may create visibility; only validated, governed models may affect
ordering or selection.** A change, a mismatch, or a contradiction can make a player/team/game
**visible** (surface it, flag it, let the user investigate). None of them may change **ranking,
confidence, selection, or recommendation** unless a corresponding Sport × Market × Angle model has
passed governance (status = Qualified). Lookup is a **disciplined decision workflow**, not a statistical
encyclopedia and not a picks page. **No new black-box scores are introduced by any refinement here.**

---

## 1. Shared architecture — Player, Team, Matchup
Every Player, Team and Matchup page renders the **same ordered sequence** — **"What's Changed?" is the
default opening module, before averages, heat maps, splits and logs.** Modules are omitted (not faked)
when their data isn't cleared or present:

```
What's Changed?                 ← default opener (before averages/heat maps/splits/logs)
├─ New Information               (an injury, role, line, weather, availability or lineup actually changed)
└─ Newly Significant Information (an existing fact became relevant because the player/opponent/matchup changed)
What Did I Miss?                ← user-facing change view (the former "New Since You Last Looked")
Why This Is Interesting         ← attention layer: short, traceable, evidence-linked factual statements
Facts                           ← logs, markets, availability, raw splits
Context                         ← distributions (median/percentiles/σ/n), stability, environment
Mismatch Detector               ← descriptive archetype × opponent tendency (visibility only)
Contradictions                  ← material opposing facts, no hidden score
Research                        ← governed angle models, explicit status + explanation
Decision Journal                ← the user's decision, thesis and result (existing system)
```

The three page types share one engine and one change-event store; they differ only in the **entity**
(player / team / game) and which modules apply.

---

## 2. Canonical change-event schema
One row = one change to one field of one entity, between two observations. **Four clocks are stored and
never treated as interchangeable**, and events are **immutable, idempotent, and ordered by a monotonic
sequence** (so delayed/backfilled/corrected events behave correctly).

### 2a. Identity, ordering, idempotency, correction lineage (correction 4)
| Field | Meaning |
|---|---|
| `change_event_id` | **immutable** unique id, assigned once; never rewritten |
| `event_sequence` | **monotonic** per-store sequence number; the basis for "new since" watermarks |
| `dedup_key` | deterministic key = hash(entity_id, field, derivation_version, source_observation_id or (prior,current,effective_time)); re-ingesting the same observation is a no-op |
| `source_observation_id` | the source's own observation/reference id where available |
| `supersedes` / `corrects` | id of the event this one corrects (a correction is a **new** event that references, never mutates, the original) |
| `derivation_version` | version of the logic that produced a **derived** change (null for observed) |

### 2b. Timestamps — four clocks (corrections 1, 8)
| Clock | Meaning | Rules |
|---|---|---|
| `source_updated_at` | when the **source/book** reported the datum updated (e.g., Odds API bookmaker `last_update`) | UTC; keep the original source string + offset where supplied |
| **`first_captured_at`** | when the event **first became available to Bankroll Kings** (ingestion of this observation) | UTC; the basis (with `event_sequence`) for unread detection |
| `effective_time` | when the **real-world change actually occurred** (source-reported where present) | UTC; retained **separately** — never used alone for unread detection |
| `displayed_at` | when the **user viewed** it | computed at render; not persisted on the event |

All internal timestamps are **stored in UTC**; the original source timestamp + offset are retained where
supplied. A timestamp whose timezone is unknown **may be displayed** (labeled "tz unknown") but **must
not** support ordering, unread-event boundaries, CLV, or before/after comparisons (correction 8).

### 2c. Content
| Field | Meaning |
|---|---|
| `entity_type` / `entity_id` | player / team / game (stable id; names are display only) |
| `field` | the changed datum (e.g., `market_line`, `injury_status`, `designed_run_rate`, `minutes`, `opp_channel_rank`, `weather_wind`, `expected_lineup`) |
| `change_class` | **`observed`** (injury designation, quote, lineup announcement) or **`derived`** (designed-run rate, percentiles, opponent-channel rank, stability label) — correction 5 |
| `prior_value` / `current_value` | before/after values (typed; unknown stays unknown) |
| `derived_meta` | for `derived` events only: formula + `derivation_version`, input window, sample size, and the `source_observation_id`s it was built from (correction 5) |
| `reliability_state` | `confirmed` / `preliminary` (official ruling vs beat-report) |
| `market_relative_timing` | **tri-state `true` / `false` / `unknown`** (correction 3): whether the change post-dates the displayed market quote; with `referenced_quote_id` + the **exact timestamp used for the comparison**. Never compares `effective_time` to a bookmaker-update time as equivalent clocks |
| `dataset` / `source` | the dataset lineage of the field (links to §8; gates display) |
| `comparison_window` | the two snapshots compared ("yesterday 18:00 → now", "last 3 games") |
| `explanation` | one honest user-facing sentence: what changed, with window + source |

Every change item shown to a user displays its **comparison window, source, `source_updated_at` +
`first_captured_at`, confirmed/preliminary, and its tri-state market-relative timing**. An event with no
valid (tz-aware) timestamps is not shown as a timed change. A **corrected source value appears as a new
event that `corrects` the original** — it never silently rewrites the original and never re-appears as a
fresh change on every ingestion (the `dedup_key` + `supersedes` lineage prevent both).

---

## 3. "What's Changed?" (default opener), "What Did I Miss?", "Why This Is Interesting"

### 3a. What's Changed? — the default opening module (refinement 1)
**Objective, global** changes between defined snapshots (e.g., open → now; last game → this game), the
same for every viewer, shown **before averages, heat maps, splits and logs**. It is divided into two
labeled sub-sections, each item carrying its window + source + timing per §2:
- **New Information** — an injury, role, line, weather, availability, or lineup **actually changed**
  (a `change_class = observed` event, or a `derived` event whose underlying datum moved). Examples:
  "Line moved 63.5 → 67.5 (book, 2h ago)"; "Starting RB ruled out (confirmed, 40m ago)";
  "Designed-run rate 12% → 19% (last 3)".
- **Newly Significant Information** — an existing fact **became relevant because the player, opponent,
  or matchup changed** (nothing about the fact itself changed; its *relevance* did). Examples: "This
  player's QB-rushing profile now meets a defense that allows QB rushing (opponent changed)"; "A stable
  role is newly material because the projected game script flipped." Significance is a **visibility**
  signal only; what counts as "newly significant" is a **frozen contract owned by a named Model-Registry
  entry** and **abstains until that entry exists** (§6, correction 6) — never a developer-chosen rule,
  never a score.

### 3b. What Did I Miss? — the personalized change view (refinement 5; renames "New Since You Last Looked")
The **user-specific** subset of qualifying change events the user has not yet seen. It shows the
**last-view timestamp** and **all newly available or corrected events since that visit**, determined by
**Bankroll Kings' capture sequence/time, not a provider's historical effective time** (correction 1) —
so a **delayed correction surfaces even if its `effective_time` predates the visit**. An event is in
"What Did I Miss?" when `event_sequence > user.last_seen_sequence(entity)` (equivalently
`first_captured_at > user.last_viewed_at(entity)`). It is a *filter over the same immutable change
events*, not a second tracking system. **First visits show an honest baseline, never a fabricated change
history** (§4): the section is empty and seeds the watermark.

### 3c. Why This Is Interesting — the attention layer (refinement 2)
A short list of **traceable factual statements** that **direct the user toward situations worth
researching**. Each statement:
- is a plain fact with its window + source, **not** a verdict;
- **never** says "best bet", "boost", "edge", or "recommended";
- **links back to its underlying evidence** (the change event, the distribution, the mismatch row, or
  the contradiction it summarizes);
- creates **visibility/attention only** — it never ranks, scores, selects, or changes confidence.
It is a human-readable index over the modules below it (What's Changed / Facts / Context / Mismatch /
Contradictions), not a new computation. Example: "Three inputs moved this week — role up, opponent
weak vs this channel, line up 7 — worth a look" with each clause linking to its source row.

---

## 4. Per-user last-seen state, view/update race, first visit
- **Minimal state only:** `(user_id, entity_type, entity_id, last_seen_sequence, last_viewed_at)` — one
  row per user per entity. `last_seen_sequence` is the authoritative watermark (monotonic event
  sequence); `last_viewed_at` is kept for display/debug only. **No behavioral surveillance**, no
  event-by-event clickstream, **not cookie-only** (server-side, tied to the authenticated account).
- **View/update race (correction 2):** do **not** advance the watermark before deciding which events
  the response contains. The order is: (a) **read** the previous `last_seen_sequence`; (b) select +
  render the eligible events (`event_sequence >` that watermark); (c) advance the watermark **only to
  the highest `event_sequence` actually included in a successfully rendered response.** A failed/partial
  render never advances it, so nothing is silently marked "seen."
- **First visit (frozen):** when no row exists for `(user, entity)`, there is **no** "new since"
  baseline — the first view shows **What's Changed?** but an **empty "What Did I Miss?"** (an honest
  baseline, never a fabricated change history), and sets `last_seen_sequence` to the highest rendered
  event. The user is never shown a flood of "new" events on their first visit.
- **Privacy/retention:** store only the latest watermark per (user, entity); no view history; purge on
  account deletion; covered by the privacy policy (`docs/legal_register_v2.md` §7/§9). `displayed_at` is
  computed at render time and is **not** persisted as a tracking log.

---

## 5. Module boundaries (what each may and may not do)
- **Facts** — logs, markets, availability, raw splits. Display only; no scoring.
- **Context** — trends, **descriptive distributions**, rotation/role stability, schedule stress
  (rest/travel/workload where reliable sources exist). **No verdicts, and no "consistency score."**
  **Refinement 4 — distributions replace any consistency score.** Every distribution shown reports:
  **median; 25th & 75th percentiles; optional 10th & 90th percentiles; standard deviation; sample size
  (n); the declared window; and the availability context** (what was/wasn't available across that
  window). Floor/median/ceiling is presented **as this descriptive historical distribution, explicitly
  not a projection** unless a governed model owns it. A single opaque "consistency"/"stability" number
  is **prohibited** — the distribution itself is the artifact.
- **Mismatch Detector** — **descriptive** factual **archetype × opponent tendency** alignment (e.g.,
  mobile-QB archetype vs a defense that allows QB rushing). **Refinement 3 — it stays descriptive:** each
  mismatch row shows the **player archetype, the opponent tendency, the sample size, the comparison
  window, the data freshness, and the data source**, and carries **no opaque mismatch score**. It
  **creates visibility only** — it may surface/flag but may **not** rank, score, boost, select, or change
  confidence. Every mismatch maps to a Sport × Market × Angle model id; it **may change
  ordering/selection/confidence only once a separately governed model Qualifies that exact
  Sport × Market × Angle** (§13 governance) — never before.
- **Contradictions** — lists **material opposing facts** in two columns ("Supports higher…" /
  "Pushes the other way…") with no forced verdict and **no hidden score**. Example (QB rushing):
  supports = designed runs up + opponent allows QB rushing; against = line moved 38.5 → 45.5 + starting
  LT out + severe wind. The user weighs it. **Inclusion is governed, not developer-chosen** (correction
  6): which facts count as "material" is a frozen contract owned by a named Model-Registry entry; until
  that entry exists the module **abstains** for that market rather than applying an arbitrary rule.
- **Research** — governed angle models with an explicit **status** (Discovery / Under Review / Qualified
  / Failed / Retired) and an **explanation contract** (which inputs raised, lowered, or left the
  assessment unchanged). Failed/Retired never act as live signals; a page may *link* "why we don't use
  X here."
- **Decision Journal** — the existing built system. Integration is **unavailable until the Journal's
  own production gate opens** (correction 9): while `DECISION_JOURNAL_ENABLED` is off, a Lookup page may
  **show the planned integration** (a disabled/"coming soon" affordance) but **cannot create any
  Journal record**. It never adds a second notebook.

---

## 6. Environment Stability (explainable, no hidden score)
A plain label — **Stable / Mixed / Unstable** — whose **deterministic rules are published** and whose
**every contributing event is visible**. No meter, no opaque number. Example:

> Environment: **Unstable**
> Changed: new starter · two injury-designation changes · market moved 4 yards · role sample is 2 games

The rule set is **a frozen contract owned by a named Model-Registry entry**, not a developer-selected
`N`/`M` (correction 6): the thresholds (how many material changes, what role-sample minimum, which
confirmed events force "Unstable") are defined in that registry entry, published, and every contributing
event is listed. **Until the owning registry entry exists, the Stable/Mixed/Unstable label abstains**
(not shown) rather than applying an arbitrary rule. The label is **context, not a score**, and never
alters ordering/selection.

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
Every field on every module declares its **dataset** (per `docs/legal_register_v2.md`). **A fact being a
"Factual Reference" does not by itself authorize copying it from a restricted database** (correction 7).
A field renders **only when BOTH hold**:
1. **permissible factual / nominative use** (the fact itself, neutrally used); **and**
2. **authorized source lineage** — it came from an Owned/Licensed dataset, or is an **independently
   generated observation** (our own capture), not copied from a Permission-Required/Prohibited source.

- Both conditions met → display (with any required attribution).
- Either missing (e.g., a factual stat whose only lineage is a restricted NBA.com endpoint) → **withheld**;
  the module shows its honest unavailable state and, where useful, links "why this isn't shown."
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
The clean prioritization (refinements): **build the shared change-event foundation first, then the two
change views and the evidence-backed interest summaries, then distributions, team context, mismatch
detection, Research, and Journal integration. No new black-box scores are needed at any phase.**
1. **Change-event store + schema** (the four clocks, identity/idempotency/correction lineage),
   read-only population from already-cleared datasets (Odds API market changes first). No UI ordering impact.
2. **The two change views + attention layer:** **What's Changed?** (incl. the *New Information* and
   *Newly Significant Information* sub-sections) + **What Did I Miss?** + **Why This Is Interesting**
   (evidence-linked factual statements) + the minimal per-user last-viewed state.
3. **Facts + Context** — Context uses the §5 **distributions** (median / 25th–75th / optional 10th–90th
   / σ / n / window / availability), stability as context, Unavailable Production. Cleared datasets only;
   NBA.com-derived withheld behind the gate.
4. **Contradictions** (two-column, no score).
5. **Mismatch Detector** (descriptive, visibility only) + mapping each output to a model-registry angle id.
6. **Research** surface reading governed model status (no ordering change until a model is Qualified).
7. **Decision Journal integration** on the page — **view-only (planned affordance) until the Journal's
   production gate opens**; no record creation while its flag is off.
Data/validation-gated items (CLV, performance-by-line-range, market-movement, referee, weather, Similar
Games) wait on their prerequisites (captured market observations, licensed sources, frozen similarity
definition) and are **not** built in these phases.

**Phase status (2026-10-18):** Phase 1 was explicitly authorized and implemented in
`services/lookup_changes.py` with the read-only adapter `ingest_lookup_market_changes.py`. The store is
outside the checkout, has no Flask/UI consumer, accepts only the cleared `odds_api_player_props`
dataset, and treats the first observation as a baseline. `qc_lookup_change_store.py` is the acceptance
gate. Phase 2 remains closed pending review.

## 12. Acceptance tests (per phase)
- **Timestamps:** every change item carries `source_updated_at` + `first_captured_at` (+ `displayed_at`
  at render) stored in UTC; each labeled with timezone or "tz unknown"; the clocks are never conflated.
  A **tz-unknown** timestamp is rejected for ordering, unread boundaries, CLV, and before/after compares.
- **Unread by availability (not effective time):** a backfilled/corrected event whose `effective_time`
  predates the last visit but whose `event_sequence`/`first_captured_at` is new **appears in What Did I Miss?**.
- **View/update race + first visit:** the watermark advances only to the highest `event_sequence`
  actually rendered; a failed render does not advance it; a first visit shows an **empty** "What Did I
  Miss?" (honest baseline) and seeds the watermark (no flood).
- **Idempotency + correction lineage:** re-ingesting the same observation is a no-op (`dedup_key`); a
  corrected value is a **new** event that `corrects` the original (original not mutated, not re-shown as
  new on every ingestion).
- **Market-relative timing tri-state:** `true/false/unknown` with `referenced_quote_id` + the exact
  comparison timestamp; the test proves `effective_time` is never compared to a bookmaker-update time as
  if equivalent.
- **Observed vs derived:** derived change events carry formula + `derivation_version`, input window,
  sample size, and the `source_observation_id`s they were built from.
- **Materiality abstention:** with no owning Model-Registry entry, Contradictions inclusion and the
  Stable/Mixed/Unstable label **abstain** (not shown); no developer-selected `N`/`M` appears.
- **Lineage (both conditions):** a factual field whose only lineage is a restricted source (e.g.,
  NBA.com) is **withheld** even though the fact is nominative; an independently-captured equivalent may
  show.
- **Visibility ≠ ordering:** a mismatch/change/contradiction surfaces an entity but does **not** alter
  the ranking or add a score; ordering only changes when a Qualified model drives it (asserted against a
  fixture where no model is Qualified → order unchanged).
- **Lineage gating:** a field whose dataset is Prohibited/Permission-Required/Unknown is **not
  rendered**; NBA.com-derived modules are withheld while `BK_NBA_STATS_ENABLED=0`, while Odds API market
  facts still render.
- **Abstention:** stale/absent/un-cleared inputs → the module shows an honest unavailable state, never a
  fabricated value or projection.
- **What Did I Miss? correctness:** only events with `event_sequence > last_seen_sequence` (equivalently
  `first_captured_at > last_viewed_at`) appear — **by availability, never by `effective_time`**; the
  per-user state stores exactly one `(last_seen_sequence, last_viewed_at)` per (user, entity) and nothing
  else. A distribution shown in Context carries median/25th/75th/σ/n/window (no consistency score); a
  Mismatch row carries archetype/opponent-tendency/sample/window/freshness/source (no mismatch score);
  a "Why This Is Interesting" statement links to its evidence and uses no bet-authority words.
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

## 15. Changelog — Revision 2 (nine implementation-readiness corrections)
1. **Unread by availability, not effective time** — "New Since" uses `event_sequence` /
   `first_captured_at` (added), with `effective_time` retained separately; delayed/backfilled
   corrections surface as new. (§2b, §3)
2. **View/update race** — read the watermark, render, then advance only to the highest rendered
   `event_sequence`; first-visit behavior frozen (empty New-Since, seed the watermark). (§4)
3. **Market-relative timing tri-state** — `true/false/unknown` + `referenced_quote_id` + the exact
   comparison timestamp; never compares `effective_time` to a bookmaker clock. (§2c)
4. **Idempotency + correction lineage** — `change_event_id`, `event_sequence`, `dedup_key`,
   `source_observation_id`, `supersedes`/`corrects`, `derivation_version`; corrections are new events,
   never silent rewrites. (§2a)
5. **Observed vs derived** — `change_class` + `derived_meta` (formula/version, window, sample, source
   observations) for derived changes. (§2c)
6. **Materiality contracts frozen + delegated** — "material change", Contradictions inclusion, and the
   Stable/Mixed/Unstable thresholds are owned by named Model-Registry entries; **abstain until the entry
   exists**; no developer `N`/`M`. (§5, §6)
7. **Tighter legal rule** — display requires BOTH permissible factual/nominative use AND authorized
   source lineage (or an independently generated observation); Factual Reference alone is insufficient.
   (§8)
8. **UTC timestamps** — all internal timestamps in UTC + retain the source string/offset; a tz-unknown
   timestamp may display but cannot drive ordering, unread boundaries, CLV, or before/after. (§2b)
9. **Decision Journal gated** — integration is view-only (planned affordance) and creates no record
   until the Journal production gate opens. (§5, §11)

## 16. Changelog — Revision 3 (five frozen product refinements)
1. **"What's Changed?" is the default opener** — before averages/heat maps/splits/logs — split into
   **New Information** (a datum actually changed) and **Newly Significant Information** (an existing fact
   became relevant because the player/opponent/matchup changed; governed, abstains until its registry
   entry exists). (§1, §3a)
2. **"Why This Is Interesting" attention layer** — short, traceable, evidence-linked factual statements
   that direct attention; never "best bet/boost/edge/recommended"; visibility only, each clause links to
   its source. (§1, §3c)
3. **Mismatch Detector stays descriptive** — shows archetype, opponent tendency, sample, comparison
   window, freshness, data source; **no opaque mismatch score**; may change ordering/selection/confidence
   only once a separately governed model Qualifies that exact Sport × Market × Angle. (§5)
4. **Distributions replace consistency scores** — median, 25th/75th, optional 10th/90th, standard
   deviation, sample size, declared window + availability context; a single opaque consistency/stability
   number is prohibited. (§5)
5. **"What Did I Miss?"** is the user-facing name for the former "New Since You Last Looked" — shows the
   last-view timestamp and all newly available/corrected events since, by Bankroll Kings' capture
   sequence/time (not a provider's effective time); first visits show an honest baseline. (§1, §3b, §4)

**Governing principle (frozen):** *Facts create visibility. Research creates hypotheses. Qualified
models may create authority. The Decision Journal creates learning.* No new black-box scores.
