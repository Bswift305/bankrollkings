# Decision Integrity Architecture Constitution

**Status: DESIGN ONLY — returned for approval before any implementation (Phase 2).** Date 2026-10-25.
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
- **L2 — Exactly one terminal disposition.** Every entity in the expected universe receives **exactly one**
  terminal disposition (§3). No entity is silently dropped; none is double-counted. (Proven necessary by
  the CFB ATS six-row remainder: `graded ⊇ expected` is not conservation.)
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
- **L12 — Receipts are immutable and tamper-evident.** A published receipt is append-only and carries a
  content hash; a correction is a new receipt that references it, never an edit in place.

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
| **Canonical Events** | validated rows | canonical event keys (e.g. `game_id`, `(player,stat,week)`) | `CANONICAL_OK`, `DUPLICATE_COLLAPSED`, `CONFLICT`, `MALFORMED` | unique events, collapsed, conflicts, malformed | conflict/malformed → fail closed |
| **Identity Resolution** | canonical events + identity registry | resolved entity ids + identity-quality class | `PROVIDER_ID`, `COMPOSITE_NAME_EVENT`, `ALIAS_RESOLVED`, `AMBIGUOUS`, `UNRESOLVED` | resolved, ambiguous, unresolved | ambiguous/unresolved for an authoritative join → ineligible (§6) |
| **Eligibility** | resolved entities + boundaries (season, completed week, line-bearing, conference, gate) | eligible set + exclusions | `ELIGIBLE`, `OUT_OF_SEASON`, `OUTSIDE_COMPLETED_BOUNDARY`, `NO_LINE`, `KNOWN_NON_FBS`, `UNKNOWN_CONFERENCE`, `DATA_RIGHTS_GATE`, `FUTURE_OR_PENDING` | expected, each exclusion class | UNKNOWN-class (e.g. conference) → fail closed |
| **Calculation** | eligible set | computed values (streak, grade, ATS sign, probability) | `GRADED`, `PENDING`, `PUSH`, `VOID`, `INDETERMINATE_MISSING_OBSERVATION` | graded/pending/void | uncomputable → `INDETERMINATE`, never fabricated |
| **Membership** | computed values + factual rule | member set (factual; model may never suppress) | `ADMITTED`, `BELOW_THRESHOLD`, `FAILED_CLOSED` | members, non-members | rule is factual + deterministic; model is overlay only (§9) |
| **Ordering** | member set + declared sort | ordered members + sort label | `SORTED_BY_<declared>` | — | deterministic tiebreak; model never reorders beyond the declared factual sort |
| **Presentation Eligibility** | ordered members + display policy | rendered subset + suppressed | `RENDERED`, `SUPPRESSED_DISPLAY_LIMIT`, `SUPPRESSED_POLICY` | rendered, suppressed | suppression is disclosed + counted, never silent |
| **Render Reconciliation** | rendered subset | render receipt (hash of what the page shows) | `RENDER_MATCHES_MEMBERSHIP`, `RENDER_MISMATCH` | rendered rows vs membership hash | mismatch → alarm (the page must equal the receipt) |

**Open question (O-2a):** should `Presentation Eligibility` and `Render Reconciliation` be mandatory for
every surface, or only for authoritative boards? **Recommended default:** mandatory for authoritative
boards; optional (but encouraged) for chrome.

---

## 3. Expected-universe conservation

Every entity in the expected universe lands in **exactly one** mutually-exclusive terminal bucket:

```
Expected Universe
  = Rendered
  + Excluded        (legitimate, e.g. KNOWN_NON_FBS, NO_LINE, DATA_RIGHTS_GATE)
  + Suppressed      (display-limit / policy; disclosed + counted)
  + Unavailable     (fail-closed: source/identity/completeness unproven)
  + Indeterminate   (completed/expected but evidence missing — never silently a non-event)
  + Failed          (malformed / conflict / schema-invalid)
```

Rules:
- **No overlap, no residual.** `sum(buckets) == |Expected Universe|`. (The CFB ATS conservation probe is
  the prototype: `expected_FBS + known_non_FBS + no_line + future_week + … = graded`, proven, no residual.)
- **Entities outside the expected universe** (e.g. a completed game beyond the completed-week boundary, or
  a different season) are classified in their own terminal category (`OUTSIDE_BOUNDARY`, `OUT_OF_SEASON`)
  and never counted as Rendered/Excluded; they are reported, not ignored.
