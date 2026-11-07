# Green Light Restoration P0 — completed audit + restoration plan (DESIGN ONLY, 2026-11-07)

**Status:** prepared for owner review. **Not built.** No implementation, merge, push or deploy until the owner reviews
this plan, and not before the `b12eec3` production receipt closes (PROGRAM_TABLE P1-1 → P1-GL).
**Intent preserved:** Green Light = the convergence board — several trusted factors supporting a play, with
contradictions and missing evidence visible. No new score, no redesign, no automatic picks, no manufactured confidence.
**Owner decisions recorded (2026-11-07):** (1) the workspace-default switch `9057ba1` was not owner-approved; the
convergence board returns as the main experience **only after** its prices and event eligibility are trustworthy.
(2) Unsupported model numbers are hidden or clearly quarantined until governed — never silently shown as facts.

Inputs: `docs/green_light_play_finding_audit_20261107.md` (live audit), `docs/green_light_audit_code_history_20261107.md`
(code/history). Code citations are `b12eec3` line numbers.

---

## Part 1 — Completed read-only audit (owner items 1–6)

### 1. Stale inputs: production files and responsible jobs (prod, read-only SSM, 2026-11-07 ~15:10 UTC)
| Input | Prod file / producer | Observed | Verdict |
|---|---|---|---|
| NFL line movement | `data/tracking/NFL_LineMovementCurrent.csv` ← `refresh_football_line_movement.py` (`bk-daily` step "Football line movement", **PASS** today) | mtime 13:00 UTC; 591 rows; `Date` 2026-09-09 → 2027-01-10; `LastUpdated` max 08:00 ET | **Not stale. Unfiltered.** The file carries the whole season; the GL Line Movement lens lists completed games as live (no upcoming/completed filter). |
| Matchup Center line-move join | `_line_movement_for_game` app.py (returns `spread_open/spread_cur/total_open/total_cur`) | Unavailable for all 14 games | **Two defects:** (a) the join returns None for every current game (date-format vs abbreviation mismatch — exact cause UNVERIFIED); (b) **key-schema mismatch** — Matchup Center reads `book/first_captured/spread_first/spread_last/total_first/total_last`, which the function never returns ⇒ What's Changed can never fire, even after (a) is fixed. |
| NFL Wave (`/tools/nfl-wave`, Matchup Center ATS module) | `build_nfl_wave_watch_context` ← runtime `scenarios/nfl_scores.json` (`build_nfl_scores.py`, `bk-daily` "NFL scores + QB1", **PASS**) | mtime 13:05 UTC; `ats` has all 32 teams (e.g. SEA 2-4-2) | **Data current; logic obsolete.** A "wave" = season-long *undefeated* ATS (`w>=2 and l==0`) and a "sinker" = winless — designed for Weeks 2–3; no team qualifies at Week 9. Also **model-gated** (rides need `projected_margin` edge ≥1.5). A working active-run builder already exists (`build_nfl_ats_wave`, used by the GL ATS lens). |
| Riding the Wave "through Feb 8, 2026" | `load_nfl_game_lines_history` ← `data/historical/NFL_GameLines_History.csv` | **MISSING on prod**; falls back to `NFL_Archive_10Y_SBR.json` (ends at Super Bowl LX) | **Data gap + label.** The lens's `data_through` is the archive's max date; situational "season openers" runs (2004–2025) keep the lens "available". |
| CFB current-season inputs | runtime `scenarios/cfb_2026_*.json`, `cfb_ats_streaks.json`, `cfb_line_moves.json`, `cfb_pace.json` … ← `refresh_cfb_data.py` (`bk-daily` "CFB data refresh") | **all mtime 2026-10-21 13:06**; `cfbd_quota_state.json` → `"exhausted": true`; today's step **FAIL** | **Stale by quota latch** (17 days). Not a Green Light code fix — attaches to P1-6 (CFBD allowance decision). |
| Baseline for the `b12eec3` receipt | today's pre-deploy `bk-daily` | DEGRADED: CFB data refresh, MLB daily refresh, **NBA daily refresh**, WNBA game lines FAIL | NBA board emptiness traces to "NBA daily refresh" — first post-deploy evidence 2026-11-08 13:00 UTC. |

