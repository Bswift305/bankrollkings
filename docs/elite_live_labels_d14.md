# Elite live line-movement labels — D14 / P1 audit and contract

Status: implemented on branch `fix/nba-market-v6-on-17b5e69` (branch only, not deployed). D14 final: no open questions (section 5).
Module: `services/elite_live_labels.py`. QC: `qc_elite_live_labels.py`. History rule (unchanged, owner-approved):
`docs/game_lines_event_contract.md` "Elite alert history" + `qc_elite_alert_history.py`.

## 1. Audit — before this change (file:line at `3403f4a`)

### Where each urgency value came from (`app.py` `build_elite_sharp_money_scanner`, 15441–15530)

A move is kept when an open→current implied-probability move is ≥ 2.0 points on either side, or the line moved
≥ 0.5 (scaled ×4 into the same "strength" unit, 15484–15492). The largest move picked `sharp_side` (15495).
`alignment` = `ALIGNED` / `CONFLICT` (model side on record vs. that side) / `UNKNOWN` (15496–15498). Then:

| Label | Exact predicate (in evaluation order) | Time-based? |
|---|---|---|
| `ACT` | default for every scanned move (15499) | no |
| `HOLD` | `alignment == 'CONFLICT'` (15500–15501) | no |
| `WINDOW CLOSING` | not CONFLICT and `abs(move_strength) >= 5` and model reliability in {`ANCHOR`,`WATCH`} (15502–15503) | **no** — no start time read at all |
| `PASS` | none of the above and reliability `AVOID` (15504–15505) | no |

`score` = `abs(move_strength) + 8·ALIGNED + 6·ANCHOR / 3·WATCH` (15526), a composite with no governed meaning.
Sort: `WINDOW CLOSING` first, then `ALIGNED`, then `score` (15529). None of the four labels had a decision
contract behind it; `ACT` was an instruction to bet on every move by default.

### Every surface where the labels / `sharp_side` / `urgency` / `score` appeared or were derived

| # | Surface | file:line (at `3403f4a`) | What it showed |
|---|---|---|---|
| 1 | Scanner builder | `app.py:15495–15529` | derives `sharp_side`, `urgency`, `score`, urgency-first sort |
| 2 | `/elite` "Sharp Money / Line Movement Scanner" card | `templates/elite_dashboard.html:304–351` | title "Sharp Money", subtitle "act/hold labels", column "Sharp Side" (`row.sharp_side`, 341), column "Action" with `row.urgency` badge, `badge-accent` on WINDOW CLOSING (347) |
| 3 | `/elite/matchup-builder` "Line Movement In This Game" | `templates/elite_matchup_builder.html:124–133`; context `app.py:15887–15960` | `row.urgency` badge (131), `row.sharp_side` (133) |
| 4 | Matchup builder notes | `app.py:15949` | "market conflict(s) should be treated as hold or pass signals" |
| 5 | Persisted alert archive `data/tracking/Elite_LineMove_Alerts.csv` | `app.py:15533–15540` (columns), `15661–15717` (persist) | stored `SharpSide`, `Urgency`, `Score`; sorted by `Score` |
| 6 | Alert id | `app.py:15636–15647` | hashes `sharp_side` (value only) |
| 7 | Alert grading | `app.py:15751` | grades `SharpSide` as the direction (internal) |
| 8 | Alert history summary / buckets | `app.py:15843–15867` | groups by `SharpSide` value (OVER/UNDER — no "sharp" text shown) |
| 9 | `/elite/alerts/export` CSV | `app.py:43444–43452`, `elite_alert_export_frame` 15618–15633 | `Urgency` blanked (v5 history rule) but header present; `SharpSide` header; `Score` exported |
| 10 | Recent Alerts (history) | `templates/elite_dashboard.html:501–521` | already owner-approved history rule: label, no action, provenance-gated book/line (`row.side` from `SharpSide`, value only) |
| 11 | Elite learning module "Reading Line Movement" (`/elite/learn`) | `app.py:16745–16748` | "Sharp Money Scanner", "sharp side", "action window can close fast", "Start with WINDOW CLOSING alerts" |
| 12 | Elite feature preview (`GLOBAL_FEATURE_PREVIEWS['elite']`) | `app.py:23079–23085` | "sharp-money line-move alerts", "sharp side … action window closes fast … no play" |
| 13 | `/elite` page snapshot (12h runtime snapshot) | `app.py:43339` | `elite_dashboard_v4_*` payload froze rows with `urgency`/`sharp_side`/`score` |
| 14 | Docs | `docs/game_lines_event_contract.md:366–381` | history rule (historical rows never show ACT/WINDOW CLOSING) |
| 15 | QC | `qc_elite_alert_history.py:55,137,152,188` | history-rule checks |

