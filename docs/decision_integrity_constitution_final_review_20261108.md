# Decision Integrity Constitution — final-review package (read-only, 2026-11-08) — UNCOMMITTED DRAFT

Review memo only. **No new policy, no reinterpretation, no implementation requirement** beyond the approved text.
Where the record is unclear it is **flagged, not resolved**. No code, branch, commit, push or program-table change.
Program position: ∥ G / G-1 (`docs/PROGRAM_TABLE.md`) — "Owner approval ⇒ versioned + frozen; no Phase 2 implementation."

## 1. Exact current revision and controlling document

| Document | Approved revision | Where the approved text lives | Identity |
|---|---|---|---|
| **Constitution** `docs/decision_integrity_constitution.md` | **Rev 2.1** (`7863a3d` Rev 1 → `bac0c6d` Rev 2 → `146589e` Rev 2.1, all 2026-10-25) | **`origin/master` = prod `b12eec3`**; byte-identical on `program/ledger` and `claude/jolly-ishizaka-c6519a` | git blob `634d98e6366af557193e24372d61728848777c30` |
| Phase 2A contracts `docs/decision_integrity_phase2a_contracts.md` (subordinate, design) | **Rev 2.2 approved** (`d5700c5`) per program table G-1; later **Rev 2.3** (`73a1fba`) and **Rev 2.3a** (`baa7d37`) exist | Rev 2.2–2.3a **only on paused branch** `claude/jolly-ishizaka-c6519a` @ `9db4583`; master holds **Rev 2** (`ed0bf37`, blob `1652cc4…`) | Rev 2.2 blob `7fd6f9f…`; Rev 2.3a blob `b01b4c9…` |

**Controlling document:** the Constitution at blob `634d98e…` (commit `146589e`). Phase 2A is a subordinate
design contract and is not part of the Constitution freeze unless the owner says so (see F-4).

Companion documents the Constitution names (governs alongside, not inside): `BANKROLL_KINGS_DOCTRINE.md` (the
why, §11 product contract) and `docs/ats_wave_contract.md` (a frozen per-surface contract it generalizes).

## 2. Recorded owner approvals (only what the record shows)

| Date | Approval | Evidence |
|---|---|---|
| 2026-10-25 | Rev 1 "accepted in direction"; ten corrections and six open-question decisions supplied by the reviewer | `bac0c6d` message |
| 2026-10-25 | **Constitution Rev 2.1 approved**; Phase 2A (contracts only) may begin | `146589e` message ("on clean verification, Phase 2A may begin"); `d37b84f` cites "the approved Constitution Rev 2.1"; program table G-1 "Rev 2.1 approved" |
| 2026-10-25 | **Phase 2A Rev 2.2 design approved**; adopted defaults P2A-1…6; transition = provisional pilot invariant (NFL ATS only), not law | G-1 row; Phase 2A "Decisions — ADOPTED"; `d5700c5` |
| 2026-10-25 | Phase 2A Rev 2.3a described as a "narrow, authorized amendment" (adds `team` grain) | `baa7d37` message only |
| 2026-10-25 | Phase 2B Slices 1–3 approved and closed (local, pre-production); 2C-dark pilot built, local wiring closed as fail-closed / not runnable | branch commits `b585f3c`, `15df219`, `04dc181`, `d8bcb86`; project memory |
| 2026-11-07 | Program reset: Constitution = parallel governance item "final owner review, version, freeze"; no Phase 2 implementation; Phase 2 is the owner's choice at position 5 | `docs/PROGRAM_TABLE.md` controlling program order |

**Not found:** no recorded owner approval of the Constitution as **frozen**; this package prepares that decision.

## 3. Unresolved contradictions and open decisions (flagged, not resolved)

- **F-1 Header label.** The Constitution's title and status line still read **"Rev 2"** / "returned for formal
  approval", though the body carries the Rev 2.1 corrections (`146589e`). The header text and the approved
  revision disagree. *Owner decision:* whether to freeze the text as-is under a version identifier (§8), or
  correct the header first as a documented amendment.
