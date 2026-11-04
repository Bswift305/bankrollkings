# Production follow-ups after the 2026-11-03 acceptance (read-only evidence)

Companion to `docs/rc_receipt_20261103_slate_turnover_acceptance.md`. Everything here was gathered read-only:
SSM Run Command on `i-08d2fd818875381dd` (outputs read via CloudShell), local `git` and code reading at
exact `a5de400`. No deploy, no push to master, no data regeneration, no paid call, no flag or timer change.

## 1. Remaining RC production evidence — SSM `75c0ff13-beba-430f-8ab0-f6b26f094489` (16:21 UTC, HEAD `a5de400`)

| Check | Result |
|---|---|
| Governed roster identity nulls | `null_governed_identity_rows=0`, `all_identity_null_rows=0` (8,420 rows) |
| Aggregate-row sanitation | Producer logged `removed 8 non-player aggregate row(s) with all identity columns null`; published file has `aggregate_like_rows=0` (blank/team/total/nan names, 4 identity columns checked) |
| Roster season | `seasons=[2026]`, max week 8 |
| Roster file | `data/tracking/_nflverse_stats_2026.parquet` mode 600, owner ubuntu, inode 1835061, 488,232 B, mtime 2026-11-03 13:03:19Z, sha256 `a522f7d1217067f0…` |
| Roster final writer | `bk-daily` step **NFL weekly player stats** `[PASS]` → `fetch_nfl_player_week.py` (log 632–635: 8,420 rows, weeks 1–8). mtime falls inside that step. The only other unit referencing the roster writer is `bk-nfl-postweek` (`/usr/local/bin/bk-nfl-postweek-refresh.sh`); it ran 14:00:00–14:00:01 and did **not** rewrite (mtime unchanged). `bk-nfl-gameday`/`bk-nfl-games` do not reference it. No leftover `nflwk_out_*` / `NFL_Props.*.tmp` |
| Collision audit | `name_to_multi_id=3`, `id_to_multi_name=0` (unchanged from 11-02) |
| Board resolution (new props × roster) | 139 distinct names: **120 resolved, 18 unresolved, 1 ambiguous** (`justin jefferson`); 413/450 rows admitted. Unresolved are mostly team D/ST and "defense" rows plus suffix variants (`brian robinson jr.`, `brian thomas jr`) |
| Adapter dry-run | `pairs=139 RESOLVED_capturable=120 NAME_UNRESOLVED=18 NAME_AMBIGUOUS=1` — **no** `ROW_SOURCE_TIME_ABSENT` (was 621/621 on 11-02), no artifact-level abstention |
| Evidence/provenance round-trip | 120/120 resolved: `props_sha256` and `roster_sha256` equal the files' own hashes (`e607456b…`, `a522f7d1…`), `roster_season=2026`, event id and player binding match the input, `event_effective` equals the row's `EventCommenceAtUTC`, `resolved_at` tz-aware, and EntityIdentity/EventIdentity/ResolutionEvidence reconstruct equal from their fields — **0 mismatches** |
| No database while capture OFF | `BK_RESEARCH_CANDIDATE*` absent from `.env`; no research-candidate file anywhere under `/var/lib/bankrollkings`, `/opt/bankrollkings-runtime`, `data/` before or after the dry-run. DBs present are pre-existing and unrelated: `decision_journal/journal.db` (+ daily/monthly backups), `kings_tickets/active_drafts.db` (2026-10-21). `data/cache/candidate_review_*.pkl` belong to the Candidate Review page, not the RC store |

### 1a. Denominator and abstentions

- **Adapter inputs:** 139 distinct `(Player, EventId)` pairs, built from all 450 published rows (non-blank player
  and event id). **Reconciliation: 120 + 18 + 1 = 139.**
- **Every outcome code and count:** `RESOLVED_capturable=120`, `NAME_UNRESOLVED=18`, `NAME_AMBIGUOUS=1`. The tally
  shows nothing else, so these were all **zero**: `ROW_SOURCE_TIME_ABSENT`, `PROPS_SCHEMA_INVALID`,
  `ROSTER_SCHEMA_INVALID`, `ROSTER_SEASON_MISMATCH`, `PROPS_STALE`, and every event/binding abstention.
- **Every `RESOLVED_capturable` is tied to a future event.** This is derived from two verified facts rather than a
  separate per-pair assertion:
  1. The round-trip proved, for all 120, that `event.event_effective` equals that row's `EventCommenceAtUTC`.
  2. All 450 published rows have `EventCommenceAtUTC` ≥ `2026-11-06T01:15:00Z`, with 0 started rows (SSM read at
     16:11Z). The dry-run ran at 16:21Z.
  So every resolved event kicks off at least 2 days 8 h after the resolution instant. A per-pair `> now` assertion
  belongs in the next receipt script.

### 1b. Roster artifact

`data/tracking/_nflverse_stats_2026.parquet`:
- sha256 `a522f7d1217067f0c7846eab8b45f2c4d986d1749996ebef4b2425c04bd61ae2`
- mtime 2026-11-03T13:03:19Z; 488,232 B; inode 1835061; mode 0600; owner ubuntu
- **Final writer:** `bk-daily.service` → `run_daily.py` step "NFL weekly player stats" → `fetch_nfl_player_week.py`
  (log 632–635, inside the 13:00–13:20 run).
- **Attribution basis:** mtime matched to the step's log lines. Unlike 11-02, there was no live writer-watch, so this
  is mtime + log attribution, not process capture.
- The only other configured writer, `bk-nfl-postweek` (`/usr/local/bin/bk-nfl-postweek-refresh.sh`), ran
  14:00:00–14:00:01 and left the mtime unchanged.

### 1c. Proof that no Research Candidate DB exists

**Code contract** (`a5de400:services/research_candidate_boundary.py:27-30, 61-77`):
- A store path exists only when **both** `BK_RESEARCH_CANDIDATE_DB_PATH` and `BK_RESEARCH_CANDIDATE_ROOT` are set,
  absolute and contained.
- There is **no default root and no default path**. A missing value raises `ConfigError` before any open.
- Capture also needs `BK_RESEARCH_CANDIDATE_ENABLED` truthy.

