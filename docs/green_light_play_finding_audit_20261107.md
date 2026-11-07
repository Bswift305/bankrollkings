# Green Light & play-finding regression audit — findings + restoration backlog (READ-ONLY, 2026-11-07)

**Scope / rules.** Step 5 of the program reset, run while `b12eec3` is under production observation. Regression /
restoration audit of the EXISTING experience — not a redesign. No code, merge, push, deploy, timer, paid request or
refresh. Method: signed-in owner session on `https://bankrollkings.com` (prod = `b12eec3`), ~15:00–15:45 UTC Sat
2026-11-07 (NFL Week 9: TNF played; 14-game Sunday slate ahead). 86 sidebar/tool routes fetched (all HTTP 200),
Green Light workspace rendered live with every lens expanded, classic board read, then targeted reads of the
deployed code (`b12eec3`) to confirm root causes. Companion code/history input:
`docs/green_light_audit_code_history_20261107.md`.

**Green Light's intent (preserved).** Surface plays where several trusted factors converge — a count of configured
lenses pointing the same way, with the market shown as context. Nothing below proposes a score, pick, prediction
engine or new design.

Legend — *Where* = route; *Current/sourced* = observed freshness + source label; *GL uses* = classic (C) / workspace
(W) / neither; *Reach* = reachable without hunting; *State* = OK / BROKEN / MISLEADING / MISSING / DISCONNECTED;
*Fix type* = code / data / licensing / scheduling / nav-UI.

## 1. Green Light itself
| Item | Where | Current / sourced | GL | Reach | State | Fix type |
|---|---|---|---|---|---|---|
| Classic convergence board (5 lenses, tiers, why-chips, fragile flag, TD angle, position filter) | `/tools/green-light?view=classic` | Current: Week 9 slate, 18 plays (3×3-lens, 6×2, 9×1), 15:01 UTC stamp | is GL | **No** — default is the workspace; classic is a small "←" link | Works; **demoted** by `9057ba1` default flip (no owner approval found; contradicts preferences contract §"unchanged default") | nav-UI (route default) |
| Classic row prices | same | `O97.5 (-114)` — no book, no capture time; FanDuel-only; no kickoff gate (code) | C | — | MISLEADING (unlabeled quote; below `17b5e69` provenance standard) | code |
| Workspace lens frame | `/tools/green-light` (default) | 12 lenses each fetched `/tools/green-light/lens/<key>`, all 200 in 0.3–3.2 s | W | Yes | Loads; **no stuck LOADING today** (Market-Line Streaks shows "Loading…" ~3 s then fills). D3 not reproduced on this visit | — |
| Proposed ticket in workspace | same → `/tools/green-light/ticket` | Daily-Card legs, priced per book, "illustrative" combined | W | Yes | DISCONNECTED from convergence (it is Daily Card output under the Green Light name) | nav-UI / copy |