- **F-2 Phase 2A revision.** G-1 records Rev 2.2 as approved. Rev 2.3 is described as a "final semantic
  correction before Phase 2B" and Rev 2.3a as "authorized"; neither has a separately recorded owner approval.
  The Phase 2A header also still reads "Rev 2.1". *Owner decision:* which Phase 2A revision is approved.
- **F-3 Approved Phase 2A not on master.** Master/prod carries Phase 2A **Rev 2**, older than the approved
  Rev 2.2. Anyone reading master sees a superseded contract.
- **F-4 Freeze scope.** It is unclear whether the freeze covers the Constitution only, or the Constitution plus
  Phase 2A plus the Research Candidate Contract. G-2 says the Research Candidate Contract is "folded into the G-1
  review".
- **F-5 Research Candidate Contract status.** G-2 says "DESIGN (stopped for review)". Project memory and later
  branch commits record **Rev 2.1 APPROVED** with Slices 1–2D1 built, and 2D1 deployed OFF (`628657b`). The doc's
  own status line still says "Returned for review". These disagree.
- **F-6 Exemptions and new surfaces.** §12 exempts "a legacy surface not yet migrated" if it is labeled
  non-receipted. It does not say whether a **new** surface built before Phase 2 exists (e.g. NCAAB) is "legacy"
  for this purpose. The text does not specify where or how "labeled non-receipted" appears.
