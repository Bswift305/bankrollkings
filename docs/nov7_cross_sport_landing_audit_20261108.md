# November 7 Cross-Sport Landing Audit — INTERIM (read-only, 2026-11-08 ~09:00 UTC)

Scope: data lineage and grading only. No outcome is used to claim any pregame signal predicted anything.
Evidence: signed-in production pages + two read-only SSM file inventories (no provider calls, no writes).

## Structural fact that bounds this audit
Every Nov 7 production artifact was written by the 2026-11-07 13:00–13:27 UTC `bk-daily` run — **before**
Saturday's CFB slate and the evening NBA slate began. No Nov 7 *Saturday* finals can exist yet on prod. They are
first eligible to land in today's 13:00 UTC `bk-daily`. Columns "Final received / Correctly graded" below are
therefore NOT YET DUE for Saturday events; they are completed after today's run.

## Sports with governed events on Nov 7
| Sport | Events | Source |
|---|---|---|
| NFL | **NO EVENTS** (Saturday) | `NFL_Schedule.csv`; last final = Thu Wk 9 JAX@BAL |
| NCAAF | Yes — 152 odds rows dated 11-07; Slate Pulse 66 games | `NCAAF_Odds.csv` (11-07 08:00 ET) |
| NBA | Yes — 7 games | `NBA_Schedule.csv` (7 rows), `NBA_Odds.csv` (21 rows) |
| NCAAB | **NO GOVERNED EVENTS** — 0 NCAAB files on prod | inventory |
| NHL | **NOT SUPPORTED** — 0 NHL files on prod | inventory |
| MLB / WNBA | Off-season | Slate Pulse 255h / 183h stale |

## NBA
| Metric | Scheduled | Pregame captured | Final received | Correctly graded | Missing/incorrect |
|---|---|---|---|---|---|
| Games / ML / spread / total | 7 (GameIDs e.g. `e76682ca…` DEN@IND 17:10) | 21 rows = 7 × {BetMGM, DraftKings, FanDuel}, 08:05 ET | **0 — no NBA finals artifact exists** (`data/scores/` holds only CFB/NFL) | 0 | **All 7** |
| Props | — | `NBA_Props.csv` 855 rows (`EventCommenceAtUTC` ≤ 11-08T03:00) | `NBA_GameLogs.csv` **last written 2026-06-05, max date Oct 31, 2025** | `NBA_AllPropResults.csv` SnapshotDate 11-07 but **GameDay/ResultDate all null** | **All** |

Pipeline: pregame capture works. **No 2026-27 NBA result has ever landed** — the gamelog producer has not written
since June; the daily NBA step was FAIL in the pre-deploy baseline. Downstream: NBA Streak Patterns shows 0
game-log rows; Command Center blank "Results through". Under the NBA season-readiness gate this is a P0 data gap.

## NCAAF
| Metric | Scheduled | Pregame captured | Final received | Correctly graded | Missing/incorrect |
|---|---|---|---|---|---|
| Sat Nov 7 games | 152 odds rows dated 11-07 (3 books) | yes, 11-07 08:00 ET | not yet due (lands ≥ 11-08 13:00 UTC) | not yet due | — |
| Fri Nov 6 (ET) games | — | — | **5 finals stored with Date = 2026-11-07** | — | **date anchoring** (below) |
| Grading rows | `NCAAF_GameLineResults_Scored.csv` holds Week-10 11-07 rows (e.g. Oregon@Ohio State `401858514`, Georgia@Ole Miss `401856741`) as `Game Line Backfill` rows dated `2026-11-07 05:00+00:00` | | | pending | verify they are pending, not graded |

Discrepancies:
1. **Finals dated in UTC, not Eastern (CLAUDE.md §5).** `CFB_Finals.csv` rows written 2026-11-07 13:04 UTC — before
   any Saturday kickoff — carry `Date=2026-11-07`: TCU@Arizona `401856855` 28–29, USF@ECU `401862818` 17–20,
   Nebraska@Illinois `401858510` 13–24, New Mexico@Nevada `401864533` 31–3, Virginia Tech@SMU `401858288` 28–51.
   These are Friday-night (Nov 6 ET) games. Same pattern in `NFL_Finals.csv` (Thu 11-05 ET JAX@BAL dated 11-06;
   Mon 11-02 ET CHI@SEA dated 11-03). Any Eastern-dated join (schedule, line history, results pages) can land
   them on the wrong day. Producer to confirm: the finals writer (`refresh_live_scores` / scores step).
