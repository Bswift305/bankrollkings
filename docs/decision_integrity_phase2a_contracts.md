# Decision Integrity — Phase 2A Contracts (DESIGN ONLY)

**Status: Phase 2A — contracts-only. Returned for explicit approval before Phase 2B.** Date 2026-10-25.
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
| `schema_version` | int | req | MUST | Envelope+body schema version (registry §3). Integer, monotonically increasing. |
| `surface_id` | string | req | MUST | The authoritative surface (e.g. `nfl_ats_wave`). |
| `universe` | map | req | MUST | `{grain, id, version}` of the universe this receipt reconciles (Constitution §3). |
| `created_seq` | int | req | MUST | Immutable monotonic BK sequence (Constitution §7/§8); the authority on ordering. |
| `created_at` | instant[UTC] | req | MUST | Wall-clock creation; **informational only**, never used for correction ordering. |
| `clocks` | map | cond | MUST when the receipt bears event/observation time | `{source_updated?, bk_captured, event_effective?}` (§5/§6; `bk_captured` req, others opt per grain). |
| `input_hashes` | list<hash> | cond | MUST when `replay_class != NON_REPLAYABLE` | Canonical input hashes (§4). |
| `versions` | map | req | MUST | `{build_id, config_version, rule_versions{…}}` in force. |
| `replay_class` | enum | req | MUST | `EXACT_REPLAY` \| `EVIDENCE_EQUIVALENT` \| `NON_REPLAYABLE` (Constitution §8). |
| `integrity` | map | req | MUST | `{content_hash, mechanism}`; `mechanism ∈ {none, hash_chain, signed, worm, anchored, audit_log}`. **`tamper_evident` is true only when `mechanism != none`** (Constitution L12); otherwise the receipt is integrity-verifiable. |
| `supersedes` | ref | opt | MUST when this is a correction | Points to the `receipt_id` this supersedes (§6). |
| `refs` | map | cond | MUST for composite receipts | Hierarchical references (§7), e.g. `{entity_dispositions, source_health, render}`. |
| `authority_class` | enum | req | MUST | `fact` \| `derived_context` \| `descriptive_mismatch` \| `governed_model` \| `user_thesis` (Constitution §9). |
| `projection` | enum | req | MUST | `internal` \| `user_safe` (§8). A `user_safe` receipt MUST NOT contain fields its `internal` source lacks. |

**Rules:** R1 A receipt MUST NOT be edited after publication; a change is a new receipt with `supersedes`
(Constitution L6/L12). R2 `created_seq` MUST be unique and monotonic per surface. R3 `content_hash` MUST
cover the envelope+body under the canonical serialization (§4).

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
| `leaf_or_health` | enum | req | MUST | The leaf (§2) or health state it maps to. |
| `param_fields` | list<string> | opt | SHOULD | Names of governed params carried alongside (e.g. `sort_rule_id`). |

**Rules:** R7 A stage MUST emit only registered codes. R8 Codes MUST be stable identifiers; governed
variation goes in `param_fields` (e.g. `reason_code=SORTED, sort_rule_id=…, sort_rule_version=…`), **never**
`SORTED_BY_<x>`. R9 Changing a definition MUST bump `def_version`; the code string MUST NOT change.

---

## 4. Canonical serialization (for hashing + EXACT_REPLAY)

Equality for `EXACT_REPLAY` and all `content_hash`/`input_hashes` MUST be judged under one canonical form:

| Rule | Norm | Detail |
|---|---|---|
| Field ordering | MUST | Object keys sorted lexicographically; order-independent. |
| Excluded fields | MUST | Runtime-only fields excluded from the hash: `created_at`, process ids, generation timestamps, any `projection`-specific display text. `created_seq` **is** included. |
| Number normalization | MUST | Decimals in a fixed precision (e.g. lines to 2 dp); no `-0`; integers not float. |
| Null handling | MUST | Absent vs explicit-null are equal; a field at its documented default MAY be omitted. |
| Encoding | MUST | UTF-8; normalized unicode (NFC). |
| Hash algorithm | MUST | A single declared algorithm (SHA-256 baseline); recorded in `integrity.mechanism` context. |

