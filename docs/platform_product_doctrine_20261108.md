# Bankroll Kings — controlling platform product doctrine + reconciliation (owner, 2026-11-08) — UNCOMMITTED DRAFT

**Status:** owner-approved controlling platform principle (recorded 2026-11-08). Documentation only.
- It changes the **standard of success** for every future design, repair and acceptance review. It does **not**
  change the release order.
- `b12eec3` remediation stays the only active implementation and is not expanded by this doctrine.
- Nothing enters build unless it is ordered and scoped in `docs/PROGRAM_TABLE.md`.
- This is **not** an amendment to frozen `DIC-1.0`. Any later incorporation uses the approved amendment process.

## 1. Canonical doctrine (owner wording)
1. Identity comes before evidence.
2. BK preserves the complete governed information and market universe.
3. BK begins with observed reality, not sportsbook selection.
4. BK discovers trends, distributions, meaningful thresholds, changes, conflicts and context.
5. BK treats sportsbook lines, BK milestones and user-defined thresholds as separate but comparable research
   targets.
6. BK connects those targets to identity-bound market offers without inventing missing prices, sides, timestamps
   or associations.
7. BK explains provenance, freshness, applicability, stability, missing information, unknowns, conflicts and
   limitations.
8. BK keeps visibility, evidence, eligibility, actionability and the user's decision independent. **Eligibility
   controls actionability — not visibility.**
9. BK records what the user decided, why, what happened, and what was learned.
10. BK does not determine what the user should bet. **The user decides what receives the Green Light.**

**Decision flow:** reality → trend discovery (over / under / no-trend treated equally) → threshold discovery
(book lines · BK milestones · user lines) → context (supporting / contradicting / missing / unknown /
conflicting / disqualifying / not applicable) → market evaluation (book, line, price, source time, observed time,
executable?) → human decision (Green Light / Watch / Pass / Revisit) → learning.

**Architecture boundary:**
- The **evidence and milestone engine** (retained performance → distributions, thresholds, streaks, context)
  needs no sportsbook offer.
- The **market adapter** attaches identity-bound offers afterwards and never changes the evidence.

**Required identity binding** before evidence or an offer is attached:
- sport and competition;
- player or team;
- event and opponent;
- event time and venue;
- market, period, selection and side;
- sportsbook, line and price;
- provider source time and BK observation time.

Unresolved records may be preserved for investigation. They are never presented as resolved facts or executable
offers.

**Independent customer states**, decided separately for every item:
1. Visible and searchable?
2. Evidence eligible?
3. Current executable offer?
4. May it enter a ticket?
5. User decision recorded?

A stale or started market may stay visible as context while being non-executable. This is consistent with the
four states (`AVAILABLE` / `CONTEXT ONLY` / `REVIEW REQUIRED` / `UNAVAILABLE`) and the least-restrictive-truthful
rule recorded in the Nov 7 audit.

**Value** is one lens, never the discovery engine or a visibility gate. "Green Light Specials" may later flag
governed pricing situations, but never mean "best plays", "highest confidence" or "recommended bets".

**No generic confidence score.** Trust is shown as explicit dimensions:
- source authority;
- identity integrity;
- freshness;
- applicability;
- sample size;
- stability (current / short-term / seasonal / historical);
- status (factual / derived / governed-model / research-candidate).

**Distribution, not average alone.** A historical minimum or percentile is a fact. An asserted future "floor" or
"ceiling" is a projection and must be labelled as one.

## 2. Acceptance fixtures recorded today
- **Bijan Robinson rushing yards (2026-11-08)**
  - Line 96.5. Last five results: 145, 86, 61, 63, 76 (nflverse 2026 REG Weeks 4–8, verified against the retained
    parquet).
  - Over 1 of 5, under 4 of 5. **Active under streak: 4.** Season average 97.5; last-five median 76.
  - Context: ATL is the underdog; Brian Robinson Jr. is on IR.
  - A compliant surface shows all of this symmetrically and hides nothing because the system prefers another
    side.
- **Tee Higgins (owner example)**
  - A season average of 100+ receiving yards must be researchable at 75+ / 80+ / 90+ / 100+ / any user number.
  - Each threshold shows hit rates, an active streak and the distribution.
  - The market is attached only if a governed book offers that exact threshold. Otherwise the threshold stays a
    research target, and BK never invents a price.

## 3. Reconciliation against the release plan