2. **CFBD results frozen since 2026-10-24.** `cfbd_quota_state.json`: `exhausted:true`, `reason: HTTP 429 (monthly
   quota) at step 'CFB current-season results'`, **`reset_at: null`** — so the latch did not clear at the November
   monthly reset and will not clear on its own. Downstream: Wave "graded through Wk 7", Streaks "through Wk 8",
   Top Board "Week 8" while the season is in Week 10. Clearing it is an owner decision (override listed in the file);
   nothing changed.
3. **Completed games remain on live surfaces.** Slate Pulse counts 66 NCAAF games as "with live markets today".

## NFL
| Metric | Scheduled | Pregame captured | Final received | Correctly graded | Missing/incorrect |
|---|---|---|---|---|---|
| Nov 7 | NO EVENTS | — | — | — | — |
| Last game (Thu Wk 9 JAX@BAL `401873037`) | yes | yes | 33–10 Final, landed 11-07 13:04 | props: "Week 9 · 132 props" graded | date stored as 11-06 (UTC) |
| Player stats | — | — | `NFL_GameLogs.csv` max 2026-10-30 (Wk 8) | — | expected: nflverse publishes after the week |

Also stale: `NFL_GameWeather.csv` last written 2026-10-16 (max date 10-25) → "No forecast available" on every
current Matchup Center card. Matchup Center injury module reads "Unavailable" despite `NFL_Injuries.csv` 11-08 07:00.

## Trend-input landing (yesterday → today)
| Input | NFL | NCAAF | NBA |
|---|---|---|---|
| ATS/SU/totals | through Wk 9 (Riding the Wave) | **frozen Wk 7–8** (CFBD latch) | none for 2026-27 |
| Recent form / player history | gamelog through Wk 8 (expected) | frozen | **none since Oct 2025** |
| Streaks | heat map through Wk 8 | frozen | 0 rows |
| Matchup evidence | weather stale, injuries not joined, line-move join null | stale | — |
| Green Light lens inputs | NFL only; through Wk 8 | n/a | n/a |

## Read-only RCAs (code traced at `b12eec3`; prod confirmation pending where noted)

| # | RCA | Root cause (code) | Introduced | Classification | Owner |
|---|---|---|---|---|---|
| 1 | NBA results never land | No current-season regular-season gamelog producer in `run_daily`: `refresh_nba_daily.py` STEPS has only playoff steps (hardcoded `"2025-26"`); the only `NBA_GameLogs.csv` writer (`floor_play_package/refresh_data.py`) is unwired and writes under `floor_play_package/`. No NBA finals writer. AND the NBA data-rights gate (`services/nba_source_gate.py`, default OFF) blanks gamelog loading + NBA prop grading, so rows stay Pending even with a fresh file. | pre-existing | gate = **unsupported by design** (data-rights review); missing producer = **pre-existing** | consolidated `bk-daily` obligation / NBA season readiness |
| 2 | CFBD latch | `refresh_cfb_data.py`: `reset_at` comes only from env `BK_CFBD_RESET_AT`; never derived (no Retry-After, no monthly rollover) → blocks forever. Cleared only by a fully clean run, `BK_CFBD_FORCE=1`, or deleting the file. No allowance recorded anywhere; ~180–200+ CFBD requests/run (≈130 roster calls). | `95d51da` (2026-10-23), before `3d7cda1` | **pre-existing, exposed by truthful semantics** (`b12eec3` only made it exit 3 / `BLOCKED_QUOTA` hard failure) | consolidated `bk-daily` obligation (owner decision on reset) |
| 3 | UTC calendar dates | `fetch_final_scores.py:65` `date[:10]` of ESPN UTC (no code consumer yet). **Material:** `fetch_cfbd_game_scores.py:55` UTC date inner-joined at `build_ncaaf_game_lines_history.py:168` against Eastern odds dates → every CFB kickoff ≥ 8 PM ET silently dropped from line history / graded results / ATS / streaks / Wave / O-U tendencies / calibration. `refresh_live_scores.py:91-93` "today" = UTC → evening games stop polling after 8 PM ET. | `32e3f44` (09-26), `952385a`; before `3d7cda1` | **pre-existing** | consolidated `bk-daily` / data-integrity obligation (live ticker also feeds 1A started-event exclusion) |
| 4 | Completed / stale games on live surfaces | (A) `_format_game_market_odds` drops `LastUpdated` → `get_lines_refresh_meta` age None → 6h line gate never fires for NFL/NCAAF/MLB/WNBA (b12eec3 restored it for NBA only, by design). (B) No completed-game / kickoff check on football surfaces; shared predicates `_leg_quote_failures` / `_kickoff_gate_failure` used only by ticket/SGP legs; NBA uses `_kickoff_is_current`. Slate Pulse counts distinct odds-file games unfiltered. Classic GL reads `NFL_Props.csv` directly (no freshness, no kickoff gate, sorted by lens count then game text). Matchup Center line-move: team-name join (`normalize_team_abbr` returns NFL full names) + field-name mismatch (`spread_first` vs `spread_open`). | pre-existing | **pre-existing**; 1A scope covers only the Classic GL path | **Green Light 1A** (GL freshness / started-event / kickoff order; Matchup Center line-move join = 1A item 4) + cross-surface obligation (A, Slate Pulse, Best Lines) |