**Environment — no variable matching `BK_RESEARCH_CANDIDATE*` is set:**
- `/opt/bankrollkings/.env` (the unit's only `EnvironmentFile`): `grep -c BK_RESEARCH_CANDIDATE` = 0.
- `systemctl show bankrollkings -p Environment`: absent.
- Recursive grep of `/etc/systemd/system/`: no file mentions it.
- `/proc/<pid>/environ` of the gunicorn master 1605749 and workers 1605753/1605755: no `^BK_RESEARCH_CANDIDATE` line.
- This covers `_ENABLED`, `_DB_PATH`, `_ROOT`, `_PROPS` and `_ROSTER`.

**Filesystem**, searched before and after the dry-run, `find -maxdepth 4`:
- Names matching `*research*` / `*candidate*` under `/var/lib/bankrollkings`, `/opt/bankrollkings-runtime` and
  `/opt/bankrollkings/data`.
- `*.db`, `*.sqlite*`, `*-wal` under `/var/lib/bankrollkings` and `/opt/bankrollkings-runtime`.
- Only pre-existing unrelated stores were found (§1 table).
- **Not searched:** `/tmp`, `/var/tmp`, `/home/ubuntu` (including `bk-backups`), deeper than 4 levels. With no path
  env set, the code cannot place a store anywhere, but those locations were not inspected.

### 1d. No writable store or network was opened by the audit

- The dry-run imported only `services.nfl_identity_event_adapter`. Its imports are `research_candidate` (stdlib value
  objects only), `nfl_season_contract`, `freshness_contract`, `timeutils` and pandas — no store, sqlite, boundary,
  HTTP or socket module.
- The adapter opens artifacts with `os.open(path, O_RDONLY)`. It ran as `ubuntu` with `PYTHONDONTWRITEBYTECODE=1`
  (no `__pycache__` writes).
- **No-network basis:** the code path imports no network module. That is a code-path guarantee, not a runtime
  socket guard; `qc_offline.py` was not used on the box.

**Reading:** the RC artifact path is now evidenced end to end on production data: roster identity, props source
time, adapter, and provenance. Phase 2 stays blocked on Phase 1 (1.7) and its own steps (2.2+).

## 2. The seven `bk-daily` failures (11-03 log `logs/daily_operator_20261103_130000.log`; SSM `ebd4f3f6…`, `f0fd000d…`)

Four root causes, not seven. None is dismissed.

| # | Step (log line) | Exact error | Root-cause class | Fixed on an isolated branch? | Stale / customer-visible? | Reversible correction + evidence |
|---|---|---|---|---|---|---|
| 1 | CFB data refresh (733) | `[SKIP] CFB refresh: CFBD quota EXHAUSTED state persisted (detected 2026-10-24T13:04:29Z, reason 'HTTP 429 (monthly quota) at step 'CFB current-season results'', reset unknown)`; `/opt/bankrollkings-runtime/cfbd_quota_state.json` `exhausted:true, reset_at:null` | Operator/config — **stale latch** (the 11-01 probe already returned HTTP 200) + no configured reset | No code fix needed to clear; budget client `feat/cfbd-budget-client-scaffold` `905cabe` is unwired; F7 `bdc06c4` makes CFBD fail-closed | **Yes.** CFB current-season results/form/regression frozen since 10-24 (10 days into the season's back half) | Owner action (ledger 1.6/1.6c): confirm allowance + reset in the CFBD account, set `BK_CFBD_RESET_AT`, clear the latch once. Evidence: one probe 200, CFB refresh `[PASS]`, artifacts dated today. Risk: re-exhausts ~late Nov without the budget client |
| 2 | MLB daily refresh (745; child `game_lines` 796) | `Strong validation FAILED … empty/too-small current slice: 0 rows < min 1` → `[FAIL] game_lines exited with code 1`; schedule `Saved 0 MLB schedule rows` (11-03→11-17) | **Season gate missing** — off-season sport executed as active | **Yes:** F2v2 `fix/bk-daily-f2v2-season-preexec` `0ccf053` + F6 `3fd0e40` (skip OFF_SEASON before any call) | Off-season; `MLB_Odds.csv` 2026-10-28 (3 rows), `MLB_Props.csv` 10-28. Visible only where MLB pages show those as current (Q-A freshness defect 1.5f/1.5l) | Merge the Season/phase group after its review items (1.5o). Evidence: next run shows `[SKIP (off-season …)]`, no Odds call, step not FAIL |
| 3 | **NBA daily refresh** (806; child `game_lines` 846) | `Loaded 15 bookmaker rows` → `implausible row-count collapse: 15 rows < 50% of prior 45` → `[FAIL] game_lines exited with code 1`; the child **stops** — NBA props never ran | **Slate-turnover false rejection** (same class as the accepted props fix) on **NBA game lines**, plus a halt-on-first-failure that also starves NBA props | **No.** F5 `cea32ea` covers NFL/NCAAF game lines only; NBA's slate-aware spec covers NBA *props*, not game lines | **Yes — in season.** `NBA_Odds.csv` 2026-11-02 13:05Z (45 rows, includes Monday's completed games), `NBA_Props.csv` 2026-11-02 13:05Z (1,727 rows) — a day old on the live NBA board. **Highest priority of the seven** | New branch: apply the event-aware validator (a5de400 pattern / F5) to NBA game lines; decide whether a lines rejection should still let the independent props child run. Evidence: replay fixture 45→15 with completed events removed ⇒ publish; vanished-future-event and true collapse still reject; one scheduled run publishes NBA lines + props |
| 4 | WNBA game lines (848) | `empty/too-small current slice: 0 rows < min 1` (0 credits) | Season gate missing | **Yes:** F2v2 + F6 | Off-season; `WNBA_Odds.csv` 2026-11-01 (2 rows) | Same as #2. Also 1.5k: `bk-linemove.timer` still pays for MLB+WNBA every 4h off-season — not covered by F2v2 |
| 5 | WNBA player props (874) | `Found 0 events in the next 5 days` → `empty/too-small current slice: 0 rows < min 1` + `implausible row-count collapse: 0 rows < 50% of prior 72` | Season gate missing | **Yes:** F2v2 + F6 | Off-season; `WNBA_Props.csv` 2026-10-31 (72 rows) | Same as #2 |
| 6 | All scorecards (1095) | Only failing section inside the runner is **NFL Heat-Map Freshness QC** (every other section `[PASS]`) | **QC drift** — `8a3ff74` changed the label to `Appearances: Wks 1–4`; `qc_nfl_heatmap_freshness.py:127` still expects `Wks 1–4` | **Yes:** F1 `fix/bk-daily-f1-heatmap-qc` `3564dc7` (inside the Integrity group) | Not customer-visible (QC only), but it keeps the prelaunch scorecard NO-GO every day | Ships with the Integrity group. Evidence: scorecard section `[PASS]` on the next run |
| 7 | NFL Heat-Map Freshness QC (1108) | Same QC as #6, run as its own step | Same as #6 | **Yes:** F1 | Same as #6 | Same as #6 |

### New findings from the same log (not among the seven)

- **D11 (P1) — Run Status reads the previous day's operator log** (ledger D11). The `Run status` step (≈13:07, mid-run) printed
  `FRESH Daily Operator 23.8h logs/daily_operator_20261102_130000.log` and `DEGRADED: … child outcome(s) alerting:
  football_props:…=VALIDATION_FAILED` — those are **11-02** outcomes; today's props were `UPDATED`. The status a
  reader sees therefore describes yesterday. Class: truth-model ordering (status generated before the run it
  reports has finished, from the newest *complete* log). Needs its own branch: generate Run Status after the run, or
  bind it to the current run id and mark in-progress honestly.
- **Pre-refresh "props STALE while lines FRESH"** lines (log 14–15) are expected before the refresh; the post-refresh
  odds health `[PASS]` is the authoritative result. Consider labelling the pre-check as a pre-refresh snapshot so it
  is not read as a failure.

### 2a. NBA game-lines slate turnover — read-only RCA (failure #3; code at exact `a5de400`, no network, nothing edited)

- **Path.** `refresh_nba_daily.py:29-47` → `fetch_game_lines.py --days 5` (default `basketball_nba`) →
  `validate_feed(df, GAME_LINES_SPEC, prior_df=<current NBA_Odds.csv>, allow_collapse=False)` (`:441-452`).
  `services/feed_validation.py:158-162` rejects when `rows < 0.5 × prior` (prior ≥ 5). A row is event × book
  (`:250-252`); the prior is the **whole** file being replaced, with no kickoff filter (`:443`).
- **Root cause 1 — whole-file collapse on a daily-turnover feed.** The candidate holds only not-yet-started games
  (`commenceTimeFrom=now`, `:235`); the prior still holds Monday's played games. 45 → 15 ≈ 11–12 → 4 events × ~4
  books. [inference] That is normal turnover, not a loss. Same class as the accepted props fix and F5.
- **Root cause 2 — halt-on-first-failure.** Only `player_props` is soft (`:70-84`); any other non-zero exit returns
  (`:94-101`). A lines reject therefore skipped **all 11 later steps** (props, injuries, officiating ×2, coverage,
  calibration, runtime snapshots, 4 QCs), not just props. Props genuinely depend on lines: the NBA props validator
  uses `NBA_Odds.csv` as its independent event list (`fetch_player_props.py:124-153, 835-858`).
  [inference] Running props against Monday's stale list would likely spend credits and then reject (coverage < 100%).
- **Reuse.** F5 is not an ancestor of `a5de400` and covers NFL/NCAAF only; adding NBA to it works only when the
  previous line-movement snapshot already held the next day's games, otherwise it falls back to the absolute rule.
  `validate_feed_event_slate` cannot be reused unchanged: it needs `EventCommenceAtUTC` (absent from lines output),
  its malformed-row rule reads `Line` (absent → every row dropped), and its per-event floor (20 prior rows) can never
  fire at ≤ 4 rows/event.
- **Blast radius.** `NBA_Odds.csv` feeds `load_game_market_odds` (`app.py:17990`) on frontpage, NBA command center,
  live prop context, schedule, `/game-lines`, team, series, matchup and fantasy; `load_schedule` (`:20682`) also
  derives the NBA schedule from it. **No line-age label exists downstream** (`_format_game_market_odds` drops
  `LastUpdated`), so `/game-lines` shows Monday's played games at pre-game lines as current. Stale props are hidden
  instead (`require_fresh=True` → empty board after 6h). [inference] Props `LastUpdated` is naive Eastern compared
  with naive UTC "now" on prod, overstating age by ~5h — a separate small defect.
- **Same latent defect elsewhere.** NCAAF still fails most Sundays until F5 merges; WNBA/MLB lines (off-season) have
  it too, and `refresh_line_movement_snapshots.py:47-49` reports exit 1 as benign (silent OK). NFL passes only
  because `--days 130` holds the rest of the season.
- **Proposed correction (proposal only; new branch off `a5de400`, e.g. `fix/nba-game-lines-event-aware`).**
  Add `EventCommenceAtUTC` (canonical `Z`) to lines output; a game-lines usable-row rule (one complete market);
  `NBA_GAME_LINES_EVENT_SPEC` — a vanished not-yet-started event rejects at any size, started events excluded from
  both sides, provider error / zero usable events reject; publish only the current-slate frame to all outputs and the
  movement snapshot, with a props-format receipt; `refresh_nba_daily` classifies a lines reject as DEGRADED and keeps
  running the independent steps. QC `qc_game_lines_event_slate.py`: 45→15 replay publishes; vanished future event,
  4→1 books, provider error, zero usable, blank GameID, non-`Z` kickoff reject; kickoff == now excluded / now+1s
  eligible; malformed row dropped; migration prior without the UTC column; other sports unchanged; stubbed end-to-end
  reject leaves file hashes unchanged; lines reject still runs injuries + QCs; rerun `qc_slate_validation`,
  `qc_props_slate_turnover`, `qc_odds_recovery_preflight`.
- **Owner decisions required before build:** (1) new NBA event-aware path vs F5 + NBA by configuration;
  (2) per-event floor `min_prior_rows=2` — new, not evidence-derived; (3) migration of today's prior that lacks the
  UTC column — as sketched the comparison would be skipped (**fail-open**), so either a one-time kickoff derived from
  Eastern Date/Time labelled DERIVED (F5 precedent) or one explicit operator-approved run; (4) on lines reject, skip
  props with an explicit "lines manifest unavailable" outcome (recommended) or run them; (5) whether a lines reject
  may stop independent steps (recommended: no); (6) immediate recovery — a one-off `--allow-collapse` run costs one
  credit and [inference] would publish correct rows. **Nothing was run.**

#### 2b. Owner decisions on 2a (2026-11-03) — build authorized on `fix/nba-game-lines-event-aware` from exact `a5de400`

1. No isolated NBA-only algorithm; F5 is **not** merged wholesale. Build a **configurable event-aware game-lines
   contract in the shared validation service**; NBA is the first production consumer. Record how F5 later migrates
   onto it.
2. **No invented per-event minimum** (the proposed `2` is rejected). First governed version: zero valid rows for a
   previously published still-future event = reject; ≥ 1 structurally valid current quote may publish; reduced book
   coverage is logged `COVERAGE_DEGRADED`. A read-only historical coverage audit must precede any stronger rule.
3. **Governed one-time legacy kickoff bridge:** prior comparison instant derived from explicit Eastern Date+Time via
   `America/New_York` (DST-aware), labelled `DERIVED_LEGACY_KICKOFF` in the receipt, used only to classify prior
   events started/future, never written as provenance; missing/ambiguous/unparseable fails closed. Every newly
   published row carries the provider's UTC kickoff.
4. **Step isolation:** explicit dependency map; dependents report `SKIPPED_BLOCKED_BY_LINES`, independent fetches and
   QCs continue, the run stays degraded. The 4-hourly line-movement job must never report a failed fetch as `OK`.
5. **Customer containment** (same track): timezone-aware UTC age (fixes the props Eastern-vs-UTC bug, DST QC), actual
   update time shown, prominent stale/unavailable state or no executable actions, played games never shown as a
   current slate.
6. **No paid recovery fetch or override today.** After code review + Linux gate, the next ordinary refresh is the
   production test. Branch stays separate from D1, D4 and the Integrity group.

#### 2c. NBA branch built — `fix/nba-game-lines-event-aware` @ `c9bc3746ca7955ec22caa6b8ff4fcaa459dc865f` (branch-only; IN REVIEW; no Linux gate)

Six commits on exact `a5de400`; 15 files, +1862/−74: shared contract `game_lines_event_v1`
(`services/feed_validation.py`), NBA wiring + atomic 3-file publish + receipt (`fetch_game_lines.py`,
`services/atomic_csv.py`), dependency-mapped isolation (`refresh_nba_daily.py`, `services/run_outcomes.py`),
line-movement job never reports a failed fetch as OK, customer containment + tz-aware ages (`app.py`,
`services/timeutils.py`, `templates/_nba_lines_status.html` new, `dashboard.html`, `game_lines.html`), QCs
`qc_game_lines_event_slate.py` (59) + `qc_odds_age_timezone.py` (19), contract doc `docs/game_lines_event_contract.md`
(frozen malformed-row rule R1–R9 / M1–M3 / D1–D3; no per-event minimum; `COVERAGE_DEGRADED`, `NEW_EVENT_SPARSE`;
coverage audit required before any stronger rule; F5 migration path).

Independent re-run by the coordinator (Windows, Python-socket block, 0 attempted connections): compile 0 on all 10
changed `.py`; `qc_game_lines_event_slate` 59/59; `qc_odds_age_timezone` 19/19; `qc_slate_validation`,
`qc_props_slate_turnover` (77/77), `qc_odds_recovery_preflight`, `qc_game_lines_freshness`, `qc_run_outcomes`,
`qc_atomic_csv`, `qc_freshness_contract`, `qc_nba_gated_market_facts` all rc 0. **`qc_nba_market_only` rc 1**
(`/sports/nba/props`, `/sports/wnba/props` → 401) — **identical on clean `a5de400`**; not caused by this branch but
**not waived**: it renders NBA surfaces this branch touches, so it must be made self-contained (in-memory auth, the
D1 pattern) or excluded with proof before any Linux gate.

Open review points for the owner:
- Props classified **dependent** on lines (`SPORT_EVENT_MANIFESTS["basketball_nba"]` = `NBA_Odds.csv` is the props
  coverage denominator) → `SKIPPED_BLOCKED_BY_LINES` on a lines reject.
- Enforcing the existing 6h `LIVE_LINES_MAX_AGE_HOURS` for NBA (once-daily lines refresh) withholds NBA prices
  outside ~6h after each refresh — a cadence/credit decision.
- The shared odds formatter drops `LastUpdated` for WNBA/MLB/NFL/NCAAF, so their stale gate never fires in
  production — untouched here, recorded in the F5 migration section.
- `qc_odds_feed.py` exit-3 refusal lives on the Integrity branch, not `a5de400`; not run here.

#### 2d. Owner decisions on 2c (2026-11-03) + read-only cadence/quota audit (production side)

Decisions: (1) NBA props stay `SKIPPED_BLOCKED_BY_LINES` when lines are unavailable (lines are their event-identity
source); follow-up design item: an **independent NBA props event adapter** that establishes identity + kickoff from
authoritative props/provider data, with its own contract. (2) Keep the 6h executable-price rule; never loosen it to
fill the board. (3) Once-daily refresh is **not** the final operating model; cadence/quota audit before the Linux
gate; no timer change until audit + schedule are reviewed. (4) Other sports = governed migration track (matrix in the
contract doc), not blocking NBA. (5) Fix `qc_nba_market_only` with the existing `services.qc_auth` helper, no waiver.
(6) Rebuild on current master `6bdb73f` (branch `fix/nba-game-lines-event-aware-v2`); `c9bc374` is never gated or
deployed from its old base.

Production evidence (SSM `I`/`J`, 2026-11-03 ~23:40Z, read-only; no key values printed):

| Fact | Evidence |
|---|---|
| Cost of one NBA lines refresh | **3 credits** (11-03 log l.771–789: `game_lines`, `basketball_nba`, regions `us`, markets h2h/spreads/totals, books draftkings/caesars/fanduel/betmgm, `x-requests-last (sum = fetch cost): 3`). `/events` is free; an empty slate costs **0** (WNBA 20:00Z: `responses 1`, `x-requests-last 0`) |
| Plan size / remaining | `x-requests-used 1429` + `x-requests-remaining 98571` = **100,000 / month** |
| Reset contract | monthly on the 1st: remaining 94,341 (10-31) → 99,759 (11-01) |
| Current burn | Nov 1→2: 735; Nov 2→3: 453; late Oct ≈ 480–740/day. Month projection ≈ 15–22k of 100k |
| Existing calls | `bk-daily` 13:00Z daily (`run_daily.py --sports nba,wnba,mlb --continue-on-error`; runs ≈ 20–25 min, ends 13:20–13:25Z; **exits 1 every day since 10-27** — known standing failure); `bk-linemove` 00/04/08/12/16/20Z, `refresh_line_movement_snapshots.py` = **MLB + WNBA game lines only (no NBA)**; `bk-nfl-postweek` Tue/Wed 11–23Z ×5; `bk-live-scores` every 1 min (self-gated) |
| Line-movement "OK" bug — live | 11-03 20:00Z: WNBA `Strong validation FAILED … 0 rows < min 1`, then the job printed `[WNBA game lines] OK` and "All line-movement snapshots captured." Confirms the defect the branch fixes |
| Overlap protection | **none**: no `flock`/`Conflicts=` in `bk-daily.service` or `bk-linemove.service`. Observed windows do not overlap (12:00Z linemove finishes in seconds; bk-daily 13:00–13:25Z) but nothing enforces it |
| Quota state files | only `cfbd_quota_state.json` (CFBD, unrelated); no Odds API budget/state file |

Projection for NBA lines only (3 credits/run; off-days cost 0 because an empty slate is free):

| Cadence | Runs/day | Credits/day | ≈ Credits/month | Keeps quotes ≤ 6h? |
|---|---|---|---|---|
| Today (daily) | 1 | 3 | 90 | **no** (prices withheld ~18h/day under the 6h rule) |
| Every 6h | 4 | 12 | 360 | **no margin** — age reaches 6h + run time at every boundary |
| Every 4h (aligned with `bk-linemove`) | 6 | 18 | 540 | yes, ≤ ~4h + run time |
| Slate-aware: hourly 15:00–04:00Z on game days + 1 overnight | ≈ 14 | ≈ 42 | ≈ 1,100 (fewer on off-days) | yes, ≤ ~1h before/through tip |

All options are < 1.2% of the 100k monthly plan. Proposal (not enacted — needs review): 4-hourly NBA lines via the
governed event-aware fetch, optionally slate-aware tightening later; serialize with `bk-daily` (shared `flock` or
skip the 12:00Z tick) so two writers never validate against the same prior concurrently. Whether `bk-linemove` can
carry NBA depends on the code-side facts (pending from the rebuild): today it fetches MLB/WNBA only and its exit-code
semantics are what this branch fixes.

Code-side facts (v2 build, file:line at `f06e568`): one refresh = one `GET /v4/sports/basketball_nba/odds`
(`fetch_game_lines.py:290-303`; `/events` defined `:180` but unused), repo formula `calls × markets × regions` =
1×3×1 = 3 (`services/odds_quota.py:26-36`), matching the production receipt. **`bk-linemove` cannot carry NBA as-is**:
it runs only MLB/WNBA (`refresh_line_movement_snapshots.py:26-29`) through the old whole-file validator, and has no
props/snapshot sequencing — a governed NBA cadence needs its own step/unit. No locking in either path (repo `flock`
only in deploy/backup/nfl-games scripts); WNBA is fetched by both `run_daily.py:200` and the linemove job (shared
files + receipt; `os.replace` atomicity only). **No-game days:** linemove treats a fresh `NO_ACTIVE_EVENTS` receipt as
benign (`:61-63`), but `refresh_nba_daily` records it as `VALIDATION_FAILED` → DEGRADED (`:149-155`, `:197`) — a
mislabel to fix before cadence goes live.

#### 2e. NBA v2 review package — `fix/nba-game-lines-event-aware-v2` @ `f06e568c96fd8ce5753d9b79fffbc74405ff200d` (pushed; IN REVIEW; no Linux gate)

- On exact `6bdb73f`. Commits: `08aef8a`, `44ff9aa`, `2be0f78`, `97ef6bc`, `b99b7cd`, `f522b06` (the six `c9bc374`
  commits, all clean cherry-picks, `range-diff` all `=`), `d7ab7ee` (qc_nba_market_only self-contained), `f06e568`
  (migration matrix + independent-props-adapter item). 17 files, +2142/−111.
- **D1 preserved:** normalized `diff a5de400 6bdb73f` ≡ `diff c9bc374 f522b06`; overlapping files only `app.py`
  and `run_all_scorecards.py`, non-overlapping hunks; the 8 D1-only files identical to `6bdb73f` (coordinator
  re-checked: none differ).
- **`qc_nba_market_only`:** private owner-row lookup removed; `services/qc_auth.py` gains `isolated_member_client`
  (non-owner synthetic member, refuses to resolve as owner). Proves signed-out 401, free member 403 + upgrade gate,
  paid member + owner 200 on NBA and WNBA, no writes under `data/tracking|user_prefs|live_scores` (sha/mtime +
  `save_user`/`update_user_membership` tripwires), stale 10h lines fixture → `/game-lines` withheld, stale props →
  `require_fresh` empty. Mutations (no plan gate / loosened 6h / file write) each fail it.
- **Gate (builder):** 25 QCs rc 0, 0 network attempts, worktree **and** clean `git archive` export; compile 0 on 13
  files; clean tree. **Coordinator re-run:** `qc_nba_market_only` (Market-only board verified),
  `qc_game_lines_event_slate` 59/59, `qc_odds_age_timezone` 19/19, `qc_nfl_weather_venue_integrity` 275/275 — all rc
  0, 0 network attempts.
- **New finding (not fixed, outside scope):** the market-only NBA/WNBA props boards call the feed with
  `require_fresh=False` (`build_market_only_board`, `app.py` ~41380), so a > 6h props file renders as current
  quotes — conflicts with the stale-price rule. Needs an owner decision.

#### 2f. D4 v2 review package — `fix/d4-kickoff-gate-v2` @ `a0867647d217366c675f98242f2c59309d984ef8` (pushed; HELD)

- Six commits on the Integrity rebuild `672480d` (i.e. on the **old `a5de400` base**): `63721b7` single predicate +
  `_leg_kickoff_failure` wrapper, `34aab19` server-side gate on Daily Card / King's Tickets / Green Light ticket / Menu
  / Featured Parlay / image POST (409), `2b0b8ac` editor + Menu mirror on a server-anchored clock, `66ac33a`
  "Kickoff unavailable — context only" labels (Green Light no longer drops them silently), `5bdc996` SGP Workbench
  gate, `a086764` QCs. 12 files, +1479/−94.
- SGP: started/unknown-kickoff legs never addable (browsable as "Started — live/historical market, not addable", no
  price); held leg crossing kickoff → "Started — remove or rebuild"; vanished leg kept and named "No longer on the
  board — kickoff unavailable; remove or rebuild"; `_sgp_ticket_gate` re-checks every leg server-side and rejects
  export/handoff; forged client clock ignored; kickoff == now excluded, now−1s offered. NFL game-line/spread/team-total
  legs are context-only (no governed kickoff) — a possible `GameID`↔`EventId` join is an owner decision.
- Builder gate: 34 Integrity QCs + `qc_ticket_kickoff_gate` 119/119 + new `qc_sgp_kickoff_gate` 53/53, all rc 0;
  `qc_odds_feed` refused exit 3 via `qc_offline.py`; mutations M1/M2 caught. Coordinator re-run (0 network attempts):
  `qc_ticket_kickoff_gate` 119/119, `qc_sgp_kickoff_gate` 53/53, `qc_sgp_workbench`, `qc_unpriced_line_legs` 172/172,
  `qc_ticket_editor_shared`, `qc_green_light_workspace` all rc 0.
- **Next per release order:** rebuild Integrity + D4 v2 on master `6bdb73f`, full offline gate, then (after review) a
  scoped Linux gate. Not browser-rendered; not deployed.

#### 2g. Coordinator incident — `qc_odds_feed.py` run directly (2026-11-03 15:48/15:49 local)

While re-verifying D4 v2 the coordinator ran `py -3 qc_odds_feed.py` directly (twice) instead of through
`qc_offline.py`, violating the standing rule. Effect: two Odds API requests from the dev box with the **local** key,
both **HTTP 401 Unauthorized** (key rejected → no credit could be charged; the endpoint is the free `/v4/sports`), and
two rows appended to the gitignored local `d4-v2/data/tracking/QC_Run_Log.csv` (left in place as evidence). No
production or tracked file touched. Through the runner it is refused correctly (`NOT RUN … REQUIRES_NETWORK`, exit
3). Side observation: the local dev Odds API key is rejected (prod key unaffected — prod receipts show HTTP 200).
**Owner classification: execution mistake; no production impact.** Local log evidence preserved; the key will not be
"tested" again; `qc_odds_feed.py` is run only through `qc_offline.py`.

#### 2h. Owner decisions (2026-11-03, after 2e/2f) — NBA v3 and Integrity+D4 rebuild

**Cadence decision:** the intended operating cadence for NBA lines is **every 4 hours**, keeping the 6h executable-
price boundary (~540 credits/month). Code and systemd/timer change are separate reversible commits; the timer is
**not installed or enabled** until separately authorized after the code deploys and its ordinary daily path is
accepted.

**NBA v3** (branch `fix/nba-game-lines-event-aware-v3` from `f06e568`, still on `6bdb73f`) must close three gaps before
any Linux gate:
1. *Governed no-game result* — an empty provider response is not proof. Audit the authoritative NBA schedule source:
   fresh schedule says zero games for the governed service date → `NO_GAMES_SCHEDULED` (checked before the provider
   call, zero credits, no stale executable board); schedule expects games but provider returns zero → fail closed;
   schedule missing/stale/ambiguous → `SCHEDULE_UNAVAILABLE`, fail closed; no authoritative source → never invent a
   no-game result.
2. *Central stale-props enforcement* — the 6h rule in the central NBA/WNBA props loader; full route inventory; stale
   data yields no executable rows, shows the real update time + an honest unavailable state, cannot enter Green Light,
   tickets, images or payouts; tz-aware UTC age; resolve the v2 contradiction (QC tested the loader, the market-only
   board used `require_fresh=False`); one fixture per affected route.
3. *Single publisher + shared lock* — one NBA-lines publisher for `bk-daily` and the 4-hour job; kernel-backed lock
   at one runtime path outside the checkout, taken before any paid request; contention → `SKIPPED_LOCKED`, zero
   credits, no write, never `OK`; auto-release on exit; same validation + atomic publish; `bk-daily` may reuse a fresh
   file; a failed fetch never prints `OK`/"all snapshots captured"; real two-process concurrency QC.

**Integrity + D4:** rebuild exact D4 v2 (`a086764`) + the Integrity group onto `6bdb73f` (branch
`integration/integrity-d4-6bdb73f`), preserving D1. Workbench behaviour approved as built. NFL team-line legs stay
`Kickoff unavailable — context only`; **new item: governed NFL team-line identity/kickoff mapping (`GameID`↔`EventId`)
— design only, do not infer the mapping now.** Full offline gate (34 Integrity QCs, kickoff 119/119, SGP kickoff 53/53,
D1 weather, slate turnover, `qc_odds_feed` exit 3, clean tree, no network); return SHA + exact diff before any Linux
gate.

**Rollout order:** (1) finish + review NBA v3; (2) finish + review rebuilt Integrity+D4; (3) Linux-gate each
separately; (4) deploy code before changing cadence; (5) validate the ordinary daily path; (6) separately authorize and
enable the 4-hour timer. **D12 and the remaining daily failures stay open.**

#### 2i. Integrity + D4 rebuilt on master — `integration/integrity-d4-6bdb73f` @ `e1e33dc32777e2a9ec69f04293dbbc546eb00faf` (pushed; IN REVIEW; no Linux gate)

- On exact `6bdb73f`: four re-made merges (`8d9189a` F1, `ef1dcb1` qc-wnba-nba-self-contained, `2fda677`
  daily-card-no-fabricated-price, `cbef5bb` F7 — second parents are the original feature SHAs) + six D4 commits
  (`4005e2f`, `25b13a7`, `17e35e1`, `03e4f83`, `e7692dc`, `e1e33dc`). 55 files, +4422/−334 — same totals as
  `a5de400..a086764`. `range-diff` all 16 commits `=`.
- **One overlapping line (only `app.py`):** `build_nfl_game_board_context` Totals `cands.append` — D1 added
  weather/roof fields + the WIND flag, Integrity added `line_source`/`updated_utc`. Resolved as the **union** (coordinator
  inspected: D1's `wind`, `weather_label`, `roof`, `roof_label`, `flag` lines kept verbatim; Integrity's
  `line_source`/`updated_utc` appended). The F7 merge reproduces `672480d`'s amended resolution (incl. `KNOWN_PENDING`
  emptied). Invariants 1 and 2 hold except that single hunk (both sides edit it); a 3-way merge of `app.py`
  (a5de400 / 6bdb73f / a086764) has exactly that one conflict and HEAD equals it resolved as the union — no other byte
  differs. All 9 D1-only files blob-identical to `6bdb73f`; all 54 Integrity/D4-only files blob-identical to `a086764`.
