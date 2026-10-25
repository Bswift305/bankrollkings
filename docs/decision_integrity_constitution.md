# Decision Integrity Architecture Constitution — Rev 2

**Status: DESIGN ONLY — Rev 2 (revision pass applied; returned for formal approval before Phase 2).**
Date 2026-10-25. Rev 2 applies the reviewer's ten constitutional corrections, resolves the six open
questions with the supplied decisions, and adds hierarchical receipt composition. Still no code, schemas,
registries, validators, or production changes.
This is a **platform constitution**, not a feature spec. It defines the laws, contracts, and registries
every authoritative surface must obey, so that what the product shows can always be explained, reconciled,
and reproduced. No code, no schema files, no DB/JSON, no production changes accompany this document.

It codifies, as binding law, the patterns the three streak audits (Hot Hand, NFL ATS, CFB ATS) and the
capture-precision / entity-link work already proved in practice — and the incidents that motivated them.
It pairs with `BANKROLL_KINGS_DOCTRINE.md` (the why) and `docs/ats_wave_contract.md` (a frozen per-surface
contract that this generalizes).

Scope note: throughout, **"authoritative conclusion"** means any output the product presents as factual or
decision-bearing to a user or to another governed stage (a board row, a membership set, a streak, a
grade, a sync verdict). Pure presentation chrome is not authoritative.

---

## 1. Constitutional laws

These are invariants. A surface that cannot satisfy them is not eligible to present authoritative output;
it fails closed to an honest unavailable/indeterminate state (never a guess, never a silent partial).

- **L1 — Receipts.** Every authoritative conclusion emits a **versioned receipt** recording its inputs,
  stage outputs, reason codes, counts, and the versions that produced it. No receipt → not authoritative.
- **L2 — Exactly one terminal LEAF disposition.** Every entity in the expected universe receives **exactly
  one terminal leaf disposition** from the closed set
  `{ Excluded | Unavailable | Indeterminate | Failed | NonMember | Rendered | Suppressed }`. The nested
  conservation intermediates **`Eligible` and `Members` are NOT terminal dispositions** — they are roll-ups
  (§3), so an implementation must never record both `Eligible` (or `Members`) and `Rendered` as competing
  terminal states for the same entity. No entity is silently dropped; none is double-counted. (Proven
  necessary by the CFB ATS six-row remainder: `graded ⊇ expected` is not conservation.)
- **L3 — The UI never determines reasoning.** Membership, ordering, grading, and explanations are computed
  upstream and **emitted** to the view. Templates render builder-provided evidence; they never recompute
  membership or invent a reason. (Hot Hand F2: the label is builder-emitted, not reconstructed in Jinja.)
- **L4 — Every stage is observable.** Each stage (§2) emits **counts, health, reason codes, and versions**.
  "It looked fine" is not evidence; the per-stage receipt is.
- **L5 — Identity is explicit.** Authoritative joins use a declared identity (provider ID or a declared
  composite), never silent fuzzy name resolution (§6). Identity quality is classified and recorded.
- **L6 — Corrections are additive.** A changed input (rescheduled kickoff, regrade, line correction)
  produces a **new** record linked to what it supersedes; history is never silently rewritten (§8).
- **L7 — Pillars remain distinct.** Market facts, analytical context, research status, governed model
  reads, and the user's own thesis are separate layers and are never merged into a single composite score
  (doctrine §11; do-not-build list). Trust/authority classes are governed in §9.
- **L8 — Incomplete evidence is ineligible for authority.** A stage that cannot prove completeness/
  freshness fails closed; partial evidence never masquerades as a complete answer. (NFL/CFB ATS fail-closed
  sync; Hot Hand completed-week boundary.)
- **L9 — Decision-time preservation.** When an authoritative conclusion is recorded for later grading, it
  preserves **what was knowable at decision time** (the pregame quote, the line, the scope) and never
  back-fills it from hindsight. (Capture-precision: provable-pregame only; no post-start line used.)
- **L10 — One record, two audiences.** Internal (full-fidelity) and user-safe explanations derive from the
  **same** receipt; a user-facing claim can never assert more than the internal record supports.
- **L11 — Replayability is declared.** Every conclusion declares its reproducibility class (§8:
  `EXACT_REPLAY` / `EVIDENCE_EQUIVALENT` / `NON_REPLAYABLE`) and carries the hashes/versions that class
  requires.
