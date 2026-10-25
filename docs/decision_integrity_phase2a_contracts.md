# Decision Integrity — Phase 2A Contracts (DESIGN ONLY) — Rev 2.1

**Status: Phase 2A Rev 2.1 — contracts-only. Returned for formal approval before Phase 2B.** Date 2026-10-25.
Rev 2.1 fixes six residual contradictions (NFL ATS decision-vs-board grain → two linked universes; §7
render-ref removed; `content_hash` covers the whole instance; supersession typo; unknown clock typed as
null + status, not a literal; `DECLARED_COMPOSITE` identity class), corrects the stale "schema_version is an
integer" + "tamper_evident from a mechanism name" statements, and **adopts** the P2A defaults.
Rev 2 applies nine contract-level corrections (receipt-vs-replay hash split; no self-referential hash;
immutable render linkage; canonical null handling; per-field numeric profiles; structured versioning;
hash-algorithm vs integrity-mechanism split; NFL-ATS pilot repaired to its real universe + clocks; three
typing/linkage fixes), labels the transition envelope **provisional** (not a seventh receipt kind), and
restates P2A-1…P2A-6 + transition granularity as **proposed defaults for approval**.
Implements the *contract definitions* called for by the approved Constitution Rev 2.1
(`docs/decision_integrity_constitution.md`). This document defines shapes, rules, and policies in prose +
tables. It writes **no code, no schema files, no registries, no DB files, no runtime flags, no routes, and
changes no production behavior** (see the Declaration at the end).

## Conventions
- **Normative keywords:** **MUST** (required), **SHOULD** (recommended; deviations recorded), **MAY**
  (optional). A surface that cannot meet a MUST is ineligible for authority and fails closed (Constitution
  L8).
- **Field tables:** `Field | Type | Null? | Norm | Meaning`. **Null?** = `req` (never null) / `opt`
  (nullable, meaning defined) / `cond` (conditional, with the condition). **Norm** = MUST/SHOULD/MAY.
- **Types** are logical (string, int, decimal, instant[UTC], enum, hash, ref, list<…>, map), not a storage
  encoding. Phase 2B picks encodings.