- **Offline gate (builder, worktree + clean export, all through `qc_offline.py`):** compile 0 on 46 files; all 34
  Integrity QCs rc 0 (`unpriced_line_legs` 172/172, `route_qc_harness` 8/8, `decision_journal` 18/18,
  `props_slate_turnover` 77/77, single-writer/source-time QCs fail=0, …); `ticket_kickoff_gate` 119/119;
  `sgp_kickoff_gate` 53/53; D1 `nfl_weather_venue_integrity` 275/275 + `nfl_board`/`cfb_board`/`football_board`/
  `nfl_visual_trust` rc 0; `qc_odds_feed` NOT RUN exit 3. Blocked connections: 5 per run, all inside
  `qc_unpriced_line_legs`' own guard self-tests (expected). Tracked tree clean before/after. Export note: three QCs call
  `git ls-files`, so the export was given a throwaway index whose tree equals HEAD's (`822290e`).
- **Coordinator re-run (rc 0):** compile; `ticket_kickoff_gate` 119/119; `sgp_kickoff_gate` 53/53;
  `nfl_weather_venue_integrity` 275/275; `nfl_board`; `unpriced_line_legs` 172/172; `props_slate_turnover` 77/77;
  `game_lines_freshness`; `qc_offline.py qc_odds_feed.py` → NOT RUN, exit 3; clean tree.