### Workspace lenses (live, expanded)
| Lens | Live result | Current? | State | Root cause (code-confirmed unless marked) | Fix type |
|---|---|---|---|---|---|
| What's Changed | UNAVAILABLE "nothing changed since the last capture" | — | **MISLEADING** — absence of a join reported as "nothing changed" | fed only by Matchup-Center line-move join, which matches no current game (see Line Movement); injury changes never feed it (list/dict bug) | code + data |
| Heat Map | 50 records, "through 2026-11-07 08:04 ET" | Week 8 complete | OK (labels have no line/number detail) | — | — |
| Riding the Wave | 29 records, "**through Feb 8, 2026**" | **No** — 15 "hot start" items are the TNF BAL/JAX players; 14 are "Season openers" runs (Michael Vick 2004-2013, Peyton Manning…) | **MISLEADING** — last-season date as freshness; historical openers runs listed as current evidence in Week 9 | adapter `data_through` = max game-lines-history date; situational openers keep lens "available" | code |
| Milestone Streaks | 15 records, through 08:04 ET | Yes | OK | — | — |
| Market-Line Streaks | 4 records (Henry, Hill, Andrews×2) "Graded through 2026 Week 9" | **Partial week** — only TNF graded; heat map says Week 8 | MISLEADING (week label on a 1-game partial week; inconsistent with Heat Map) | graded file max week | code (label) |
| ATS Waves | 28 records "through wk 7" | NFL items Wks 5–8 OK; **CFB items "through wk 7"** (~4 weeks stale) and phrased "Model rates above/below the line" inside a FACT lens | MISLEADING (stale CFB; model language in a fact lens) | CFB sync inputs stale (CFBD) | data/scheduling + copy |
| Matchup Context | 14 games, through 08:00 ET | Yes (cards) | Lens OK; cards' modules broken (see §4) | — | — |
| Injuries / Return Status | 133 records, **no through-date** | file 08:00 ET (fresh) | Partially misleading — no freshness shown; "return-from-participation" promised, source has status changes only | adapter `data_through=None`; label | code (label) |
| Weather | UNAVAILABLE "no outdoor wind data for the slate"; source line says "**validated** totals-under flag" | — | **MISLEADING ×2** — licence gate (`BK_WEATHER_SOURCE_LICENSED` off) reported as missing data; "validated" claim regressed after `c4ca828` S5 | code (copy) + **licensing decision** |
| Line Movement | 407 records | **No** — items are prior-week matchups (NE@SEA, SF@LAR, ATL@PIT, BUF@HOU…), none on this week's slate | **MISLEADING** — old snapshots shown as live | `NFL_LineMovementCurrent.csv` not current for Week 9 (verify producer cadence on prod: `refresh_football_line_movement.py`; `bk-daily` runs `--sports nba,wnba,mlb`) + no staleness/completed-game filter | scheduling/data + code |
| Contradictions | UNAVAILABLE "no contradictions flagged" | — | **MISLEADING** — single rule depends on licence-gated weather, so structurally empty; "none flagged" ≠ "unavailable" | code (copy) |
| Governed Research Models | GATED, 1 (QB rushing, Discovery) | — | OK by design | — | — |

## 2. Slate, lines, prices
| Item | Where | Current / sourced | GL | Reach | State | Fix type |
|---|---|---|---|---|---|---|
| NFL slate + game lines | `/sports/nfl` (26 rows), `/tools/nfl-game-board`, `/tools/nfl-totals-today` | 08:00 ET, BetMGM/DK/FD | C (Game Identity via spread/ML) | Yes | OK; game/totals boards also show **"MODEL Total … model 39"** reads | governance question (model reads on boards) |
| CFB slate + lines | `/sports/ncaaf` (140 rows) | 08:01 ET | W (ATS) | Yes, but **23.7 s** cold load | OK / slow | perf (later) |
| NBA slate | `/sports/nba` | Slate Pulse: 21 NBA games, **props "—"**, "Props feed is stale"; Command Center **0 games / 0 props** | — | Yes | **BROKEN for play-finding** — NBA board empty on a full Saturday slate | **Tied to `b12eec3` observation** (NBA props publisher runs in `bk-daily`; first post-deploy run 2026-11-08 13:00 UTC). Do not treat separately until that receipt |
| MLB / WNBA | `/sports/mlb`, `/sports/wnba` | Off-season; Slate Pulse "238h/166h stale"; Game Context still shows a **Brewers @ Rays "Both confirmed"** card in November | — | — | MISLEADING (stale off-season context presented as a matchup) | code (season gate) |
| Period lines (1H/1Q spread+total, team totals) | `/tools/nfl-period-board` | 3 books, every Sunday game | **No** | Only via NFL Hub list | OK data; **"Model 1H/1Q Total"** reference from the full-game model (e.g. DAL@IND model 61.3 vs market 51.5) | governance question; DISCONNECTED from GL |
| CFB period lines | `/tools/cfb-first-half` is game-flow trends, not posted 1H lines | — | No | — | MISSING (no CFB 1H line board) | Future |
| Props | `/sports/nfl/props` (3 books), `/tools/best-lines` | 08:00 ET | C (FanDuel Rush/Rec Yds only) | Yes (8.2 s) | Screener lists **OUT/IR players** (e.g. Zavier Scott, IR Nov 5) as rows with a "Model Read"; prices print `+1300.0` | code |
| Best price + book | `/tools/best-lines` | per-book price, ET capture time, "3 books same/different number" | **No** (classic uses FanDuel only) | Yes | OK — the reference provenance standard | GL disconnected |