- **`instant[UTC]`** MUST be tz-aware ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`); Eastern is display-only.
- All examples use the audited NFL ATS surface (`build_nfl_ats_wave`) so they are concrete, not
  hypothetical. **No surface is migrated.**

---

## 1. Receipt envelope (common to all six receipt kinds)

Every receipt (Constitution §4) MUST carry a common envelope; kind-specific bodies attach under `body`.

| Field | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `receipt_id` | string | req | MUST | Stable unique id for this receipt instance. |
| `receipt_kind` | enum | req | MUST | One of `live_evidence` \| `entity_disposition` \| `decision_time` \| `correction` \| `render` \| `source_health`. |
| `schema_version` | map | req | MUST | Structured `{major:int, minor:int}` (Rev-2 #6). Unknown `major` → reader fails closed; a supported newer `minor` follows the forward-compatibility rule (Versioning policy). |
| `surface_id` | string | req | MUST | The authoritative surface (e.g. `nfl_ats_wave`). |
| `universe` | map | req | MUST | `{grain, id, version}` of the universe this receipt reconciles (Constitution §3). |
| `created_seq` | int | req | MUST | Immutable monotonic BK sequence (Constitution §7/§8); the authority on ordering. |
| `created_at` | instant[UTC] | req | MUST | Wall-clock creation; **informational only**, never used for correction ordering. |
| `clocks` | map | cond | MUST when the receipt bears event/observation time | `{source_updated?, source_updated_status, bk_captured, event_effective?}`. `source_updated` is `instant[UTC]` and **MUST be null/absent when unknown — never the literal `"UNKNOWN"`** (Rev-2.1 #5, would violate the type); `source_updated_status ∈ {PRESENT, UNKNOWN, NOT_PROVIDED}` carries that fact. `bk_captured` req; `event_effective` opt per grain. |
| `input_hashes` | list<hash> | cond | MUST when `replay_class != NON_REPLAYABLE` | Canonical input hashes (§4). |
| `conclusion_hash` | hash | req | MUST | Hash of the authoritative **canonical output** (§4), **excluding** receipt-instance metadata (`receipt_id`, `created_seq`, `created_at`, `integrity`). Two receipts whose conclusions are identical share a `conclusion_hash` even though their `content_hash`/`created_seq` differ (Rev-2 #1). Replay equality (§8 reproducibility) compares `conclusion_hash`. |
| `versions` | map | req | MUST | `{build_id, config_version, rule_versions{…}}` in force. |
| `replay_class` | enum | req | MUST | `EXACT_REPLAY` \| `EVIDENCE_EQUIVALENT` \| `NON_REPLAYABLE` (Constitution §8). |
| `integrity` | map | req | MUST | `{content_hash, hash_algorithm, mechanism, proof?}` (`hash_algorithm` e.g. `sha256`, separate from `mechanism`). `content_hash` hashes the **entire receipt instance** (every stored envelope+body field) **excluding only `integrity.content_hash` itself and signature/anchoring proof material that necessarily wraps the digest** (Rev-2.1 #3 — so a change to any stored field, incl. `created_at`, is detectable). `mechanism ∈ {none, hash_chain, signed, worm, anchored, audit_log}`. **`tamper_evident` is true only when `mechanism != none` AND the backing proof metadata/reference is present** (Rev-2.1 — a mechanism *name* alone is insufficient); otherwise integrity-verifiable. |
| `supersedes` | ref | opt | MUST when this is a correction | The **authoritative** reference: the `receipt_id` this supersedes (§6). The body's `supersedes_seq` MUST equal **the superseded receipt's** `created_seq` (Rev-2.1 #4 — fixed from "this receipt's"; validated, R15b). |
| `refs` | map | cond | MUST for composite receipts | Hierarchical references (§7), **forward-only, acyclic** (Rev-2 #3): an `live_evidence` receipt references `{entity_dispositions, source_health}` (NOT render — it is immutable and render comes later). A `render` receipt references the `live_evidence` receipt + its `conclusion_hash`/membership hash. No mutable back-reference. |
| `authority_class` | enum | req | MUST | `fact` \| `derived_context` \| `descriptive_mismatch` \| `governed_model` \| `user_thesis` (Constitution §9). |
| `projection` | enum | req | MUST | `internal` \| `user_safe` (§8). A `user_safe` receipt MUST NOT contain fields its `internal` source lacks (root-and-reference rule, §8). |

**Rules:** R1 A receipt MUST NOT be edited after publication; a change is a new receipt with `supersedes`
(Constitution L6/L12). R2 `created_seq` MUST be unique and monotonic per surface, and MUST be included in
`content_hash` but **excluded** from `conclusion_hash` (Rev-2 #1). R3 `content_hash` MUST cover the
envelope+body under the canonical serialization (§4) **excluding `integrity.content_hash` itself and any
signature/anchoring proof fields** (Rev-2 #2 — a digest cannot cover itself). R3b `conclusion_hash` MUST
cover only the authoritative canonical output, excluding receipt-instance metadata (`receipt_id`,
`created_seq`, `created_at`, `integrity`).

---

## 2. Terminal leaf dispositions

The closed set (Constitution L2). Every expected entity MUST receive **exactly one** leaf. `Eligible` and
`Members` are roll-ups, **never** stored as a leaf.

| Leaf | Rolls into | Definition | Example (NFL ATS) |
|---|---|---|---|
| `RENDERED` | Members→Eligible | admitted member shown on the page | a team with `cover_streak ≥ 3` displayed |
| `SUPPRESSED` | Members→Eligible | admitted member withheld by display-limit/policy (disclosed+counted) | member beyond a view row cap |
| `NONMEMBER` | Eligible | eligible, computed, did not qualify | `BELOW_THRESHOLD` (cover_streak 2) |
| `EXCLUDED` | Expected | legitimately out of scope | `KNOWN_NON_FBS`, `NO_LINE` |
| `UNAVAILABLE` | Expected | fail-closed: source/identity/completeness unproven, incl. `DATA_RIGHTS_GATE` | overdue ungraded game → sync fails closed |
| `INDETERMINATE` | Expected | expected/completed but evidence missing | completed appearance, no valid pregame observation |
| `FAILED` | Expected | malformed / conflict / schema-invalid | `(GameID,TeamSide)` conflict |

| Field (on an entity-disposition record) | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `entity_ref` | ref | req | MUST | The grain-specific identity (§5). |
| `leaf` | enum | req | MUST | One of the seven leaves above. |
| `reason_code` | string | req | MUST | Registered code (§3) explaining the leaf. |
| `reason_def_version` | int | req | MUST | Definition version of `reason_code`. |
| `params` | map | opt | SHOULD | Governed params (e.g. `{threshold:3}`, `{boundary_week:7}`). |
| `identity_quality` | enum | req | MUST | §5 class. |

**Rules:** R4 An entity MUST NOT carry two leaves. R5 A roll-up name (`ELIGIBLE`,`MEMBERS`) MUST NOT appear
as a `leaf`. R6 `UNAVAILABLE` MUST be used for gated/unproven data, never `EXCLUDED`.

---

## 3. Reason-code registry structure

| Field | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `code` | string | req | MUST | Stable, UPPER_SNAKE, no embedded version, **no interpolated runtime values** (Constitution §5). |
| `definition` | string | req | MUST | One-sentence meaning. |
| `def_version` | int | req | MUST | Increments when the *meaning* changes. |
| `owner` | string | req | MUST | Accountable owner. |
| `stage` | enum | req | MUST | Which stage (Constitution §2) may emit it. |
| `semantic_category` | enum | req | MUST | What the code describes (Rev-2 #9a): `leaf` \| `health` \| `stage_outcome` \| `transition`. (`SORTED` is a `stage_outcome`, not a leaf/health; `BELOW_THRESHOLD` is a `leaf`; `SOURCE_STALE` is `health`.) |
| `maps_to` | string | cond | MUST when `semantic_category ∈ {leaf, health}` | The specific leaf (§2) or health state; empty for `stage_outcome`/`transition`. |
| `param_fields` | list<string> | opt | SHOULD | Names of governed params carried alongside (e.g. `sort_rule_id`). |

**Rules:** R7 A stage MUST emit only registered codes. R8 Codes MUST be stable identifiers; governed
variation goes in `param_fields` (e.g. `reason_code=SORTED, sort_rule_id=…, sort_rule_version=…`), **never**
`SORTED_BY_<x>`. R9 Changing a definition MUST bump `def_version`; the code string MUST NOT change.

---

## 4. Canonical serialization (for hashing + EXACT_REPLAY)

Equality for `EXACT_REPLAY` compares **`conclusion_hash`**; all of `content_hash` / `conclusion_hash` /
`input_hashes` MUST be computed under one canonical form (two digests, different scopes — Rev-2 #1/#2):

| Rule | Norm | Detail |
|---|---|---|
| Field ordering | MUST | Object keys sorted lexicographically; order-independent. |
| Scope: two digests | MUST | **`content_hash`** hashes the **entire** receipt instance — **every stored envelope+body field** (incl. `created_at` and `created_seq`) — excluding **only** `integrity.content_hash` itself and signature/anchoring proof material (Rev-2.1 #3: so any stored-field change is detectable; process/generation ids are not receipt fields). **`conclusion_hash`** hashes only the authoritative canonical output, excluding receipt-instance metadata (`receipt_id`, `created_seq`, `created_at`, `integrity`). |
| Number normalization | MUST | **Per-field governed numeric profile** (Rev-2 #5) — NOT one implied precision. Each numeric field declares its profile, e.g. a **canonical decimal-string** at the field's scale: `line` (half-points), `probability` (fixed dp), `price` (American integer), `count` (integer). No `-0`; integers never serialized as floats. |
| Null handling | MUST | **Required fields are never absent/null** (Rev-2 #4). For an **optional** field, absent ≡ explicit-null **only when that field's schema declares the two identical**; defaults are **schema-declared, never inferred**. |
| Encoding | MUST | UTF-8; normalized unicode (NFC). |
| Hash algorithm | MUST | A single declared algorithm recorded in **`integrity.hash_algorithm`** (Rev-2 #7; separate from `mechanism`); `sha256` baseline. |

**Rules:** R10 Two conclusions identical under this canonical form MUST share a `conclusion_hash` (so
incidental formatting, and differing `created_seq`/`receipt_id`, never fail replay — Rev-2 #1,
Constitution §8). R11 `EXACT_REPLAY` MUST reproduce the canonical **conclusion** form from recorded
`input_hashes` + `versions`, matching `conclusion_hash` (not `content_hash`).

---

## 5. Grain-specific identity profiles

Base identity (Constitution §6): `sport + season + EventId + entity + market/stat`. Each grain extends it;
**no single universal key** across grains. Every profile MUST declare a collision test.

| Grain | Identity key (profile) | Extends base with | NFL ATS example |
|---|---|---|---|
| **Event** | `sport, season, EventId` | — | `nfl, 2026, 401...` (nflverse `game_id`) |
| **Team-side decision** | event + `TeamSide` | `TeamSide ∈ {HOME,AWAY}` | `(game_id, HOME)` — the audited CFB/NFL identity |
| **Market observation (quote)** | event + entity + market + `side, line, book, quote_scope, captured_obs_id` | direction/side, line, book, quote scope, capture ts/observation id | a captured prop line (Lane-2 shape) |
| **Selection** | event + entity + market + `selection_key` | the user/model selection id | an SGP leg |
| **Grading** | event + entity + market (resolves to the decision) | graded result ref | a graded ATS decision |

| Field (identity record) | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `grain` | enum | req | MUST | event \| team_side \| market_obs \| selection \| grading. |
| `base` | map | req | MUST | `{sport, season, event_id, entity?, market?}`. |
| `ext` | map | cond | MUST per grain | grain-specific extension fields (table above). |
| `identity_quality` | enum | req | MUST | `PROVIDER_ID` (a **provider-issued entity identifier**, e.g. a bare `game_id`/`event_id`) \| `DECLARED_COMPOSITE` (a governed multi-field key, e.g. `(game_id, TeamSide)` — records its `profile`+`version`+collision proof; Rev-2.1 #6) \| `COMPOSITE_NAME_EVENT` \| `ALIAS_RESOLVED` \| `NAME_ONLY` \| `AMBIGUOUS` \| `UNRESOLVED`. |
| `collision_tested` | bool | req | MUST | True only when the profile's collision test passed for this record (required for `DECLARED_COMPOSITE`/`COMPOSITE_NAME_EVENT`). |

**Rules:** R12 An authoritative join MUST use `PROVIDER_ID`, a declared composite, or `ALIAS_RESOLVED`
(curated exact) — never fuzzy (Constitution §6). R13 `AMBIGUOUS`/`UNRESOLVED`/`NAME_ONLY` MUST fail closed
(leaf `UNAVAILABLE`/`INDETERMINATE`). R14 A composite key MUST set `collision_tested=true` or be ineligible.

---

## 6. Correction linkage

| Field (correction receipt body) | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `supersedes_seq` | int | req | MUST | `created_seq` of the superseded receipt. This is a convenience copy; the **authoritative** reference is the envelope's `supersedes` (receipt_id). `supersedes_seq` MUST equal `envelope.supersedes`'s `created_seq` (Rev-2 #9b consistency validation). |
| `change_kind` | enum | req | MUST | `regrade` \| `line_correction` \| `reschedule` \| `identity_fix` \| `retraction`. |
| `before` | map | req | MUST | The prior value(s). |
| `after` | map | cond | MUST unless `retraction` | The new value(s). |
| `cause_clock` | map | opt | SHOULD | `{source_updated?, event_effective?}` that motivated it. |

**Rules:** R15 A correction MUST be a new receipt whose **authoritative** link is the envelope's
`supersedes` (receipt_id); the superseded receipt MUST remain unchanged. R15b A validator MUST reject a
correction whose body `supersedes_seq` does not equal `envelope.supersedes`'s `created_seq` (Rev-2 #9b).
R16 Lineage ordering MUST follow `created_seq`, **never** `source_updated` alone (Constitution §7/§8).
R17 A reader MUST be able to walk the `supersedes` chain to the current head and to every prior state.

---

## 7. Hierarchical references

A board (live-evidence) receipt MUST reference, not inline, its per-entity detail (Constitution §4
hierarchy):

| Ref (in `refs`) | Points to | Cardinality | Norm |
|---|---|---|---|
| `entity_dispositions` | a batch of entity-disposition records for the expected universe | 1 batch ref | MUST |
| `source_health` | the source-health receipt | 1 | MUST |

(Rev-2.1 #2: the immutable `live_evidence` receipt references **only** `entity_dispositions` +
`source_health` — **never `render`**. The `render` receipt is published later and references the evidence
receipt + its `conclusion_hash`/membership hash. The link is **forward-only render→evidence**, so the
immutable evidence receipt never needs a back-reference it cannot later add.)

**Rules:** R18 A board receipt MUST carry the membership hash + per-leaf counts, and reference (not copy)
the entity-disposition batch. R19 Per-row data MUST live in the entity-disposition records, referenced by
id — not duplicated into board or render receipts (volume control). R20 Counts in the board receipt MUST
reconcile against the referenced disposition batch (the §3 equations).

---

## 8. User-safe projection boundaries

| Internal-only (MUST be stripped from `user_safe`) | Rationale |
|---|---|
| raw provider payloads, provider internal ids beyond the public entity | licensing/security (Constitution §10) |
| model internals (weights, private formula params) | proprietary-model protection |
| secrets/tokens/keys | security |
| full `input_hashes` / internal lineage detail | internal audit only |
| account PII | PII minimization |

| Field | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `projection` | enum | req | MUST | `user_safe` here. |
| `claims` | list | req | MUST | Only claims the `internal` receipt supports (Constitution L10). |
| `disclosures` | list | SHOULD | Honest unavailable/partial/gated states surfaced to the user. |

**Rules:** R21 **Root-and-reference projection (Rev-2 #9c):** a `user_safe` receipt derives from one
**root** `internal` receipt and MAY include projections of that root's **referenced** internal receipts
(§7); each user-safe field MUST trace to a field in the root or a referenced internal receipt, and the
projection MUST NOT assert more than those internal receipts support. Because the board root does **not**
reference render (Rev-2.1 #2, forward-only render→board→decision), there are two distinct composite
projections and no backward board→render reference (Rev-2.2):
- a **user-safe evidence projection** derives from the **board evidence root** and its
  decision/disposition/source-health references;
- a **user-safe render projection** derives from the **render root**, which references the board
  evidence receipt (never the reverse).
R22 A `user_safe` receipt MUST NOT contain any internal-only field above.

---

## Cross-cutting A — Transition-event proposal (PROPOSED pilot invariant, not yet law)

A **transition record** captures a *governed change* in an authoritative conclusion over time (distinct
from a correction, which fixes a prior receipt; a transition marks that state legitimately moved).

**Provisional status (Rev-2):** `transition` is **NOT one of the six approved receipt kinds** (§1
`receipt_kind` enum is unchanged). Its envelope shape here is **PROVISIONAL** and MUST NOT be added as a
seventh kind until the pilot runs and governance decides. During the NFL ATS pilot a transition MAY be
recorded as a provisional/experimental record outside the approved kind set; promotion to a kind (and to
law) is a later governance step.

| Warrants a transition record (MUST, when adopted) | Does NOT (MUST NOT emit noise) |
|---|---|
| a member joins/leaves the factual set (streak crosses the threshold) | an unchanged rebuild (same membership hash) |
| a leaf disposition changes (`INDETERMINATE`→`RENDERED` once graded) | presentation-only change (sort re-label, cosmetic) |
| `synchronized` flips (healthy↔fail-closed) | a `created_at` difference with identical canonical content |
| graded-through boundary advances | re-serialization with no canonical-form change |

**Proposed pilot invariant "No Silent Transition":** *an authoritative surface SHOULD emit a transition
record for every governed change above, and MUST NOT present a changed state with no record of the change.*
This is proposed **as a pilot on NFL ATS only**, not yet a constitutional law; promotion to law requires a
later governance pass after the pilot shows it is noise-free.

**Transition granularity (P2A-T1) — ADOPTED (provisional pilot decision, Rev-2.2):** **per-board-delta**,
referencing the changed entity dispositions (keeps volume bounded; mirrors the §7 hierarchy). This holds
for the NFL ATS pilot only and is revisited in the post-pilot governance pass; it is not platform law.

---

## Cross-cutting B — NFL ATS pilot mapping (examples only; NOT a migration)

**Two linked universes (Rev-2.1 #1 — the rendered members are *teams*, not game decisions, so one equation
cannot reconcile both):**
- **Decision universe** — grain `(game_id, TeamSide)`. This grain is **supporting stage evidence consumed by
  calculation — it is never rendered to the user**, so it carries **stage outcomes**, not presentation leaves:
  `GRADED` (with `PUSH` / `VOID` where the result is a push/void) / `NO_LINE` / `OVERDUE` / `MALFORMED` /
  `OUTSIDE_BOUNDARY` (the Audit #2/#3 conservation partition). Its counts reconcile **independently**.
  `universe={grain:"team_side_decision", id:"nfl_ats_decisions_2026", version}`.
- **Board universe** — grain **one record per NFL team**, each computed from that team's *eligible decision
  history*. This is the **terminal-disposition** universe: each expected team ends in exactly one of
  `RENDERED` / `SUPPRESSED` / `NONMEMBER` / `UNAVAILABLE` / `INDETERMINATE` / `FAILED` / `EXCLUDED` (where
  applicable). `universe={grain:"team", id:"nfl_ats_board_2026", version}`.
- The **board receipt MUST reference the decision-universe/calculation receipt** (hierarchical, §7). The two
  equations reconcile **independently** (§3); game decisions and rendered teams are **never** summed in one
  equation.

How the audited `build_nfl_ats_wave` maps onto these contracts (illustrative; no code/behavior change):

| Contract | NFL ATS mapping (from Audit #2/#3 evidence) |
|---|---|
| Receipt envelope | two receipts: a **decision** evidence receipt (`universe` = the decision universe) and a **board** evidence receipt (`universe` = the board universe) that references it. `surface_id=nfl_ats_wave`; `authority_class=fact`; `replay_class=EVIDENCE_EQUIVALENT`; **clocks (Rev-2.1 #5):** `bk_captured`=sidecar `checked_at_utc` (a BK observation/check clock) / `content_fetched_at_utc`; **`source_updated=null`, `source_updated_status=NOT_PROVIDED`** — the nflverse games parquet exposes no provider source-update clock (the check clock is never substituted for it); `event_effective`=kickoff. |
| Stage outcomes vs terminal leaves (two universes) | **Decision universe** (`(game_id,TeamSide)`, no FBS/conference concept — that is CFB only) is **stage evidence consumed by calculation, never rendered**, so it carries **stage outcomes, not presentation leaves**: graded → `GRADED` (`PUSH`/`VOID` on a push/void); completed game with **no recorded spread** → `NO_LINE`; past-grace ungraded → `OVERDUE`; malformed spread → `MALFORMED`; future/within-grace → `OUTSIDE_BOUNDARY` out-of-universe tag (e.g. the 2 finished Week-8 decisions). Its counts reconcile independently; it receives **no** presentation leaf. **Board universe** (one record per team, from eligible decision history) is the **terminal-disposition** universe — each expected team gets exactly one: `cover_streak≥3` shown → `RENDERED`; admitted but display-capped → `SUPPRESSED`; below threshold → `NONMEMBER`; history `OVERDUE`/source-stale → `UNAVAILABLE`; not yet gradable → `INDETERMINATE`; `MALFORMED`/`CONFLICT` → `FAILED`; legitimately out → `EXCLUDED`. The **board receipt references the decision-stage receipt as evidence**. |
| Reason-code registry | **Decision-stage** (`stage_outcome`, never a presentation leaf): `GRADED`/`PUSH`/`VOID`; `NO_LINE`; `OVERDUE`; `MALFORMED`; `OUTSIDE_BOUNDARY`. **Health:** `SOURCE_STALE` (`health`). **Board leaves** (`leaf`, terminal): `BELOW_THRESHOLD` (cover_streak<3 → `NONMEMBER`); `OVERDUE`/`SOURCE_STALE` history → `UNAVAILABLE`; `MALFORMED`/`CONFLICT` → `FAILED`. `SORTED` + `sort_rule_id=streak_desc_team_asc` is a board-stage ordering (`stage_outcome`). (No FBS/conference codes — those belong to the CFB surface.) |
| Canonical serialization | the membership hash + sidecar `content_sha256` are the prototypes; member rows serialized sorted, excluding render timestamps. |
| Grain-specific identity | decision universe key `(game_id, TeamSide)` → `identity_quality=DECLARED_COMPOSITE` (Rev-2.1 #6: `game_id` alone is `PROVIDER_ID`, but the `(game_id,TeamSide)` composite is a governed declared key with its profile/version + collision proof recorded). Board universe key = NFL team (provider team name, sport-scoped). |
| Correction linkage | a regraded game or a corrected spread → a `correction` receipt (`change_kind=regrade`/`line_correction`) superseding the prior decision receipt. |
| Hierarchical refs | the **decision-stage** evidence receipt records team-side decision **stage outcomes** + the source-health receipt (sidecar freshness); the **board** evidence receipt references the decision-stage/calculation receipt + per-team board **terminal dispositions**; the **render receipt** references the board evidence receipt + its `conclusion_hash`/membership hash (forward-only render→board→decision, acyclic — Rev-2.1 #1/#2). |
| User-safe projection | user sees members + the honest empty state ("no active 3+ ATS cover streaks") + "sorted by active cover streak"; internal retains sha/lineage. |
| Transition-event (pilot) | a team crossing to a 3-cover streak, or `synchronized` flipping, emits a transition record; an unchanged rebuild does not. |

**Empty-membership state (Audit #2, `members=0`)** is a **valid, fully-receipted outcome**, not an
error, and resolves per universe (Rev-2.2 — the two grains never mix):
- The **decision universe** reconciles its decision **stage outcomes** independently — each
  `(game_id,TeamSide)` is `GRADED` (`PUSH`/`VOID` where applicable) / `NO_LINE` / `OVERDUE` / `MALFORMED`,
  future/within-grace → `OUTSIDE_BOUNDARY`. These are stage outcomes consumed by calculation, **never
  presentation leaves**, and are unaffected by board membership.
- The **board universe** assigns each expected NFL team exactly one terminal disposition
  (`RENDERED`/`SUPPRESSED`/`NONMEMBER`/`UNAVAILABLE`/`INDETERMINATE`/`FAILED`/`EXCLUDED`).
- With `members=0`, the board universe has `RENDERED=0` and all qualifying expected teams as
  `NONMEMBER` (max cover_streak was 2 — `BELOW_THRESHOLD`), conservation balanced, and the render
  receipt shows the honest empty state.

---

## Versioning & compatibility policy
- **`schema_version`** (envelope/body) is a structured **`{major, minor}`** (Rev-2.1 — not an integer);
  **`def_version`** (reason-code meaning) is an integer. They are independent (Constitution §5). A reader
  MUST honor its known versions and MUST reject (fail closed) an unknown `major`.
- **Additive** fields (new optional) are a MINOR bump (backward compatible); **breaking** changes (removed/
  retyped field, changed leaf set) are a MAJOR bump. Policy: `MAJOR.MINOR` per receipt kind.
- A reason-code **definition** change bumps `def_version`; the **code string never changes** (R8/R9).
- Identity **profiles** are versioned per grain; a profile change that alters the key is MAJOR.

## Decisions — ADOPTED (Rev-2.1, approved)
- **P2A-1 — ADOPTED:** receipt id = **opaque UUID** + **separate hashes** (`content_hash`,
  `conclusion_hash`); content-addressing is not the id (corrections would break it).
- **P2A-2 — ADOPTED:** `created_seq` scoped **per surface**.
- **P2A-3 — ADOPTED:** **one disposition batch per build**, referencing the universe id.
- **P2A-4 — ADOPTED:** **SHA-256 baseline** with an **allowlisted `hash_algorithm` field** (agility via an
  allowlist, not free-form).
- **P2A-5 — ADOPTED:** transition granularity = **per-board-delta** (referencing changed dispositions).
- **P2A-6 — ADOPTED:** boundary/season states (`OUTSIDE_BOUNDARY`/`OUT_OF_SEASON`) are **out-of-universe
  tags, reported separately**, not leaves of the Expected Universe (matches CFB ATS §3).
- **Transition — ADOPTED:** remains **provisional**, outside the six approved receipt kinds, pending pilot
  governance.

## Phase 2B implementation / QC plan (NO implementation written here)
When Phase 2A is approved, Phase 2B (still pre-production) SHOULD, in order:
1. Encode the envelope + leaf + reason-code + identity-profile + serialization contracts as shared
   library definitions (no surface wired).
2. Build validators (Constitution §11) as QC tools: receipt-envelope validator; leaf-exclusivity +
   conservation validator; reason-code registry validator; canonical-serialization/replay validator;
   identity-profile + collision validator; correction-lineage validator; hierarchical-reference +
   count-reconciliation validator; user-safe projection validator.
3. Author fixtures from the NFL ATS pilot mapping (valid + invalid) and prove each validator catches the
   invalid cases.
4. Report-only CI (no blocking yet), then a flagged, fail-closed runtime assertion (O-11a) — **Phase 2C**.
No database, production integration, surface migration, or runtime enforcement in Phase 2B.

## Valid / invalid examples (illustrative)
- **VALID** entity-disposition: `{entity_ref:(game_id,HOME), leaf:NONMEMBER, reason_code:BELOW_THRESHOLD,
  reason_def_version:1, params:{threshold:3}, identity_quality:PROVIDER_ID}`.
- **INVALID** (R5): `leaf:ELIGIBLE` — a roll-up is not a terminal leaf.
- **INVALID** (R8): `reason_code:SORTED_BY_streak_desc_team_asc` — interpolated runtime value in the code.
- **INVALID** (R6): a gated NBA injury side with `leaf:EXCLUDED` — gated data MUST be `UNAVAILABLE`.
- **INVALID** (L12/envelope): `integrity:{mechanism:none}` labeled `tamper_evident:true` — only
  integrity-verifiable without a real mechanism.
- **VALID** correction: `{receipt_kind:correction, supersedes:<rid-1041>, supersedes_seq:1041,
  change_kind:regrade, before:{result:Miss}, after:{result:Hit}}` with a new `created_seq`;
  `supersedes_seq` equals the superseded receipt's `created_seq` (R15b).
- **VALID (two hashes, Rev-2 #1):** two rebuilds of an unchanged NFL ATS board share one `conclusion_hash`
  but differ in `content_hash` and `created_seq` — they replay-equal (EXACT_REPLAY on `conclusion_hash`)
  yet are distinct immutable receipts.
- **INVALID (Rev-2 #2):** `content_hash` computed over a body that includes `integrity.content_hash` — a
  digest cannot cover itself; it MUST exclude `integrity.content_hash` + proof fields.
- **VALID (immutable render linkage, Rev-2 #3):** a `live_evidence` receipt refs `{entity_dispositions,
  source_health}`; later a `render` receipt refs that evidence receipt + its `conclusion_hash`. **INVALID:**
  publishing the evidence receipt with `render=0` and later mutating it to add the render ref (receipts are
  immutable; the link is forward-only from render→evidence).
- **VALID (clocks, Rev-2.1 #5):** NFL ATS `clocks={bk_captured:<sidecar checked_at>, source_updated:null,
  source_updated_status:"NOT_PROVIDED", event_effective:<kickoff>}`. **INVALID:**
  `source_updated:"UNKNOWN"` — a literal string violates the `instant[UTC]` type (use null + status).
  **INVALID:** `source_updated:<sidecar checked_at>` — the check clock is a BK observation, never the
  provider source-update clock.
- **INVALID (NFL ATS universe, Rev-2 #8):** an NFL ATS disposition `reason_code:KNOWN_NON_FBS` — FBS/
  conference concepts belong to the CFB surface, not NFL ATS.
- **VALID (numeric profile, Rev-2 #5):** `line` serialized `"-3.00"` (half-point profile), `price` `"-110"`
  (American integer), `probability` `"0.5000"` (fixed dp) — each per its declared profile, not one implied
  precision.
- **INVALID (version, Rev-2 #6):** `schema_version: 3` (bare int) — MUST be `{major:3, minor:0}`.

---

## Declaration
This Phase 2A deliverable is **design only**. **No code, schemas, registries, database files, runtime
flags, routes, or production behavior were created or changed.** It defines contracts for review.
**Phase 2B MUST NOT begin until Phase 2A receives explicit approval.**