**Rules:** R10 Two conclusions identical under this canonical form MUST hash identically (so incidental
formatting never fails replay — Constitution §8). R11 `EXACT_REPLAY` MUST reproduce the canonical form
byte-for-byte from recorded `input_hashes` + `versions`.

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
| `identity_quality` | enum | req | MUST | `PROVIDER_ID` \| `COMPOSITE_NAME_EVENT` \| `ALIAS_RESOLVED` \| `NAME_ONLY` \| `AMBIGUOUS` \| `UNRESOLVED`. |
| `collision_tested` | bool | req | MUST | True only when the profile's collision test passed for this record. |

**Rules:** R12 An authoritative join MUST use `PROVIDER_ID`, a declared composite, or `ALIAS_RESOLVED`
(curated exact) — never fuzzy (Constitution §6). R13 `AMBIGUOUS`/`UNRESOLVED`/`NAME_ONLY` MUST fail closed
(leaf `UNAVAILABLE`/`INDETERMINATE`). R14 A composite key MUST set `collision_tested=true` or be ineligible.

---

## 6. Correction linkage

| Field (correction receipt body) | Type | Null? | Norm | Meaning |
|---|---|---|---|---|
| `supersedes_seq` | int | req | MUST | `created_seq` of the superseded receipt. |
| `change_kind` | enum | req | MUST | `regrade` \| `line_correction` \| `reschedule` \| `identity_fix` \| `retraction`. |
| `before` | map | req | MUST | The prior value(s). |
| `after` | map | cond | MUST unless `retraction` | The new value(s). |
| `cause_clock` | map | opt | SHOULD | `{source_updated?, event_effective?}` that motivated it. |

**Rules:** R15 A correction MUST be a new receipt referencing `supersedes_seq`; the superseded receipt MUST
remain unchanged. R16 Lineage ordering MUST follow `created_seq`, **never** `source_updated` alone
(Constitution §7/§8). R17 A reader MUST be able to walk `supersedes_seq` to the current head and to every
prior state.

---

## 7. Hierarchical references

A board (live-evidence) receipt MUST reference, not inline, its per-entity detail (Constitution §4
hierarchy):

| Ref (in `refs`) | Points to | Cardinality | Norm |
|---|---|---|---|
| `entity_dispositions` | a batch of entity-disposition records for the expected universe | 1 batch ref | MUST |
| `source_health` | the source-health receipt | 1 | MUST |
| `render` | the linked render receipt | 0..1 (0 until rendered) | MUST when rendered |

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

**Rules:** R21 A `user_safe` receipt MUST derive from exactly one `internal` receipt and MUST NOT assert
more than it supports. R22 A `user_safe` receipt MUST NOT contain any internal-only field above.

---

## Cross-cutting A — Transition-event proposal (PROPOSED pilot invariant, not yet law)

A **transition record** captures a *governed change* in an authoritative conclusion over time (distinct
from a correction, which fixes a prior receipt; a transition marks that state legitimately moved).

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

**Unresolved (P2A-T1):** transition granularity — per-entity vs per-board-delta. **Recommended default:**
per-board-delta referencing changed entity dispositions (keeps volume bounded; mirrors §7 hierarchy).

---

## Cross-cutting B — NFL ATS pilot mapping (examples only; NOT a migration)

How the audited `build_nfl_ats_wave` maps onto these contracts (illustrative; no code/behavior change):