## 3. Streaks & form
| Item | Where | Current | GL | State | Fix type |
|---|---|---|---|---|---|
| NFL ATS wave page | `/tools/nfl-wave` | "**No wave yet** — fills in once teams have a 2026 ATS record… NFL is only 2–3 games in" (Week 9) | feeds Matchup Center ATS module | **BROKEN + stale copy** (while the GL ATS lens, from a different builder, has NFL Wks 5–8 runs) | code (builder/source) |
| NFL team ATS/SU/O-U table | `/tools/nfl-ats`, `/tools/nfl-team` | "real graded games (**1999-2025**)" — no 2026 | No | MISSING current season | data/code |
| CFB ATS & O/U streaks | `/tools/cfb-ats-streaks` | "through Wk 8 · Updated **2026-10-21**" | W (ATS lens) | **STALE ~17 days** | data/scheduling (CFBD latch → P1-6) |
| CFB Wave Watch | `/tools/cfb-wave` | "through Week 7" | W | STALE | same |
| CFB pace/totals | `/tools/cfb-pace` | Updated 2026-10-21 | No | STALE | same |
| Recent form | `/tools/nfl-heatmap` (Wk 8 ✓), `/tools/riding-the-wave` (Wk 9 partial), `/tools/nfl-rankings` "Through Week 9", `/tools/nfl-regression` "Wk 9" | mixed week labels on a 1-game partial week | partly | MISLEADING (inconsistent "through" week across surfaces) | code (labels) |
| Milestones | `/tools/nfl-milestones` | Wk-labelled, historical runs disclosed | W | OK | — |

## 4. Matchup / history / context
| Item | Where | Current | GL | State | Fix type |
|---|---|---|---|---|---|
| NFL Matchup Center | `/tools/nfl-matchup-center` (14 games) | market ✓ 08:00 ET; O/U tendencies ✓; roof ✓ | W (Matchup lens) | **BROKEN joins** — for every game: Injury "Unavailable" (injury file fresh, 467 NFL rows) — `build_nfl_matchup_center_context` calls `build_nfl_injury_changes(...).get('changes')` guarded by `isinstance(..., dict)` but the builder returns a **list** ⇒ always `{}`; ATS wave "Unavailable" — joined from the empty `/tools/nfl-wave` builder; Line movement "Unavailable" — current-movement file holds prior-week games; Milestones "Unavailable" (season-streak join only — verify) | code + data |
| Matchup edge / DvP / officiating / team profile | `/tools/nfl-matchup-edge` (updated 14:59 UTC), `/tools/nfl-matchup`, `/tools/nfl-dvp`, `/tools/nfl-officiating` | current | C (Matchup lens uses team form) | OK but scattered across ~25 NFL sidebar entries | DISCONNECTED (nav) |
| Game Context coverage | `/tools/game-context` | honest coverage table (NFL weather Unavailable) | No | OK | — |
| CFB matchup card | `/tools/cfb-matchup` | "stale history; weight 2026" | No | OK (disclosed) | — |

## 5. Injuries, weather, stadium
| Item | Where | State | Fix type |
|---|---|---|---|
| Injury report | `/tools/injury-report` (NFL 467, MLB, …) | OK, current | — |
| Injuries inside GL / Matchup Center | lens ✓ (no date); Matchup module ✗ (bug above); props screener shows OUT players | P0 join bug | code |
| Weather | every NFL surface Unavailable; licence flag off by default | MISSING by licence; wording misattributes | **licensing decision**, then copy |
| Stadium / roof | Matchup Center: "Dome", "Retractable roof (open/closed not sourced)" | OK, honest | — |

## 6. Line / price movement
| Item | Where | State |
|---|---|---|
| Market Movers | `/tools/market-movers` — 68 games, NFL+NCAAF, open→current, snapshot depth | **OK** (the working movement source) |
| Classic GL line-state | "Line +2 since open" per row (props open/current) | OK |
| GL Line Movement lens / What's Changed / Matchup line module | stale current-movement file | **MISLEADING / BROKEN** (§1, §4) |

## 7. Supporting, contradictory, missing evidence
- **Supporting**: classic why-chips (per-lens reasons) — OK but hidden behind the non-default view.
- **Contradictory**: workspace Contradictions lens is structurally empty and says "none flagged"; classic Fragile flag is the only live contradiction-type signal.
- **Missing**: the "Unavailable, never a zero" frame exists (Matchup Center, Game Context) but today mostly reports *false* unavailability caused by join/data defects, which teaches the user to ignore it.

