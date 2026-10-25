# Research Candidate Contract — DESIGN ONLY

**Status: DESIGN ONLY — Rev 1. Returned for review before anything is built.** Date 2026-10-25.

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
(three clocks, append-only corrections, supersession, replay class, RESEARCH_ONLY authority) but defines
a **distinct object model**; §8 states exactly how the two connect **by reference, never by merge**.

Case #1 is the preserved pre-kickoff Freiermuth observation
(`docs/research_candidate_player_milestone_usage.md`); this contract generalizes it to any
`BIRTHDAY`, `REVENGE_GAME`, `RECORD_CHASE`, `CONTRACT_INCENTIVE`, or `HOMECOMING` observation.

---

## 0. Why four objects and not one

A single "observation record" would quietly let three different things blur together: what a person
*felt*, what we *froze as testable*, what actually *happened*, and what the *accumulated evidence*
supports. Keeping them separate is the whole point — it is what makes hindsight rationalization
structurally impossible rather than merely discouraged. The four objects below each own exactly one of
those, at a declared grain, and link forward-only.

---

## 1. The four objects (distinct, forward-linked)

| Object | Grain | Owns | Mutability |
|---|---|---|---|
| **`UserObservation`** | one human noticing, one case | the subjective seed — who noticed what, when, about which entity/event, in their own words, with their sources, and whether they acted | immutable once recorded; a change is a correction (new record, §6) |
| **`ResearchCandidate`** | one case, frozen **before** the event | the **testable form** — category/sub-label, the frozen primary endpoint, baseline method, assumptions, invalidation conditions, the three clocks, the pre-event snapshot | **frozen** at `MEASUREMENT_DEFINED`; content-hashed; never edited |
| **`CandidateOutcome`** | one case, appended **after** the event | what actually happened — actual outcome, completeness, baseline comparison, confounders, measurement-receipt reference, per-case disposition | **append-only**; attaches to its candidate without touching frozen fields |
| **`ValidatedFinding`** | one **family**, aggregate | the evaluated verdict over a *matched sample* of cases sharing a family key — the research status and the sample statistics behind it | append-only; a re-evaluation is a new, superseding finding (§6) |

**Family key** (the unit a `ValidatedFinding` evaluates) =
`(category, sub_label, primary_endpoint_def@version, baseline_method@version)`.
A `ResearchCandidate` belongs to exactly one family key. Many candidates (with their outcomes) roll up to
one family; **a `ValidatedFinding` is never created from a single case** (§7).

**Cardinality:** `UserObservation 1—1 ResearchCandidate` (promotion) · `ResearchCandidate 1—0..1
CandidateOutcome` (0 while pending/invalidated-before-capture) · `family —N ResearchCandidate` ·
`family —0..1 ValidatedFinding` (current; prior superseded).