None of the four was introduced by `b12eec3`, and none violates a `b12eec3` acceptance requirement on the code
evidence. Production confirmation (unit command line incl. `--continue-on-error`, `BK_NBA_STATS_ENABLED`,
`_child_outcomes_nba_daily.json`) is collected with today's `bk-daily` observation.

## Green Light 1A P0 — cross-event overwrite (confirmed 2026-11-08, read-only)
`_nfl_game_scripts()` (`app.py` at `b12eec3`) iterates every `GameID` in `NFL_Odds.csv` (dates 11-08 … 11-16) and
overwrites `out[team]`; the last-iterated game wins, with no event filter. Matchup and Game Identity both read it, so
today's prop + today's usage were combined with **next week's opponent / spread / script** for **11 of the 28
teams** on the 14-game slate (13 Sunday games + BUF@MIN Monday; every team appears once):
ARI, CAR, DAL, DET, GB, HOU, IND, MIA, MIN, NE, NO. Correctly bound (17): ATL, BUF, CHI, CIN, CLE, DEN, KC, LAC,
LAR, LV, NYG, NYJ, PHI, SEA, SF, TB, WAS. The Classic board itself shows 13 distinct teams (ARI, ATL, CAR, CIN,
DAL, DET, GB, IND, KC, LAR, LV, NO, SEA); **7 of those 13** are wrong-bound (ARI, CAR, DAL, DET, GB, IND, NO).
(An earlier chat report said "12 of 27"; that was a counting error — the replay printed 28 teams and 11 mismatches,
and BUF was omitted from the correctly-bound list. 11 of 28 is authoritative.) Replay on prod reproduces Green Light's text exactly
(Hubbard → NO 11-15; Wilson "dog by 7.5" → ARI vs LAR 11-15; Lamb "dog by 4" → DAL @ SF 11-15, while today DAL is
favored by 5). Prop lookup is keyed `(player, stat)` with no event. Hubbard is the known example, not an isolated case.

**Future acceptance requirements (owner 2026-11-08; evidence only — not yet in the program table, not code):**
1. A team appearing in multiple events cannot have one event overwrite another.
2. Every Matchup and Game Identity lens must expose and match the candidate's `EventId`.
3. Prop lookup must include `EventId`; `(player, stat)` alone is forbidden.
4. A mismatch causes the lens to abstain, never fall back to another event.
5. Adversarial QC includes today/next-week games for the same team in reversed file orders and proves identical results.
6. The rendered opponent, spread, kickoff, player and offer all round-trip to the same event.

Binding contract: game script `(EventId, team_id)`; opponent derived from that same event; prop offer
`(EventId, player_id, market/stat, sportsbook)`; lens evidence carries the event identity through rendering.

## NFL refresh cadence and provider cost (read-only, 2026-11-08; findings only — no timer proposal)
- `bk-daily`: `run_daily.py --sports nba,wnba,mlb --continue-on-error`, `OnCalendar=13:00 UTC`. NFL game lines publish
  ~13:00:15Z (3 credits, 1 request); NFL props ~13:00:50Z (event list 0 credits + ~8 credits per event with markets
  posted; 11-07 = 112). No intra-day NFL refresh (`bk-linemove` = MLB/WNBA only). CFB step runs after NFL fetches.