| Contract | NFL ATS mapping (from Audit #2/#3 evidence) |
|---|---|
| Receipt envelope | `surface_id=nfl_ats_wave`; `universe={grain:"team_side_decision", id:"nfl_ats_2026", version:…}`; `authority_class=fact`; `replay_class=EVIDENCE_EQUIVALENT`; `clocks.source_updated`=sidecar `checked_at_utc`, `bk_captured`=fetch time, `event_effective`=kickoff. |
| Terminal leaves | the conservation partition already proven: `expected_FBS`→Members/NonMember(by streak), `known_non_FBS`→`EXCLUDED`, `no_line`→`EXCLUDED`, `future_week`/`not_completed`→`OUTSIDE_BOUNDARY` (outside universe), overdue→`UNAVAILABLE`, conflict→`FAILED`. |
| Reason-code registry | `SORTED` + `sort_rule_id=streak_desc_team_asc`; `BELOW_THRESHOLD` (cover_streak<3); `KNOWN_NON_FBS`; `NO_LINE`; `SOURCE_STALE`; `OVERDUE`. |
| Canonical serialization | the membership hash + sidecar `content_sha256` are the prototypes; member rows serialized sorted, excluding render timestamps. |
| Grain-specific identity | `team_side_decision` = `(game_id, TeamSide)` — the audited authoritative key; `identity_quality=PROVIDER_ID`. |
| Correction linkage | a regraded game or a corrected spread → a `correction` receipt (`change_kind=regrade`/`line_correction`) superseding the prior decision receipt. |
| Hierarchical refs | a board receipt for the wave references entity-disposition records for all expected FBS sides + the source-health receipt (sidecar freshness) + a render receipt. |
| User-safe projection | user sees members + the honest empty state ("no active 3+ ATS cover streaks") + "sorted by active cover streak"; internal retains sha/lineage. |
| Transition-event (pilot) | a team crossing to a 3-cover streak, or `synchronized` flipping, emits a transition record; an unchanged rebuild does not. |

**Empty-membership state (Audit #2, `members=0`)** maps to: all expected FBS decisions dispositioned
(`RENDERED`=0, `NONMEMBER`=all), conservation balanced, render receipt shows the honest empty state — a
**valid, fully-receipted outcome**, not an error.

---

## Versioning & compatibility policy
- **`schema_version`** (envelope/body) and **`def_version`** (reason-code meaning) are independent integers
  (Constitution §5). A reader MUST honor its known versions and MUST reject (fail closed) an unknown MAJOR.
- **Additive** fields (new optional) are a MINOR bump (backward compatible); **breaking** changes (removed/
  retyped field, changed leaf set) are a MAJOR bump. Policy: `MAJOR.MINOR` per receipt kind.
- A reason-code **definition** change bumps `def_version`; the **code string never changes** (R8/R9).
- Identity **profiles** are versioned per grain; a profile change that alters the key is MAJOR.

## Unresolved decisions (with recommended defaults)
- **P2A-1** receipt id scheme (uuid vs content-addressed). *Default:* opaque uuid + separate `content_hash`
  (content-addressing couples id to content, which corrections break).
- **P2A-2** `created_seq` scope — per surface vs global. *Default:* per surface (simpler monotonicity;
  cross-surface ordering not needed).
- **P2A-3** entity-disposition batching grain — one batch per build vs per universe. *Default:* per build,
  referencing the universe id.
- **P2A-4** hash algorithm agility (allow future algorithms). *Default:* record algorithm in `integrity`;
  SHA-256 baseline; add agility in a MINOR bump if needed.
- **P2A-5** transition granularity (= P2A-T1). *Default:* per-board-delta.
- **P2A-6** where `OUTSIDE_BOUNDARY`/`OUT_OF_SEASON` sit — a leaf vs an out-of-universe tag. *Default:*
  out-of-universe tag (not a leaf of the Expected Universe), reported separately (matches CFB ATS §3).

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
- **VALID** correction: `{receipt_kind:correction, supersedes_seq:1041, change_kind:regrade,
  before:{result:Miss}, after:{result:Hit}}` with a new `created_seq`.

---

## Declaration
This Phase 2A deliverable is **design only**. **No code, schemas, registries, database files, runtime
flags, routes, or production behavior were created or changed.** It defines contracts for review.
**Phase 2B MUST NOT begin until Phase 2A receives explicit approval.**
