# Research Candidate Contract — DESIGN ONLY

**Status: DESIGN ONLY — Rev 2.1. Returned for review before anything is built.** Date 2026-10-25.
Rev 2 applied the reviewer's ten corrections (cardinalities; case-identity vs family-membership;
four temporal concepts; invalidation selection-bias guard; continuous endpoint + case states;
strengthened evidence bar; `ValidatedFinding`→`EvaluatedFinding`; receipt eligibility for evaluation;
privacy-dependent deletion; corrected Freiermuth example). **Rev 2.1** applies four precision
corrections: (1) measurement failure is **not** `INVALIDATED` — it is a counted `UNMEASURABLE` state
subject to missingness analysis; (2) `INCONCLUSIVE` is an **immutable** finding, never a rewind to
`SAMPLE_ACCUMULATING`; (3) "effect already priced" is removed from `UNSUPPORTED` (this contract measures
opportunity/usage, not market value); (4) Freiermuth Case #1 is a valid observation + descriptive seed
but **ineligible** for the evaluated sample because its numeric MEPI was not frozen pre-kickoff (never
backfilled).

This defines the **object model and lifecycle** for turning a human observation into an honestly
testable research record. It is a contract, not an implementation. There is:

- **no database**, no table, no migration, no store of any kind;
- **no route, no UI, no automation, no job**;
- **no scoring, no ranking, no recommendation, no betting guidance, no production behavior**.