- Under the 6h source-time rule, one 13:00Z refresh covers Madrid + 1:00 PM ET games only; 4:05/4:25 PM, SNF, MNF and
  TNF **cannot be fresh at kickoff**. Fetchers support only `--days N` (no event-ID / hour window).
- Minimum extra windows: Sun ~20:00Z (late games + SNF), Mon ~20:00Z (MNF), Thu ~20:00Z (TNF). Next-day-scoped
  (`--days 1`) ≈ 43 + 11 + 11 = **~65 credits/week (~280/month)**; re-running the existing 7-day wrappers ≈ **~345/week
  (~1,500/month)**, NFL only (wrappers also spend NCAAF). Later design decision.

## NFL ATS discrepancy reconciliation (DAL, DET, NYJ, SEA, NE) — read-only
BK canonical ATS (`build_nfl_scores.py` → `nfl_scores.json`) grades every game against **nflverse `games.csv`
`spread_line`** (one consensus closing line), downloaded each run and **not retained** on prod (the stored
`NFL_Games_nfldata.csv` has no 2026 `spread_line`). The manual reconstruction graded against the **median of the
last daily-captured line** (`NFL_LineMovementCurrent`, ~13:00Z snapshots, three books). Every discrepancy sits on a
key number where those two line sources differ by a half point:
| Game | Score / margin | Captured BetMGM / DK / FD (home pts) | Manual (median) | Implied BK canonical | Cause |
|---|---|---|---|---|---|
| BAL @ DAL 09-27 | 34-31, DAL −3 | +3.5 / +3.5 / +3.5 | DAL W | DAL **P** (line 3) | line source/timing |
| NYJ @ DET 09-27 | 31-24, DET +7 | −6.5 ×3 | DET W / NYJ L | **P** (line 7) | line source/timing |
| NE @ SEA 09-09 | 13-10, SEA +3 | −3.5 / **−3.0** / −3.5 | SEA L / NE W | **P** (line 3) | line source/timing + book-specific (DK push) |
| NYJ @ NE 10-18 | 26-19, NE +7 | **−7.0** / −7.5 / −7.5 | NE L / NYJ W | same as median (consistent with BK counts) | book-specific (BetMGM push) |
**Auditability obligation (owner 2026-11-08, recorded only):** the exact downloaded nflverse source is not retained,
so the canonical ATS outcome cannot be replayed later; no change to today's canonical records.
No sign, rounding or missing-event defect found. Implied canonical lines are inferred from BK's W-L-P counts; they
cannot be verified without the non-retained nflverse file → **BK's displayed ATS is not reproducible from retained
artifacts**. ATS is book- and timing-dependent at key numbers. Classic GL lenses do not use ATS; the Workspace
"ATS Waves" adapter reads the canonical record.

## Neutral-site venue defect — blast radius (read-only, 2026-11-08)
At `b12eec3` every NFL venue fact is looked up from the nominal HOME team (`nfl_venue_roof(home)` →
`services/nfl_stadiums.py`); `app.py:7259-7261` states neutral/international venues are not detected. CFB is the
exception (`neutralSite` read; HFA dropped for neutral games). No NFL event source BK consumes carries venue: Odds API
game-line/prop rows, `NFL_Schedule.csv` and ESPN finals (ignores `competitions[0].neutralSite`/`venue`) have none;
nflverse `games.csv` has `location`/`stadium`/`roof`/`*_rest` but no NFL app code reads them.
- **Display only:** Matchup Center "Roof (home stadium)" (`templates/nfl_matchup_center.html:77`) — the CIN@ATL label.
- **Feeds computation:** `fetch_nfl_weather.py` (coordinates + roof by home) → wind → totals tier/score, WIND flag,
  `wind_under` sort, Matchup Center why/contradiction lists, GL Workspace weather lens, props scorer WIND_15_PLUS /
  DOME tags; `nfl_totals.py` HFA 1.6 added unconditionally to `projected_margin` (spread edge); ATS home/away split.
  Classic GL lenses do not read venue (Game Identity uses spread size; `home` stored, unread). SGP/tickets: none.
  Today CIN@ATL produces only the wrong roof label (ATL retractable → no wind row).