**Distinctions that must never collapse:**
- A `UserObservation` is **not** testable. It can be vague ("Rodgers might feed Freiermuth on his
  birthday"). Promotion to a `ResearchCandidate` is where it is made precise — or rejected as
  untestable.
- A `ResearchCandidate` is **not** a result. It is a frozen question.
- A `CandidateOutcome` is **not** a verdict on the hypothesis. It is one data point.
- A `ValidatedFinding` is **not** a recommendation or an edge claim. "Validated" means *evaluated against
  the frozen contract with sufficient evidence*, and its status can be `UNSUPPORTED` (§7, §10 Q10).

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
edge":

- **Per-case track (one candidate):** `OBSERVED → MEASUREMENT_DEFINED → OUTCOME_CAPTURED`, then the case
  *contributes to* its family's `SAMPLE_ACCUMULATING`. A single candidate can go no further on its own.
- **Family track:** `SAMPLE_ACCUMULATING → EVALUATED → {SUPPORTED | UNSUPPORTED | INCONCLUSIVE}`, gated
  by the minimum-evidence requirements of §7.

| State | Grain | Entered when | Preconditions / invariants |
|---|---|---|---|
| `OBSERVED` | case | `UserObservation` recorded | observer + `observed_at` + an entity/event the observation points at |
| `MEASUREMENT_DEFINED` | case | `ResearchCandidate` frozen | **all §3 before-event fields present and frozen BEFORE `event_effective`**; else the case can never leave this state as valid (it becomes a descriptive note, never a graded candidate) |
| `OUTCOME_CAPTURED` | case | `CandidateOutcome` appended | event has occurred; completeness recorded; missing variables **pending**, never zero-filled |
| `SAMPLE_ACCUMULATING` | family | ≥1 captured outcome exists for the family key | the matched sample is below the §7 minimum |
| `EVALUATED` | family | §7 minimum reached and an evaluation run against the **frozen** endpoint | evaluation uses only frozen endpoints; no endpoint substitution (§5) |
| `SUPPORTED` | family | evaluation meets §7 evidence bar | out-of-sample; CI/correction satisfied; still **not** an authority grant (§0) |
| `UNSUPPORTED` | family | evaluation shows no effect / effect already priced | recorded with equal weight to SUPPORTED |
| `INCONCLUSIVE` | family | evidence insufficient to separate the two | the honest default; re-enters `SAMPLE_ACCUMULATING` as data grows |

**`INVALIDATED` — a per-case side exit, not a terminal verdict.** If a frozen **invalidation condition**
(§3) fires (e.g. the player is inactive, the assumed QB does not start, game script removes pass volume),
the case is marked `INVALIDATED` and **excluded from the matched sample**. It is **not** graded as a miss
/ `NO_LIFT` — the thesis was never fairly testable. `INVALIDATED` can be reached from
`MEASUREMENT_DEFINED` or `OUTCOME_CAPTURED`.

Transitions are forward-only. A state is never silently rewound; re-evaluation and corrections are new,
superseding records (§6).

---

## 3. Frozen before-event fields (locked at `MEASUREMENT_DEFINED`)

These are the `ResearchCandidate`'s content. They are **frozen before `event_effective`**, content-hashed,
and never edited. Freezing before the event is the entire source of the record's credibility.

| Field | Grain | Notes |
|---|---|---|
| **observer** | who recorded it (`user` / id) | carried from the `UserObservation`; privacy-scoped (§6) |
| **three clocks** | `observed_at` (observer, tz-aware ET+UTC), `event_effective` (the event's own clock — kickoff/first pitch, tz-aware UTC), `bk_captured` (ingestion, + an immutable monotonic `record_seq`) | aligns with Constitution §7. **No clock is ever substituted for another.** When provider data (a posted line) is captured in the snapshot, that provider's `source_updated` is recorded **separately** with a `source_updated_status ∈ {PRESENT, UNKNOWN, NOT_PROVIDED}`; a missing provider clock is never backfilled from `bk_captured` |
| **entity identity** | the subject (player/team), by canonical id | uses the existing resolver discipline — unresolved/ambiguous identity → the candidate is held `UNKNOWN` and is **ineligible**, never guessed (mirrors CFB `(GameID,TeamSide)` fail-closed) |
| **event identity** | the game/event, by canonical id | with `event_effective` |
| **category / sub_label** | e.g. `PLAYER_MILESTONE_USAGE` / `BIRTHDAY` | adding a sub_label is a **data-labeling** decision, never a scoring change |
| **thesis** | the hypothesis in plain words | frozen verbatim; the human claim being tested |
| **primary endpoint** | the ONE pre-registered measurement | e.g. within-player matched **target-share lift**. Causal/opportunity, **not** a prop result, **not** a bet result. Exactly one; immutable |
| **baseline method** | how "expected" is computed | e.g. role/matchup/game-script/team-pass-volume expected usage; method is versioned |
| **assumptions** | what must hold for the test to be valid | e.g. player active, normal snap role, assumed starter plays |
| **invalidation conditions** | what voids the test (→ `INVALIDATED`, §2) | frozen pre-event; firing excludes the case from the sample, never grades it a miss |
| **whether the user acted** | did the observer place a bet / take a position? | recorded as **context only**; it has **no** effect on the endpoint, which is usage, not bet outcome (§8 link to Decision Journal is by reference) |
| **pre-event snapshot** | what was knowable at `observed_at` | posted lines/prices + their provider `source_updated`, pregame expected usage, competing-receiver availability; a variable not obtainable pre-event is **pending**, never zero-filled |
| **sources** | user-supplied provenance | URLs/citations as given (e.g. the Steelers bio for a birthday); not independently authoritative |

A candidate whose §3 set is incomplete, or frozen **after** `event_effective`, is permanently a
descriptive note — it can never enter the matched sample.

---

## 4. Append-only after-event fields (`CandidateOutcome`)

Appended after the event. These **attach** to the candidate; they **never** touch a frozen field.

| Field | Notes |
|---|---|
| **actual outcome** | the realized value of the **frozen primary endpoint** only (plus the measured variables it needs) |
| **completeness** | `COMPLETE` / `PARTIAL` / `PENDING` per variable; missing variables stay **pending**, never zero-filled; a partial case states what it can and cannot support |
| **baseline comparison** | actual vs the frozen baseline's **expected** — the comparison the endpoint defines, nothing substituted |
| **confounders** | observed co-causes (snaps, QB change within tolerance, blowout script, competing-WR injury) recorded so the matched evaluation can control for them |
| **measurement receipt (ref)** | a reference to a Decision-Integrity `decision_time`/`source_health` receipt id that captured the inputs, **if** one exists — a pointer, not an embedded receipt (§8). Absent ⇒ replay class is declared lower, not faked |
| **per-case disposition** | `CONFIRMED_LIFT` / `NO_LIFT` / `INVALIDATED` — a per-case label, **not** a verdict on the family |
| **research status (case view)** | always `RESEARCH_ONLY`; a case never earns authority |

Append-only + supersession (§6) means a regrade or a late correction is a **new** `CandidateOutcome`
linked to the one it supersedes; history is never silently rewritten.

---

## 5. Hindsight prohibition (the load-bearing rule)

1. **No endpoint substitution.** The `ValidatedFinding` and every `CandidateOutcome` are evaluated
   against the **frozen primary endpoint** recorded at `MEASUREMENT_DEFINED`. The endpoint cannot be
   changed, swapped, or "clarified" after the event. If the frozen endpoint turns out to be the wrong
   question, that is itself a finding (often `INCONCLUSIVE`/`UNSUPPORTED`) — you do **not** rescue the
   case by re-aiming at whatever happened to move.
2. **Secondary outcomes are descriptive only.** Anything observed that is not the frozen primary endpoint
   (the prop over/under, touchdowns, the bet result, "he had a big game") MUST be labeled
   **`descriptive`** and **can never replace or stand in for** the primary endpoint, nor contribute to the
   `SUPPORTED/UNSUPPORTED` evaluation. They may be shown as context; they are never the grade.
3. **Pre-registration is the test.** A candidate frozen after `event_effective` (§3) is ineligible. The
   value is entirely in the before/after split.
4. **One primary endpoint.** Exactly one, chosen before the event. "Multiple primary endpoints" is a way
   to guarantee one of them moves; it is prohibited.

---

## 6. Boundaries: identity, correction, supersession, privacy, licensing, deletion

- **Identity.** Entities resolve through the existing sport-scoped resolver; unresolved or ambiguous
  identity ⇒ the candidate is `UNKNOWN` and **ineligible**, never guessed. Family membership is keyed on
  the resolved canonical id + the family key, so two spellings of one player never split a sample and two
  players never merge.
- **Correction.** A changed input (rescheduled kickoff, a regrade, a line correction, a fixed birthday)
  produces a **new** record linked to what it supersedes. Frozen before-event fields are **never** edited
  in place; if the freeze itself was wrong, the old candidate is **superseded and excluded**, and a new
  candidate can only be frozen if a valid pre-event timestamp still exists — otherwise it is a descriptive
  note (you cannot "re-freeze" after the event). (Constitution L6/L12.)
- **Supersession.** Ordering is by an immutable **`record_seq`**, never by provider `source_updated`
  (which can regress or arrive late). A superseding record references the superseded one by `record_seq`;
  the lineage is readable end-to-end.
- **Privacy.** A `UserObservation` is personal data scoped to its observer. Observations are
  **not** shared, cross-joined across users, or surfaced publicly. A `ValidatedFinding`, if it ever
  exists, reports **aggregate, de-identified** sample statistics only — never an individual's observation
  text or betting activity.
- **Licensing.** Provider data captured in the pre-event snapshot (posted lines, usage stats) is stored
  and retained **only** as each provider's license permits; where it does not, the variable is **gated**
  (`Unavailable`), never copied or synthesized. Usage measurement draws on licensed sources (e.g.
  nflverse under its terms); lines per the odds provider's terms.
- **Deletion.** An observer may delete their `UserObservation`; deletion **tombstones** the observation
  and strips its PII/free text. Whether an already-evaluated, de-identified `CandidateOutcome` is also
  purged (forcing a sample recount) or retained as an anonymous data point is a genuine policy choice —
  see §10 Q8. Default: tombstone the observation; retain the de-identified outcome with a supersession
  note, unless stricter privacy is elected.

---

## 7. Minimum evidence before a `ValidatedFinding`

**One case can never establish an edge.** A single game is recorded only to *seed* a matched sample. A
family may be promoted out of `SAMPLE_ACCUMULATING` to `EVALUATED`, and a `ValidatedFinding` created, only
when **all** of the following hold (exact numeric floors are §10 Q3, pending a power analysis):

1. **Pre-registered primary endpoint**, frozen per §3 for every contributing case.
2. **Matched design.** Within-player (or within-entity) comparison of milestone cases vs the same
   entity's non-milestone cases, **controlling for** routes, snaps, quarterback, opponent, injuries, and
   team pass volume (per the family's baseline method). Unmatched counts do not qualify.
3. **Out-of-sample.** The effect must survive out-of-sample / holdout measurement. In-sample strength is
   not evidence (CLAUDE.md §10: four streak-parlay rules with in-sample lower-CI bounds of +8.3 to +17.8
   all reversed to significantly negative out-of-sample).
4. **Sample floor + power.** A minimum number of matched pairs across **independent** cases (not one
   player, not one week), set by a power calculation. Small-sample mirages are the known failure mode
   (CLAUDE.md §10: a 3-leg parlay rule showed **+63% at n=21** and **−29% at n=2,861**).
5. **Multiple-comparison discipline.** Each sub_label is a separate test; evaluating five narratives
   requires family-wise error correction. A `SUPPORTED` verdict needs the **corrected** CI lower bound to
   clear zero, not the raw one.
6. **Invalidated cases excluded** (§2) — never silently counted as misses.
7. **Completeness.** Partial cases (pending variables) are weighted honestly or excluded per the frozen
   rule; a sample padded with zero-filled variables does not qualify.

If these are met and the effect holds, the finding is `SUPPORTED`; if the effect is absent or already in
the price, `UNSUPPORTED`; if the evidence cannot separate the two, `INCONCLUSIVE` (and the family returns
to `SAMPLE_ACCUMULATING`). **`SUPPORTED` is still `RESEARCH_ONLY`** — promotion to any authority is a
separate, governed decision outside this contract (Constitution §9), not a consequence of this verdict.

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
  `decision_time` receipt (the capture-precision record of the pre-event snapshot) and/or a
  `source_health` receipt. It stores the **id**, not the receipt body. The receipt keeps its own envelope,
  hashes, and lifecycle; the candidate keeps its own.
- If the observer acted on the observation, the `UserObservation.acted` flag MAY reference a **Decision
  Journal entry id**. That link lets a reader see "the person also bet this," but the candidate's endpoint
  remains **usage**, not the bet result — the journal entry never feeds the evaluation.
- **No shared primary key, no joined table, no inherited schema.** A receipt is never a candidate; a
  candidate is never a receipt; a journal entry is never either. The reuse is of **discipline** (three
  clocks, append-only corrections, supersession, replay class, RESEARCH_ONLY) and of **references**.
- Replay/correction semantics are borrowed, not merged: a candidate declares its own reproducibility
  posture, and a corrected candidate supersedes by `record_seq` exactly as a correction receipt does.

This keeps the option open to, one day, show "this observation was pre-registered (candidate), its inputs
are integrity-verifiable (receipt), and the person acted on it (journal)" — three linked records, three
intact models.

---

## 9. Worked examples

### 9.1 VALID — Case #1, Pat Freiermuth `BIRTHDAY` (the preserved pre-kickoff observation)

- **`UserObservation`**: observer = user; `observed_at` = 2026-10-25 08:51 EDT (`2026-10-25T12:51:21Z`),
  **before kickoff**; subject = Pat Freiermuth (TE, PIT, canonical id); event = PIT vs NO (Paris);
  thesis = "Rodgers may involve Freiermuth more than his normal role **because it is his birthday**";
  sources = Steelers bio + schedule; `acted` = (recorded as context).
- **`ResearchCandidate`** (frozen at `MEASUREMENT_DEFINED`, pre-kickoff): category
  `PLAYER_MILESTONE_USAGE` / sub_label `BIRTHDAY`; **primary endpoint = within-player matched
  target-share lift** (not receptions, not a prop, not a bet); baseline = role/matchup/game-script/team-
  pass-volume expected usage; assumptions = {active, normal snap role, Rodgers starts}; invalidation =
  {reduced snaps, injury limitation, QB change, pass-volume-killing script}; pre-event snapshot = posted
  rec/yards lines + prices @ `observed_at` (pending until recorded, never zero-filled), pregame expected
  usage (pending). → state `MEASUREMENT_DEFINED`, `RESEARCH_ONLY`.
- **`CandidateOutcome`** (after the game): actual targets/target share, routes/TPRR, first-half,
  third-down + RZ targets, team pass volume, snaps, competing-WR availability; **baseline comparison** =
  actual vs expected usage; confounders noted; per-case disposition ∈ {`CONFIRMED_LIFT`, `NO_LIFT`,
  `INVALIDATED`}. Missing variables stay **pending**.
- **Why valid:** one endpoint, frozen before kickoff, graded on usage, not the prop. It **seeds** the
  `BIRTHDAY` family; it is explicitly **not** evidence of an edge. The family stays
  `SAMPLE_ACCUMULATING`.

### 9.2 INVALID — hindsight endpoint substitution
After the game Freiermuth has 2 catches for 15 yards (no usage lift) but scores a TD. Re-labeling the case
a "birthday **touchdown** effect" to call it a hit. → **Prohibited (§5.1/§5.2).** The TD is a `descriptive`
secondary outcome; the frozen endpoint was usage lift; the case grades `NO_LIFT`.

### 9.3 INVALID — one case becomes a finding
A single `CONFIRMED_LIFT` case is promoted to a `ValidatedFinding` ("birthdays boost usage"). →
**Prohibited (§1, §7).** No `ValidatedFinding` from one case; the family remains `SAMPLE_ACCUMULATING`.

### 9.4 INVALID — secondary outcome replaces the primary
The posted baseline-usage data never arrives, so the evaluation quietly switches to "did the receiving
prop go over?" because that data is handy. → **Prohibited (§5.2).** The prop is descriptive; a missing
baseline keeps the variable **pending**; the case is `PARTIAL`, not re-aimed.

### 9.5 INVALID — post-hoc freeze
The observation is entered **after** kickoff but back-dated, or frozen with assumptions written to match
what happened. → **Prohibited (§3, §5.3).** A candidate frozen after `event_effective` is a descriptive
note, ineligible for the sample.

### 9.6 VALID — honest `UNSUPPORTED`
After enough matched `REVENGE_GAME` cases across many players/seasons, out-of-sample target-share lift is
≈0 with a corrected CI spanning zero. → `EVALUATED → UNSUPPORTED`. Recorded with the same weight as a
positive result; this is a successful use of the system, not a failure.

---

## 10. Unresolved decisions (recommended defaults — STOP for review)

| # | Decision | Recommended default | Why it needs a human |
|---|---|---|---|
| Q1 | Candidate grain: per-case frozen candidate + family-level finding, as in §1? | **Adopt the two-grain model** (per-case `ResearchCandidate`, family-level `ValidatedFinding`) | It is the cleanest way to satisfy "freeze per case" *and* "one case ≠ an edge"; confirm before anything downstream assumes it |
| Q2 | Who may create a `UserObservation`? | **Owner/founder only** during the design era; per-observer privacy scoping when/if opened up | Scope + privacy posture is a product call |
| Q3 | Exact §7 numeric floors (min matched pairs, power, significance, correction method) | **Defer to a power analysis**; interim floor: ≥2 independent seasons AND a power-justified pair count AND corrected-CI lower bound > 0 | The numbers decide what "supported" ever means; must not be guessed |
| Q4 | Deletion vs sample integrity (§6) | **Tombstone the observation (strip PII); retain the de-identified outcome** with a supersession note | A real privacy-vs-research-integrity tradeoff the owner must choose |
| Q5 | Which secondary outcomes are allowed as `descriptive` context | An explicit allow-list (prop line/result, TDs, yards) shown but **never graded** | Prevents §5.2 drift via an ad-hoc list |
| Q6 | `ValidatedFinding` naming — does `UNSUPPORTED`/`INCONCLUSIVE` live under "ValidatedFinding"? | **Yes** — "validated" = *evaluated against the frozen contract*, any terminal status | The word reads as "confirmed"; confirm the semantics or rename (e.g. `EvaluatedFinding`) |
| Q7 | Clock set: three (`observed_at`/`event_effective`/`bk_captured`) + provider `source_updated` recorded separately? | **Yes**, exactly as §3 | Confirm the alignment with Constitution §7 before any capture format is drawn |
| Q8 | Measurement-receipt reference — required or optional for a case to be eligible? | **Optional**; absence lowers the declared replay class, does not disqualify | Tightening to "required" would block seeding real cases early |
| Q9 | Sub_label extensibility — who may add a narrative (`BIRTHDAY`, …)? | **Owner approval**; adding a label is data-labeling, never a scoring change | Keeps the family list governed |
| Q10 | Promotion path from `SUPPORTED` to any authority | **Out of scope here** — a separate governed decision (Constitution §9); this contract grants none | Must stay firewalled from this design |

**STOP — returned for review.** No store, route, UI, job, score, or production behavior exists or is
proposed. Nothing here touches the factual boards, Green Light, rankings, tickets, or governed models.
The NFL ATS runtime pilot stays OFF; the NBA acceptance receipt remains an independent production gate.
```