- **L12 — Receipts are immutable and integrity-verifiable.** A published receipt is append-only; a
  correction is a new receipt that references it, never an edit in place. A bare content hash is NOT
  tamper-evidence (it can be recomputed after modification): a receipt is only called **tamper-evident**
  when backed by at least one genuine mechanism — **hash chaining**, **signed/keyed checkpoints**,
  **append-only/WORM storage**, **independently anchored manifests**, or **access-controlled audit logs**.
  Absent such a mechanism, the receipt is labeled **integrity-verifiable** (content-hashed), not
  tamper-evident. (Rev-2 correction #4.)

**Recommended default for a non-conforming surface:** render the honest unavailable/indeterminate state
with its reason code, exactly as the ATS boards and the post-F5 Hot Hand already do. Fail closed, disclose.

---

## 2. Stage model

The canonical pipeline. Each stage has declared inputs, outputs, permissible reason codes, required counts,
and a failure behavior. A stage may only consume the prior stage's declared outputs.

```
Source → Canonical Events → Identity Resolution → Eligibility → Calculation
       → Membership → Ordering → Presentation Eligibility → Render Reconciliation
```

| Stage | Inputs | Outputs | Permissible reason codes (examples) | Counts | Failure behavior |
|---|---|---|---|---|---|
| **Source** | provider/runtime artifact + sidecar | validated rows + source-health receipt | `SOURCE_FRESH`, `SOURCE_STALE`, `SOURCE_MISSING`, `SOURCE_CORRUPT`, `SCHEMA_INVALID` | rows, mtime/sidecar age, sha | fail closed on missing/corrupt/mismatch; **no mtime fallback** where a sidecar exists |
| **Canonical Events** | validated rows | canonical event keys — **`sport + season + EventId + entity identity + market/stat`**; a composite key is permitted ONLY when collision-tested and explicitly classified (Rev-2 #2: `(player,stat,week)` is insufficient — the Lane-2 investigation proved it) | `CANONICAL_OK`, `DUPLICATE_COLLAPSED`, `CONFLICT`, `MALFORMED` | unique events, collapsed, conflicts, malformed | conflict/malformed → fail closed |
| **Identity Resolution** | canonical events + identity registry | resolved entity ids + identity-quality class | `PROVIDER_ID`, `COMPOSITE_NAME_EVENT`, `ALIAS_RESOLVED`, `AMBIGUOUS`, `UNRESOLVED` | resolved, ambiguous, unresolved | ambiguous/unresolved for an authoritative join → ineligible (§6) |
| **Eligibility** | resolved entities + boundaries (season, completed week, line-bearing, conference, gate) | eligible set + exclusions | `ELIGIBLE`, `OUT_OF_SEASON`, `OUTSIDE_COMPLETED_BOUNDARY`, `NO_LINE`, `KNOWN_NON_FBS`, `UNKNOWN_CONFERENCE`, `DATA_RIGHTS_GATE`, `FUTURE_OR_PENDING` | expected, each exclusion class | UNKNOWN-class (e.g. conference) → fail closed |
| **Calculation** | eligible set | computed values (streak, grade, ATS sign, probability) | `GRADED`, `PENDING`, `PUSH`, `VOID`, `INDETERMINATE_MISSING_OBSERVATION` | graded/pending/void | uncomputable → `INDETERMINATE`, never fabricated |
| **Membership** | computed values + factual rule | member set (factual; model may never suppress) | `ADMITTED`, `BELOW_THRESHOLD`, `FAILED_CLOSED` | members, non-members | rule is factual + deterministic; model is overlay only (§9) |
| **Ordering** | member set + declared sort | ordered members + sort governance fields | `SORTED` (+ `sort_rule_id`, `sort_rule_version` — Rev-2 #7: stable code + governed fields, never a dynamic `SORTED_BY_<x>` code) | — | deterministic tiebreak; model never reorders beyond the declared factual sort |
| **Presentation Eligibility** | ordered members + display policy | rendered subset + suppressed | `RENDERED`, `SUPPRESSED_DISPLAY_LIMIT`, `SUPPRESSED_POLICY` | rendered, suppressed | suppression is disclosed + counted, never silent |
| **Render Reconciliation** | rendered subset | render receipt (two levels — Rev-2 #9) | `SERVER_RENDER_MATCHES_MEMBERSHIP`, `SERVER_RENDER_MISMATCH`, `CLIENT_RENDER_VERIFIED`, `CLIENT_RENDER_UNVERIFIED` | server-rendered rows vs membership hash; client/DOM-confirmed rows | **Level 1 (server):** deterministic server-render reconciliation — the server-generated HTML equals the membership/render receipt. **Level 2 (client/DOM):** confirmed only by browser tests or runtime telemetry. Level 1 is NOT claimed as proof of Level 2. Mismatch → alarm |

**O-2a — RESOLVED:** `Presentation Eligibility` and `Render Reconciliation` are **mandatory for every
authoritative board** and **optional for non-authoritative chrome**.

---

## 3. Expected-universe conservation

Conservation is **nested** (Rev-2 #1 + O-3a): authority conservation and presentation conservation are
separate equations that each reconcile **independently**. Mixing eligibility, membership, and rendering in
one equation was the Rev-1 error.

```
Expected Universe
  = Eligible
  + Excluded        (legitimate, e.g. KNOWN_NON_FBS, NO_LINE)
  + Unavailable     (fail-closed: source/identity/completeness unproven, incl. DATA_RIGHTS_GATE)
  + Indeterminate   (expected/completed but evidence missing — never silently a non-event)
  + Failed          (malformed / conflict / schema-invalid)

Eligible
  = Members
  + NonMembers      (eligible but did not qualify, e.g. BELOW_THRESHOLD)

Members
  = Rendered
  + Suppressed      (display-limit / policy; disclosed + counted)
```

Placement corrections (Rev-2 #1):
- **`DATA_RIGHTS_GATE` → `Unavailable`**, not ordinary `Excluded` (a gated datum is withheld because we may
  not serve it, not because it is legitimately out of scope).
- **`BELOW_THRESHOLD` → `NonMembers`** (eligible, computed, simply did not qualify) — never `Excluded`.

Rules:
- **Each equation reconciles independently, no overlap, no residual.** The authority equation balances the
  Expected Universe; the membership equation balances Eligible; the presentation equation balances Members.
  (The CFB ATS conservation probe — `expected_FBS + known_non_FBS + no_line + future_week + … = graded`,
  proven, no residual — is the prototype for the authority equation.)
- **Every universe declares its `grain`, `id`, and `version`** (what one row means, which universe it is,
  and the definition version in force) so two reconciliations are never silently compared across grains
  (the Lane-2 lesson: SnapshotDate-season vs GameDay-season were apples-to-oranges).
- **Entities outside the expected universe** (a completed game beyond the completed-week boundary, a
  different season) are classified in their own terminal category (`OUTSIDE_BOUNDARY`, `OUT_OF_SEASON`) and
  reported, never folded into Eligible/Excluded. (CFB ATS: the 6 `future_week` rows.)
- **Queried absent entities** (a user asks for an entity not in the universe — the Nico "expected but
  absent" case) get an explicit disposition (`NOT_IN_UNIVERSE`, `UNRESOLVED`, `GATED`), never a blank or a
  fabricated zero.
- **Indeterminate is first-class**, distinct from Excluded/Unavailable: a completed event the system
  *should* have but cannot prove (a completed appearance with no valid pregame observation) is
  `INDETERMINATE_MISSING_OBSERVATION`, not silently bridged and not a legitimate exclusion.

---

## 4. Receipt taxonomy (design, not implemented)

Six receipt kinds. Each is versioned (§5), immutable, and **integrity-verifiable** — a receipt is called
**tamper-evident only when its declared mechanism supports that claim** (chaining/signing/WORM/anchoring/
audit-log; §1 L12), otherwise it is integrity-verifiable (content-hashed). Each has an internal and a
user-safe projection (L10). No schema is drawn here — only purpose, required content, and lifecycle.

1. **Live evidence receipt** — for an authoritative board state as served. Content: stage counts + health,
   membership hash, ordering label, source-health reference, versions. Lifecycle: produced per build;
   superseded by the next build (prior retained per retention policy).
2. **Entity-disposition receipt** (Rev-2.1 #5 — renamed from "exclusion receipt": the dispositions are
   **not all exclusions** — `NonMember`/`BELOW_THRESHOLD`, `DATA_RIGHTS_GATE`→`Unavailable`, and
   `Indeterminate` are distinct terminal leaves, §3/L2). Records, per expected entity, its **one terminal
   leaf disposition** + entity id, identity quality, reason code + version, and the boundary/gate/threshold
   that produced it. This is where **F3** (defense props, unresolved identities) lives — a governed
   disposition record, not an ad-hoc banner.
3. **Decision-time receipt** — what was knowable when a decision/observation was recorded (L9). Content:
   the three clocks (§7), the quote/line/scope, identity, eligibility class, pre-event snapshot. This is the
   capture-precision record generalized.
4. **Correction receipt** — a superseding record (L6/L12). Content: reference to the superseded receipt,
   what changed (kickoff, grade, line), the new value, correction ordering key. Never an in-place edit.
5. **Render receipt** — what was rendered, reconciled to membership (stage 9), at **two levels** (Rev-2
   #9): *server* (the server-generated HTML equals the membership/render receipt — deterministic) and
   *client/DOM* (confirmed only by browser tests or runtime telemetry). The server level is never claimed
   as proof of the client level. Content: rendered entity set + hash, suppressed count, the membership hash
   it must equal, and the reconciliation level achieved.
6. **Operational / source-health receipt** — source freshness, sidecar/sha verification, provider state.
   **Must keep the provider dimension separate from the artifact dimension** (CFB: a CFBD quota outage ≠ a
   stale last-known-good artifact; a fresh artifact ≠ provider reachable).

**O-4a — RESOLVED:** **two linked receipts** — an evidence receipt ("what we computed") and a render
receipt ("what we showed"), joined by the membership hash. Clean separation.

### Hierarchical receipt composition (Rev-2 additional requirement)
To stay auditable without uncontrolled receipt volume, authoritative output does NOT duplicate a full
receipt per row. Instead it composes:

- a **board receipt** (the live-evidence receipt for the surface: stage counts/health, membership hash,
  sort governance, versions) that **references** —
- **entity-disposition records** (one terminal disposition per expected entity — the exclusion/membership
  detail; §3), stored once and referenced, not inlined per render;
- a **source-health receipt** (§4.6), referenced;
- a **linked render receipt** (above).

A reader walks board → dispositions → source-health → render. Per-row data lives in the referenced
disposition records, not copied into every board or render receipt.

---

## 5. Registries

Centralized, versioned governance so meanings never drift silently.

- **Terminal dispositions registry** — the closed set of terminal buckets (§3) + their definitions. Adding
  one is a governed change with a version bump.
- **Reason-code governance** — every reason code is defined once, with an owner and a definition; stages
  may only emit registered codes. (The stage table in §2 seeds this.)
- **Reason-definition versioning** — a code's *meaning* carries a version; if the definition changes, the
  version increments and receipts record which definition version they used.
- **Receipt schema versioning** — each receipt kind carries a schema version field.
- **Stage + authority classification registry** — which stages are authoritative, and each surface's
  authority class (§9).

**Binding rule (naming) — two prohibitions:**
- **No embedded version names.** Use stable code + version field: `disposition="EXPECTED_FBS",
  def_version=3` — never `EXPECTED_FBS_v3` as the code. (A code is an identity; a version is metadata.)
- **No dynamic/interpolated codes** (Rev-2 #7). A reason code is a fixed member of the registry, never a
  string built from runtime values. Governed parameters go in separate fields:
  `reason_code="SORTED", sort_rule_id="streak_desc_team_asc", sort_rule_version=1` — **never**
  `SORTED_BY_streak_desc_team_asc` as the code. The same applies to any `*_BY_<x>` / `*_<entity>` shape.

---

## 6. Identity contract

Authoritative joins resolve identity in a declared priority and record the quality used.

- **Priority:** (1) **provider ID** (e.g. CFBD `game_id`, Odds API `event_id`) → highest; (2) **declared
  composite** (e.g. `(GameID, TeamSide)`, `(Season, Game, GameDate, Player, Stat)`) → when no stable id;
  (3) **alias table** (explicit, curated) for known renames/short-forms; (4) otherwise `AMBIGUOUS` /
  `UNRESOLVED`.
- **Grain-specific identity (Rev-2.1 #3).** `sport + season + EventId + entity + market/stat` is the
  **base** event/entity identity; it does **not** uniquely identify every grain. Phase 2 defines
  **grain-specific identity profiles** that extend the base with governed dimensions where applicable —
  e.g. a **market observation** adds `direction/side`, `line`, `book`, `quote_scope`, `captured
  timestamp/observation id`; a **selection** adds its selection key; a **grading** record keys to the
  resolved event. **Do not force one universal key across the event, selection, quote-observation, and
  grading grains** — each grain declares its own profile (and its collision test).
- **Identity-quality classes (recorded on every resolved entity):** `PROVIDER_ID`, `COMPOSITE_NAME_EVENT`,
  `ALIAS_RESOLVED`, `NAME_ONLY`, `AMBIGUOUS`, `UNRESOLVED`. A `NAME_ONLY`/`AMBIGUOUS`/`UNRESOLVED` entity is
  **ineligible for an authoritative join** (fails closed to an exclusion/indeterminate disposition).
- **Ambiguous identities** (one key → many entities): never silently merged; recorded as `AMBIGUOUS` and
  excluded from authority until disambiguated. (CFB `(GameID,TeamSide)` identity-conflict → fail closed.)
- **Cross-sport collisions** (same name across sports/teams): resolution is always **sport-scoped**; names
  never cross-link across sports (the entity-link resolver already enforces this).
- **Alias policy (FROZEN, Rev-2 #10)** — the Rev-1 phrase "fuzzy allowed on exact match" was contradictory
  and is removed. The policy is three disjoint rules:
  1. **Curated exact aliases** (explicit, reviewed entries, e.g. `N.Collins → Nico Collins`) **may support
     authoritative resolution.** An alias hit is an exact match against a governed table, not a fuzzy score.
  2. **Fuzzy matching may only SUGGEST candidates** for human review or for clearly-labeled
     **non-authoritative** display — it never changes membership/ordering.
  3. **Fuzzy matching never automatically authorizes an identity join or link.** An authoritative join uses
     provider ID, declared composite, or a curated exact alias — full stop.
  (Nico Collins: `N.Collins` resolves via a curated alias/ID, never a silent fuzzy match that could drop or
  merge a player. The CFB overlay's exact-provider-name-or-omitted rule — misattributions 0 by construction
  — is an instance of rule 2.)

**O-6a — RESOLVED:** **per-sport alias registries behind one platform interface** (identity spaces don't
cross sports; one interface keeps callers uniform).

---

## 7. Time contract

Three clocks, never substituted for one another:

- **`source_updated`** — when the provider/bookmaker last updated the datum (provable UTC or absent).
- **`bk_captured`** — when BK ingested it (precise UTC, always available).
- **`user_observed`** — when the user saw the conclusion (render time).

Plus:
- **`event_effective`** — the event's own clock (kickoff / game start), tz-aware UTC. The decision-time
  gate (pregame vs post-start) compares `bk_captured`/`source_updated` against `event_effective`.
- **Timestamp-unknown behavior:** a clock that is absent or not provably tz-aware is **`UNKNOWN`** and
  **ineligible for temporal ordering** — never assumed UTC, never assumed pregame. (Capture-precision:
  date-only `SnapshotDate` → same-day is `TEMPORALLY_INDETERMINATE`, excluded from a pregame reference.)
- **Correction ordering (Rev-2 #8):** corrections are **never** ordered solely by `source_updated` —
  provider clocks can regress or arrive late. Four facts are recorded **separately**: `event_effective`
  (the event's clock), `source_updated` (provider), `bk_captured` (ingestion), and an **immutable receipt
  sequence** (a monotonic BK-assigned order). The **receipt sequence** preserves true observation history
  (the order in which BK learned things); the effective/source clocks describe the event itself. A
  correction references the superseded receipt by sequence, so late/regressing provider clocks can never
  reorder history.
- **Timezone requirement:** all stored instants are tz-aware ISO-8601 UTC. Eastern is a *display*
  projection only (via `services/timeutils`), never a stored authoritative instant.
- **No silent clock substitution:** a missing `source_updated` is never backfilled from `bk_captured`; they
  are distinct fields with distinct meanings.

---

## 8. Reproducibility and corrections

Every authoritative conclusion declares one reproducibility class and carries what it needs to honor it:

- **`EXACT_REPLAY`** — re-running the same inputs + versions yields an identical output **under a canonical
  serialization** (Rev-2 #5): equality is judged after normalizing field order and excluding runtime-only
  fields (generation timestamps, process ids), so two otherwise-identical conclusions never fail replay on
  incidental formatting. Requires canonical input hashes + build/config/rule versions; deterministic
  computations only.
- **`EVIDENCE_EQUIVALENT`** — inputs may have been superseded (regrades, line moves), but the receipt chain
  proves the conclusion was correct *given what was knowable then* (L9). The default for graded records.
- **`NON_REPLAYABLE`** — a dependency cannot be reconstructed (ephemeral provider state, unretained
  source). Must be **declared, not discovered**, and (Rev-2 #5) is **ineligible for governed authority**:
  it may appear only as explicitly degraded informational context, never as a factual or model-authoritative
  conclusion.
- **Canonical input hashes** — a stable hash of the exact inputs (the ATS sidecar sha + the candidate sha
  patterns generalize).
- **Build / config / rule versions** — code build id, config snapshot, and the rule/definition versions
  (§5) in force.
- **Correction + supersession lineage** — a correction receipt links to the superseded one; a reader can
  walk the chain to the current truth and to every prior state. (Rescheduled kickoff, regrade.)
- **Deterministic vs stochastic** — stochastic computations (simulations) record their seed + method
  version and declare `EVIDENCE_EQUIVALENT` (not `EXACT_REPLAY`) unless the seed is retained.

---

## 9. Trust and authority

Five classes, kept distinct (L7). The registry (§5) records each surface's authority class.

| Class | Definition | May influence visibility? | ordering? | selection/membership? | confidence? |
|---|---|---|---|---|---|
| **Fact** | graded result, recorded line, completed game | yes | yes (factual sort) | yes | n/a |
| **Derived context** | opponent-adjusted, SoS, situational splits | yes (as context) | **no** | **no** | as labeled context only |
| **Descriptive mismatch** | "model rates above/below the line" overlay | **no** | **no** | **no** | overlay only |
| **Governed model** | a registered model read with declared authority | **on a factual board: no.** As its OWN product: yes, within its grant | factual board: **no**; own product: yes | factual board: **no**; own product: yes | yes, within its grant |
| **User thesis** | the user's own angle (SGP thesis, saved view) | yes (their own view) | their own | their own | n/a (theirs) |

**Binding rule (FROZEN, Rev-2 #3) — the factual board vs the governed-model product are two different
conclusions:**
- **Factual boards** (Hot Hand, both ATS Waves, etc.): membership and ordering are **Fact-only**. A model
  or overlay may **annotate** a row but may **never remove, reorder, or rewrite** membership on the
  underlying factual board.
- **Governed-model products** (a recommendation/selection surface): a model may produce a **separate**
  recommendation/selection conclusion **under an explicit authority grant** in the model registry
  (`services/model_registry.py` lineage), with its **own** receipt. That conclusion is a distinct product,
  not a mutation of the factual board.
- **The model-product receipt MUST reference the factual-universe receipt it consumed** — so a reader can
  see exactly which facts the recommendation was built on, and the factual board remains independently
  reconcilable.

This removes the Rev-1 contradiction (a model could not be both "may influence membership if granted" and
"membership is Fact-only" — those are two different surfaces, now frozen apart).

---

## 10. Privacy, licensing, and security

- **Internal vs user-safe receipts (L10):** internal receipts may hold raw payload refs, provider ids, and
  model internals; the user-safe projection strips these to what the user may see and what the claim
  supports. A user-safe receipt never exceeds the internal record's support.
- **Dataset-level licensing:** every source carries its license (the legal register / nflverse CC BY 4.0,
  CFBD terms, Odds API, NBA data-rights gate). A receipt records the source license; a surface under a
  data-rights gate (NBA stats/injuries) fails closed to the cleared/market-only destination (`DATA_RIGHTS_
  GATE` disposition), never the gated content.
- **Retention limits (O-13a):** receipts have a retention class (decision-time + correction receipts
  retained longest for audit; live-evidence receipts rotate). **Do not set final durations in this design.**
  Define the retention *classes* in Phase 2, and **require privacy/legal approval before activating any
  account-linked retention**.
- **Personal-data minimization:** receipts store player/team *public* identities and market facts; no
  end-user PII beyond what account features require, and none in authoritative receipts.
- **Proprietary-model protection:** model internals (weights, private formulas) live only in internal
  receipts; user-safe projections expose the governed read + its authority class, not the mechanism.
- **Secret / raw-payload exclusion:** no API keys, tokens, or raw provider payloads in any published or
  user-safe receipt (the diagnostics already redact; this makes it law).
- **Immutability vs privacy deletion (FROZEN boundary, Rev-2 #6):** the Constitution cannot promise both
  immutable retention and deletion of the *same* record, so they are split:
  - the **immutable market/evidence receipt contains no user PII** (public entities + market facts only) —
    it is retained and never deleted;
  - a **deletable account-association record** *references* that receipt (so "which user saw/acted on this"
    is removable without touching the fact);
  - **user-authored content** (theses, saved views, journal entries) is **deletable**;
  - a correction/deletion **leaves a non-identifying tombstone** where legally appropriate (so lineage
    stays walkable without re-exposing deleted data);
  - **activating account-linked retention requires privacy/legal approval** (ties to O-13a).
  A data-access/deletion request thus removes the account association + user-authored content, never the
  PII-free market-fact receipts.

---

## 11. Enforcement layer (design)

The constitution is enforced by validators + CI, mirroring the QC pattern already in use (the `qc_*` and
`diag_*` tools are the prototypes). Design only here.

- **Receipt validator** — every authoritative output has a schema-valid, versioned receipt (L1).
- **Reason-code validator** — stages emit only registered codes with a definition version (§5).
- **Conservation tests** — the Expected-Universe equation holds with no residual/overlap (§3); the CFB ATS
  conservation probe is the template.
- **Identity tests** — authoritative joins use PROVIDER_ID/COMPOSITE only; no silent fuzzy (§6);
  collisions/ambiguous fail closed.
- **Replay determinism** — `EXACT_REPLAY` conclusions reproduce byte-identically from their recorded
  hashes/versions; `EVIDENCE_EQUIVALENT` chains resolve.
- **Correction lineage** — every correction references a superseded receipt; no in-place edits (L6/L12).
- **Render reconciliation** — the rendered page equals the membership/render receipt (stage 9).
- **CI rule:** an authoritative output without a conformant receipt **fails the build**. No receiptless
  authority ships.

**O-11a — RESOLVED:** **CI-first**, then **flagged runtime enforcement**. CI blocks receiptless
authoritative output at build time. Once receipts exist, add a runtime assertion behind a flag that **fails
closed to the honest unavailable state — never a 500** — when an authoritative response lacks a conformant
receipt.

---

## 12. Migration program (incremental, reversible)

No big-bang. Each phase is independently reversible and coexists with legacy surfaces.

1. **Constitution approval** (this document).
2. **Core contracts** — terminal-disposition + reason-code registries, receipt interfaces, the three-clock
   + identity contracts as shared services (no surface migrated yet).
3. **Enforcement** — validators + CI rule (initially report-only, then blocking).
4. **NFL ATS pilot** — the cleanest, already-contract-backed board becomes the first fully receipted
   surface (the enforcement pilot). Prove the whole chain end-to-end on it.
5. **Hot Hand / Heat Map** — carry the F5/F2 fixes into receipts + F3's entity-disposition records.
6. **Riding the Wave** — the prop-streak board, once the capture-precision history accrues (`BLOCKED_
   ACCUMULATING_VERIFIED_HISTORY`).
7. **Green Light** — convergence/lens attribution under the authority classes (§9).
8. **Lookup** — the change-first lookup store.
9. **SGP / King's Tickets** — book-specific legs + the held multi-leg handoff.
10. **Decision Journal + future models** — reasoning-to-result records + governed model reads.

**Exemptions:** a legacy surface not yet migrated is exempt but must be **labeled non-receipted** (not
silently trusted as if it were). **Rollback:** each phase reverts to the prior (legacy or earlier-phase)
behavior by a source/flag change, never a data migration that can't be undone. **Coexistence:** receipted
and legacy surfaces run side by side; the registry records which is which.

---

## 13. Worked examples (real incidents mapped to the constitution)

1. **Nico expected-but-absent** — a queried player absent from the board. Constitution: §3 queried-absent
   disposition (`UNRESOLVED`/`NOT_IN_UNIVERSE`) + §6 alias resolution for the `N.Collins` short form →
   explicit, never a silent drop. entity-disposition receipt (§4.2) records the reason.
2. **CFB identity collision avoided by `(GameID, TeamSide)`** — §6 composite identity + §2 Canonical Events
   conflict handling (exact repeat collapses, conflicting fails closed). Proven live in Audit #3.
3. **Hot Hand partial-week leakage (F5)** — §2 Eligibility completed-week boundary (filter before
   Calculation) + §3 `OUTSIDE_COMPLETED_BOUNDARY` vs `FUTURE_OR_PENDING`. The in-progress week cannot enter
   membership; the board fails to an honest "through Week N".
4. **NFL ATS factual empty state** — §9 Fact-only membership + §3 conservation: `members=0` is a true
   `BELOW_THRESHOLD` partition, rendered as an honest empty state, not a bug.
5. **NBA props validation failure** — §2 Source + Calculation fail-closed (`VALIDATION_FAILED`), §3
   `Failed`/`Unavailable`; a smaller current slate is judged by a completeness contract, never an absolute
   collapse vs a stale prior.
6. **Data-rights-gated injuries** — §10 licensing + §3 `DATA_RIGHTS_GATE` disposition; the surface fails
   closed to the cleared/market-only destination (`SKIP — DATA_RIGHTS_GATE`), never the gated content.
7. **Entity link resolved vs merely linked** — §6 identity quality: a link is emitted only when the entity
   resolves to a real sport-scoped destination (gate-aware `team_url`/`player_url`); unknown/ambiguous/gated
   → plain text, never a wrong or sport-less link (the schedule `/team/` fix).
8. **Correction receipt** — a rescheduled kickoff or a regrade: §8 supersession lineage + §4.4 correction
   receipt; the prior state is preserved, the new one references it, nothing is rewritten in place.

---

## Explicit decisions / recommended defaults (summary)
- Membership + factual sort are **Fact-only**; model is overlay (§9) — **decided**.
- Stable codes + version fields, never versioned code names (§5) — **decided**.
- Alias policy (§6, frozen): **curated exact aliases may authorize resolution; fuzzy matching may only
  suggest candidates or support explicitly non-authoritative display, and never authorizes a join** —
  **decided**.
- Three clocks never substituted; unknown-tz is ineligible (§7) — **decided**.
- Fail closed to honest unavailable/indeterminate, never partial/guess (L8) — **decided**.
- NFL ATS is the enforcement pilot (§12.4) — **decided**.

## Open questions — ALL RESOLVED in Rev 2 (per the supplied decisions)
- **O-2a** → mandatory for every authoritative board; optional for non-authoritative chrome.
- **O-3a** → nested conservation equations (§3); `Members = Rendered + Suppressed`.
- **O-4a** → two linked receipts (evidence + render); + hierarchical composition (§4).
- **O-6a** → per-sport alias registries behind one platform interface.
- **O-11a** → CI-first, then flagged runtime enforcement that fails closed (no 500).
- **O-13a** → no final durations now; define retention classes in Phase 2; privacy/legal approval before
  activating account-linked retention.

## Rev-2 corrections applied (changelog)
1. Nested authority/membership/presentation conservation; `DATA_RIGHTS_GATE`→Unavailable,
   `BELOW_THRESHOLD`→NonMembers; every universe declares grain/id/version (§3).
2. Canonical-event identity = `sport+season+EventId+entity+market/stat`; `(player,stat,week)` removed (§2).
3. Authority contradiction frozen: factual boards Fact-only; governed models are a separate product under
   a grant, referencing the factual-universe receipt; never mutate the factual board (§9).
4. L12 tamper-evidence requires a real mechanism (chaining/signing/WORM/anchoring/audit-log); otherwise
   "integrity-verifiable" (§1 L12).
5. `NON_REPLAYABLE` ineligible for governed authority; `EXACT_REPLAY` judged under canonical serialization
   (§8).
6. Immutable (PII-free) market receipt vs deletable account association + user content + tombstone +
   privacy/legal approval (§10).
7. No dynamic reason codes (`SORTED` + `sort_rule_id`/`sort_rule_version`, not `SORTED_BY_<x>`) (§5, §2).
8. Correction ordering uses an immutable receipt sequence, not solely `source_updated` (§7).
9. Render reconciliation split into server (deterministic) and client/DOM (telemetry/tests) levels (§2, §4).
10. Alias policy frozen: curated exact aliases authoritative; fuzzy only suggests / non-authoritative;
    fuzzy never auto-authorizes a join (§6).
+ Hierarchical receipt composition (board → entity-disposition records → source-health → render) (§4).

## Open items carried (NOT part of this design; not forgotten)
- **CFB ATS six-row remainder — RECONCILED** (Audit #3: all 6 are `future_week`, conservation proven; no
  action). Listed here only to close the loop.
- **NBA scheduled-slate acceptance receipt** — independent observation gate, still pending its prod run.
- **Owner visuals** — `/schedule`, WNBA dashboard, Hot Hand, and both ATS surfaces (presentation
  acceptance; non-blocking for this design).

**Deliverable status:** design document only. No implementation, no schema/DB/JSON files, no production
changes. **Returned for approval before Phase 2 (Core contracts).**