## 8. Ticket building & fragility
| Item | Where | State | Fix type |
|---|---|---|---|
| Daily Cards / GL proposed ticket | `/tools/daily-card` | cards priced per book (book + capture time on hover); **swap pool: 19 candidates "Unavailable — no verified book quote · update time not recorded", 14 "Kickoff unavailable"** | data/code (L1 / F-T family) |
| King's Tickets editor | `/tools/kings-tickets` | works; drafts held (storage review) | held by design |
| Classic → ticket | "Build a ticket → King's Tickets" opens a fresh ticket (no carry) | DISCONNECTED by design until storage review | — |
| Fragility | classic Fragile flag works; all-over parlay warning not exercised in this audit | OK / not verified | — |
| Parlay Builder | `/home/parlay` | preview lines "Anytime TD **O0**" | verify (label) |

## Restoration backlog (ranked; nothing implemented)
### P0 — existing functionality broken or misleading
1. **Matchup Center injury join** (list/dict) — every game reads Injury Unavailable; also starves What's Changed. *code, one-line class.*
2. **NFL ATS wave source** — `/tools/nfl-wave` "No wave yet / 2–3 games in" at Week 9; feeds Matchup Center ATS module. *code (builder/source) + copy.*
3. **NFL current line-movement file stale** — GL Line Movement lens lists prior-week games as live; Matchup line module + What's Changed empty. *scheduling/data (confirm producer on prod) + staleness/completed-game filter.*
4. **Riding the Wave lens** — "through Feb 8, 2026" + 2004-era openers as current evidence. *code (adapter freshness + current-season scoping).*
5. **"validated" weather claim regression** ×3 (GL source line, weather adapter, Matchup Center why-text). *copy.*
6. **False-absence wording** — Weather ("no wind data" = licence gate), Contradictions ("none flagged" = no rule can fire), What's Changed ("nothing changed" = no join). *copy.*
7. **CFB current-season data ~17 days stale** (ATS streaks, Wave, pace; GL ATS lens CFB items). *data/scheduling — attaches to P1-6 (CFBD latch), not a GL code fix.*
8. **NBA board empty (0 games/0 props) with 21 games lined** — *held: first evidence comes from the `b12eec3` `bk-daily` receipt (2026-11-08).*
9. **Classic GL price provenance** — FanDuel-only, no book/time, no kickoff gate; must land **with** any default restoration. *code.*
10. **Props screener lists OUT/IR players** as live rows. *code.*

### P1 — evidence present but disconnected / hard to use
1. **Restore classic convergence board as the Green Light default** (forward edit; workspace on `?view=workspace`), together with P0-9. *nav-UI + QC inversion.*
2. Per-row links from classic rows to Player Check, Matchup Center card, Best Lines for that prop. *nav-UI.*
3. Partial-week labels unified ("through Week 9" on a 1-game week vs Heat Map Week 8). *code (labels).*
4. Injuries lens freshness date + honest label (status changes, not return-from-participation). *copy/code.*
5. Period Board + Best Lines not reachable from GL / Matchup Center. *nav-UI.*
6. NFL ATS/SU/O-U table lacks 2026. *data/code.*
7. Off-season MLB card in Game Context (Brewers @ Rays, Nov). *code (season gate).*
8. Daily Card swap pool mostly unpriced / time not recorded. *L1 family (P1-4).*
9. Cold loads: `/sports/ncaaf` 23.7 s, `/tools/nfl-hub` 24.3 s, `/sports/nfl/props` 8.2 s. *perf/prewarm.*
10. ~25 NFL sidebar entries + a stray legacy "DASHBOARD:" strip on GL pages — evidence scattered. *nav-UI.*

### P2 — approved-type usability improvements (need owner approval first)
1. One "game card" path: slate → Matchup Center card → its GL plays → its period lines / props / best price (navigation only, existing modules).
2. Position filter adds QB on classic (currently All/RB/WR/TE when no QB rows).
3. Workspace lens items carry the number/line they refer to (Heat Map items are names only).

### Governance questions (not fixes — owner decision)
- Model totals on Game Board / NFL Board and "Model 1H/1Q Total" on the Period Board, and "Model rates above the line" in the CFB ATS lens: ungoverned model reads on fact surfaces (matchup page contract: predictive content needs a governance record).
- `9057ba1` default flip: confirm whether it was owner-approved.

### Future — genuinely new capabilities
- Licensed weather source (decision), CFB posted 1H/1Q line board, college injury source, NCAAB anything (Phase 3).

## Not verified in this audit
Prod data files directly (all freshness above is as rendered); whether started-game rows appear in classic GL;
all-over parlay warning; Matchup Center milestone join correctness; NBA after the post-deploy `bk-daily`.
