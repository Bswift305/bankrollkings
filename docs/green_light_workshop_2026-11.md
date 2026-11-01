# Green Light workshop — materials (design only)

Status: **preparation only. No implementation.** Workshop decisions are reconciled into the existing contract
[`green_light_preferences_contract.md`](green_light_preferences_contract.md) — this is not a competing spec.
Scope and intent come from [`platform_todo.md`](platform_todo.md) ("Queued — Green Light decision-convergence
workshop").

## 0. What the workshop must produce

1. Your actual decision process, written down in your words — the order you look at things.
2. For each sport/market you bet: **required** signals, **optional** signals, **contradictions** (evidence
   against), **disqualifiers** (stop, no matter what else lines up).
3. How missing or stale evidence must look (never silently neutral).
4. What you want to see the moment you open Green Light (default view) vs. on drill-down.
5. Account-level preferences to save.
6. The ticket handoff: what has to travel from research into a ticket (line, timestamp, rationale, evidence).

Ground rules (from doctrine and your direction): the decision stays yours; no composite confidence score, no
"lock", no auto-EV; a count such as "4 of 6 of *your* signals aligned" may organize evidence but is not a
grade; a result never proves an edge (out-of-sample or it does not count).

## 1. Case 1 — UCLA −23 vs Nevada (2026-10-31), covered

Treat as a **pregame reconstruction**, not proof. Keep the fact (UCLA covered) separate from the hypothesis
(UCLA is systematically undervalued / faded).

### 1a. What you saw and did (you fill in)
| Item | Your answer |
|---|---|
| When you first noticed the play (date/time) | |
| What caught your eye first | (your note: sustained ATS run + others/market willing to fade UCLA) |
| Line you took, book, time placed | −23 @ ___ , ___ , ___ |
| What else you checked before betting | |
| What would have made you pass | |
| Closing line | |
| Result | UCLA covered (score: ___) |

### 1b. What the platform could actually show before kickoff (evidence audit)
| Signal you might use | Platform lens today | Available for this CFB game pre-kickoff? |
|---|---|---|
| ATS run / wave | `ats_waves` (`build_cfb_wave_context`) | **Stale** — every CFB dataset was frozen at **2026-10-24** (CFBD quota latch; see `docs/bk_daily_rca_2026-11-01.md`). Anything that week was 7 days old |
| Current-season form, common opponents | `cfb_current_form` on the matchup card | **Stale** (same latch) |
| Line movement open→current | CFB line moves (`fetch_cfb_line_moves.py`) | **Stale** (CFBD); Odds-API NCAAF lines were live but the Sunday collapse guard sometimes held them (F5) |
| Market / public positioning ("others fade UCLA") | **none** — no verified public-betting source; doctrine bars "sharp/steam" labels | **Missing** — this was your read, not platform data |
| Injuries | NFL-only lens (`injuries_return`) | **Missing for CFB** |
| Matchup context | NFL-only lens (`matchup_context`) | **Missing for CFB** |
| Weather | NFL-only lens; CFB weather gated by licensing | **Missing/gated** |
| Contradictions | `contradictions` (cfb QC exists) | Available (verify it ran) |
| Coach / big-favorite history | CFB favorite/coach trends research (`project_cfb_favorite_trends`) | **Research only** — not productized; note 10-yr data: big early favorites cover ~48% |

**Takeaway to confirm with you:** for this case most of what you weighed either did not exist in the
platform for CFB or was a week stale. That is the first concrete Green Light gap list.

### 1c. Questions for you
- Which of these were **required** before you'd bet UCLA? Which were nice-to-have?
- What, if present, would have **disqualified** it (e.g., a QB out, a line moving through a key number,
  a big-favorite-at-−20+ history)?
- How do you want "others are fading this team" represented when no verified source exists — your own
  observation logged with a timestamp, or not at all?
- Does a 23-point spread change how much a long ATS run means to you?

## 2. Case 2 — today's NFL slate (2026-11-01) — capture template

Your observations from today, one row per idea you considered (played **or** passed):
| Game / player / market | Line + time | What supported it | What contradicted it | What was missing | Acted or passed, and why | Result (fill later) |
|---|---|---|---|---|---|---|
| | | | | | | |

For each row we will mark which platform lens supplied each piece (NFL has the full registry:
What's Changed, Heat Map, Riding the Wave, Milestone Streaks, Market-Line Streaks, ATS Waves, Matchup
Context, Injuries/Return, Weather, Line Movement, Contradictions, Governed Models) and which came from
outside the site.

## 3. Draft factor taxonomy (to edit together)
| Class | Meaning | Examples to confirm |
|---|---|---|
| Required | idea is not considered without it | current line + book + time; injury status of key players |
| Optional (supporting) | raises interest when present | ATS/prop run; matchup edge; line moving your way |
| Contradiction | real evidence against; shown, not hidden | opposing trend; line moving against; weather vs. an over |
| Disqualifier | stop | key player out after line set; stale data on a required signal; price past your limit |
| Missing / stale | never neutral; visibly flagged | any lens without current data (e.g., CFB on 10-31) |

## 4. Decisions to record at the end (maps to the contract)
- Lens choices per sport → contract §1 (registry) and §2 (preferences).
- Default view vs drill-down → §4 (output).
- What must be stored with a proposed ticket → §4 and Phase 4 (ticket workflow).
- Acceptance tests for each decision → §5.

## 5. Out of scope for the workshop
Implementation, new data providers, any confidence score, any claim that a factor "works" without graded
out-of-sample evidence.