- **Queried absent entities** (a user asks for a player/entity not in the universe — the Nico "expected but
  absent" case) get an explicit disposition (`NOT_IN_UNIVERSE`, `UNRESOLVED`, `GATED`) with a reason, never
  a blank or a fabricated zero.
- **Indeterminate is first-class** and distinct from Excluded/Unavailable: a completed event the system
  *should* have but cannot prove (e.g. a completed appearance with no valid pregame observation) is
  `INDETERMINATE_MISSING_OBSERVATION`, not silently bridged and not a legitimate exclusion.

**Open question (O-3a):** is `Suppressed` (display-limit) part of the Expected Universe conservation, or a
presentation-layer sub-partition of `Rendered + Suppressed`? **Recommended default:** a sub-partition of
the admitted members (`Rendered + Suppressed == Members`), itself reconciled, so authority-level
conservation uses Members while presentation-level conservation uses Rendered/Suppressed.

---

## 4. Receipt taxonomy (design, not implemented)

Six receipt kinds. Each is versioned (§5), immutable, tamper-evident (L12), and has an internal and a
user-safe projection (L10). No schema is drawn here — only purpose, required content, and lifecycle.

1. **Live evidence receipt** — for an authoritative board state as served. Content: stage counts + health,
   membership hash, ordering label, source-health reference, versions. Lifecycle: produced per build;
   superseded by the next build (prior retained per retention policy).
2. **Exclusion receipt** — why each expected entity is *not* a member. Content: entity id, identity
   quality, terminal disposition, reason code + version, the boundary/gate that excluded it. This is where
   **F3** (defense props, unresolved identities) lives — a governed absence record, not an ad-hoc banner.
3. **Decision-time receipt** — what was knowable when a decision/observation was recorded (L9). Content:
   the three clocks (§7), the quote/line/scope, identity, eligibility class, pre-event snapshot. This is the
   capture-precision record generalized.
4. **Correction receipt** — a superseding record (L6/L12). Content: reference to the superseded receipt,
   what changed (kickoff, grade, line), the new value, correction ordering key. Never an in-place edit.
5. **Render receipt** — what the page actually showed, reconciled to membership (stage 9). Content:
   rendered entity set + hash, suppressed count, the membership hash it must equal.
6. **Operational / source-health receipt** — source freshness, sidecar/sha verification, provider state.
   **Must keep the provider dimension separate from the artifact dimension** (CFB: a CFBD quota outage ≠ a
   stale last-known-good artifact; a fresh artifact ≠ provider reachable).

**Open question (O-4a):** live-evidence and render receipts could be one record with two sections, or two
linked records. **Recommended default:** two linked records (clean separation of "what we computed" vs
"what we showed"), joined by the membership hash.

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

**Binding rule (naming):** use **stable codes + explicit version fields**, never embedded version names.
`disposition="EXPECTED_FBS", def_version=3` — **never** `EXPECTED_FBS_v3` as the code. (A code is an
identity; a version is metadata. Baking the version into the code breaks every downstream match.)

---

## 6. Identity contract

Authoritative joins resolve identity in a declared priority and record the quality used.

- **Priority:** (1) **provider ID** (e.g. CFBD `game_id`, Odds API `event_id`) → highest; (2) **declared
  composite** (e.g. `(GameID, TeamSide)`, `(Season, Game, GameDate, Player, Stat)`) → when no stable id;
  (3) **alias table** (explicit, curated) for known renames/short-forms; (4) otherwise `AMBIGUOUS` /
  `UNRESOLVED`.
- **Identity-quality classes (recorded on every resolved entity):** `PROVIDER_ID`, `COMPOSITE_NAME_EVENT`,
  `ALIAS_RESOLVED`, `NAME_ONLY`, `AMBIGUOUS`, `UNRESOLVED`. A `NAME_ONLY`/`AMBIGUOUS`/`UNRESOLVED` entity is
  **ineligible for an authoritative join** (fails closed to an exclusion/indeterminate disposition).
- **Ambiguous identities** (one key → many entities): never silently merged; recorded as `AMBIGUOUS` and
  excluded from authority until disambiguated. (CFB `(GameID,TeamSide)` identity-conflict → fail closed.)
- **Cross-sport collisions** (same name across sports/teams): resolution is always **sport-scoped**; names
  never cross-link across sports (the entity-link resolver already enforces this).
- **Prohibition:** **no silent fuzzy resolution for authoritative joins.** Fuzzy/name-key resolution is
  permitted only for *presentation overlays that cannot change membership or ordering*, and even then only
  on an exact match (the CFB overlay rule: exact provider-name or omitted; misattributions 0 by
  construction). (Nico Collins: a short-form `N.Collins` must resolve via an explicit alias/ID, never a
  silent fuzzy match that drops or merges a player.)

**Open question (O-6a):** build a platform-wide alias registry now, or per-sport? **Recommended default:**
per-sport alias tables feeding one interface, since identity spaces don't cross sports.

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
- **Correction ordering:** corrections (§8) order by a declared correction key (source update time, then
  capture time), not by wall-clock of processing.
- **Timezone requirement:** all stored instants are tz-aware ISO-8601 UTC. Eastern is a *display*
  projection only (via `services/timeutils`), never a stored authoritative instant.
- **No silent clock substitution:** a missing `source_updated` is never backfilled from `bk_captured`; they
  are distinct fields with distinct meanings.

---

## 8. Reproducibility and corrections

Every authoritative conclusion declares one reproducibility class and carries what it needs to honor it:

- **`EXACT_REPLAY`** — re-running the same inputs + versions yields byte-identical output. Requires
  canonical input hashes + build/config/rule versions; only for deterministic computations.
- **`EVIDENCE_EQUIVALENT`** — inputs may have been superseded (regrades, line moves), but the receipt chain
  proves the conclusion was correct *given what was knowable then* (L9). The default for graded records.
- **`NON_REPLAYABLE`** — a dependency cannot be reconstructed (ephemeral provider state, unretained
  source). Must be declared, not discovered.
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
| **Governed model** | a registered model read with declared authority | only if the model registry grants it authority | only if granted | only if granted | yes, within its grant |
| **User thesis** | the user's own angle (SGP thesis, saved view) | yes (their own view) | their own | their own | n/a (theirs) |

**Binding rule:** **membership and the factual sort are Fact-only.** A model/overlay may annotate a row
but may **never suppress a qualifying entity or reorder beyond the declared factual sort** (the ATS
contract's firewall, generalized). Governed-model influence requires an explicit authority grant in the
model registry (`services/model_registry.py` lineage), with its own receipt.

---

## 10. Privacy, licensing, and security

- **Internal vs user-safe receipts (L10):** internal receipts may hold raw payload refs, provider ids, and
  model internals; the user-safe projection strips these to what the user may see and what the claim
  supports. A user-safe receipt never exceeds the internal record's support.
- **Dataset-level licensing:** every source carries its license (the legal register / nflverse CC BY 4.0,
  CFBD terms, Odds API, NBA data-rights gate). A receipt records the source license; a surface under a
  data-rights gate (NBA stats/injuries) fails closed to the cleared/market-only destination (`DATA_RIGHTS_
  GATE` disposition), never the gated content.
- **Retention limits:** receipts have a retention class (decision-time + correction receipts retained
  longest for audit; live-evidence receipts rotate). Define per class in Phase 2.
- **Personal-data minimization:** receipts store player/team *public* identities and market facts; no
  end-user PII beyond what account features require, and none in authoritative receipts.
- **Proprietary-model protection:** model internals (weights, private formulas) live only in internal
  receipts; user-safe projections expose the governed read + its authority class, not the mechanism.
- **Secret / raw-payload exclusion:** no API keys, tokens, or raw provider payloads in any published or
  user-safe receipt (the diagnostics already redact; this makes it law).
- **Account deletion / data access:** a data-access/deletion request must be able to find and remove a
  user's own data (saved views, journal, theses) without touching immutable *market-fact* receipts (which
  contain no PII). Define the boundary in Phase 2.

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

**Open question (O-11a):** enforce at runtime (reject a receiptless authoritative response) as well as in
CI? **Recommended default:** CI-first; add a runtime assertion in the enforcement phase once receipts exist,
behind a flag, failing closed to unavailable rather than 500.

---

## 12. Migration program (incremental, reversible)

No big-bang. Each phase is independently reversible and coexists with legacy surfaces.

1. **Constitution approval** (this document).
2. **Core contracts** — terminal-disposition + reason-code registries, receipt interfaces, the three-clock
   + identity contracts as shared services (no surface migrated yet).
3. **Enforcement** — validators + CI rule (initially report-only, then blocking).
4. **NFL ATS pilot** — the cleanest, already-contract-backed board becomes the first fully receipted
   surface (the enforcement pilot). Prove the whole chain end-to-end on it.
5. **Hot Hand / Heat Map** — carry the F5/F2 fixes into receipts + the F3 exclusion receipt.
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
   explicit, never a silent drop. Exclusion receipt (§4.2) records the reason.
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
- No silent fuzzy resolution for authoritative joins; fuzzy allowed only for non-membership overlays on
  exact match (§6) — **decided**.
- Three clocks never substituted; unknown-tz is ineligible (§7) — **decided**.
- Fail closed to honest unavailable/indeterminate, never partial/guess (L8) — **decided**.
- NFL ATS is the enforcement pilot (§12.4) — **decided**.

## Open questions (for the approval pass)
- **O-2a** mandatory presentation-eligibility/render-reconciliation scope.
- **O-3a** where display-limit suppression sits in conservation.
- **O-4a** one live+render receipt vs two linked.
- **O-6a** alias registry platform-wide vs per-sport.
- **O-11a** runtime enforcement vs CI-only.
- **O-13a** retention windows per receipt class (Phase 2).

## Open items carried (NOT part of this design; not forgotten)
- **CFB ATS six-row remainder — RECONCILED** (Audit #3: all 6 are `future_week`, conservation proven; no
  action). Listed here only to close the loop.
- **NBA scheduled-slate acceptance receipt** — independent observation gate, still pending its prod run.
- **Owner visuals** — `/schedule`, WNBA dashboard, Hot Hand, and both ATS surfaces (presentation
  acceptance; non-blocking for this design).

**Deliverable status:** design document only. No implementation, no schema/DB/JSON files, no production
changes. **Returned for approval before Phase 2 (Core contracts).**