### 2. Does the classic convergence board include started games? — **Yes, it can.**
`_nfl_wisdom_props()` reads `data/props/NFL_Props.csv` (FanDuel rows) and never reads `EventCommenceAtUTC`;
`build_green_light` has no kickoff gate. Today it shows none only because the 13:00 UTC props refresh dropped the TNF
game (prod file: min `EventCommenceAtUTC` = 2026-11-08T14:30Z, 0 BAL/JAX rows). Props refresh daily, so from the first
Sunday kickoff until the next refresh (Mon 13:00 UTC) started games stay in the file and the board would list them with
pre-game prices. Exclusion today is incidental to refresh timing, not a rule.

### 3. The uniform −114 — **genuine FanDuel quotes, not synthetic.**
Prod `NFL_Props.csv`: 229 FanDuel Rush/Rec Yds rows, 220 priced −114/−114 (others −108, −102, −115, −128, +100);
non-FanDuel books vary widely (−115, −111, −120 …). Each row carries `SourceUpdatedAtUTC` 12:57–13:00Z. Example:
Bijan Robinson Rush Yds FanDuel open 95.5 → current 97.5 at −114 (BetMGM 92.5 −125, DraftKings 97.5 −111). No default
or fill value exists in the fetch path. This is FanDuel's standard two-way yardage pricing. **But:** it is a 13:00 UTC
snapshot (not proof of a currently executable price), FanDuel-only (not the best available), and the classic board
shows it with **no book and no quote time**.

### 4. All-overs parlay warning — exists, but not where the overs are.
Three implementations: `analyze_saved_parlay_ticket` (app.py:14171-14188, saved Parlay Builder tickets),
`build_ticket_check_context` (:21006) and `build_pick_analyzer_context` (:21113). **Not shown** on Today's Cards,
King's Tickets, the Green Light proposed ticket or the SGP Workbench — whose NFL prop legs are all overs by construction
(`"{player} {stat} {line}+"`, no direction key, app.py:34321-34327). Ticket Check's parser reads only sides starting
"O"/"U", so a pasted "6.5+" floor leg is not counted as an over.

### 5. Model-generated numbers on factual pages
Governed registry (`services/model_registry.py`) holds exactly one entry (`nfl_qb_rushing_yards`, Discovery).
**Every number below is ungoverned.**
| Surface | Number | Class | Authority today |
|---|---|---|---|
| NFL Board | "model total" | MODEL (`nfl_totals.total_read`) | **decides membership** (≥2.5 off the line) |
| NFL Game Board / NFL Hub preview | model margin/total; wind tier labelled **"Validated"** | MODEL | **decides sort + membership** (top 20) |
| Matchup Edge `/tools/nfl-matchup-edge`, Hub "77 edge" | 0–100 edge blend | MODEL (composite score) | **decides sort** |
| NFL Wave Watch | "model's margin" | MODEL | **decides membership** |
| Period Board | "Model 1H/1Q Total", "Full-game model", fixed ~52%/~23% split | MODEL | display only |
| CFB Wave overlay, CFB Matchup "Edge Card" | SRS/SP+ blend reads | MODEL | display only |
| NFL Power / Elo, game-lines Elo edge | Elo | MODEL (own skill gate, unregistered) | ranks the page |
| CFB Power | SP+/FPI (third-party) | MODEL (external) | ranks the page |
| Props screener "Fair −106 · **Model** 51.4%" | de-vigged multi-book price | **MARKET-DERIVED, mislabelled Model** | — |
| Props screener "CONFIDENCE" | rescaled de-vig (50–99) | **MARKET-DERIVED, presented as confidence** | user-selectable sort |
| GL ATS Waves (CFB) "Model rates above the line" / "Soft schedule (opponent-adjusted)" | AP-poll trend; `orank` hard-coded 999 | **DESCRIPTIVE, mislabelled Model; "opponent-adjusted" claim has no data behind it** | — |
| GL classic "Game Identity … 61% to lead" | de-vigged moneyline | MARKET-DERIVED (it is win probability, not "to lead") | sets certainty ⇒ affects lens count |
| Totals "Over env", BK Power | O/U and ATS records | DESCRIPTIVE | — |

### 6. Ruled-out / IR filtering gap — confirmed.
Props screener: `annotate_prop_rows_with_injuries` (app.py:21226-21254) **labels only** — OUT/DOUBTFUL → PASS + note,
QUESTIONABLE → CONFLICTED; **no row is removed or demoted** (default sort = player name). **IR, PUP, NFI, SUSPENDED
match no branch** (badge only, no PASS, no note). A correct classifier already exists and is unused here
(`_nfl_player_availability` :32377-32433; `_injury_severity_bucket` :19892). **Same gap, with no handling at all:**
the shared predicate `services/nfl_inclusion.py`, Daily Cards / King's Tickets / swap pool, Green Light classic,
Player Check (would explain an OUT player as INCLUDED), Best Lines. Ticket Check / Pick Analyzer flag only.