A Research Candidate is **`RESEARCH_ONLY`**: it carries **zero** authority. It MUST NOT influence the
factual boards, Green Light, rankings, tickets, Daily Cards, or any governed model — not its score, not
its sort order, not its membership. It is a disciplined way to *collect and later evaluate* observations,
nothing more. (Doctrine §10–§11; CLAUDE.md §10: "every predictive factor tested so far is already in the
price"; "out-of-sample or it does not count.") The NFL ATS runtime pilot stays **OFF**. The NBA
acceptance receipt remains an independent production gate, untouched by this.

This slice is **separate from Decision Integrity runtime work**. It reuses that system's *vocabulary*
(the clocks, append-only corrections, supersession, replay class, RESEARCH_ONLY authority) but defines a
**distinct object model**; §8 states exactly how the two connect **by reference, never by merge**.

Case #1 is the preserved pre-kickoff Freiermuth observation
(`docs/research_candidate_player_milestone_usage.md`); this contract generalizes it to any
`BIRTHDAY`, `REVENGE_GAME`, `RECORD_CHASE`, `CONTRACT_INCENTIVE`, or `HOMECOMING` observation.

---

## 0. Why four objects and not one

A single "observation record" would quietly let four different things blur together: what a person
*felt*, what we *froze as testable*, what actually *happened*, and what the *accumulated evidence*
supports. Keeping them separate is the whole point — it is what makes hindsight rationalization
structurally impossible rather than merely discouraged. The four objects below each own exactly one of
those, at a declared grain, and link forward-only.

---

## 1. The four objects (distinct, forward-linked)

| Object | Grain | Owns | Mutability |
|---|---|---|---|
| **`UserObservation`** | one human noticing, one case | the subjective seed — who noticed what, when, about which entity/event, in their own words, with their sources, and whether they acted | immutable once recorded; a change is a correction (new record, §6) |
| **`ResearchCandidate`** | one case, frozen **before** the event | the **testable form** — category/sub-label, the frozen primary endpoint (incl. direction + minimum effect of interest, §7), baseline method, assumptions, eligibility + invalidation conditions, the four temporal facts, the pre-event snapshot | **frozen** at `MEASUREMENT_DEFINED`; content-hashed; never edited |
| **`CandidateOutcome`** | one case, appended **after** the event | what actually happened — the **continuous** observed endpoint + its baseline comparison, completeness, confounders/covariates, measurement-receipt reference, and the case **state** (not a win/loss grade) | **append-only, versioned**; a regrade is a new version superseding the prior; exactly one current |
| **`EvaluatedFinding`** | one **family**, aggregate | the verdict over a *matched sample* of eligible cases sharing a family key — the research status and the full evidence behind it | append-only; a re-evaluation is a new, superseding finding (§6) |

> **Renamed in Rev 2:** `ValidatedFinding` → **`EvaluatedFinding`**. "Validated" reads as "confirmed";
> this object may resolve to `SUPPORTED`, `UNSUPPORTED`, or `INCONCLUSIVE`. **Even `SUPPORTED` remains
> `RESEARCH_ONLY`** — it is never an authority grant (§0, §7).

**Case identity vs. family membership (kept separate — Rev 2 #2).**
- A **case** is identified by **canonical entity + event + candidate contract** (the frozen measurement
  definition). That triple names *this* observation uniquely.
- A **research family** is keyed **only by the governed family definition** =
  `(category, sub_label, primary_endpoint_def@version, baseline_method@version)`.
  **The entity id is NOT part of the family key.** Putting it in the key would fragment the sample into
  one-player families and defeat the cross-player matched design. A case *maps to* its family by the
  family definition; the within-entity / matched grouping happens at **evaluation time** (§7), not in
  the key.

**Cardinality (Rev 2 #1):**
- `UserObservation 1 — 0..1 ResearchCandidate` — promotion is **optional**: a vague or late observation
  may never be promoted (it stays a descriptive note).
- `ResearchCandidate 1 — 0..N CandidateOutcome versions` — append-only corrections, with **exactly one
  current (non-superseded) outcome** at any time (0 while pending/invalidated-before-capture).
- `family — N ResearchCandidate`.
- `family — 0..1 EvaluatedFinding` (current; prior superseded).

**Distinctions that must never collapse:**
- A `UserObservation` is **not** testable. Promotion to a `ResearchCandidate` is where it is made precise
  — or declined as untestable.
- A `ResearchCandidate` is **not** a result. It is a frozen question.
- A `CandidateOutcome` is **not** a verdict on the hypothesis. It is one measured data point.
- An `EvaluatedFinding` is **not** a recommendation or an edge claim.

---

## 2. Lifecycle

```
OBSERVED → MEASUREMENT_DEFINED → OUTCOME_CAPTURED → SAMPLE_ACCUMULATING → EVALUATED
                                                                              │
                                              ┌───────────────┬───────────────┤
                                              ▼               ▼               ▼
                                          SUPPORTED      UNSUPPORTED     INCONCLUSIVE
```

The machine runs at **two grains**, which is why it does not contradict "one case can never establish an
effect":

- **Per-case track (one candidate):** `OBSERVED → MEASUREMENT_DEFINED → OUTCOME_CAPTURED`, then the case
  *contributes to* its family's `SAMPLE_ACCUMULATING`. A single candidate can go no further on its own.
- **Family track:** `SAMPLE_ACCUMULATING → EVALUATED → {SUPPORTED | UNSUPPORTED | INCONCLUSIVE}`, gated
  by the minimum-evidence requirements of §7.

| State | Grain | Entered when | Preconditions / invariants |
|---|---|---|---|
| `OBSERVED` | case | `UserObservation` recorded | observer + `observed_at` + an entity/event the observation points at |
| `MEASUREMENT_DEFINED` | case | `ResearchCandidate` frozen | **all §3 before-event fields present and frozen BEFORE `event_effective`**; else the case is permanently a descriptive note, never a graded candidate |
| `OUTCOME_CAPTURED` | case | current `CandidateOutcome` version appended | event has occurred; the **continuous** endpoint + baseline comparison recorded; missing variables **pending**, never zero-filled |
| `SAMPLE_ACCUMULATING` | family | ≥1 **eligible** captured outcome exists for the family key | the matched sample is below the §7 minimum |
| `EVALUATED` | family | §7 minimum reached and an evaluation run against the **frozen** endpoint | evaluation uses only frozen endpoints; no endpoint substitution (§5); only §8-eligible cases enter |
| `SUPPORTED` | family | evaluation clears the §7 bar (direction + minimum effect + uncertainty + out-of-sample + sensitivity) | still **not** an authority grant (§0) |
| `UNSUPPORTED` | family | evaluation shows no effect of interest (below MEPI) | recorded with equal weight to SUPPORTED. **"Already priced" is NOT a criterion** here (Rev 2.1 #3): this contract measures opportunity/usage, not market value — whether a real effect is in the price is a separate market-value study |
| `INCONCLUSIVE` | family | evidence insufficient to separate the two | the honest default, recorded as an **immutable** `EvaluatedFinding(status=INCONCLUSIVE)` (Rev 2.1 #2). It does **not** rewind to `SAMPLE_ACCUMULATING`; more cases accumulate afterward and a **later evaluation creates a new superseding finding** |

**`INVALIDATED` — a per-case side exit, not a terminal verdict, and strictly bounded (Rev 2 / 2.1 #1,
#4).** A case is `INVALIDATED` **only** when a **frozen pre-event eligibility condition failed** — an
eligibility condition recorded *before* the event did not hold (e.g. the player was inactive, the assumed
starter did not start). That is its **sole** meaning.

- **Measurement failure is NOT `INVALIDATED` (Rev 2.1 #1).** If the outcome data is simply missing or the
  primary endpoint cannot be measured after an *eligible* event, the case is `PENDING` / `PARTIAL` /
  `UNMEASURABLE` (§4) — **counted**, and handled by the predeclared **missingness analysis** (§7.7).
  Routing missing data to `INVALIDATED` would silently drop it and create selection bias; it must stay in
  the accounting.
- `INVALIDATED` MUST NOT be used for an **unfavorable downstream condition correlated with the outcome**
  (e.g. "the game script suppressed pass volume"). Excluding cases on outcome-correlated conditions is
  selection bias dressed as rigor; such conditions are **context or a predeclared covariate** (§3, §4).

Invalidated **counts and reasons are reported**, and where exclusion (of either kind — eligibility or
missingness) could bias results a **sensitivity analysis is required** (§7). An invalidated case is
excluded from the matched sample and is **never** counted as a negative result.

Transitions are forward-only; re-evaluation and corrections are new, superseding records (§6).

---

## 3. Frozen before-event fields (locked at `MEASUREMENT_DEFINED`)

These are the `ResearchCandidate`'s content. They are **frozen before `event_effective`**, content-hashed,
and never edited. Freezing before the event is the entire source of the record's credibility.

| Field | Grain | Notes |
|---|---|---|
| **observer** | who recorded it (`user` / id) | carried from the `UserObservation`; privacy-scoped (§6) |
| **four temporal facts** | `observed_at`, `source_updated`, `event_effective`, `bk_captured` | see the box below — **four distinct concepts**, none substituted for another |
| **entity identity** | the subject (player/team), by canonical id | uses the existing resolver discipline — unresolved/ambiguous identity ⇒ the candidate is held `UNKNOWN` and is **ineligible**, never guessed (mirrors CFB `(GameID,TeamSide)` fail-closed) |
| **event identity** | the game/event, by canonical id | with `event_effective`. (Entity + event + this contract = the **case identity**, §1) |
| **category / sub_label** | e.g. `PLAYER_MILESTONE_USAGE` / `BIRTHDAY` | adding a sub_label is a **data-labeling** decision, never a scoring change |
| **thesis** | the hypothesis in plain words | frozen verbatim |
| **primary endpoint** | the ONE pre-registered measurement, **with its direction and minimum effect of interest** | e.g. within-player matched **target-share lift**, direction = *increase*, MEPI set per §7. Causal/opportunity, **not** a prop result, **not** a bet result. Exactly one; immutable |
| **baseline method** | how "expected" is computed, incl. **predeclared covariates** | e.g. role/matchup/game-script/team-pass-volume expected usage; game script + team pass volume are **covariates here**, not invalidation triggers; versioned |
| **assumptions** | what must hold for the test to be valid | e.g. player active, normal snap role, assumed starter plays |
| **eligibility + invalidation conditions** | frozen pre-event; bounded per §2 (Rev 2 / 2.1 #1, #4) | a frozen **eligibility failure** only (e.g. inactive, assumed starter benched) — **never** measurement failure (that is `UNMEASURABLE`, §4) and **never** an outcome-correlated downstream condition (that is a covariate) |
| **whether the user acted** | did the observer take a position? | recorded as **context only**; no effect on the endpoint (§8 link to Decision Journal is by reference) |
| **pre-event snapshot** | what was knowable at `observed_at` | posted lines/prices + their provider `source_updated`, pregame expected usage, competing-receiver availability; a variable not obtainable pre-event is **pending**, never zero-filled |
| **sources** | user-supplied provenance | URLs/citations as given; not independently authoritative |

> **The four temporal facts (Rev 2 #3).** This object has **four distinct temporal concepts**, not a
> renamed "three-clock" model:
> 1. **`observed_at`** — the **human-observation clock**: when the person made the observation (tz-aware
>    ET+UTC). This is *additional* to the Decision-Integrity clocks.
> 2. **`source_updated`** — the **provider clock** for any provider data folded into the snapshot
>    (tz-aware UTC), with `source_updated_status ∈ {PRESENT, UNKNOWN, NOT_PROVIDED}`; absent ⇒ null,
>    never backfilled.
> 3. **`event_effective`** — the **event's own clock** (kickoff / first pitch), tz-aware UTC.
> 4. **`bk_captured`** — the **ingestion clock** (when BK recorded it) + an immutable monotonic
>    `record_seq` used for correction ordering (§6).
> The three DI clocks remain `source_updated` / `event_effective` / `bk_captured` (Constitution §7);
> `observed_at` is the human clock on top. **No clock is ever substituted for another.**

A candidate whose §3 set is incomplete, or frozen **after** `event_effective`, is permanently a
descriptive note — it can never enter the matched sample.

---

## 4. Append-only, versioned after-event fields (`CandidateOutcome`)

Appended after the event. These **attach** to the candidate; they **never** touch a frozen field. A
correction is a **new version** superseding the prior (§6), with exactly one current version.

| Field | Notes |
|---|---|
| **observed endpoint (continuous)** | the **measured value** of the frozen primary endpoint (e.g. the actual target-share lift), stored as a number, **not** dichotomized |
| **baseline comparison (continuous)** | actual vs the frozen baseline's **expected** — the difference the endpoint defines, with its covariates; no substitution |
| **completeness** | per variable `COMPLETE` / `PARTIAL` / `PENDING`; missing variables stay **pending**, never zero-filled |
| **confounders / covariates** | observed co-causes (snaps, QB change, game script, team pass volume, competing-WR availability) recorded so the matched evaluation can **control** for them — game script lives here, never as an invalidation |
| **measurement receipt (ref)** | a reference to a Decision-Integrity `decision_time`/`source_health` receipt id, **if** one exists — a pointer, not an embedded receipt (§8). Its presence/quality governs **evaluation** eligibility (§8), not early preservation |
| **case state** | one of `MEASURED` · `PARTIAL` · `PENDING` · `UNMEASURABLE` · `INVALIDATED` — a **descriptive state of this case's measurement**, NOT a win/loss grade (Rev 2 #5). `UNMEASURABLE` = the event was *eligible* but the endpoint cannot be measured (data does not exist) — it is **counted** and enters the missingness analysis (§7.7), it is **not** `INVALIDATED` (Rev 2.1 #1). `INVALIDATED` is reserved for a frozen eligibility failure (§2). Whether the evidence supports an effect is decided **only** at family-level evaluation (§7) |

There is deliberately **no** `CONFIRMED_LIFT` / `NO_LIFT` per-case label: a single case is never "a hit"
or "a miss." It is a measured (or partial/pending/invalidated) data point.

---

## 5. Hindsight prohibition (the load-bearing rule)

1. **No endpoint substitution.** The `EvaluatedFinding` and every `CandidateOutcome` are measured against
   the **frozen primary endpoint** (value + direction + MEPI) recorded at `MEASUREMENT_DEFINED`. The
   endpoint cannot be changed, swapped, or "clarified" after the event. If the frozen endpoint was the
   wrong question, that is itself a finding — you do **not** re-aim at whatever moved.
2. **Secondary outcomes are descriptive only.** Anything that is not the frozen primary endpoint (the
   prop over/under, touchdowns, the bet result, "he had a big game") MUST be labeled **`descriptive`** and
   can **never** replace the primary endpoint nor contribute to the `SUPPORTED/UNSUPPORTED` evaluation.
3. **Pre-registration is the test.** A candidate frozen after `event_effective` is ineligible.
4. **One primary endpoint**, with its direction and MEPI, chosen before the event. "Multiple primary
   endpoints" guarantees one moves; it is prohibited.
5. **No outcome-correlated exclusion.** Dropping cases on a downstream condition correlated with the
   outcome (§2/§4) is prohibited; such conditions are covariates, and exclusions require sensitivity
   analysis (§7).

---

## 6. Boundaries: identity, correction, supersession, privacy, licensing, deletion

- **Identity.** Entities resolve through the existing sport-scoped resolver; unresolved or ambiguous
  identity ⇒ the candidate is `UNKNOWN` and **ineligible**, never guessed. **Case identity** is the
  (entity, event, contract) triple (§1); it does **not** key the family.
- **Correction.** A changed input (rescheduled kickoff, a regrade, a line correction, a fixed birthday)
  produces a **new** record linked to what it supersedes. Frozen before-event fields are **never** edited
  in place; a wrong freeze is **superseded and excluded**, and a new candidate can be frozen only if a
  valid pre-event timestamp still exists — otherwise it is a descriptive note (no "re-freeze" after the
  event). (Constitution L6/L12.)
- **Supersession.** Ordering is by an immutable **`record_seq`**, never by provider `source_updated`
  (which can regress or arrive late). A superseding record references the superseded one by `record_seq`;
  `CandidateOutcome` corrections form a version chain with exactly one current.
- **Privacy.** A `UserObservation` is personal data scoped to its observer. Observations are **not**
  shared, cross-joined across users, or surfaced publicly. An `EvaluatedFinding` reports **aggregate,
  de-identified** sample statistics only — never an individual's observation text or betting activity.
- **Licensing.** Provider data captured in the pre-event snapshot (posted lines, usage stats) is stored
  and retained **only** as each provider's license permits; where it does not, the variable is **gated**
  (`Unavailable`), never copied or synthesized. Usage measurement draws on licensed sources under their
  terms.
- **Deletion (privacy/legal-dependent — Rev 2 #9).** **Permanent retention of a de-identified outcome is
  NOT adopted.** This is a privacy/legal question flagged for a human decision. **Until that is approved,
  deletion of a `UserObservation`:** (a) removes the account linkage / PII, (b) **excludes the case from
  all future evaluations**, and (c) retains **only** a **non-identifying tombstone + a recount notice**
  so the sample accounting stays honest. No de-identified outcome is retained for evaluation without an
  approved policy.

---

## 7. Minimum evidence before an `EvaluatedFinding` resolves `SUPPORTED`

**One case can never establish an effect.** A single game is recorded only to *seed* a matched sample. A
family may be `EVALUATED` and resolve `SUPPORTED` only when **all** of the following hold (exact numeric
floors are §10 Q3, pending a power/MEPI analysis). **Statistical significance alone must never produce
`SUPPORTED`** (Rev 2 #6):

1. **Pre-registered endpoint with direction and a minimum effect of practical interest (MEPI).** The
   effect must be in the frozen direction **and** at least the frozen MEPI — not merely "a corrected CI
   above zero." A statistically detectable but practically trivial effect is `UNSUPPORTED`.
2. **Uncertainty estimates.** Effect size with a confidence/credible interval; point estimates alone do
   not qualify.
3. **Matched design.** Within-entity comparison of milestone cases vs the same entity's non-milestone
   cases, **controlling for** the predeclared covariates (routes, snaps, quarterback, opponent, injuries,
   team pass volume, game script). The within-entity grouping is applied here, at evaluation — it is not
   in the family key (§1).
4. **Out-of-sample performance.** The effect must survive out-of-sample / holdout measurement; in-sample
   strength is not evidence (CLAUDE.md §10: four streak-parlay rules with in-sample lower-CI bounds +8.3
   to +17.8 all reversed out-of-sample).
5. **Independence / effective sample size.** Power is judged on the **effective** sample size (independent
   cases across players and weeks), not a raw row count inflated by repeated measures on one player
   (CLAUDE.md §10: a 3-leg rule showed **+63% at n=21** and **−29% at n=2,861**).
6. **Multiplicity control.** Each sub_label is a separate test; evaluating several narratives requires
   family-wise / false-discovery correction, and the **corrected** interval must clear both zero and the
   MEPI.
7. **Missingness handling.** Pending/partial variables are handled by a predeclared rule (honest
   weighting or exclusion); a sample padded with zero-filled variables does not qualify.
8. **Sensitivity analysis.** Where invalidated/excluded cases could bias the result, a sensitivity
   analysis is **required** and reported (Rev 2 #4).

If the effect holds under all of the above → `SUPPORTED`; if it is absent or below the MEPI →
`UNSUPPORTED` (whether a *real* effect is already in the price is **out of scope** — this contract
measures usage, and "priced" is a separate market-value study, Rev 2.1 #3); if the evidence cannot
separate the two → `INCONCLUSIVE`, recorded as an **immutable** `EvaluatedFinding` that a **later**
evaluation may supersede as more cases accumulate — it does not rewind the family (Rev 2.1 #2).
**`SUPPORTED` is still `RESEARCH_ONLY`** — promotion to any authority is a separate, governed decision
outside this contract (Constitution §9).

---

## 8. How this connects to the Decision Journal and Decision Integrity — by reference, never by merge

The three systems answer three different questions and keep three different object models. They link
**forward-only, by id**; no object embeds another's model.

| System | Question it answers | Object model |
|---|---|---|
| **Decision Integrity receipts** | "What was knowable/served/rendered, and is it integrity-verifiable?" | the six receipt kinds + envelope (Constitution §4–§5) |
| **Decision Journal** | "Which reasoning produced this *bet* result?" | journal entries keyed to tickets; book settlement authoritative |
| **Research Candidate (this doc)** | "Does a *named human observation* measurably move *opportunity*, out-of-sample?" | the four objects of §1 |

**Linkage rules:**
- A `ResearchCandidate`/`CandidateOutcome` MAY carry a **reference** (`receipt_id`) to a Decision-Integrity
  `decision_time` and/or `source_health` receipt. It stores the **id**, not the receipt body.
- **Receipt eligibility (Rev 2 #8).** A measurement receipt is **optional for preserving an early
  candidate** (seeding a case costs nothing). But **inclusion in a family *evaluation* requires** that the
  case's provenance, completeness, and **replay quality meet the family's frozen eligibility contract**.
  "Optional receipt" must **never** mean unverifiable cases silently enter the evaluated sample: a case
  that cannot meet the frozen evaluation-eligibility bar stays in `SAMPLE_ACCUMULATING` as context and is
  excluded from the `EVALUATED` computation (and counted in the exclusion report, §7.8).
- If the observer acted, `UserObservation.acted` MAY reference a **Decision Journal entry id** — "the
  person also bet this" — but the endpoint remains **usage**, not the bet result; the journal entry never
  feeds the evaluation.
- **No shared primary key, no joined table, no inherited schema.** A receipt is never a candidate; a
  candidate is never a receipt; a journal entry is never either. The reuse is of **discipline** and of
  **references**.

---

## 9. Worked examples

### 9.1 Case #1, Pat Freiermuth `BIRTHDAY` — valid observation + descriptive seed, NOT an evaluated-sample case

- **`UserObservation` (valid, pre-kickoff — this stands).** observer = user; `observed_at` =
  2026-10-25 08:51 EDT (`2026-10-25T12:51:21Z`), **before kickoff**; subject = Pat Freiermuth (TE, PIT,
  canonical id); event = PIT vs NO (Paris); thesis = "Rodgers may involve Freiermuth more than his normal
  role **because it is his birthday**"; sources = Steelers bio + schedule; `acted` = (recorded as context).
- **`ResearchCandidate` — INELIGIBLE for the governed evaluated sample (Rev 2.1 #4).** The preserved
  pre-kickoff record froze the endpoint (within-player matched target-share lift, direction = increase),
  the baseline (**game script + team pass volume are covariates**), the eligibility set {active, normal
  snap role, Rodgers starts}, and the invalidation set {player inactive, assumed starter does not play}
  — **not** "pass-volume-killing script" (a covariate, Rev 2 #10), and a non-measurable endpoint would be
  `UNMEASURABLE`, not invalidation. **But Rev 2 later added a required *numeric MEPI* and the stricter
  evaluation contract (§7), and those were NOT frozen before kickoff.** So Case #1 is preserved as a
  **research seed / descriptive candidate** only. It is **ineligible for the evaluated sample** unless
  every required field — *including the numeric MEPI* — was genuinely recorded before kickoff. **The MEPI
  MUST NEVER be backfilled** to rescue eligibility; doing so would manufacture the pre-registration the
  record lacks (and violate §5).
- **`CandidateOutcome` (as a seed).** If measured: the **continuous** target-share lift (actual vs
  expected) with covariates incl. the observed game script and team pass volume; case **state** ∈
  {`MEASURED`, `PARTIAL`, `PENDING`, `UNMEASURABLE`, `INVALIDATED`}. It contributes **context**, not an
  evaluated data point.
- **Status:** a valid pre-kickoff observation and the first `BIRTHDAY` seed — explicitly **not** evidence
  of an effect, and **not** a governed evaluated-sample case. Its lesson is operational: future
  `BIRTHDAY` candidates must freeze a numeric MEPI (and the full §3 set) **before** the event so they
  *are* eligible.

### 9.2 INVALID — hindsight endpoint substitution
After the game the usage lift is ≈0 but Freiermuth scores a TD; re-labeling the case a "birthday
**touchdown** effect." → **Prohibited (§5.1/§5.2).** The TD is a `descriptive` secondary outcome; the
frozen endpoint was usage lift; the case is simply `MEASURED` with a near-zero lift.

### 9.3 INVALID — one case becomes a finding
A single high-lift case is promoted to an `EvaluatedFinding`. → **Prohibited (§1, §7).** No finding from
one case; the family remains `SAMPLE_ACCUMULATING`.

### 9.4 INVALID — outcome-correlated exclusion (selection bias)
A reviewer drops every milestone game where the team fell behind and abandoned the pass, because "the
thesis couldn't show." → **Prohibited (Rev 2 #4, §2, §5.5).** Game script is a covariate; those cases
stay `MEASURED` and are controlled for; any exclusion requires a reported sensitivity analysis.

### 9.5 INVALID — secondary outcome replaces the primary
The baseline-usage data never arrives, so evaluation quietly switches to "did the receiving prop go
over?" → **Prohibited (§5.2).** The prop is descriptive; a missing baseline keeps the variable
**pending**; the case is `PARTIAL`, not re-aimed.

### 9.6 INVALID — significance without a real effect
A family shows a statistically significant but trivially small lift, below the frozen MEPI, and is called
`SUPPORTED`. → **Prohibited (§7.1/§7.6).** Below MEPI (or not clearing the corrected interval) ⇒
`UNSUPPORTED`.

### 9.7 VALID — honest `UNSUPPORTED`
After enough matched, out-of-sample `REVENGE_GAME` cases across many players/seasons, the lift is below
MEPI with a corrected interval spanning it. → `EVALUATED → UNSUPPORTED`. Recorded with the same weight as
a positive result.

---

## 10. Unresolved decisions (recommended defaults — STOP for review)

| # | Decision | Recommended default | Why it needs a human |
|---|---|---|---|
| Q1 | Two-grain model (per-case `ResearchCandidate`, family-level `EvaluatedFinding`), cardinalities per §1 | **Adopt as written** (1→0..1 promotion; 1→0..N outcome versions, one current) | Confirm before anything downstream assumes it |
| Q2 | Who may create a `UserObservation`? | **Owner/founder only** during the design era; per-observer privacy scoping if opened up | Scope + privacy posture is a product call |
| Q3 | Exact §7 floors (MEPI value, effective-n / power, correction method, missingness rule) | **Defer to a power + MEPI analysis**; no `SUPPORTED` without direction + MEPI + corrected interval + out-of-sample + sensitivity | The numbers define what "supported" ever means |
| Q4 | Deletion vs sample integrity (§6) | **Privacy/legal-dependent; do NOT retain yet.** Interim: remove account linkage, **exclude from future evaluations**, keep only a non-identifying tombstone + recount notice | A real privacy-vs-research tradeoff; needs legal sign-off |
| Q5 | Which secondary outcomes are allowed as `descriptive` context | An explicit allow-list (prop line/result, TDs, yards) shown but **never graded** | Prevents §5.2 drift |
| Q6 | Name `EvaluatedFinding` (was `ValidatedFinding`) | **Adopted in Rev 2**; `SUPPORTED`/`UNSUPPORTED`/`INCONCLUSIVE`; `SUPPORTED` stays `RESEARCH_ONLY` | Confirm the rename + the semantics |
| Q7 | Four temporal facts (`observed_at` + the three DI clocks), none substituted | **Adopt as §3** | Confirm before any capture format is drawn |
| Q8 | Evaluation-eligibility bar (provenance + completeness + replay quality) | **Required for evaluation, optional for seeding** (§8) | Sets how strict the evaluated sample is |
| Q9 | Sub_label extensibility | **Owner approval**; adding a label is data-labeling, never a scoring change | Keeps the family list governed |
| Q10 | Promotion path from `SUPPORTED` to any authority | **Out of scope here** — a separate governed decision (Constitution §9); this contract grants none | Must stay firewalled from this design |

**STOP — returned for review.** No store, route, UI, job, score, or production behavior exists or is
proposed. Nothing here touches the factual boards, Green Light, rankings, tickets, or governed models.
The NFL ATS runtime pilot stays OFF; the NBA acceptance receipt remains an independent production gate.
```