- Cosmetic: the four merge commits carry no `Co-Authored-By` trailer (as the originals) and two carry a
  `# Conflicts: app.py` note; rewriting would change all ten SHAs.

#### 2j. NBA v3 review package — `fix/nba-game-lines-event-aware-v3` @ `9ac078f27bd88aae85b0524e28ac55462480e316` (pushed; IN REVIEW; no Linux gate)

On `f06e568` (→ exact `6bdb73f`). Commits: `394c12f` governed no-game result, `5a5af43` single publisher + kernel lock,
`c5b8663` 4-hourly entrypoint `refresh_nba_lines.py`, `65b791c` `ops/bk-nba-lines.{service,timer}` (not installed),
`8f2b274` central 6h stale-props gate, `9ac078f` QC registration. `f06e568..HEAD` 22 files +2246/−98;
`6bdb73f..HEAD` 31 files +4344/−165. New files: `services/{process_lock,nba_lines_publisher,nba_schedule_authority}.py`,
`refresh_nba_lines.py`, `templates/_props_feed_status.html`, `qc_nba_{lines_lock,no_game_governance,wnba_props_stale}.py`.

- **Schedule-source audit: no independent authoritative NBA schedule exists.** `data/schedules/NBA_Schedule.csv` is
  written from the same `/odds` response (`fetch_game_lines.py:587-591`); `app.load_schedule` (`:20934-20968`) derives
  from `NBA_Odds` while the stats gate is off; `fetch_schedule.py` (nba_api) is gated off, dev-only (`batch/*.bat`),
  falls back to `NBA_Odds`, uses naive `datetime.now()`; playoff results are backward-looking; `/events` is the same
  provider. Therefore `AUTHORITATIVE_SOURCES` is empty and the verdict is always `SCHEDULE_UNAVAILABLE` (checked before
  the paid call, recorded in the receipt); a zero-event NBA provider answer → `SCHEDULE_UNAVAILABLE`, exit 1, files
  untouched; **`NO_GAMES_SCHEDULED` can never be emitted** until a licensed, non-odds-provider schedule (game ids, UTC
  tip, fetched-at + source, explicit Eastern service date, freshness bound, own QC, wired in `run_daily.py`) is chosen.
  Outcomes: `NO_GAMES_SCHEDULED`/`REUSED_FRESH` benign; `SCHEDULE_UNAVAILABLE`/`SKIPPED_LOCKED` alerting; unknown
  outcome strings now alert (fail closed). Classification binds to this run's receipt only.