- **2026 neutral games in retained data** (nflverse file, through 10-04): SF@LAR (Melbourne), **BAL@DAL (Rio,
  09-27 — also one of the ATS push games)**, IND@WAS (London). CIN@ATL Madrid (11-08) is not in retained data.
- **Future acceptance contract (owner 2026-11-08):** venue comes from `EventId`; a neutral flag suppresses home-field
  assumptions (HFA, home/away splits, home-stadium weather); roof belongs to the actual venue; an unavailable actual
  venue causes abstention, never a home-stadium fallback.

## Classic Green Light — Coaching and Concentration lens provenance (read-only, 2026-11-08)
- **Coaching** (`data/scenarios/nfl_coaching.json`, built by `build_nfl_coaching.py`, committed `a62f37a` 2026-10-04,
  not in `run_daily` → static): keyed by **team only**, from 2023–2025 nflverse PBP (4th-down go rate, early-down pass
  rate, no-huddle, RZ pass rate). No season/staff field. The builder's own caveat: "roster-stable, NOT staff-stable".
  Source PBP (`data/pbp/nfl_pbp_2019_2025_slim.parquet`) is retained on the dev box only, not on prod.
  - **Bijan / ATL — INVALID for 2026:** ATL's note reflects the 2023–25 staff; BK's own injury feed quotes "Coach Kevin
    Stefanski" for the 2026 Falcons (new staff). Bijan's verified count drops from 3 to **2** (Opportunity + Matchup).
  - **Hubbard / CAR — UNVERIFIED:** 2023–25 blend with no 2026 staff check; Hubbard is already on hold (invalid Matchup).
- **Concentration** (`nfl_concentration.json`, `build_nfl_concentration.py`, `f7d7193` 2026-10-04, static, 2023–25
  PBP, keyed by PBP `F.Last` → `(initial, LAST)` via `_usage_name_key`): TD-angle note only — not counted in the
  yardage lens total. **Identity defect:** "Amon-Ra St. Brown" → `('A','BROWN')`, which matches **A.Brown (A.J. Brown,
  23% RZ targets)** instead of `A.St. Brown` (34%) — St. Brown's shown note is another player's data (**INVALID**).
  First-initial + last-name keys can also collide for common surnames (Williams). All other notes (London, Lamb,
  Taylor, Gibbs, Kyren Williams, Hubbard) are 2023–25 tendencies, unverified for 2026 roles (**UNVERIFIED**).
- **Opportunity** (`build_nfl_usage_board` ← `_nfl_player_week_data()` = nflverse weekly `_nflverse_stats_2026.parquet`,
  refreshed daily, last 2026-11-07 ~13:04Z, Weeks 1–8): current-season **season-to-date means** — WR/TE mean
  `target_share` (Alpha ≥0.28, Featured ≥0.20); RB carries ÷ team carries (Bell-cow ≥0.62, Lead back ≥0.45). Vote = role
  in {Alpha, Featured, Bell-cow, Lead back}. Identity key = full display name; team = **mode over the season** (current
  team not enforced — a mid-season move would blend). Season means **can conceal a recent decline** (Jeanty). The
  "locked role (a real floor)" text comes from `nfl_role_stability.json` — committed static 2026-10-09 (`587ae69`), not
  refreshed by `run_daily`, so it reflects early weeks only (**annotation UNVERIFIED**). Reproducible from the retained
  parquet only in its current state (overwritten daily; no historical replay).
  Verdicts: London, Bijan, Chase Brown, Walker, Gibbs, Taylor, Lamb **VERIFIED** (vote); Jeanty **UNVERIFIED** (season
  mean conceals a 58→9 rush-yard decline; recent share not computed).