Searched and **not** found for the scanner labels: `static/js/**`, `marketing/**`, `services/**` (other than the new
module), any JSON API (`/elite*` has no JSON route; the only payload is the server-rendered context + the runtime
snapshot), and other templates. `franchise_kings.py` has an unrelated `urgency` (franchise game alerts).

### Adjacent directives found but OUT of D14 scope (not changed — owner decisions, §5)

- Elite **Action Queue** card (`templates/elite_dashboard.html:196–199`; `app.py:15385–15402` at `3403f4a`) emits
  `HOLD` ("Track But Do Not Force"), `AVOID` ("Pause …"), `BUILD`, `WATCH`, `LEAK`, `EDGE` cards.
- **BankrollIQ** (`calculate_bankroll_iq`, `app.py:15007–15042`) emits a Kelly sizing label `PASS` and a
  recommended stake — Kelly is on the do-not-build list (doctrine).
- `explain_profile_stack` (`app.py:23685–23710`) market-gate glossary "Hold means … you should be cautious".
- Market timing watch (`build_elite_market_timing_watch`, `app.py:15405–15425`) "before pushing stake".
- Candidate pool table renders the composite `row.score` (`templates/elite_dashboard.html:181`).
- Branding: "Sharp University" (`templates/elite_learn.html:3,11`, `templates/elite_dashboard.html:19`),
  "Weekly Sharp Report" (`templates/elite_dashboard.html:246`), `templates/info.html:378`
  "Sharp money came in. Be cautious."

## 2. Contract (implemented; owner decision 2026-11-04 is binding)

### 2a. Move state — line and price are different units, never combined

The old scanner put an implied-probability price move (≥ 2.0 pts) and a line move (×4) into one "strength" and
one ≥ 5 threshold. That is gone. `services/elite_live_labels.classify_move` keeps each unit's **actual delta**:

| Field | Unit | How |
|---|---|---|
| `line_delta` | points | `CurrentLine − OpenLine` (both required) |
| `over_price_delta_cents`, `under_price_delta_cents` | American-odds cents | price mapped to the continuous cents scale (`a<0 → a+100`, `a>0 → a−100`; \|odds\| < 100 invalid), then current − open. So −110 → −150 = −40¢ and −105 → +105 = +10¢. Negative = that side became more expensive. |

Qualifying thresholds (facts about what the scanner lists, not authority — `LINE_MOVE_MIN_POINTS = 0.5`,
`PRICE_MOVE_MIN_CENTS = 10`):

| State (exact) | Predicate |
|---|---|
| `LINE_MOVED` | \|line_delta\| ≥ 0.5 points; no price side ≥ 10¢ |
| `PRICE_MOVED` | either side's \|price delta\| ≥ 10¢; line delta < 0.5 or unknown |
| `LINE_AND_PRICE_MOVED` | both of the above |
| `NO_QUALIFYING_MOVE` | at least one delta computable, none qualifies (e.g. 0.4 pt + 9¢ — never added together) |
| `INSUFFICIENT_DATA` | no line delta and no price delta computable on either side (never zero-filled) |