- **Central stale-props gate:** `load_props`, `load_wnba_props` and both live-feed loaders return only executable rows
  (tz-aware UTC `LastUpdated` ≤ 6h, not > 5 min future); callers can tighten, never loosen; `props_feed_status()` gives
  real update time/age/reason; `_build_file_token` folds an executable-state token for NBA/WNBA props inputs (cache
  invalidation at the 6h flip). Route inventory — stale exposed at `f06e568` → now withheld/gated:
  `/sports/nba/props`, `/sports/wnba/props` (market-only, `require_fresh=False`); NBA props board / `/sports/nba` /
  `/parlay` + saved-ticket payout / market-edge (12h runtime cache); `/sports/wnba`, `/parlay?sport=wnba`, WNBA
  method/matchup (`build_wnba_prop_board` cache); NBA/WNBA/Elite runtime snapshots (servable to 72h); `/`, `/dashboard`,
  `/free`, `/home/*` (direct CSV reads, even with the data gate off); `/derivatives`; `/elite` scanner + best-book;
  `/tools/nba-player`, `/tools/wnba-player` ("data through" was file mtime); `/tools/best-lines` (labelled STALE but
  priced); `/tools/risk-radar`, `/tools/slate-pulse`. Already strict: `/player`, `/series`, `/matchup`, `/raw-data`,
  trend board. No NBA/WNBA props input: Green Light, King's Tickets, Daily Card (+png), Menu (static proof in QC).
  **Contradiction resolved:** v2's QC exercised the loader with `require_fresh=True` and stubbed the board with 2099
  fixtures, while the board called the loader with `require_fresh=False`; now the board passes `True`, the loader
  ignores loosening, the board re-checks, and the QC renders board + page through the real loader. One stale fixture
  + fresh control per route in `qc_nba_wnba_props_stale.py` (`services.qc_auth`, temp data dir, no user-store writes).