- **Matchup** (`_adj_run_rank` / `_adj_pass_rank` ← `nfl_2026_form.json`, runtime copy built 2026-11-07 13:04Z by
  `build_nfl_team_form.py` from the same nflverse weekly parquet): **opponent-adjusted** per-carry / per-dropback rank —
  a single-pass strength-of-schedule adjustment (opponents' offense in their other games, head-to-head excluded);
  a documented derived transformation, **not** a registered model. CIN reproduced: run **adj 25th** (raw 29th, 4.84 →
  4.67 YPC), pass **adj 27th** (raw 24th, 7.55 → 7.79 Y/A); 7 games, opponents TB HOU PIT JAX MIA BAL TEN (no future
  game, no wrong opponent). The GL label "ranks 25th per-play" omits "opponent-adjusted". Both votes survive on raw
  ranks too (≥20). London and Bijan Matchup **VERIFIED** (binding + reproduction), label caveat recorded.
- **Recalculated verified counts for today** (Opportunity + Matchup + event-bound Game Identity; no Coaching,
  Concentration or weather): London 3 · Bijan 2 · Chase Brown 2 · Walker 2 · Gibbs 1 · Taylor 1 · Lamb 1 · Jeanty 0.
- The NFL wind-under study is research only (not in `services/model_registry.py`); do not call it validated authority.

## Green Light 1A truth defect — unlabelled injury timestamp (2026-11-08)
`/tools/injury-report` shows NFL "Updated 2026-11-08 07:00" with no zone; it is **UTC** (the same feed renders as
"02:00 ET" in NFL Matchup Center). Customer-facing times must carry their zone or be converted and labelled. Also:
BK has no event-specific inactive feed. Absence from BK's own injury artifact is not evidence; the tiered rule below uses
the **official** NFL injury report.

**Player availability rule — owner correction 2026-11-08 (supersedes "require affirmative active confirmation").**
The rule has three tiers.
1. **`UNAVAILABLE`**: OUT, IR, PUP, suspended, or officially inactive.
2. **`REVIEW REQUIRED`**: questionable, doubtful, or a conflicting designation. These players require the official
   inactive list.
3. **`AVAILABILITY PASSED`**: all three conditions hold:
   - absent from the official weekly injury report;
   - current roster and event binding confirmed;
   - no contradictory transaction.

Additional rules:
- The official inactive list is a **final override before any owner submission**, not a universal prerequisite.
- A sportsbook quote never overrides an official unavailable status.
- Applied 2026-11-08 (Madrid): Drake London, Bijan Robinson and Chase Brown are **AVAILABILITY PASSED**.
  - They are absent from the official Week 9 injury report, bound to CIN@ATL, and have no conflicting transaction.
    The ATL roster release of 11-07 concerns Brian Robinson Jr. to IR and Khalil Herbert signed; it does not
    concern Bijan.
  - Their market evaluation proceeds on fresh offers. The inactive list, expected about 13:00Z, remains the final
    override.

## P0 market integrity — spread price has no side identity (confirmed 2026-11-08, read-only)
`fetch_game_lines.py:329-341` (`parse_event_markets`, at `b12eec3`): `Spread` is always the home point (home outcome
stored, or away outcome negated), but `SpreadOdds` is the price of **whichever spread outcome the provider lists
first** (home or away), then `break`. The second outcome is discarded at write time; no artifact holds it
(`NFL_LineMovementCurrent.csv` `OpenSpreadOdds`/`CurrentSpreadOdds` inherit the single unlabelled price). The number
is home-perspective on all 14 games × 3 books (consistent with the moneyline favourite). Matchup Center renders the
home number with no team label (secondary usability defect; it caused a DAL/IND misreading in chat, not a data flip).

**Blast radius (readers of `SpreadOdds` / derived fields at `b12eec3`):**
| Consumer | Use | Class |
|---|---|---|
| **SGP Workbench** `app.py:49460-49478` (`/tools/sgp-workbench`, live) | home spread leg `price = SpreadOdds` (code comment asserts it is the home price); away leg `price=None` | **ticket construction + export/handoff** — the "full-fidelity copy" (`templates/sgp_workbench.html` §8) prints `label | book | price | timestamp` for the user to rebuild in King's Tickets. **PRODUCTION INCIDENT CANDIDATE**: the home spread leg can carry the away side's price. |
| `build_mlb_odds_lookup` → `mlb_matchup.html` `run_line_price` | displayed beside the home run line | display-only context (MLB off-season) — mislabelled when away-first |
| `build_mlb/wnba_odds_lookup`, `build_live_game_lookup`, `build_game_market_lookup` (`'spread_odds'` key) | dict field | not read by any template/JS/py at `b12eec3` (dead) |
| `services/feed_validation.py` | completeness/validity of the column | validation only (passes an unattributed price as valid) |
| `build_ncaaf_game_lines_history.py:109` | `SpreadOdds` median into history | stored; no grading/payout reader of it found |
| `_format_game_market_odds` | column passthrough | passthrough |
No payout or grading consumer of spread price found. Moneyline (`h2h`) and totals keep side identity by outcome name.

**Moneyline / totals schema (verified):** `h2h` assigns `HomeML`/`AwayML` by outcome name (no first-wins); `totals`
assigns `OverOdds`/`UnderOdds` by name (`Total` = the over's point; the under's point is used only if the over's is
missing — edge case if the two points ever differ). Timestamp `LastUpdated` = **bookmaker-level** `last_update`
converted by `to_eastern_datetime_str` → an **Eastern wall-clock string with no zone marker** (writer-proven Eastern,
but zone-less in the artifact — same class as the props `LastUpdated` authority issue). Prod rows: all 14 events × 3
books carry both ML sides and both O/U prices; favourites agree with the spread sign on every row.

**Classification (owner 2026-11-08): LATENT P0 spread-price binding defect, presently contained by the kickoff
gate; mandatory before Green Light 1A activates game-line legs.** Not an active production incident.
- **Containment proof (prod, `b12eec3`, read-only):** game-line SGP legs carry no kickoff (`_no_kick`), so the D4
  kickoff gate sets `MISSING_KICKOFF` / `ticket_ok=False`; live `/tools/sgp-workbench` (CIN@ATL) renders both spread
  legs "Kickoff unavailable — context only · no price — not addable"; a selected one makes the ticket
  non-executable (no full-fidelity copy / export / handoff). The unattributed `SpreadOdds` sits in the leg dict but
  is never shown, addable, exportable or handed off.
- **Exposure condition:** any change that gives game-line legs a governed kickoff/event identity (e.g. GL 1A event
  binding) removes that safeguard and would surface the side-less price on the home spread leg.
- **Containment change:** local commit **`2e2adc6`** on `hotfix/sgp-spread-price-containment` (from exact `b12eec3`):
  home spread leg `price=None` (both spread legs unpriced → `MISSING_PRICE`) + `qc_sgp_spread_price_containment.py`
  (15/15 incl. order reversal, defence-in-depth with a valid kickoff, mutation). SGP/ticket suite green.
- **Mandatory inclusion:** `2e2adc6` (exact change + QC) must land in / before Green Light 1A, before 1A supplies
  kickoff/event identity to game-line legs. **No separate deployment authorized**; not pushed.

**Future spread-writer acceptance requirements (owner 2026-11-08; evidence only — not a build or program order):**
1. Preserve both spread outcomes.
2. Retain explicit selection/team identity for each.
3. Bind sportsbook, point, price and timestamp per outcome.
4. Reject incomplete or duplicated sides.
5. Prove correctness when provider outcome order is reversed.
6. Never synthesize the opposite price.

## Remaining (after today's 13:00 UTC `bk-daily`)
Re-run the inventory; reconcile each Saturday NCAAF and NBA event: final received, ML/spread/total graded at the
exact captured book/line, push handling, props grading, removal from live surfaces, and the producer outcome.

## Green Light 1A acceptance requirement — least-restrictive truthful state (owner, 2026-11-08; recorded only)
**Every gate must distinguish four things:**
- research visibility;
- lens eligibility;
- offer executability;
- submission/handoff eligibility.

**States:**
- `AVAILABLE`: current, governed and usable for its stated purpose.
- `CONTEXT ONLY`: displayed with its source and as-of time, but not counted as current support and not executable.
- `REVIEW REQUIRED`: stays visible, with the contradiction or unresolved fact named.
- `UNAVAILABLE`: the specific offer or action fails a hard prerequisite.

**Principle:** suppress only the claim or action that the missing evidence invalidates. Missing optional evidence
abstains; the candidate does not disappear.

**Hard suppression is reserved for:**
- legal or data-rights prohibition;
- unresolved subject identity;
- actions that would be unsafe or dishonest.

Recorded as a 1A product/acceptance interpretation consistent with `DIC-1.0` (L8 and §3 abstention). This is not
a Constitution amendment.

**Pending:** a read-only behavior matrix after today's operational reports, with columns: Condition / Display for
research? / Count as lens support? / Executable offer? / Ticket or handoff? / Required label. Conditions to cover:
- stale quote;
- missing quote time;
- missing weather;
- missing movement;
- invalid or unverified lens;
- questionable player;
- officially unavailable player;
- unresolved event identity;
- unknown venue or roof;
- unknown spread-price side;
- unbound total side;
- unregistered model;
- data-rights restriction;
- started event.