Only the first three are listed in the scanner; the per-unit thresholds are stated in the card subtitle.
`move_side` (renamed from `sharp_side`): when the line qualifies, line up → `OVER`, down → `UNDER`; for a
price-only move, the side whose price became more expensive by more cents; a tie → no side (shown "Mixed"),
which also means no countdown (no single side's price).

### 2b. Label wording

| Old label | New factual text | Exact predicate | Required inputs | Fail-closed behaviour |
|---|---|---|---|---|
| `ACT` | *(removed — no replacement directive)*. The row states facts only: move state + actual deltas, line-move side, model side, model-vs-move, and (if evidenced) a start countdown. | — | — | never rendered, persisted or exported |
| `HOLD` | "Model side differs from the line-move side" | `alignment == 'CONFLICT'` (model side on record ≠ `move_side`) | candidate `direction` for the same sport/player/stat; `move_side` | no model side, or no single move side → "No model side on record" |
| (ALIGNED) | "Model side matches the line-move side" | `alignment == 'ALIGNED'` | as HOLD | as HOLD |
| `PASS` | *(removed)*. The `AVOID` tier is no longer shown in the scanner at all (2c). | — | — | — |
| `WINDOW CLOSING` | "Starts in N minutes" (< 1 h; "under 1 minute" < 60 s), "Starts in H h M min" (< 48 h), "Starts in D days H h"; plus the start in ET ("Wed Nov 04, 09:00 PM ET") | ALL of: `EventCommenceAtUTC` parses as explicit UTC; `now < start`; `SourceUpdatedAtUTC` parses as explicit UTC, not > 5 min in the future, age ≤ `LIVE_MARKET_MAX_AGE_HOURS` (6 h, CLOCK A); `source_provenance` starts `props_feed:` AND `EventId` AND book present; finite current line AND a valid American price (\|odds\| ≥ 100) on `move_side` | props row `EventCommenceAtUTC`, `SourceUpdatedAtUTC`, `EventId`, `Book`, `CurrentLine`, `OverOdds`/`UnderOdds`; aware UTC now (`services.timeutils.utc_now`) | **no label**; neutral note "No countdown: <reasons>." naming each failed input (`event start time not verified` / `event start time has passed` / `quote update time not recorded` / `quote older than 6h` / `quote source not recorded` / `no complete price on the line-move side`). An evaluation error → no label, "start facts could not be evaluated". Never a default. |
| `sharp_side` / "Sharp Side" | `move_side` / "Line-move side" | 2a | open/current lines and prices | "Mixed" when no single side |
| `score` | *(not surfaced)* — removed from rows, not persisted for new alerts, dropped from the export | — | — | — |
| "Start with WINDOW CLOSING alerts…" (learning module) | removed; factual guidance about the countdown and that a move is not an instruction to bet | — | — | — |

Wording rules: no "sharp"/"steam", no instruction verbs, a move "describes the market; it does not predict the
result" (card subtitle).

### 2c. `ANCHOR` / `WATCH` / `AVOID` — what they actually are

They are **not** data-coverage labels. They are in-sample **hit-rate tiers** of the graded record:

- `services/review_center.py:1013` and `build_floor_play_index.py:65` `calculate_floor_reliability(resolved_count,
  hit_rate)`, and `app.py:4766` `calculate_mlb_launch_reliability`: `SMALL SAMPLE` if < 10 resolved (or no rate);
  `ANCHOR` if ≥ 20 resolved and hit rate ≥ 65%; `WATCH` if ≥ 10 and ≥ 60%; `AVOID` if ≥ 10 and < 52%; else
  `DEVELOPING`. Bucket = sport × stat × direction (floor plays) or player / bucket × stat × direction (MLB).
- Hit rate only: not price-adjusted, not ROI, not out-of-sample. Per CLAUDE.md §10 the market prices what moves
  hit rate, so a hit-rate tier is not evidence of an edge.
- In the Elite candidate builder (`_elite_candidate_from_prop`, `app.py:15150`) they also add +10 / +5 / −20 to
  the candidate `score`, and `true_prob` falls back to market prob / confidence / a fixed **0.55** when no hit
  rate exists (clamped 0.35–0.92) — a manufactured probability.

Because they are performance tiers (only `SMALL SAMPLE` is a pure coverage statement), they cannot honestly be
renamed to coverage labels. In the live scanner they are therefore **no longer shown, persisted or exported**:
scanner rows carry no `reliability` / `true_prob`; new alert rows persist `Reliability=''`, `TrueProb=''`; the
export drops `Reliability`, `TrueProb`, `Score`, `Urgency`. The scanner shows the model side only, as a fact.
Their other uses (candidate pool, matchup builder candidate list, parlay-EV tiers, action queue) are outside
D14 — see §5.

### 2d. Ordering

**Default (neutral):** upcoming events with a verified start, soonest first → events whose start is unverified →
events that have started (most recent first); within a group the most recent quote update first, then player
name. No move size, alignment, tier or composite score influences the default order. Applied at build time
(top-24 cut) and again at render time.

**Explicit user choices** (links on the `/elite` card; query params on `/elite` and `/elite/matchup-builder`):
`moves_sort=line` → by \|line_delta\| (points) only; `moves_sort=price` → by the larger \|price delta\| (cents)
only; `moves_state=LINE_MOVED|PRICE_MOVED|LINE_AND_PRICE_MOVED` filters. The two units are never mixed in one
sort. Unknown values are ignored (default order).

### Time handling (CLAUDE.md §5)

All arithmetic is aware UTC (`utc_now()`); the ET display uses `format_eastern_display`. The module never calls
`datetime.now()` or a bare `.astimezone()`, so a UTC prod server after 8 pm ET counts down correctly (QC (6)).

### Caching (CLAUDE.md §4)

- The `/elite` context is a 12 h runtime snapshot. The countdown is **not** stored in it: the scanner stores
  only facts; `annotate_elite_line_moves` computes labels (and applies the user's sort/filter) per request in
  `elite_dashboard()` and `elite_matchup_builder()`. A snapshot built while a game was upcoming shows no
  countdown once it starts (QC (7)).
- Snapshot key bumped `elite_dashboard_v4_*` → `elite_dashboard_v5_*` so pre-D14 payloads (with
  `urgency`/`sharp_side`/`score`) are never served. `qc_elite_alert_history.py` (5) updated to require v5.
- No CSS/JS/static asset changed → no `?v=` / service-worker bump needed. Template changes need a
  `systemctl restart` on prod (the auto-deploy already restarts).

### Persisted alerts / export

- `ELITE_ALERT_COLUMNS` gains (additive, at the end) `MoveState`, `OverPriceDeltaCents`, `UnderPriceDeltaCents`;
  the cent deltas are quote columns (withheld without provenance, like the other book/line columns).
- New alerts persist `Urgency=''`, `Score=''`, `Reliability=''`, `TrueProb=''`, `OverMove=''`, `UnderMove=''` (the
  legacy implied-probability-point columns are no longer written; legacy rows keep their values, which are
  implied-probability points). `LineMove` (points) is still written. The storage column keeps its legacy name
  `SharpSide` (values OVER/UNDER) for archive continuity. Alert ids hash `move_side`; where the per-unit rule
  (2a) gives a different side than the old combined rule, that move gets a new id.
- `/elite/alerts/export` drops `Urgency`, `Score`, `Reliability`, `TrueProb` and renames `SharpSide` →
  `LineMoveSide`. The history label + provenance gate are unchanged.
- Historical rows never get live labels: `elite_alert_history_row` exposes no start/urgency field (QC (5)).

## 3. Files changed

`services/elite_live_labels.py` (new), `app.py` (scanner, alias `build_elite_line_move_scanner`,
`annotate_elite_line_moves`, persist/export, alert columns, matchup notes, learning module, Elite preview copy,
routes, snapshot key), `templates/elite_dashboard.html`, `templates/elite_matchup_builder.html`,
`qc_elite_live_labels.py` (new), `qc_elite_alert_history.py` (export check tolerates the dropped column;
snapshot v5; fixture reindexed to the extended column list), `run_all_scorecards.py`.

## 4. Data availability (what the factual replacement depends on)

- The countdown needs the props rows' `EventCommenceAtUTC` + `SourceUpdatedAtUTC` + `EventId`, written by
  `fetch_player_props.py` since the 2026-10-24 capture-precision fix. Props files written before that (or any
  other props file lacking those columns) carry none of them → those rows show **no countdown** (fail closed).
- Move states need `OpenLine`/`CurrentLine` and/or `OpenOverOdds`/`OverOdds`/`OpenUnderOdds`/`UnderOdds`;
  without them the row is `INSUFFICIENT_DATA` and not listed.
- The game-lines `EventCommenceAtUTC` (only NBA game lines are event-aware) is not used; the props row's own
  provider kickoff is the verified start.

## 5. D14 final — owner decisions applied (2026-11-04); no open questions

Status: all seven previously open questions are resolved below. Where the owner's decision did not name an
exact rule, the most conservative factual option was applied and is marked *(conservative default)*.

| # | Question | Resolved answer (implemented) |
|---|---|---|
| 1 | Price threshold value | Kept as **documented factual qualifiers, not authority**: a move is listed when the line moved ≥ 0.5 points OR either side's price moved ≥ 10 American-odds cents. The two units are never combined (no shared threshold, score or sort). `LINE_MOVE_MIN_POINTS` / `PRICE_MOVE_MIN_CENTS` in `services/elite_live_labels.py:99-100`; stated in the card subtitle. |
| 2 | Adjacent Elite directives outside D14 | **Listed for a later governed pass; none appears on a D14 surface** (proven by `qc_elite_d14_retired_scan.py` R3). Not changed: Action Queue `HOLD`/`AVOID`/`BUILD`/`WATCH`/`LEAK`/`EDGE` cards (`app.py` `build_elite_action_queue`), BankrollIQ Kelly `PASS` + recommended stake (`calculate_bankroll_iq`), market-gate glossary "Hold means…" (`explain_profile_stack`), market-timing watch "before pushing stake" (`build_elite_market_timing_watch`), candidate-pool composite `score` + ANCHOR badges (`templates/elite_dashboard.html` candidate pool), matchup-builder candidate list ANCHOR/WATCH sorting, parlay-EV "Tier 1/2" from ANCHOR, MLB Lab learning module "start with ANCHOR suppression rows" (`build_elite_learning_modules`, slug `mlb-lab`). |
| 3 | "Sharp" branding | **Separate follow-up, not on the D14 surfaces**: "Sharp University" (`templates/elite_learn.html`, Elite hero button), "Weekly Sharp Report" (`templates/elite_dashboard.html` weekly card). The one user-facing *claim* "Sharp money came in. Be cautious." (`templates/info.html:378`) was rewritten now to a fact ("That is a fact about the market; it does not say who bet or predict the result.") because the D14 scan bans the phrase on every rendered surface. |
| 4 | Countdown horizon | *(conservative default)* A countdown ("Starts in N minutes / H h M min") appears **only for a verified provider kickoff whose Eastern calendar date is today's Eastern date** (the current slate) and in the future, plus fresh quote time, recorded source and an executable price. A later slate shows its start time in ET with "No countdown: start is outside today's Eastern slate". No urgency wording anywhere. `start_facts` (`services/elite_live_labels.py:193`, reason `OUTSIDE_SLATE`). |
| 5 | ET-date-only (derived) starts | **No countdown.** Only the provider's explicit-UTC `EventCommenceAtUTC` counts as verified; an Eastern `Date`/`Time` (legacy bridge) is never used → `START_UNVERIFIED`, no label. |
| 6 | Started events | **Shown as historical / non-executable, never live**: the row carries `historical=True`, the label "Historical -- event started; not a current executable quote (started <ET>)", the line column reads "Last captured" instead of "Now", no countdown, sorted after upcoming and unverified rows. |
| 7 | Internal storage names | **Migrated now on these surfaces**: scanner `build_elite_line_move_scanner` (old name removed, no alias); context key `line_moves` (dashboard + matchup builder + templates); archive column `LineMoveSide`. The ONE remaining legacy literal is the read-only migration input `ELITE_ALERT_LEGACY_SIDE_COLUMN` (`app.py:15614`, marked `# legacy-column-migration`). Snapshot key bumped `elite_dashboard_v5_*` → `elite_dashboard_v6_*`. |

### Saved history migration (alert archive `data/tracking/Elite_LineMove_Alerts.csv`)

`ELITE_ALERT_COLUMNS` (`app.py:15601`) is now: AlertId, FirstSeen, LastSeen, Sport, Player, Stat, Book, Game,
OpenLine, CurrentLine, **LineMoveSide**, ModelSide, Alignment, LineMove (points), OutcomeState, ActualValue,
GameDate, ResolvedAt, CapturedAtUTC, SourceProvenance, MoveState, OverPriceDeltaCents, UnderPriceDeltaCents.
Retired (`ELITE_ALERT_RETIRED_COLUMNS`, `app.py:15615`): Urgency, Score, Reliability, TrueProb, OverMove,
UnderMove (implied-probability points — a third, unlabelled unit) and the legacy side column.
`migrate_elite_alert_frame` (`app.py:15694`) is applied by `load_elite_line_move_alerts` (`:15738`): the legacy
side column becomes `LineMoveSide`, retired columns are dropped, missing columns are blank; the next persist /
grade rewrites the file in the current schema. Old rows remain history: `elite_alert_history_row` (`:15666`) keeps
only the label "Historical alert — not a current executable quote" and the provenance gate.

### Final surface / export / API / history inventory (file:line at the D14-final commit)

| Surface | Where | What it shows now |
|---|---|---|
| Scanner (builder) | `app.py:15480` `build_elite_line_move_scanner` | move_state + line_delta (pts) + per-side price deltas (¢) + open/current prices, line-move side, model side, alignment, start/quote/source facts; no urgency, score, tier or model probability |
| Render-time labels | `app.py:15579` `annotate_elite_line_moves` → `services/elite_live_labels.py:246` `annotate` | countdown (current slate only) or a neutral reason note; historical label for started events; quote update time (ET); open-capture disclosure; default order kickoff → update time; explicit line / price sorts |
| `/elite` scanner card | `templates/elite_dashboard.html:301-370` (`data-live-line-moves`) | columns Prop / Book / Line (open, now or last captured, "as of" time, open-capture note) / Move (state + deltas) / Line-move side / Model side / Model vs move / Start; order + filter links (`moves_sort`, `moves_state`) |
| `/elite` route | `app.py:44534` | snapshot `elite_dashboard_v6_*`; labels computed per request |
| `/elite/matchup-builder` card + route | `templates/elite_matchup_builder.html:120-140`, `app.py:44571`, context `app.py:15969` | same facts in compact form; notes "line move(s) point the same / opposite way as the model side" (`app.py:16033`) |
| Alert history block | `templates/elite_dashboard.html:521` ("Recent Alerts") | historical label + provenance-gated book/line; side from `LineMoveSide`; no live label |
| CSV export | `app.py:44660` `/elite/alerts/export` → `elite_alert_export_frame` `app.py:15712` | HistoryLabel, ProvenanceStatus + current schema; retired columns never exported, even from legacy rows |
| Persist / grade / summary | `app.py:15748`, `:15804`, `:15920` | current schema only; grading reads `LineMoveSide` |
| Learning module | `app.py:16827` (slug `line-movement`) | factual, no "start with" |
| Elite preview copy | `app.py:23363` (`GLOBAL_FEATURE_PREVIEWS['elite']` steps) | "Read the line movement …" — factual, no "start with" |
| APIs / JSON | — | none: no `/elite*` JSON route exists; the only machine payload is the runtime snapshot (`line_moves`, facts only) |
| Static assets | `static/**` | no Elite line-movement code; scanned (R1/R2) |

### Static scan

`qc_elite_d14_retired_scan.py` (22 checks): R1/R2 across 293 rendered files (`app.py`, `services/**`,
`templates/**`, `static/**`; code strings only, Jinja comments and Python docstrings excluded); R3/R4 on the D14
surfaces listed above; R5 archive schema; 16 mutation self-tests (each retired token injected into a scanned file
is flagged; an explicit negation disclaimer is not). `docs/` is not scanned: no route renders a docs file.