- **Lock design:** `services/process_lock.py` — Linux `fcntl.flock(LOCK_EX|LOCK_NB)` (contract), Windows
  `msvcrt.locking` for local QC; fd-based, kernel-released on exit/crash, file never unlinked; creates its parent
  directory. Path: `BK_NBA_LINES_LOCK_PATH` (QC only) → `$BK_RUNTIME_DIR/locks/nba_game_lines.lock` →
  `/opt/bankrollkings-runtime/locks/nba_game_lines.lock`. Every NBA publish goes through
  `services/nba_lines_publisher.publish`; `run_fetch` refuses an NBA fetch without the lock. Contention →
  `SKIPPED_LOCKED` exit 75 (no request, receipt or write; never OK/PASS); unopenable → `LOCK_UNAVAILABLE` exit 76.
  bk-daily: `--allow-reuse --lock-wait-seconds 120`, reuses a receipt that is `UPDATED`, exit 0, contract
  `game_lines_event_v1`, ≤ 90 min, every file sha256 matching → `REUSED_FRESH`. Two-process QC: loser 0 calls/0 writes,
  winner publishes once, waiter reuses, lock free after exit and after kill. `odds_quota` cost-receipt no longer prints
  OK on a failed fetch.
- **Production check (coordinator, SSM `K`, 2026-11-04 01:36Z, names only):** `.env` sets `BK_RUNTIME_DIR` =
  `/opt/bankrollkings-runtime` (exists, `ubuntu`-owned); `bankrollkings`, `bk-daily`, `bk-linemove` all load
  `/opt/bankrollkings/.env` and run as `ubuntu`; the live app process has `BK_RUNTIME_DIR`. `locks/` does not exist yet
  — `process_lock` creates it (`mkdir(parents=True)`), so both jobs resolve the same path.