### 3a. Already inside Green Light 1A (`PROGRAM_TABLE` pos 2 scope items 1–14 + recorded 1A acceptance)
| Doctrine requirement | 1A source |
|---|---|
| Identity before evidence: event-bound lenses (fix the cross-event overwrite, 11 of 28 teams); injury and line-movement joins | items 3, 4; 11-08 P0 record |
| Same-offer binding (book, line, side, price, timestamps); spread-side dependency `2e2adc6` lands before 1A | item 5; spread P0 record |
| Both clocks, never merged (Book updated / Observed by BK) | item 6; `FetchedAtUTC` decision |
| Kickoff eligibility = actionability, not visibility | item 1; least-restrictive rule |
| Tiered availability (UNAVAILABLE / REVIEW REQUIRED / AVAILABILITY PASSED); official inactive list as final override | item 2; 11-08 owner correction |
| Missing evidence suppresses only what it invalidates (14-condition behavior matrix) | item 9; 11-08 1A acceptance requirement |
| No unregistered model output; models never select or order | item 10 |
| Lens agreement = descriptive derived evidence, ordering only with governed, event-bound, fresh, named lenses | `DIC-1.0` R7 |
| Market-implied probability labelled as a price translation; no unsupported Confidence | item 12 |
| All-overs warning on the ticket path | item 13 |

### 3b. Proposed to reconcile INTO 1A (needed for truthful restoration — owner to confirm before 1A begins)
1. **Direction symmetry for every market Classic displays.**
   - Over, under and push history, plus the active streak in either direction.
   - The Bijan fixture is the acceptance test.
   - Classic currently generates "primary over" candidates only (baseline inventory), which conflicts with the
     doctrine on any surface it shows.
2. **Visibility independent of candidate selection, within the Green Light game universe.**
   - Every eligible game in kickoff order (item 11).
   - Players with props whom the candidate generator skips stay discoverable, as context.
   - Scope limit: Green Light's own universe, **not** a site-wide props explorer.
3. **Evidence vocabulary** on the lens and evidence panel: Supporting / Contradicting / Missing / Unknown /
   Conflicting / Disqualifying / Not applicable, never collapsed.
4. **Doctrine-conformance matrix** in the 1A acceptance package, covering identity, visibility, evidence,
   eligibility, actionability and user decision.

### 3c. Green Light 1B
- Activation of the repaired workflow as the supported default, unchanged from pos 3.
- The decision vocabulary on the activated surface is Green Light / Watch / Pass / Revisit as **user** states,
  never system verdicts.

### 3d. Later platform capabilities (to be explicitly ordered — not 1A or 1B)
- BK Milestones: threshold maps from retained results, window-switchable, with sample size.
- User-defined thresholds ("Higgins 100").
- Universal props/market explorer across all governed players and markets, direction-neutral.
- Distribution views: median, range, volatility label, percentiles labelled as history.
- Evidence-stability classes and trust-dimension display.
- Cross-market views.
- Change timelines: what changed and when BK learned it.
- Green Light Specials, defined as governed pricing situations only.
- Decision Journal and the learning loop (the dark V1 exists; enablement is separate).
- Market adapter matching thresholds to alternate lines.

### 3e. NCAAB Foundation implications (apply before its build)
| Doctrine | NCAAB design status |
|---|---|
| Identity before evidence | Conforms: opaque team IDs, provider `EventId`, fail-closed resolver |
| Side binding | Conforms: side assigned by construction; totals `Point_OVER == Point_UNDER` |
| Retained outcomes, per-book grading | Conforms: own retained pre-tip snapshots, no consensus |
| Visibility independent of value | Conforms: factual slate lists every event in commence order |
| Book-independent evidence | Conforms: team context from BK's own finals. **Gap:** no team-level threshold/distribution views (later capability) |
| Evidence vocabulary | **Reconcile:** map `AVAILABLE/STALE/UNAVAILABLE/PENDING` fact states onto Supporting/…/Not applicable for the evidence panel |
| Independent customer states | Mostly conforms (kickoff gate for handoff). **Gap:** no user-decision recording (later, via the Journal) |
| New surfaces conform from release 1 | `DIC-1.0` R5 |

### 3f. Existing surfaces that conflict with the doctrine (recorded only — no scope, no branch)
| Surface | Conflict |
|---|---|
| Green Light Workspace default (`9057ba1`) | Shows a system-proposed Daily Card ticket under "Green Light"; not owner-approved |
| Green Light Classic candidate generator | "Featured non-defense usage players, primary over": over-only, a selection gate on visibility |
| Daily Card engine ("best 3/4/5-leg cards of the day") | System-selected cards framed as the destination |
| NFL props board default confidence sort / Model Read | Value-ordered visibility; the confidence restates the price |
| NBA authed board (pre-containment) | Confidence-sort, Tier "edge", LOCKS, injury BOOST |
| Props screener `confidence` default sort | Ranks by a value proxy |
| Kings Wisdomism vision ("auto-spit ranked plays") | A system-selected shortlist by design (not built) |
| Streak/heat surfaces, where only over/"hot" runs are surfaced | Direction asymmetry (verify per surface) |
| NBA market-only pages: prices withheld ~5h after each publish | Visibility of a fresh market suppressed by a timestamp misread. **In active `b12eec3` remediation** |

## 4. Procedure going forward
- Every future release supplies the doctrine-conformance matrix.
- A doctrine gap enters build only after it is recorded, ordered, scoped and accepted in `PROGRAM_TABLE.md`.
- `DIC-1.0` is unchanged.
