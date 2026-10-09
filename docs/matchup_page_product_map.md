# Matchup Page Product Map

**Status: MAPPING ONLY.** No code, UI, doctrine, schema, research, or data work is authorized
by this document. It inventories what exists, classifies it, and defines the shortest honest
path to the six-layer transparent decision-support matchup page. It does **not** authorize any
build. Grounded in the live repo (routes + components) 2026-10-09; pairs with
`BANKROLL_KINGS_DOCTRINE.md` §4–§5, §11.

Governing order (per directive): **inventory → classify → placement → only then future work.**
Nothing is assumed to need rebuilding merely because governance now exists.

---

## 1. Matchup Page Product Contract

The completed matchup page answers, in one honest flow, for a single game:

```
Market Facts → Analytical Context → Research Status → King's View → My View → Track & Learn
```

Promise: *We show the table. We show what has earned trust. We show what has not. You decide.*

| Layer | Purpose on the matchup page |
|---|---|
| **Market Facts** | What is objectively true now — line, total, books, injuries, weather, schedule, records, line movement. Correctness-gated; never a prediction. |
| **Analytical Context** | What *might* help explain the game — opponent-adjusted strength, current form, pace, rankings, matchup splits, market behavior. May disagree with each other; that's fine. |
| **Research Status** | For each contextual idea, how much trust it has earned (the governed label). The honesty layer. |
| **King's View** | Bankroll Kings' *governed* assessment for this game — built only from signals that earned authority; may be "no qualified edge, here is context." |
| **My View** | The user's own emphasis/filters + the slip they build. Options, not one pick. |
| **Track & Learn** | What they actually bet, at the price taken, and the honest after-the-fact measure (CLV, results). |

The King's View sits **inside** this flow, not above it.

---

## 2. Existing Component Inventory

Matchup-relevant components (location = `app.py` route unless noted; many share builders in
`services/`, `*_current_form.py`, `nfl_*`/`cfb_*` modules).