- **Cadence:** `OnCalendar=*-*-* 00/4:45:00` (00:45, 04:45, 08:45, 12:45, 16:45, 20:45 UTC) — ≤ 4h + run time, ~2h
  headroom under 6h, clear of bk-daily 13:00Z; 18 credits/day. Install steps in the unit header. **Not installed.**
- **Gate (builder):** 32 QCs, worktree + clean export, 0 network attempts, all rc 0 except `qc_quick_tools`
  (`/tools/real-vs-luck` MLB data absent locally) — coordinator confirmed it fails identically at `f06e568`; D1 275/275;
  D1 files identical to `6bdb73f`; clean tree. **Coordinator re-run (rc 0, 0 network):** `qc_nba_lines_lock` 34/34,
  `qc_nba_no_game_governance` 36/36, `qc_nba_wnba_props_stale` 34/34, `qc_nba_market_only`,
  `qc_game_lines_event_slate` 59/59, `qc_odds_age_timezone` 19/19, `qc_run_outcomes`, D1 275/275; compile 0.
- **Builder choices to review:** NBA lines step timeout 180→240 s (lock wait); lock contention in bk-daily counts as a
  failure (props `SKIPPED_BLOCKED_BY_LINES`); the 4h unit does not mask 75/76; `archive_daily_candidates` archives only
  executable props; `APP_CACHE_VERSION` not bumped (the new token invalidates NBA/WNBA caches only); props with no
  readable timestamp or > 5 min future are withheld (fixtures moved to relative times).
- **Builder open items, coordinator disposition:** `/elite/alerts/export` "missing auth" — **not a defect**: it is in
  `SHARP_ENDPOINTS` (`app.py:946`) behind the central plan gate. Remaining untouched: sidebar raw row counts (no prices);
  player-link identity cached from a fresh feed stays linkable after staleness (destination shows withheld state).
  Reuse window 90 min / lock wait 120 s are engineering estimates.
- **Owner decisions on 2j (2026-11-04):** 240 s step timeout and 120 s lock wait accepted (receipt re-check after
  wait/acquire); contention in bk-daily → `REUSED_FRESH_AFTER_LOCK` only for a newly published, hash-valid file inside
  the 90-min **duplicate-suppression** window (not a freshness boundary — executable boundary stays 6h), else explicit
  failure/degraded, never `OK`; 5-min future tolerance accepted as a labelled clock-skew allowance; timer moved to
  `:15` past every 4th UTC hour (12:15 run leaves 45 min before bk-daily). **Timer-enablement blocker:** the 4h timer
  cannot be enabled until an independent, legally approved schedule source or another reviewed no-game contract
  exists — never a fabricated `NO_GAMES_SCHEDULED`. NBA v4 required before any NBA Linux gate (lock re-check, path
  containment / no symlink escape / 0700 dir + 0600 file, no paid request before ownership, crash release; every
  stale route fixtured; `qc_quick_tools` self-contained, no MLB-data waiver). **The central stale gate is not to be
  deployed while props availability is unresolved without presenting that product impact for approval.**
- **NBA/WNBA props cadence — production evidence (SSM `L`, 2026-11-04 ~01:50Z, read-only):** NBA props are fetched
  only inside `bk-daily` 13:00Z (`player_props` step, after lines); no props timer exists (`bk-linemove` = MLB/WNBA
  lines only). Window = next 5 days. Cost per refresh (`x-requests-last`): 11-02 15 events → **74**; 11-01 4 → **22**;
  10-31 7 → **32**; 10-30 10 → **57**; 10-28 1 → **16**; 10-27 1 → **16** (≈ 4–5 credits/event + a small fixed part);
  11-03 and 10-29: not run (blocked by lines). Current `NBA_Props.csv`: 1,727 rows, 15 events, markets
  3PM/AST/BLK/PTS/REB/STL, 3 books, `LastUpdated` max 2026-11-02 13:05 (file mode 0600). `WNBA_Props.csv`: 72 rows, 1
  event, 2026-10-31 (off-season). Projection at the observed 16–74/refresh: 4-hourly ≈ 6 × ~45 ≈ 270/day ≈ **8k/month**
  (~8% of the 100k plan, on top of ~15–22k current); restricting intra-day refreshes to the current Eastern slate
  (instead of 5 days) should cut that roughly by the share of events beyond today (code-side confirmation pending from
  v4). No-game day: the props step is skipped when lines report no events; cost then 0 (provider `/events` is free).
- **Blast radius to note for review:** the central gate changes what `/`, `/dashboard`, `/free`, `/home/*`, `/elite`,
  `/derivatives` and the player/tool pages show whenever the NBA/WNBA props file is > 6h old — with today's once-daily
  refresh that is most of the day until the 4h cadence (which covers lines, not props) and a props cadence exist.

## 3. Read-only audits (code at exact `a5de400`)