---

## Part 2 — Restoration plan (prepared, NOT built)

One release candidate at a time, each its own branch → offline gate → exact-SHA Linux gate → owner deploy decision →
production receipt. Proposed order: **R1 Truth fixes → R2 Convergence-board integrity → R3 Usability (default
restore + connections).** Data dependencies (D) run on their own tracks and gate specific R items as noted.

### R1 — Truth fixes (correct what is shown; no new capability)
| # | Fix | Scope | Acceptance |
|---|---|---|---|
| T1 | Injury join: Matchup Center reads `build_nfl_injury_changes` as the list it returns; injury changes feed What's Changed | `build_nfl_matchup_center_context` | QC: synthetic injury change appears on its game card + What's Changed; live: no "Injury Unavailable" while the injury file is fresh |
| T2 | Line-move join + schema: fix the current-game match and align the returned keys with what Matchup Center/What's Changed read | `_line_movement_for_game`, matchup center | QC: a moved current game shows first/last captured values; an unmoved one says "no material move", never "Unavailable" |
| T3 | Stale-data suppression: GL Line Movement lens = upcoming games only; Riding the Wave lens = current-season runs only with true `data_through` and disclosed `unavailable_reason`; Heat Map passes `unavailable_reason`; partial-week "through Week N" labels unified with the completed-week calendar; injuries lens shows its as-of time | GL adapters, label helpers | QC per lens: completed game never listed; prior-season date never shown as current; partial week labelled partial |
| T4 | Honest unavailable wording: Weather = "licence gate off" (not "no wind data"); Contradictions = "unavailable — no rule can fire without weather" (not "none flagged"); What's Changed distinguishes "no change" from "no comparable capture"; empty classic board drops "Wisdomism" | adapter notes, template | QC: each state renders its true cause |
| T5 | Remove unsupported "Validated": GL weather source line, weather adapter item, Matchup Center why-text, Game Board wind tier → the S5 wording ("historical backtest, governance not yet assigned") | 4 strings | grep-QC: no "validated" outside governed entries |
| T6 | Ruled-out filtering: add an availability predicate + reason code to `services/nfl_inclusion.py` using `_nfl_player_availability` (OUT/IR/PUP/NFI/SUSPENDED, fail-closed on stale feed); apply to Green Light classic, Daily Cards/swap pool, Player Check (explains "excluded: OUT"), Best Lines; screener excludes or demotes and catches IR/PUP/SUSP | shared predicate + call sites | `qc_nfl_inclusion_parity` extended; synthetic OUT/IR player absent from every board and explained by Player Check |
| T7 | Model-number quarantine (owner rule): ungoverned MODEL numbers hidden or shown only in a labelled "Unqualified model — research only, not a fact, not a ranking" container; **no ungoverned model decides membership or sort** (NFL Board, Game Board, Matchup Edge, Wave Watch, Hub) — order falls back to neutral kickoff order; relabel market-derived values ("de-vigged market price", not "Model"/"Fair"/"Confidence"); CFB ATS tier labels replaced by the factual AP-trend wording, "opponent-adjusted" removed; "61% to lead" → "61% win probability (de-vigged moneyline)" | listed surfaces | QC: no ungoverned model field reaches a sort key or membership predicate; string QC for relabels. **Owner choice needed: hide vs quarantine-container per surface.** |
| T8 | All-overs warning where overs are built: the existing rule runs in the shared ticket editor / card builder (Daily Cards, King's Tickets, GL ticket); Ticket Check parser reads "N+" as an over | editor + parser | QC: an all-floor card shows the existing warning text; "6.5+" counted as over |

### R2 — Convergence-board integrity (gate for making it the default again)
| # | Requirement | Acceptance |
|---|---|---|
| C1 | Real sportsbook + quote time on every row: carry `Book`, `SourceUpdatedAtUTC` (never `LastUpdated`), `EventId` through `_nfl_wisdom_props`; show "FanDuel −114 · quoted 08:00 ET" | QC: no row renders a price without book + source time |
| C2 | Executable-price rule: a price is shown only within the live-market freshness window used by the ticket path (`_leg_quote_failures`); otherwise "price unavailable — line shown for context" (never a synthesized price). Optional, owner choice: show best available book alongside FanDuel (Best Lines data) | QC: stale quote → no price; fresh → price + book + time |
| C3 | Kickoff gate: `_kickoff_gate_failure(EventCommenceAtUTC, now)`; missing kickoff → row labelled, no price | QC: synthetic started event never listed |
| C4 | Started-event exclusion independent of refresh timing (C3 makes it a rule, not an accident) | prod check during a Sunday window |
| C5 | Truthful fragile-leg warnings: Fragile flag text unchanged in intent; verify its "medium-certainty script" input is labelled market-derived; add the T6 availability exclusion and the T8 all-overs warning on the ticket CTA path | QC on fragile + exclusion |
| C6 | Membership change ⇒ bump `BOARD_VERSION` (`capture_green_light.py`) so the lens-attribution archive stays honest; re-run inclusion-parity, Player Check, lens-attribution QCs | QCs green |

### D — Data dependencies (own tracks; owner decisions where marked)
| # | Dependency | Owner / track | Gates |
|---|---|---|---|
| D1 | NFL line movement: no new data needed (file is complete); filters + join in T2/T3 | R1 | T2, T3 |
| D2 | NFL Wave: replace the obsolete undefeated/winless + model gate with the existing active-run builder (`build_nfl_ats_wave`) for the page and the Matchup Center ATS module; copy "2–3 games in" removed | R1 (code) | Matchup Center ATS module |
| D3 | `NFL_GameLines_History.csv` missing on prod (Riding the Wave current-season situational runs) | data — identify producer / restore | T3 (RtW freshness) |
| D4 | CFB quota latch / CFBD allowance | **owner decision** → P1-6 | CFB items in GL ATS lens (until then: labelled stale, per T3) |
| D5 | NBA publication | `b12eec3` `bk-daily` receipt 2026-11-08 | NBA has no Green Light surface; affects play-finding inventory only |
| D6 | Weather licence | **owner decision** (Future) | Weather lens, Contradictions rule |

### R3 — Usability (only after R2 passes)
| # | Change | Rule |
|---|---|---|
| U1 | Convergence board becomes the default `/tools/green-light`; workspace moves to `?view=workspace`; `?view=classic` kept as alias; sidebar/back-links updated; `qc_green_light_workspace.py` default assertion inverted | **only after C1–C6 pass on prod**; forward edit, reversible |
| U2 | Per-row links: Player Check, the game's Matchup Center card, Best Lines for that prop, Period Board for that game | navigation only — no new evidence |
| U3 | Workspace "proposed ticket" labelled as Today's Cards output (not derived from convergence) | copy |

### Explicitly out of scope
New scoring, redesign, automatic picks, confidence numbers, Lens #8, NBA/NCAAB Green Light, weather licensing itself,
CFBD allowance itself, King's Tickets draft storage.

## Part 3 — Owner decisions recorded 2026-11-07 (supersede Part 2 where they differ)

**Still DESIGN. Nothing is built until the `b12eec3` production receipt closes.**

1. **T7 = HIDE, not quarantine.** Every unregistered model output is removed from customer-facing factual and
   play-finding surfaces. No customer-facing quarantine panel or label. Such outputs may appear **only** in an
   owner-only research inventory that states, for each: *unregistered · discovery only · not validated · not used for
   selection, ranking, Green Light, tickets or recommendations*. They must not select, rank, score, recommend or
   influence Green Light (including the classic "Game Identity" certainty input if it is ever replaced by a model).
2. **Visibility = facts only.** NFL Board and Game Board list **every eligible NFL game in kickoff order**; models
   never decide visibility or order. Users apply factual filters themselves.
3. **Prices = FanDuel + best governed-book quote.** Each quote shows sportsbook, line, price, source time
   (`SourceUpdatedAtUTC`) and freshness, **bound to the same offer** (one row of one book). A line from one book is
   never combined with a price from another. "Governed books" = the existing book policy (currently BetMGM,
   DraftKings, FanDuel in the NFL feed) — confirm the list at BUILD.
4. **Renames / removals:**
   - Props "Model %" → **"Market-implied probability"** (if retained); "Fair" relabelled the same way or removed.
   - Props **"Confidence" removed** (it is a rescaled market price, not independently governed) — including as a sort option.
   - CFB "Model rates above / well below the line" → factual AP-poll wording (e.g. "AP poll: rising").
   - **"opponent-adjusted" removed** wherever no opponent-adjustment dataset exists (CFB ATS tiers: `orank` is hard-coded).
5. **Two releases, sequential:**
   - **Release 1 — Truth & integrity:** T1 injury join, T2 line-move join/schema, T3 stale suppression, T4 honest
     unavailable states, T5 "Validated" removal, T6 player-availability filtering, T7 hide ungoverned models +
     model-free visibility (decision 2) + renames (decision 4), T8 all-overs warnings, C1/C2 sportsbook/time/freshness
     attribution with FanDuel + best governed quote (decision 3), C3/C4 kickoff exclusion, C5/C6 fragile truth +
     `BOARD_VERSION` bump. The convergence board stays at `?view=classic` during R1.
   - **Release 2 — Restoration & usability (only after Release 1's production receipt):** D2 rebuild NFL Wave page
     and Matchup Center ATS module on current factual (active-run) data; U1 convergence board becomes the default;
     U2 connect Matchup Center, Player Check, Best Lines and Period Board; U3 proposed-ticket labelling.
6. **Separate dependencies, never blockers of honest handling:** CFB quota (D4), weather licence (D6), the NBA
   result from the 2026-11-08 `bk-daily` receipt (D5), and the missing `NFL_GameLines_History.csv` (D3). Until
   resolved they render as labelled Unavailable / stale with their true cause.

## Part 4 — Proposed owner workflow (PROPOSED 2026-11-07; awaiting owner confirmation; no implementation until confirmed AND `b12eec3` closes)

1. **Default = today's slate grouped by game**, each game's converging plays beneath it. Secondary **"Top Plays"**
   view sorts plays by agreement count.
2. **Lenses = governed factual evidence only.** Injuries, line movement, ATS trends, matchup history, usage and
   milestone streaks may support or contradict a play **only when current, governed and directionally relevant**.
   Weather is context unless a defined rule connects it to the market. **Missing or stale data never counts toward
   agreement.**
3. **Every play shows three categories:** Supporting · Contradicting · Missing/unknown.
4. **Statuses:** an important unknown does not hide a play but caps it at **"Incomplete — Review Required"** (never
   the strongest status). **Hard blockers ⇒ play unavailable:** started event, stale or unpriced quote, ruled-out
   player, unresolved identity.
5. **Price:** best governed quote first, FanDuel directly underneath; each with sportsbook, line, price, source time
   and freshness from one offer — never a line from one book with another's price.
6. **Play → ticket (eventually):** selecting a play places the exact governed offer into a ticket tray/editor. Release
   1 stays research-only; the handoff belongs to Release 2 after ticket integrity and storage are ready. No silent
   repricing or leg removal.
7. **Sports:** NFL first; CFB (incl. game-level spreads/totals) only after its data is restored and proven current.
8. **Agreement is a count with named evidence, never a confidence score** — e.g. "Supported by 4 of 6 available
   lenses", listing each lens; no percentage, no composite.

**Design notes for confirmation (not decisions):**
- Item 2 expands what counts toward convergence (today: Opportunity, Matchup, Game Identity, Coaching; Concentration =
  TD corroborator). Each newly counting lens needs a written lens contract — source, freshness budget, direction rule
  (what makes it *support* vs *contradict* an over/under), governance status — before it may count. Until then it is
  shown as context only. Changing what counts changes membership ⇒ `BOARD_VERSION` bump and a fresh attribution
  series (old and new counts are not comparable).
- "Of N available lenses": N = lenses that are current and applicable to that play's market; a missing lens appears
  under Missing/unknown, never silently shrinks N without being listed.
- "Important unknown" needs a defined list (proposed: injury feed stale, quote age near the freshness limit, line
  movement unavailable for the game, lineup/role unresolved). Owner to confirm.
- Fit with the release split: R1 (truth/integrity) already delivers the hard blockers, quote display and honest
  unavailable states; the slate-by-game layout, Top Plays view, three-category evidence display, Incomplete status,
  new counting lenses and ticket handoff fall in Release 2 (or a later release if the lens contracts are not ready).

### Open owner decisions (needed before BUILD) — RESOLVED 2026-11-07 (see Part 3)
1. T7 per surface: hide, or show inside a labelled "unqualified model" container? And whether NFL Board / Game Board
   keep membership by model at all once quarantined (proposed: no — neutral kickoff order, all games listed).
2. C2: FanDuel-only price (current classic behaviour) vs FanDuel + best available book.
3. Release split: R1 as one release or two (R1a joins/wording/"Validated"/OUT filter; R1b model quarantine).
4. D4 CFBD allowance; D6 weather licence (both can stay "Unavailable, labelled" meanwhile).