| Component | Location | Purpose | Layer | Depends on | User-visible today |
|---|---|---|---|---|---|
| Legacy matchup page | `/matchup/<matchup>` | NBA/MLB h2h + players + props + records | assembly (NBA/MLB) | gamelogs, live props, game odds | Yes |
| NFL matchup card | `/tools/nfl-matchup` | NFL matchup w/ current-form read | Context | `nfl_current_form.py`, team form | Yes |
| CFB matchup card | `/tools/cfb-matchup` | CFB matchup w/ current-form + common-opponent margin | Context | `cfb_current_form.py`, `build_cfb_2026_results` | Yes |
| Matchup lens | `/matchup-lens` | lens overlay | Context | varies | Yes |
| Game lines / command | `/game-lines`, `/game-lines/command` | spreads/totals board + Elo model-edge | Facts + Context | `power_ratings.py`, odds | Yes (skill-gated) |
| Props board | `/props`, `/props/<filter>` | player prop board | Context | live props feed | Yes |
| Game Context | `/tools/game-context` | environment (pace/total/script read) | Context | current-form, totals | Yes |
| Injury Report | `/tools/injury-report`, `/injuries` | injuries + NBA/NFL with/without impact | Facts | injury feed | Yes |
| Best Lines | `/tools/best-lines` | line shopping across books | Facts | odds feed | Yes |
| Market Movers | `/tools/market-movers` | line movement snapshots | Facts (market behavior) | line-movement history | Yes |
| Slate Pulse | `/tools/slate-pulse` | slate overview | Facts/Context | odds, schedule | Yes |
| Risk Radar | `/tools/risk-radar` | exposure/avoidance warnings | Evaluation | board + guardrails | Yes |
| Ticket Check | `/tools/ticket-check`, `/tools/pick-analyzer` | challenge a ticket | Evaluation | board, parlay logic | Yes |
| Green Light | `/tools/green-light` | NFL convergence of independent lenses, market = gate | Research Status / King's View (NFL) | lens JSONs, attribution harness | Yes |
| NFL Featured / Floor / Wave | `/tools/nfl-featured`, `/tools/nfl-floor`, `/tools/nfl-wave`, `/tools/riding-the-wave` | opportunity/floor/streak surfacing | Context | gamelogs, usage | Yes |
| NFL DvP | `/tools/nfl-dvp` | defense vs channel | Context (Matchup lens) | pbp-derived splits | Yes |
| NFL current-form / rankings / power | `/tools/nfl-rankings`, `/tools/nfl-power`, `build_nfl_team_form.py` | team form, ranks, power | Context | 2026 stats | Yes |
| NFL Buy-Low | `/tools/nfl-buy-low` | opponent-adjusted buy-low | Context | form, schedule | Yes |
| CFB current-form / power / talent / rankings | `/tools/cfb-power`, `/tools/cfb-talent`, `cfb_current_form.py` | team quality/continuity | Context | CFBD, results | Yes |
| CFB ATS / streaks / favorites / key-numbers / pace | `/tools/cfb-ats*`, `/tools/cfb-favorites`, `/tools/cfb-key-numbers`, `/tools/cfb-pace` | sides/totals context | Context | CFBD lines/results | Yes |
| CFB Best Spots / big-favorites / totals | `/tools/cfb-best-spots`, `/tools/cfb-big-favorites`, `/tools/cfb-totals*` | sides/totals board | Context | CFBD | Yes |
| Opponent-adjusted SRS (Audit #1) | `research/cfb_mechanism/` | CFB team-strength benchmark | Research Status = Baseline | game-line history | No (research) |
| Team Form v1 (Audit #2) | `research/cfb_mechanism/audit_team_form_w1.py` | recency-weighted SRS | Research Status = Failed | frozen population | No (research) |
| Lens Attribution harness | `capture_green_light.py`, `grade_lenses.py` | grades NFL lenses forward | Research Status engine (NFL) | Green Light archive | No (internal) |
| Real-vs-Luck (MLB) | `/tools/real-vs-luck` | xwOBA-vs-wOBA luck | Context (MLB) | statcast | Yes |
| MLB situational / NRFI | `/tools/mlb-situational`, `/tools/nrfi` | MLB context | Context | pbp/splits | Yes |
| Scenario Lab | `/tools/scenario-lab` | situation grading (NFL pbp) | Context | 7-yr pbp | Yes |
| Menu | `/tools/menu` | full board + build-your-own slip | My View | `_card_pools` | Yes |
| My View | `/my-view` | archetype landing picker | My View | user prefs | Yes |
| Daily Card | `/tools/daily-card` | auto best 3/4/5-leg cards | My View (Build) | board pools | Yes |
| Bet Tracker | `/tools/tracker`, `services/bet_tracker.py` | personal log + CLV | Track & Learn | user bets | Yes |
| Track Record | `/tools/track-record` | honest results | Track & Learn | archives | Yes |
| Methodology | `/how-we-analyze` | public method explainer | Research Status (adjacent) | — | Yes |

---

## 3. Authority Classification

No component unclassified. (Facts carry *fact* status, not research status; see §6–§7.)

- **Fact:** line/total/books, injuries, weather, schedule, standings/records, game logs, line
  movement / Market Movers, Best Lines, Slate Pulse, live scores.
- **Context Only (built pre-governance; not audited for out-of-sample edge → treat as Legacy
  unless/until audited):** NFL & CFB current-form, rankings, power ratings/Elo model-edge, DvP,
  pace, Buy-Low, Featured/Floor/Wave, Scenario Lab, Real-vs-Luck, MLB situational, CFB
  ATS/favorites/key-numbers/best-spots/totals, Game Context.
- **Qualified:** *none yet.* No signal has earned out-of-sample decision authority.
- **Baseline:** Opponent-adjusted SRS (CFB sides).
- **Under Review:** the NFL Green Light lenses (Opportunity, Matchup, Game Identity,
  Concentration, Coaching) + Script Confidence / Fragile — being graded by the attribution
  harness, data accruing.
- **Failed:** Team Form v1 (CFB recency-weighted SRS, H=3).
- **Data-Gated:** per-possession CFB (no PBP); CFB player-prop lenses (no gamelogs/prop history).
- **Legacy:** every "Context Only" surface above that predates governance and hasn't been
  audited (this is most of the current-form/rankings/board family). Legacy = shown as context,
  **no earned authority**.
- **Retired:** none yet (nothing has held authority and lost it).
- **Evaluation tools (not signals):** Risk Radar, Ticket Check/Pick Analyzer — they warn/
  challenge; classified as **suppression/context**, never affirmative votes.

> Honest headline: **King's View currently has zero Qualified inputs.** Everything is Fact,
> Baseline, Under Review, Failed, Data-Gated, or Legacy context. A truthful King's View today
> says "no qualified edge for this game — here is the market and the context," and that is the
> product working, not failing.

---

## 4. Placement Rules

| Classification | On matchup page? | Influence King's View? | In Research Ledger? | Archive only? | Hidden from customers? |
|---|---|---|---|---|---|
| **Fact** | Yes (with fact-status) | Context/suppression only, never as prediction | No (facts aren't research) | No | No |
| **Context Only / Legacy** | Yes, labeled "context, not yet audited" | Context only; no affirmative vote | Listed (as Legacy) | No | No |
| **Qualified** | Yes, with authority | **Yes — affirmative** | Yes | No | No |
| **Baseline** | Yes, as benchmark/context | Context only (no edge) | Yes | No | No |
| **Under Review** | Yes, labeled "research in progress" | No vote until Qualified | Yes | No | No |
| **Failed** | **No live signal** — may *link* "why we don't use this here" | **No** | Yes (permanent) | Result lives in audit record | No |
| **Data-Gated** | Optional note ("insufficient evidence") | No | Yes | No | No |
| **Retired** | No live signal; link to history | No | Yes | Prior authority archived | No |

---

## 5. King's View Contract

- **May provide affirmative authority:** only **Qualified** research. (Today: none.)
- **May provide context only:** Facts, **Baseline** (SRS), **Legacy** context, **Under Review**
  (shown, not voting), **Data-Gated** (as a stated absence).
- **May suppress conclusions:** the graded-record avoidance signals (longshot-over, single-book,
  all-over, prefer-under), contradiction/QC flags, and **Failed** findings (as "we tested this,
  it didn't hold"). Suppression needs less proof than affirmation — warning is cheaper than a claim.
- **Explicitly prohibited from acting as a vote:** any Fact-as-prediction; any **Failed** or
  **Legacy** signal dressed as an edge; and everything on the §7 do-not-build list (composite
  score, lock, sharp/steam label, cross-sport best-bets, auto-EV, Kelly staking).

> Qualified research authority ≠ verified factual context. A line is *verified* (fact-status) but
> carries no research authority; a Qualified lens carries authority but is not a "fact."

---

## 6. Facts vs Research Rules (prevent a fact quietly becoming a prediction)

A fact describes **what is / what happened**; it becomes a prediction only through an *audited*
mechanism. Guardrails:

- **Injuries:** display who is in/out (fact). Prohibited: "X out → take the under" as a vote,
  unless a with/without *impact* mechanism is Qualified. Until then it's context.
- **Recent results / records:** display the record (fact). Prohibited: "won 4 straight → will
  cover" — streak-continuation is priced (graded record) and unaudited here → context only.
- **Line movement / Market Movers:** display open→now (fact). Prohibited: "sharp money", "steam"
  (do-not-build) or "moved toward X → bet X" as a vote. Market *behavior* is context.
- **Standings / rankings / power ratings:** display the number (fact/context). Prohibited: using
  a rating as an affirmative edge — opponent-adjusted strength is **Baseline** (Audit #1: no
  demonstrated ATS edge), so it is context, never a vote.
- **Current form:** display it (context, Legacy). Prohibited: presenting it as a predictive edge
  — recency-weighting specifically **Failed** (Audit #2); cumulative form is unaudited Legacy.

The rule: **facts and context may inform the user; only Qualified research may make a claim.**

---

## 7. Missing Data Behavior (fact-status; already live per doctrine §10)

| Fact status | Display | As context | Into King's View | Suppression |
|---|---|---|---|---|
| **Verified** | Yes | Yes | Yes (as fact, not vote) | n/a |
| **Partial** | Yes, flagged partial | Yes, caveated | Caveated | may trigger "incomplete" note |
| **Pending** | Yes, "updating" | Limited | No | — |
| **Stale** | Yes, timestamped stale | Limited, caveated | No | may suppress a stale-based read |
| **Unavailable** | Show absence explicitly | No | No | **suppress** any conclusion needing it |
| **Source conflict** | Show the conflict | No | No | **suppress**; never silently pick one |

Missing/old data must read as *missing*, never as neutral or zero.

---

## 8. Single Governance Source

**Finding (gap):** there is **no single governance source** today. Status lives scattered —
`docs/lens_research_queue.md` (roster states), `docs/lens_governance_constitution.md` (tests),
the CFB audit docs + `research/cfb_mechanism/*.json` (verdicts), and code-level availability
states for facts. The Research Ledger and the Matchup Page must both read **one** authoritative
registry; otherwise status will drift between surfaces.

**Requirement (not a build authorization):** one machine-readable governance registry — the
single source of truth for every component's research-status (+ the fact-status contract) — that
both the Research Ledger and the Matchup Page (and any future surface) consume. No parallel
status systems. Its *content* changes only through the governance process (audits, probation,
retirement); surfaces never hand-label status.

---

## 9. Research Ledger Contract

Public record, one entry per research item, fields:

- **Status** (Qualified / Baseline / Under Review / Failed / Data-Gated / Legacy / Retired)
- **Plain-language label** (customer translation, §11 doctrine)
- **Tested question** (the mechanism in one line)
- **Version** (e.g., Team Form **v1**, H=3)
- **Date** (status entry date)
- **Result** (the bounded finding)
- **Interpretation limit** (what it does *not* say)
- **Permitted use** (vote / context / suppression / none)

Status distinctions made explicit in the ledger:

- **Failed** — a candidate was *tested* and did not earn authority (Team Form v1). It never had a
  seat. Shown as "Tested; not supported," linkable as education, never a live vote.
- **Retired** — a signal *previously held* authority and later lost it (none yet). Its prior
  authority and the evidence that removed it are both preserved.
- **Legacy** — *predates governance*; authority never earned because it was never audited (most
  current-form/rankings surfaces). Not a failure — an untested inheritance.

---

## 10. Matchup Page Assembly (relationship/flow, not UI)

Top-to-bottom the page reads as a descent from *objective* to *governed* to *personal*:

1. **Market Facts** establish the game (line/total/books, injuries, weather, schedule, records),
   each with a fact-status chip.
2. **Analytical Context** offers lenses that may explain it (form, strength=Baseline, pace,
   DvP, market behavior) — explicitly multiple viewpoints, allowed to disagree, each carrying its
   research-status label.
3. **Research Status** is not a separate block so much as the *label on every context item* +
   a link to the ledger entry.
4. **King's View** synthesizes only Qualified inputs (today: a stated "no qualified edge, here is
   the market + context"), plus any suppression warnings.
5. **My View** lets the user emphasize the lenses they care about and build the slip.
6. **Track & Learn** captures what they bet and measures it later.

Flow invariant: nothing below "Research Status" may present an unaudited idea as a claim; the
page's authority only ever *increases* left-to-right as governance permits.

---

## 11. Cross-Sport Rules

**Shared (one governance system for all sports):** the status taxonomy, the Research Ledger, the
King's View contract, the fact-status vocabulary, the placement rules, the do-not-build list.

**Sport-specific (evidence models must NOT be forced identical):**

- **NFL** — player-prop lenses + convergence (Green Light), opportunity/role/channel; the
  attribution harness is NFL-shaped.
- **CFB** — **sides/totals** program (per `cfb_research_audit.md`); player props Data-Gated.
  King's View for CFB is game-line-shaped, not prop-shaped.
- **NBA** — props + floor-reliability (its own history); separate backtests.
- **MLB** — real-vs-luck (xwOBA), situational, NRFI; totals edge not locally provable.
- **WNBA** — props, graded record shared with MLB guardrails.
- **MBB/WBB** — themed shells; real data pending; essentially Data-Gated.

A sport inherits the *governance*, never another sport's *evidence model*.

---

## 12. Existing-Gap Assessment

| Capability | Status |
|---|---|
| Market Facts surfaced | **Exists** (line/total/injuries/weather/schedule/records/movement) |
| Fact-status chips consistently shown | **Exists but inconsistent** (states defined in doctrine/code; not uniformly rendered) |
| Analytical Context surfaces | **Exists** (form, strength, pace, DvP, boards — per sport) |
| Research-status label on each context item | **Missing** (status is internal only) |
| Research Ledger (public) | **Missing** |
| Single governance source/registry | **Missing** (status scattered across docs + research JSON + code) |
| King's View as governed per-game synthesis | **Needs integration** (Green Light is the closest NFL piece; no cross-surface King's View; CFB has none) |
| Unified matchup page (six layers) | **Needs integration** (today: fragmented `/matchup`, `/tools/nfl-matchup`, `/tools/cfb-matchup`) |
| My View / slip building | **Exists** (Menu, My View, Daily Card) |
| Track & Learn | **Exists** (Tracker, CLV, Track Record) |
| Qualified signals to populate King's View | **Needs modification/time** — none Qualified yet; attribution must accrue (NFL) / audits must pass (CFB) |
| CFB player-prop evidence | **Intentionally blocked** (Data-Gated: no gamelogs/prop history) |
| Team Form resurrection | **Intentionally blocked** (Failed) |

---

## 13. Implementation Candidates (work packages — NOT authorized)

1. **Governance source/registry** — one machine-readable source of research-status + fact-status
   contract; prerequisite for 2 and 5.
2. **Research Ledger (public page)** — renders the registry with the §9 fields + plain-language.
3. **Fact-status consistency pass** — render the existing availability states uniformly on facts.
4. **Matchup-page assembly** — one page stacking the six layers (per-sport evidence, shared
   governance), consolidating the fragmented matchup surfaces.
5. **King's View integration** — per-game synthesis reading the registry; Qualified-only
   authority + suppression; honest "no qualified edge" default.
6. **Validation/monitoring** — keep the registry honest (status reflects current audit state;
   Legacy items get audited or stay labeled Legacy).

---

## 14. Acceptance Criteria (six-layer experience "complete")

- Every matchup-page component carries a correct, registry-sourced **research-status or
  fact-status** label; none unlabeled.
- **King's View draws authority only from Qualified** items; with none Qualified it honestly says
  so; it never shows a Failed/Legacy/Fact item as a vote.
- **Failed/Retired/Legacy** are visible in the Ledger and never appear as live votes; a page may
  link a Failed item as education.
- **One** governance source feeds both Ledger and Matchup Page; no surface hand-labels status.
- Fact-status (Verified…Source conflict) governs display/suppression exactly per §7; missing data
  never reads as neutral.
- Sports share governance but keep their own evidence models (§11).
- Nothing on the do-not-build list appears (no score/lock/sharp/auto-EV/Kelly).

---

## 15. Recommended Sequence

- **Dependencies:** (1) governance source is the root — Ledger (2) and King's View (5) both
  require it. Fact-status pass (3) is independent and low-risk. Assembly (4) depends on 1–3.
  King's View (5) depends on 1 and on signals existing (mostly time/audits). Monitoring (6) wraps 1.
- **Risks:** biggest is **premature authority** — shipping King's View before anything is
  Qualified, or letting Legacy context imply edge. Mitigated by the "no qualified edge" honest
  default and registry-sourced labels. Second risk: parallel status drift — mitigated by the
  single source (8).
- **Approval gates:** each work package (§13) is its own gate — mechanism/spec → review →
  authorization → build → verify. No package starts without its gate.
- **Smallest viable path:** **governance source (1) → Research Ledger (2)** alone already delivers
  the core promise ("here is what has earned trust and what has not") with *zero* new research and
  *zero* risk of false authority, because the Ledger only reports existing governed verdicts. That
  is the smallest honest increment and the recommended first gate — the matchup assembly (4/5)
  follows once the source exists.

---

## 16. Not Planned (explicitly excluded)

Equal in importance to the roadmap. This exercise does **not** plan, propose, or justify any of:

- New lenses (NFL or any sport).
- New CFB mechanism audits (Audit #3+ remains gated and unselected).
- **Team Form resurrection** — any recency-weighting variant (v2+, other half-lives). Failed is
  final absent a governed reopening.
- Dashboard sprawl / new standalone tools beyond the six-layer integration.
- New research initiatives, schemas, or data collection (CFB gamelogs/prop capture stay blocked).
- Auto-promotion of any Legacy context to Qualified without passing an audit.
- Anything on the doctrine §7 do-not-build list.

The goal of this map is the **smallest honest path to a complete transparent decision-support
matchup page** from what already exists — not a list of interesting things to build.