### NFL props cadence and quota
- Cost per run = markets **returned** × regions per event (books don't multiply); `/events` is free; NFL ≤12 per event,
  NCAAF ≤8. Observed NFL 26–141/day; ~600/week now. `odds_credit_cost` uses markets *requested* (upper bound).
  No per-run budget cap (`refresh_football_props.py` passes no `--expected-cost`).
- One 13:00 UTC pull cannot keep kickoffs after ~2pm ET inside the 6h executable window (Sun late, SNF, MNF, TNF all
  arrive 8–12h stale ⇒ fail closed).
- Inferred plan 100k (truth-model doc 10-23); remaining 98,571; **reset date unknown** (prod
  `odds_quota_ledger.jsonl` would settle it).
- Biggest unbounded spender is **live scores** (`refresh_live_scores.py`, ~60s in game windows while a user is
  active, ~2 credits/sport/call, upper bound ~40k/month) — **not written to the quota ledger**.
- Failure behaviour gaps: events-call 401/429 crashes before any receipt and the parent may read the previous run's
  shape receipt (mislabel risk); per-event errors fan out to 13 requests with no 429 latch/backoff; any provider
  error rejects the whole paid pull.
- **Recommendation (proposal only):** Option A — extra NFL-only full pulls Thu 21:00, Sun 17:00 + 21:00, Mon 21:00 UTC
  (+Sat from mid-Dec): ≈+350 credits/week, no code change. Owner decisions: live-scores budget, books-pulled-props
  (EVENT_VANISHED) policy as pull frequency rises, 429 latch, measure CFB first-half cost.

### D4 — Green Light admits started/live legs (P0)
- Green Light's ticket is `build_daily_cards` (`app.py:33288`) via `/tools/green-light/ticket` (`:45399`); NFL prop
  legs come from `build_nfl_floor_board` (`:31193`), which aggregates by (Player, stat) and **drops `EventId`,
  `EventCommenceAtUTC`, `Book`, `SourceUpdatedAtUTC`**.
- **No kickoff gate anywhere on the path**; timeframe filters compare Eastern dates only; the a5de400 started-event
  filter applies at fetch time and props refresh once a day; `_NFL_FLOOR_BOARD_CACHE` + 24h disk pkl are keyed on file
  mtimes with no clock component; leg identity is the `Game` string; `_distinct` backfills and the client Reroll
  auto-substitutes from a `bench` with no kickoff state.
- Class: missing gate + display-cache staleness. **No branch fixes it** — the Integrity contract has no kickoff check
  and its freshness reads `LastUpdated`, so an 08:00 quote is "fresh" past a 13:00 kickoff.
- Blast radius: Daily Card, King's Tickets, Menu, Daily-Card image, Featured Parlay. SGP Workbench separate (not traced).
- Correction (own branch, built on the Integrity contract): carry `event_id` + `kickoff_utc` onto legs (bump cache
  namespace), request-time `_leg_started(leg, now_utc)` after the cache on cards, menu and bench (no kickoff ⇒ context
  only), freeze-not-replace in the editor, a `STARTED` reason code in `_leg_quote_failures`. QC: new
  `qc_ticket_kickoff_gate.py` with a frozen clock (now−1s excluded, now+1s eligible, cached build after kickoff,
  never substituted) + extend `qc_green_light_workspace.py`.

### D5 — payouts without complete executable provenance (P0)
- `_card_price` (`app.py:33038`) multiplies whatever price the leg holds: NFL prop **median across books** (no book,
  no time), MLB `_mlb_hit_price` estimate table, NFL/CFB team lines hard-coded `-110`; the template discloses "no
  book or capture time" and shows payouts anyway.
- **Already fixed in the Integrity group** (`4e8b380`/`f642091`/`0f76289`): Green Light consumes the same builder and
  editor, so it inherits the executable-leg contract unchanged (no payout unless every leg is executable; -110 and
  MLB estimates removed). Gaps that remain: no kickoff (D4); quote identity = `Game` string not `EventId`; freshness
  on `LastUpdated` not `SourceUpdatedAtUTC`; Green Light has no empty state that lists `context_lines` (inferred).
- QC: extend `qc_unpriced_line_legs.py` / `qc_ticket_editor_shared.py` to hit `/tools/green-light/ticket`.

### D1 — false NE–MIA "indoor/calm" weather (P0)
- Venue table (`services/nfl_stadiums.py`) is **correct** for all 32 teams (MIA outdoor). NE @ MIA (home MIA) joins
  correctly. Root cause: **missing weather renders as a fact** — `templates/nfl_dashboard.html:132`
  `{% else %}— indoor/calm` and `templates/nfl_totals_today.html:85` `{% else %}dome` whenever wind is None.
- Why wind is None: `fetch_nfl_weather.py` is licence-gated (`BK_WEATHER_SOURCE_LICENSED`, default off since
  `e81c163` 2026-10-16) and leaves the old file untouched ⇒ every open-air game (22 venues) reads indoor/calm or dome;
  `/sports/ncaaf` reuses the template with no CFB wind source ⇒ every college game reads "indoor/calm".
- Second defect: three home-team-only joins with no date (`app.py:34124`, `47678`, `47771`) can pin a weeks-old
  forecast to the wrong game, and `wind_home.get(h, 0)` turns missing into 0 mph. Fetcher uses `datetime.now()`.
- **No branch fixes it.** Correction (`fix/nfl-weather-unavailable-not-dome`): render "unavailable"; roof only from a
  positive venue lookup, separate field; `(date, home)` joins, no 0 default; apply the licence gate on read; CFB
  unavailable; purge `data/cache/*nfl_dashboard*` + restart on deploy. QC: new `qc_nfl_weather_venue_integrity.py`
  (32-team roof truth table; wind=None never renders dome/indoor/calm; date-mismatched row never attaches; gate off ⇒
  no wind value; NCAAF slate renders unavailable), registered in `run_all_scorecards.py`.
- Not verified on prod: the actual prod `NFL_GameWeather.csv` contents and flag value (inferred from code + local copy).

## 4. Integrity group rebuilt on exact `a5de400` — offline gate PASS (held; no Linux gate)

- **Branch:** `integration/integrity-group-a5de400` @ **`672480d1579c1f93ea569eba238d3f390741bad5`** (pushed as a
  branch; never merged). The original `integration/integrity-group` @ `1482d65` is untouched.
- **Method:** replayed the same four merges in the same order on `a5de400` — F1 `3564dc7` → QC fixtures
  `ac55194` → Daily-Card `0f76289` → F7 `4d7a60f`.
  - The one conflict (`app.py`, `build_football_live_games`) was resolved by taking `1482d65`'s approved file
    (no substituted bookmaker; `or 'DraftKings'` scan: 0 hits).
  - The approved merge-time edit "empty `KNOWN_PENDING`" was carried over from `1482d65` (`qc_unpriced_line_legs.py`).
- **Invariant:** `git diff 1482d65 672480d` is **byte-identical** to `git diff 63060a9 a5de400`. The new tree is
  exactly the approved group plus the accepted slate-turnover change, with no file overlap.
- **Diff over `a5de400`:** 50 files, +2,972/−269 (unchanged from the original group). Files (name-status):
  M	app.py; M	diag_refresh_incident.py; A	docs/f7_cutover_runbook.md; M	fetch_cfb_weather.py; M	fetch_ncaaf_slate_cfbd.py; M	grade_signals.py; M	qc_decision_journal.py; M	qc_entity_nba_wnba_market.py; M	qc_game_lines_freshness.py; M	qc_kings_tickets_drafts.py; M	qc_lens_attribution.py; M	qc_lookup_change_store.py; M	qc_lookup_change_views.py; M	qc_model_observations.py; M	qc_nba_gated_market_facts.py; M	qc_nba_market_only.py; A	qc_ncaaf_odds_single_writer.py; M	qc_nfl_capture_precision.py; M	qc_nfl_heatmap_freshness.py; M	qc_nfl_hot_hand_boundary.py; M	qc_nfl_props_source_fields.py; M	qc_nfl_props_source_time.py; M	qc_odds_feed.py; M	qc_odds_recovery_preflight.py; A	qc_offline.py; M	qc_player_check.py; A	qc_route_qc_harness.py; M	qc_season_markets.py; M	qc_sgp_workbench.py; M	qc_slate_validation.py; M	qc_streak_integrity_hothand.py; M	qc_ticket_editor_shared.py; A	qc_unpriced_line_legs.py; M	qc_wnba_readiness.py; M	qc_wnba_visual_trust.py; A	services/fabricated_price_scan.py; M	services/qc_auth.py; A	services/qc_no_network.py; A	services/qc_offline_site/sitecustomize.py; M	templates/_ticket_editor.html; A	templates/_unpriced_context_lines.html; M	templates/cfb_best_spots.html; M	templates/cfb_matchup.html; M	templates/cfb_totals.html; M	templates/daily_cards.html; M	templates/kings_tickets.html; M	templates/menu_board.html; M	templates/signal_report.html; M	templates/wnba_dashboard.html; M	templates/wnba_matchup.html
- **Offline gate** (Windows, `qc_offline.py`, `SECRET_KEY=qc-gate`, run in the rebuilt worktree):
  - `py_compile app.py grade_signals.py fetch_player_props.py services/feed_validation.py`: OK.
  - **34/34 QCs exit 0:** the 33 of the original plan plus `qc_props_slate_turnover` (77/77). Notable counts:
    `unpriced_line_legs` 172/172, `route_qc_harness` 8/8, `ncaaf_odds_single_writer` 65/0,
    `nfl_roster_single_writer` 36/0, `nfl_props_source_time` 14/0, `decision_journal` 18/18,
    `lookup_change_store` 11/11.
  - Lines containing "FAIL" or "NetworkBlocked" were all `Failures: 0` or passing network-block assertions.
  - WARN-only notes: gated NBA.com routes; thin WNBA off-season data.
  - `qc_odds_feed`: **refused, exit 3** (`NOT RUN: … REQUIRES_NETWORK`).
  - Tracked tree clean before and after (`git status --porcelain` = 0).
- **No-network guarantee (precise):** `qc_offline.py` blocks Python socket networking in the QC process and in
  Python children it starts. It does not cover non-Python subprocesses.
- **No master or production change:** `origin/master` is still `a5de400`; no SSM write, deploy, restart, purge or
  flag change.
- **Held:** no Linux gate and no merge until **D4 is corrected** (§3 D4, ledger 1.5u). Fixing payout provenance while
  started legs can still be proposed would leave a P0 trust failure in the same ticket workflow.