- **F-7 Promotion.** The Constitution does not define how something is **promoted** to authority. §9 says a
  governed model needs "an explicit authority grant in the model registry". The separate
  `docs/lens_governance_constitution.md` defines lens promotion and failure tests (≥ 25 settled, human decision,
  no automatic promotion). The Constitution does not say how these relate. CLAUDE.md §10 ("out-of-sample or it does
  not count") is operating guidance, not Constitution text.
- **F-8 Convergence classification.** §9 does not say which authority class a **lens-agreement count** belongs to.
  Derived context may not influence ordering. A governed model may order only "as its own product" under a grant;
  no Green Light grant exists. Classic's convergence sort was approved separately (`c4ca828` S6; `60226f6`), and
  1A must keep "the owner's convergence workflow intact". The relationship is not stated (see §5).
- **F-9 Amendment process.** The Constitution has no amendment clause. G-1 says "reopen only for a documented
  contradiction/amendment". §5 describes versioned governed change for registries only (see §9 below).
- **Open by design (deferred to Phase 2 in the text):** retention durations (O-13a, classes only), account-linked
  retention needs privacy/legal approval, transition receipts provisional.

## 4. Rules by area (citations to the approved text; quoted in substance, not reworded)

| Area | Constitution rule(s) |
|---|---|
| **Factual evidence** | §9 *Fact* class (graded result, recorded line, completed game) may drive visibility, factual ordering and membership. Factual boards: membership and ordering are Fact-only. L1 receipts, L2 exactly one terminal leaf, L3 UI never reasons. |
| **Derived evidence** | §9 *Derived context* (opponent-adjusted, SoS, splits): visibility as context only, **no** ordering, **no** membership, confidence only as labeled context. *Descriptive mismatch*: overlay only. |
| **Models** | §9 *Governed model*: on a factual board it may annotate but **never remove, reorder or rewrite** membership. As its own product it may select or order only under an explicit model-registry grant, with its own receipt that **references the factual-universe receipt**. L7 pillars never merged into a composite score. |
| **Prices / sportsbook attribution** | §6 grain-specific identity: a market observation extends the base key (`sport+season+EventId+entity+market/stat`) with **direction/side, line, book, quote_scope, captured timestamp/observation id**; no single universal key across grains. L9 preserve the pregame quote/line/scope. §10 every source carries its licence. |
| **Freshness** | §2 Source stage: `SOURCE_FRESH/STALE/MISSING/CORRUPT`; fail closed; **no mtime fallback where a sidecar exists**. §7 three clocks (`source_updated`, `bk_captured`, `user_observed`) + `event_effective`, **never substituted**; unknown/non-tz-aware clock is `UNKNOWN` and ineligible for temporal ordering; missing `source_updated` never backfilled from `bk_captured`. §4.6 provider dimension ≠ artifact dimension. |
| **Missing / contradictory evidence** | §3 *Indeterminate* is first-class (`INDETERMINATE_MISSING_OBSERVATION`), distinct from Excluded/Unavailable; queried-absent entities get an explicit disposition, never a blank or zero. §2 Canonical Events `CONFLICT/MALFORMED` → fail closed; §6 `AMBIGUOUS/UNRESOLVED/NAME_ONLY` ineligible for authoritative joins; fuzzy match never authorizes a join. |
| **Abstention** | §1 preamble + L8: a surface that cannot satisfy the laws fails closed to an **honest unavailable/indeterminate state with its reason code** (never a guess or silent partial). §11 O-11a runtime enforcement fails closed, **never a 500**. §10 data-rights gate → `Unavailable`, never the gated content. |
| **User observations** | §9 *User thesis*: governs only the user's own view. §10 user-authored content is **deletable**. The account association is a deletable record that **references** PII-free immutable receipts. Tombstones where legally appropriate. Account-linked retention needs privacy/legal approval. (Detail lives in the Research Candidate Contract — F-5.) |
| **Postgame evaluation** | L9 decision-time preservation (never back-filled from hindsight). §4.3 decision-time receipt. §8 `EVIDENCE_EQUIVALENT` is the default for graded records. `NON_REPLAYABLE` is ineligible for governed authority. L6/L12 + §4.4 corrections are additive, superseding receipts. §7 correction ordering by immutable receipt sequence, not by `source_updated` alone. |
| **Authority / promotion** | §9 five classes + binding rule (factual board vs governed-model product). §5 stage + authority classification registry. Promotion mechanism not defined (F-7). |

## 5. Green Light Classic restoration (1A/1B) — conformance check

Checked against the 1A scope in the controlling program order. **No conflict was found with any approved
rule.** Several 1A items apply rules directly:
- item (1) kickoff eligibility on `EventCommenceAtUTC` → §7 `event_effective` gate;
- items (2), (9) availability and stale suppression, with unavailable / missing / no-result kept distinct → L8,
  §3 *Indeterminate* vs *Unavailable*;
- items (3), (4) join repair → L5, §2 Canonical Events (`EventId`) — the cross-event overwrite is an L5 identity
  failure;
- item (5) same-offer binding → §6 market-observation grain (book, line, side, time); the held `2e2adc6` spread
  side dependency is the same rule;
- items (6), (7) "Book updated" and "Observed by BK", never merged, deployed clock retained → §7 no substitution;
- item (10) unregistered model output hidden; models never select or order → §9;
- item (12) Market-implied probability label; unsupported Confidence and "opponent-adjusted" removed → L10,
  §9 derived context labeled.

**Flags — not resolved here:**
- (a) **Receipts.** Green Light is migration step 7 (§12). Until then it is a non-migrated surface. Under the
  exemption it must be "labeled non-receipted"; 1A's scope does not mention that label (F-6).
- (b) **Convergence ordering** — the authority class of the lens count is unstated (F-8). 1A item (11) orders
  games by kickoff. Whether the within-board convergence sort is "derived context ordering" or an approved
  exception is an owner question.
- (c) **Lens promotion state** (Lens Governance Constitution "Production") is not a §9 model-registry grant (F-7).

## 6. NCAAB Foundation — conformance check

Checked against `docs/ncaab_first_slice_design_20261104.md` and its consolidation package. **No conflict was
found with any approved rule:**
- opaque permanent IDs, never name-derived; curated reviewed exact aliases only; fail-closed resolver → §6
  priority and frozen alias policy;
- `EventId` = provider id → §2;
- side assigned by construction, with point and price from the same outcome → §6 market-observation grain;
- `SourceUpdatedAtUTC` and `FetchedAtUTC` as separate columns, no `LastUpdated` → §7 (`FetchedAtUTC` =
  `bk_captured`);
- append-only snapshots; change rows for score corrections → L6/L12;
- per-book grading on BK's own retained pre-tip snapshots → L9, §8 `EVIDENCE_EQUIVALENT`;
- `NeutralSite=UNKNOWN` abstention; fact states `AVAILABLE/STALE/UNAVAILABLE/PENDING` with reason codes, never
  zero-filled → L8, §3;
- evidence counts by type, no total → L7;
- ESPN, KenPom and injuries unavailable → §10 / `DATA_RIGHTS_GATE`;
- run receipts with identity counts → L4.

Reason codes are fixed strings; `FREE_BY_USED_DELTA` is a static code, not an interpolated one (§5).
**Flags:**
- (a) NCAAB run receipts are the NBA v6 run-receipt contract, **not** the six Constitution receipt kinds.
  Whether a new pre-Phase-2 surface is "exempt / labeled non-receipted" is unclear (F-6).
- (b) NCAAB freshness uses `FetchedAtUTC` and NFL 1A uses `SourceUpdatedAtUTC`. Both are permitted by §7 (no
  clock is substituted for another), but the divergence is owner-recorded, not Constitution-decided.

## 7. Boundary: Constitution approval vs Phase 2 implementation

- Approval and freeze **authorize no implementation**. Per §12 the Constitution is migration step 1, and steps
  2–10 are separate phases. Program position 5 makes **Decision Integrity Phase 2** an owner choice after NCAAB
  Foundation, competing with Green Light Release 2.
- Existing Phase 2B/2C work (contract library, validators, report-only CI, NFL ATS dark shadow) lives only on
  paused branch `claude/jolly-ishizaka-c6519a`. It is **not** in master, is **PAUSED**, and under the reset is
  "rebuilt on current master when scheduled". Freezing does not promote, merge or revalidate it.
- No validators, CI rule, registry, runtime flag, receipt store or surface migration follows from freezing.
  §11's "CI rule fails the build" binds only once Phase 2 enforcement is separately built and approved.

## 8. Proposed frozen version identifier (owner to choose)

**`DIC-1.0`** = Decision Integrity Constitution, approved text Rev 2.1, git blob
`634d98e6366af557193e24372d61728848777c30` (commit `146589e`, present unchanged in prod `b12eec3`).
The blob hash is the freeze anchor, so header wording (F-1) cannot silently change the frozen content. A
content hash is integrity-verifiable, not tamper-evident (L12's own distinction).

## 9. Amendment process after freeze (proposal — not in the approved text; owner approval required)

Assembled only from existing recorded practice: G-1 "reopen only for a documented contradiction/amendment", §5
governed change with a version bump, and the Rev 1→2→2.1 revision passes.
1. **Trigger:** a documented contradiction (text vs text, or text vs production evidence) or an owner-requested
   amendment. Nothing else reopens it.
2. **Record:** a numbered amendment note quoting the affected passage, the proposed text and the reason.
3. **Approve:** explicit owner approval naming the amendment and the new identifier (`DIC-1.1`, …).
4. **Publish:** a new revision with a changelog entry and a new anchor hash. Prior versions stay retrievable in
   git; no in-place silent edit.
5. **Scope:** an amendment authorizes no implementation; any build it implies enters the program table
   separately.

## 9A. RECOMMENDED OWNER DECISIONS — NOT APPROVED (recommendations only until the owner explicitly confirms)

Source: CTP recommendation 2026-11-08. Nothing below alters the Constitution text or is in force. Impact column:
**1A** = Green Light Release 1A, **N** = NCAAB Foundation, **P2** = future Decision Integrity Phase 2.

| # | Recommendation | Supporting clause / recorded practice | Consequence if left unresolved | Affects |
|---|---|---|---|---|
| R1 | Freeze **only** Constitution Rev 2.1 as **`DIC-1.0`** (anchor blob `634d98e…`, `146589e`) | G-1 "Owner approval ⇒ versioned + frozen"; Rev 2.1 approval (`146589e`, G-1); §12 step 1 "Constitution approval" | The Constitution remains a revisable draft. Every later design (1A, NCAAB, Phase 2) cites a moving target | 1A, N, P2 (reference anchor only; no build) |
| R2 | Phase 2A **Rev 2.2** stays an approved **design**, outside the freeze | G-1 "Phase 2A Rev 2.2 design approved"; Phase 2A is "contracts only" subordinate to the Constitution (`d37b84f`) | Freeze scope stays ambiguous (F-4). Phase 2A could be read as frozen law, or as unapproved | P2 |
| R3 | Phase 2A **Rev 2.3 / 2.3a** remain **unapproved drafts** | No separate owner approval recorded (F-2); only commit messages (`73a1fba`, `baa7d37`) | Branch code built against 2.3a (`team` grain, decision-grain outcomes) could later be treated as conformant to an approved contract | P2 (paused branch only) |
| R4 | Research Candidate Contract = a **separate approved implementation contract**; the deployed 2D1 route stays **OFF** | Rev 2.1 approval and 2D1 OFF-state deploy `628657b` (project record); G-2 "capture OFF" | The G-2 "stopped for review" wording and the approval record keep conflicting (F-5). The contract's status is ambiguous at any enable decision | P2; none for 1A/N |
| R5 | The legacy exemption applies **only to explicitly labelled pre-existing legacy surfaces**; **new surfaces (e.g. NCAAB) conform from their first release** | §12 Exemptions ("a **legacy** surface **not yet migrated** … labeled non-receipted"); L1–L12 apply to "every authoritative surface" (§1) | NCAAB could ship under an exemption meant for pre-existing surfaces (F-6). This creates a new non-receipted surface the Constitution never contemplated | **N** (directly); 1A (Classic is pre-existing → label); P2 |
| R6 | **Nothing is promoted to authority without explicit owner approval; silence or deployment never promotes** | §9 governed model requires "an **explicit** authority grant"; Lens Governance "no automatic promotion … a human decides"; recorded practice "deployment ≠ approval" (Green Light baseline inventory, `9057ba1`) | Promotion remains undefined (F-7). A deployed lens or model could be treated as authoritative by default, as happened with the `9057ba1` default flip | **1A**, N, P2 |
| R7 | **Green Light lens agreement = descriptive derived evidence**: not a confidence score, not a prediction, not model authority; **usable for ordering only when every counted lens is governed, event-bound, fresh and visible by name**; contradictions and missing evidence remain visible | §9 Derived context (no ordering by default), Governed model (grant needed); L7 no composite score; L8 incomplete → ineligible; L5/§6 event-bound identity; §3 Indeterminate visible; doctrine §10 "correlated signals are not independent votes"; approved Classic sort (`c4ca828` S6) and tier wording (`60226f6`) | F-8 stays open. Convergence ordering in 1A has no stated basis: either it is silently treated as model authority, or the owner's convergence workflow is removed | **1A** (directly: the lens-binding and freshness conditions are the same defects 1A repairs); P2 |
| R8 | **Operational run receipts ≠ Decision Integrity observation/evaluation receipts**; keep the terms distinct | §4 defines exactly six DI receipt kinds; NBA v6 run receipts (`services/run_receipts.py`, PRE-4) are pipeline evidence; §4.6 source-health is the only operational DI kind | "Receipt" is used for two things, so a run receipt could be cited as satisfying L1 | **N** (run receipts); P2; 1A (`b12eec3` receipt wording) |
| R9 | **Approve the amendment process** in §9 | G-1 "reopen only for a documented contradiction/amendment"; §5 versioned governed change; Rev 1→2→2.1 practice | A frozen document has no defined way to change. Amendments become ad hoc or blocked (F-9) | P2 (and any future clarification) |
| R10 | **Correct stale titles later as a docs-only governed change**; never rewrite frozen content for presentation | L6/L12 (corrections additive, no in-place edit), applied by analogy; the anchor-hash freeze (§8); recorded practice of frozen release branches (`628657b` kept frozen) | Titles keep saying "Rev 2" / "Rev 2.1" (F-1, F-2), or an editorial fix silently changes the frozen anchor | None for builds; documentation only |

**Note on R7.** It sets conditions on ordering; it does not grant authority. Whether today's Classic lenses meet
"governed, event-bound, fresh, visible by name" is an evidence question for 1A's acceptance. It is not decided
here. The 11-08 audit found Matchup and Game Identity bound to the wrong event for 11 of 28 teams, and Coaching
data stale.

## 9B. FINAL OWNER SIGN-OFF (yes / no)

| | Decision | YES | NO |
|---|---|---|---|
| S1 | **Freeze Constitution Rev 2.1 as `DIC-1.0`** (blob `634d98e6366af557193e24372d61728848777c30`, commit `146589e`) | ☐ | ☐ |
| S2 | **Approve recommendations R2–R10** (§9A) as governing interpretations and process | ☐ | ☐ |
| S3 | **Authorize no implementation**: no Phase 2 build, no merge or advance of paused branches, no validator, CI rule, registry, flag or store | ☐ | ☐ |

Owner: ____________ Date (UTC): ____________

Until all three boxes are answered, the status quo stands: Rev 2.1 is approved but unfrozen, and R2–R10 are
recommendations only.

## 9C. OWNER DECISION RECORDED — 2026-11-08

**S1 = YES · S2 = YES · S3 = YES.**
Owner instruction (verbatim): "Record the owner decision: S1 = YES; S2 = YES; S3 = YES."

| Item | Recorded state |
|---|---|
| Constitution Rev 2.1 | **FROZEN as `DIC-1.0`**: exact file version from commit `146589e` (git blob `634d98e6366af557193e24372d61728848777c30`, unchanged in prod `b12eec3`). The frozen file is **not modified**. Its stale "Rev 2" title is a known presentation defect, corrected later only as a docs-only governed change (R10) |
| R2–R10 (§9A) | **APPROVED** as governing interpretations and process |
| Phase 2A Rev 2.2 (`d5700c5`) | Approved **design only**; not part of `DIC-1.0` |
| Phase 2A Rev 2.3 / 2.3a (`73a1fba`, `baa7d37`) | **Unapproved drafts** |
| Research Candidate Contract | Separate approved implementation contract; the production 2D1 route stays **OFF** |
| Phase 2 implementation | **Unauthorized and PARKED** (program position 5 owner choice unchanged). Paused branch `claude/jolly-ishizaka-c6519a` is not merged, advanced or revalidated |
| Amendment process (§9) | **In force** for `DIC-1.0` |
| Implementation authorized by this decision | **None** |

Consequences for current work, as stated by the owner decision:
- Green Light lens agreement is descriptive derived evidence, not confidence or authority (R7).
- NCAAB must conform from its first release; no legacy exemption (R5).

## 10. Owner sign-off checklist (one page)

| # | Decision | Options | ☐ |
|---|---|---|---|
| 1 | Freeze anchor | Constitution Rev 2.1 at blob `634d98e…` (`146589e`) as **`DIC-1.0`** / other identifier | ☐ |
| 2 | Header label (F-1) | Freeze as-is (anchor governs) / correct header first as amendment `DIC-1.0a` | ☐ |
| 3 | Freeze scope (F-4) | Constitution only / + Phase 2A / + Research Candidate Contract | ☐ |
| 4 | Phase 2A revision (F-2) | Rev 2.2 (recorded) / Rev 2.3a (latest) — approve or leave as design | ☐ |
| 5 | Approved Phase 2A not on master (F-3) | Accept for now / record as a docs-only item for a later release | ☐ |
| 6 | Research Candidate status (F-5) | Confirm Rev 2.1 approved / design-stopped; reconcile G-2 | ☐ |
| 7 | New-surface exemption (F-6) | Clarify by amendment / leave open until Phase 2 | ☐ |
| 8 | Promotion (F-7) | Leave to model registry + Lens Governance / define by amendment later | ☐ |
| 9 | Convergence class (F-8) | Leave open for Green Light Release 2 / decide before 1A | ☐ |
| 10 | Amendment process (§9) | Adopt as proposed / modify / reject | ☐ |
| 11 | Boundary (§7) | Confirm freeze authorizes **no** Phase 2 implementation; paused branch stays paused | ☐ |
| 12 | Green Light Classic + NCAAB conformance (§5, §6) | Accept "no conflict found, flags open" | ☐ |

Signed: ____________ (owner) Date (UTC): ____________ Frozen identifier: ____________
