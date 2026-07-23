# Bankroll Kings — Project Map

> Living source-of-truth for how this project is wired. Read this first; update it
> as things change. Goal: stop re-deriving the same facts every session.

---

## 1. Two environments — DO NOT confuse them

| | **Local dev** | **Production (the live site)** |
|---|---|---|
| URL | `http://localhost:5000` | `https://bankrollkings.com` |
| Host | this Windows box (`C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls`) | AWS EC2, `32.195.123.245`, user `ubuntu`, dir `/opt/bankrollkings` |
| Server | Flask dev (`start_server.ps1` → `.runtime/run_bankroll_flask_5000.py`) | gunicorn (`preload_app=True`) behind nginx, systemd unit `bankrollkings` |
| Data | its OWN data, refreshed by **Windows Scheduled Tasks** | its OWN data, refreshed by **systemd timers** |

**Critical:** local and prod are SEPARATE machines with SEPARATE data. Editing files
locally and restarting `:5000` does **nothing** to the live site. The user looks at
**bankrollkings.com** — always confirm which one you're debugging. (Prop counts moving
on prod = prod's own refresh jobs, not your local edits.)

Also note: `:8080` on the local box is **EnterpriseDB Postgres PEM** (a DB console),
unrelated to this app.

### The prod box — fixed size, does NOT auto-scale (2026-07-22)

`i-08d2fd818875381dd`, **t3.medium** (2 vCPU, **4 GB RAM**), us-east-1. This is a
fixed instance — nothing about it grows on its own. RAM and disk stay put until
someone deliberately resizes (a stop/start for the instance type; an online EBS
grow for disk). "It scales up when I need it" is not true here — that's for
managed services, not a plain EC2 box.

- **RAM is the real ceiling and it is tight.** Two gunicorn workers idle at
  ~2.35 GB, leaving ~1.2 GB. **`earlyoom` is active and SIGTERMs any process when
  available memory drops below 12%.** That is not a bug — it is the same reaper
  from the Jul 1-4 outage, still armed. A heavy batch job (~850 MB) run alongside
  live traffic tips it over. Symptom: a process dies with **exit 143** and no
  output. If a job "fails with no output", suspect earlyoom before a code bug:
  `sudo journalctl -u <unit> --since -10min | grep -i sigterm`. The fix for a
  heavy job is to split it into per-section subprocesses (see prelaunch scorecard
  in §6), not to touch earlyoom.
- **Disk is NOT a concern.** Two volumes: root `/` is a 7 GB OS disk at ~82%
  (system packages/logs, basically static), but **all app data lives on a SEPARATE
  50 GB volume mounted at `/opt/bankrollkings`, only ~3% used.** The archive
  growing to 226k rows is on the 50 GB volume — years of runway. Do not measure
  data growth with `df /`; use `df /opt/bankrollkings`.
- **Speed:** warm responses are ~5-10 ms; the box is CPU-idle and swap is parked
  (not thrashing). The only slow path is the ~8 s cold-cache rebuild on the first
  request after idle — a prewarm concern, NOT a RAM/CPU one. A bigger instance
  would buy headroom for launch traffic, not speed.

---

## 2. Deploy to production

**Deploy = `git push origin master`. That is the whole procedure.**

The server polls for you: `bk-deploy.timer` runs `/usr/local/bin/bk-auto-deploy.sh`
every 2 minutes, which fetches `origin/master` and — only when it has moved —
does `git pull --ff-only` + `systemctl restart bankrollkings`, then probes the app
to confirm it came back up. Nothing happens on a tick with no new commits.

Watch a deploy land:
```bash
journalctl -u bk-deploy.service -n 20 --no-pager     # or -f to follow
```

Why this exists: SSH is IP-allowlisted in the security group, and a churning
egress IP (hotel wifi / cellular) silently blocks port 22 — which repeatedly
stranded pushed commits undeployed. Pulling instead of pushing removes SSH from
the deploy path entirely.

The script lives at `/usr/local/bin/bk-auto-deploy.sh`, deliberately **outside**
the repo (bash reads scripts incrementally, so a pull rewriting the running
script could splice old and new lines). Version-controlled reference copy plus
the unit files are in `ops/`; after editing, reinstall with:
```bash
sudo install -m 755 ops/bk-auto-deploy.sh /usr/local/bin/bk-auto-deploy.sh
```

Manual deploy (only needed if the timer is stopped, or to skip the ≤2min wait):

```bash
git push origin master
ssh -i ~/.ssh/bankroll-key.pem ubuntu@32.195.123.245
cd /opt/bankrollkings && git pull origin master
sudo systemctl restart bankrollkings        # NOT reload
```

A failed tick (network blip, diverged tree) exits non-zero and leaves the service
running on the old commit — it never half-deploys, and the timer retries on the
next tick rather than disabling itself.

**LESSON (cost us hours):** gunicorn runs with `preload_app=True`, so `systemctl reload`
(a HUP) does **NOT** reliably pick up `app.py` **or** template changes — new workers fork
from the master, inheriting its loaded code and its cached Jinja templates (auto_reload is
off in prod). **Use `restart` for any `app.py` OR template change.** Only true static assets
(CSS / JS / SVG / PNG, served from disk) are fresh without a restart — bust the *browser*
cache for those with `?v=...` and/or a service-worker version bump.

`sudo -n` works on the server (NOPASSWD), so deploys are scriptable from here over SSH.

---

## 3. Caching layers (a frequent source of "I changed it but nothing happened")

1. **`DATAFRAME_CACHE`** — per-process, keyed by file mtime. Re-parses a CSV when it changes.
2. **`RUNTIME_TTL_CACHE`** + **disk pkl cache** (`data/cache/*.pkl`) — `_get_ttl_cached_value` /
   `_get_disk_ttl_cached_value`, keyed by a `_build_file_token(...)` **version**. If a cached
   builder reads a file NOT in its version token, it serves stale. (Bug we fixed:
   `build_cross_sport_dashboard_snapshots` didn't version on `Live_Scores.csv`, so live badges
   froze. Always include every input file in the version token.)
   **Stampede-protected (2026-06-10):** cold/expired keys are rebuilt under a per-key build
   lock; concurrent requests get the stale memory/disk value (or wait if there's none) instead
   of every thread running the expensive builder at once. (Before this, a cold dashboard build
   could freeze the whole process for minutes — N threads all parsing gamelog CSVs.)

   **⚠ A CODE-ONLY CHANGE TO A CACHED BUILDER IS INVISIBLE (2026-07-19).** The version token
   covers *data files*, not source. Edit board logic, leave the CSVs alone, and the builder
   keeps serving the pre-edit rows for the full 12h TTL — the change looks broken when it is
   actually fine. This cost three rounds of debugging on the `LONGSHOT OVER` guardrail: the
   code was correct the whole time. **When verifying a change to `build_*_prop_board` /
   `build_*_method_board`, first `rm -f data/cache/*<sport>_prop_board*` (and on prod, restart
   after), or pass a fresh `cache_namespace=`.** Same applies after deploying such a change:
   clear the prod cache or users see the old board until the TTL expires.
3. **Service worker** (`static/service-worker.js`) — caches `/static/css/`, `/static/logos/`,
   brand assets. Self-updating now (bumps `BK_CACHE` shell-vN, `controllerchange` auto-reload).
   Bump the version on shell-asset changes.
4. **HTTP cache** — Flask static `max-age`. Bust with `?v=...` query on the asset URL.
5. **CSS** — `bk_base.html` loads `bk-theme.css?v=YYYYMMDD-...`; bump that string on CSS edits.

---

## 4. Navigation & routes (what links go where)

- **Sidebar** (`.bk-sidebar` in `bk_base.html`, overridden by `dashboard_overview.html` on Home):
  icons via `sidebar_icon_url(key)`.
- **Icon rail** (`.bk-rail`): narrow strip, hardcoded `/static/logos/leagues/*.svg`.
- **Sport pages:** `/sports/nba|nfl|ncaaf|wnba|mlb` have explicit routes; everything else
  (incl. `ncaamb`, `ncaawb`) hits the catch-all `/sports/<league>` → `under_construction.html`.
- **Fantasy (MVP live):** sidebar "Fantasy / League" section (bk_base.html + the Home
  override in dashboard_overview.html) → `/fantasy/nfl|nba` → `fantasy_league.html`
  (login-required tabbed hub; `FANTASY_LAUNCH_PAGES` config; endpoints in PUBLIC_ENDPOINTS
  do their own auth). Tabs: Overview / Rankings & Projections / Lineup Builder / My Lineups /
  Bankroll. **Deliberately DISCONNECTED from the betting pages (user direction 2026-06-10):**
  fantasy templates blank the `workflow_toolbar` block (no Props/Market/Trends/Parlay command
  strip up top), page copy carries no prop-board references, and the betting Sport/League
  sidebar items don't highlight on fantasy pages (`active_page != 'fantasy'` guard on
  nba/nfl items) — keep it that way when adding fantasy features. NBA rankings are REAL and SIMULATION-DRIVEN: `get_fantasy_projection_rows`
  computes FP per logged game (DK incl. DD/TD bonuses / FanDuel / Yahoo via
  `FANTASY_SCORING_SYSTEMS`, `?scoring=` param), then Monte-Carlos 2,000 games per player by
  resampling whole real games recency-weighted (preserves stat correlation; seeded rng so
  ranks are stable). Proj = sim mean (ranking key), Ceiling/Floor = p90/p10, Boom/Bust% =
  share of sims ±20% vs proj. **Live injury context** (`_build_fantasy_context_maps`): the
  same boost/return-impact data as the NBA prop board shifts each player's draws (teammate
  out → up, star returning → down), with raw Boost_Pct heavily dampened (×0.05,
  sample-weighted, per-signal caps) — shown as a ±% chip by the player name. **Matchup
  layer**: opponent defense factors computed from the same logs (FP vs that team relative
  to each player's own average, ≥100 rows), applied (×0.5, ±6% cap) when the player's team
  is on the NBA odds board; the Opp column shows `OPP Soft/Neutral/Tough` live. All shifts
  combined clamp at ±15%. Disk-TTL cached per scoring style, versioned on the gamelog file,
  all five injury-context files, AND NBA_Odds.csv. NFL returns [] until season logs + a football FP formula exist. (This is separate
  from the props sim `simulate_active_sport_props.py`, which predicts prop-line hit
  probabilities, not fantasy production.) Rankings carry roster Position (filter chips G/F/C;
  combos like G-F match on contains) plus a "Show PBP + Tracking" toggle: USG%/TS%/AST%
  (play-by-play derived; source stores fractions, ×100 for display) and TCH/DRV/SPD/MILES
  (optical player tracking) from NBA_PlayerAdvanced/PlayerTracking/Rosters CSVs (all three in
  the cache version token). Lineups persist to `data/tracking/Fantasy_Lineups.csv` (per-user,
  league roster size 1–30 slots with starter-vs-bench roles — ProjectedTotal counts starters
  only; 50-lineup cap, owner-checked delete; POST endpoints CSRF-protected).
  NO salaries, NO contests (deliberate — money-league legal risk; see memory).

**Known nav behavior (NOT crashes — current product state):**
- **Parlay Builder is sport-aware.** `/parlay?sport=wnba|mlb|nfl|ncaaf` →
  `_render_sport_parlay`: loads that sport's own live prop board (same feed + builder as its
  props page via `_load_sport_parlay_board`), normalizes rows (sport/confidence/market_view +
  `setdefault(None)` for every key parlay_formula.html tests with `is not none` — Jinja
  Undefined passes that test then crashes on compare), and runs the SAME floor-parlay strategy
  pipeline as NBA (`attach_floor_reliability_to_props` degrades to SMALL SAMPLE for sports
  without floor history). NBA path (`build_live_prop_runtime_context`) is untouched.
  `sport=ncaamb|ncaawb` still short-circuits to the CBB-themed pre-season parlay shell.
  Football defaults to `date=all` (weekly slates); WNBA/MLB default `date=today`.
- **Props** with no sport → cross-sport "pick a sport" hub (`/tools/props` = `method_hub('props')`)
  or `/home/props` preview. By design ("Props is now a cross-sport entry point").
- **College hoops (ncaamb/ncaawb)** Command Center → `college_hoops_command_center.html`
  (rendered by a branch in `sport_under_construction`; that catch-all + `under_construction.html`
  now only matter for hypothetical future leagues). The command center is a real themed hub:
  hero, workflow lens, a **Board Surfaces grid linking the four themed pages below**, season
  modules, and model focus. METHOD_HUB_CONFIG college cards also link the themed boards now
  (no more "use the expansion board" copy).
  **The four main board surfaces have real CBB-themed pre-season pages** (men cyan / women
  magenta), gated like every other sport (All Access / owner). All share
  `_college_hoops_access_gate` and override `focus_mode_label`/`regular_mode_label` →
  `Top 25 Focus` / `Full Board` (with `postseason_only=False`) so they don't inherit the
  league-wide "NBA Finals" labels:
  - **Props** `/sports/{ncaamb,ncaawb}/props` → `_render_college_hoops_props` →
    `render_props_screener_page` with `_college_hoops_example_props` **example** rows.
  - **Market** `/sports/{ncaamb,ncaawb}/market-edge` → `_render_college_hoops_market` →
    `smart_picks_v2.html` (blank board, `market_sport_key` themes it).
  - **Trends** `/sports/{ncaamb,ncaawb}/trends` → `_render_college_hoops_trends` →
    `trend_board.html` (blank board, `trend_sport_key` themes it).
  - **Parlay** `/parlay?sport=ncaamb|ncaawb` → `parlay()` **short-circuits to**
    `_render_college_hoops_parlay` (blank `parlay_formula.html`) BEFORE the NBA runtime loads —
    so college Parlay no longer falls through to the NBA board.
  Real college boards/data are still NOT built — these are themed shells (example/blank "live
  board opens when the season tips off"). `smart_picks_v2.html` + `trend_board.html` had
  `active_sport` hardcoded to `nba`; now dynamic via `market_sport_key`/`trend_sport_key`
  (default `nba`, so NBA pages are unchanged).

---

## 5. Icon system

- **`sidebar_icon_url(key)`** (app.py) → premium nav badges, transparent circular PNGs in
  `static/logos/nav/` (`home.png`, `nba.png`, `men-hoops.png`, …; `?v=premium` cache-bust).
  Deliverable also has `static/logos/nav/png/<name>-64|128|256.png` + README.
  Registered as a Jinja global AND in the `inject_globals` context dicts
  (jinja_env.globals alone did NOT reach templates — 500'd; use the context dicts).
- **`sport_logo_url(key)`** → detailed board/matchup-header logos in `static/logos/leagues/official/*.png`.
  Sport-page header sits in `.command-center-hero-mark` (CSS), uniform **118px**.
- Source art for the premium set: generated concept sheets in `~/Downloads`, sliced with
  Pillow + scipy (`ndimage.label`) into transparent circles.

---

## 6. Data / refresh pipeline

- **Prod:** systemd timers on the EC2 box (`deploy/bk-live-scores.timer` etc.). `refresh_live_scores.py`
  polls every ~60s; it self-gates to game windows AND to **signed-in user activity** (heartbeat
  `data/live_scores/active_user_heartbeat.txt`, written by the web app) to save API spend, plus a
  one-time **catch-up poll** to finalize games that ended while idle. Stale 'live' rows are shown
  as "Final" (frozen score cleared).
- **Local:** Windows Scheduled Tasks ("Bankroll Kings - …"), batch files in `batch/`, registered by
  `install_task_schedules.ps1`. The path-with-spaces bug (unquoted `/TR` → `0x80070002`) is fixed.
  Live-scores task runs windowless via `run_live_scores_hidden.vbs`.
- **Daily operator** (`run_daily.py`): runs refreshes + Edge Engine (`run_bk_edge_engine_pipeline.py`)
  + scorecards (`run_all_scorecards.py`) + `generate_run_status.py` → `Run_Status.json`
  ("Daily Engine Health"). Use `--skip-refresh` to run just analysis+status on already-fresh data.

### ⚠ Football / CFB data flows on prod ONLY through run_daily steps (2026-07-19..22)

The football + CFB fetchers historically lived only in `batch/REFRESH_FOOTBALL_DATA.bat`,
which runs on the **Windows box, not the server**. Anything not explicitly added to
`run_daily.py` simply never runs on prod. That gap cost real time twice. Now wired
into `run_daily`'s always-on football steps:
- **Game lines** — `refresh_football_line_movement.py` (NFL + NCAAF, `fetch_*_game_lines`).
- **Player props** — `refresh_football_props.py` (NFL + NCAAF, `--days 7`). Self-gating:
  in the offseason the shared fetcher lists events, finds none in 7 days, and no-ops in
  ~1 s with no quota spent; it starts pulling real props automatically once games come
  within a week. Skips cleanly without `ODDS_API_KEY`.
- **CFB roster/stats/portal/master** — `refresh_cfb_data.py` (derives season years,
  self-skips without `CFBD_API_KEY`).
When adding any new sport's feed, the rule is: **add it to `run_daily.py` or it will
not run on prod** — the batch file is dev-only.

### Prelaunch scorecard runs each section in its own process (2026-07-22)

`run_prelaunch_scorecard.py` builds its 12 sections via `--section <key>` subprocesses,
not in one interpreter. In one process it peaked ~850 MB and earlyoom (§1) killed it
before it printed a line — `run_all_scorecards` then read "no output" as FAIL, so
prelaunch verification was silently dead while the code was fine. Per-section processes
cap peak memory. A section that cannot run yields an **incomplete** report (never
zero-filled — zeros would read as a pass) and surfaces as a "Scorecard Completeness"
FAIL naming what did not run.

---

## 6b. Adding a sport — start at the registry (2026-07-19)

**`sport_registry.py`** declares every sport's parts: props/gamelog/schedule/odds loaders, the
loader **grading** uses, stat-column map, archive gates, QC prefix, calibrator. Data only, no
`app` import, so `app.py` imports it without a cycle. **`qc_sport_registry.py` runs first in
`run_all_scorecards.py` and FAILS when a sport is missing a part.**

Two fields carry what a grep cannot:
- **`identity_ok`** — NBA/WNBA legitimately need no stat map (their prop stats already ARE their
  gamelog column names). `stat_column_map=None` with `identity_ok=False` is a **failure**.
- **`requires_play_verdict`** — MLB/WNBA gate archiving on `play_verdict=='PLAY'`; football does
  not. A verdict that can never be `PLAY` silently zeroes out archiving.

Irregularities it records: **NBA uses unprefixed loaders** (`load_props`, `load_schedule`,
`load_gamelogs`, `load_game_market_odds`); **NBA grading uses `load_nba_review_gamelogs`**
(includes playoffs) not `load_gamelogs` (regular season only); **NCAAF's QC/calibrator use the
`cfb` prefix**, so grepping "ncaaf" misses them.

Why it exists: two season-costing bugs were both "this sport is missing a part the others have" —
football had no stat map so nothing graded, and MLB's lineup gate could never be satisfied so
nothing archived. Neither showed up in the UI.

**Soccer will need more than a registry entry** — the archivers and graders assume OVER/UNDER,
and 3-way/draw markets break that assumption.

### Candidate archive columns (what a pick records)

Beyond the pick itself, rows now persist the drivers, so model quality is measurable after the
fact rather than inferred from source:
`ModelProb` `SimProb` `MarketProb` `LeanGap` `PlayVerdict` `LineupStatus`
`PatternHits` `PatternWindow` `StreakLen` `ConsistencyIndex` `Follow3Rate` `Follow5Rate`
`Follow3Chances` `Follow5Chances` `ActiveStreaks` `AvgGap` `MarketRate` `TrendScore`
`FloorHitRate` `ConsistencyLabel` `LongestRun`

**`load_candidate_archive()` ends in `return df[default_columns]`** — a column missing from that
list is silently dropped on read even after it is written. Add there too.

---

## 7. Timezone

Game commence times come from providers in UTC. Convert to **fixed US/Eastern** via
`services/timeutils.py` (`to_eastern_datetime_str` / `to_eastern_date_str`) — NOT a bare
`.astimezone()` (that uses the process's ambient zone and lands games on the wrong day).

**"Today" must also be Eastern (2026-07-23).** `sports_today_ts()` / `sports_today_date()`
anchor the date-filter's notion of "today" to **America/New_York**, not `datetime.now()`.
Board game dates are Eastern calendar dates, so on the **UTC prod server** a plain
`datetime.now()` rolls to the next day at 8pm ET / 00:00 UTC while that evening's slate is
still "today" in Eastern — so `date_filter='today'` matched **zero** games every
evening/overnight. That silently emptied the live board AND starved curated archiving
(`archive_daily_candidates` builds with `date_filter='today'` and runs hourly through
02:00 UTC), which is why MLB's curated track record flatlined. **A US-timezone dev box
agrees with Eastern and never reproduces this — it is prod-only.** Any new "today"/"is this
game today" logic must anchor to Eastern, never `datetime.now()`.

---

## 7b. Betting guardrails — what the graded record actually supports (2026-07-19)

Backtested on **171,476 graded MLB + WNBA props** at real lines and real prices. Full study and
method caveats in memory: `project_market_efficiency_findings`.

**Every predictive factor tested is already in the price.** Streak depth, opponent defence,
venue, rest, line movement and expected plate appearances all move the hit rate hard — and the
market's implied probability moves with them, leaving the edge flat at roughly the vig. Streaks
are REAL (NBA streak≥3 continues +15.1 points above base over 122,888 obs, rolling line, no
lookahead); the market simply knows. **Do not sell streak depth as an edge.**

What survives, and what is now enforced in code:
1. **`LONGSHOT OVER` guardrail** (`build_mlb_prop_board`) — overs under 25% implied. OVER ROI by
   implied band is monotonic: `<15% → -40.9%`, `15-25% → -20.4%`, `70%+ → -6.5%`. The *edge* is
   near-constant (-2.6 to -4.8) in every band; what changes is what a miss costs at long odds.
2. **All-over parlay warning** (`analyze_saved_parlay`) — all-over tickets returned **-22% (2
   legs) to -61% (5 legs) out-of-sample**, loss scaling with leg count. Warning only, not a grade
   penalty: the evidence is MLB/WNBA and the builder is NBA-centric.
3. **`SINGLE BOOK` → CONFLICTED** — already existed and is correct. Across the full prop
   population, 1 book returns -15.2% vs -3.9% at 5 books.
4. **Prefer UNDER** — -0.6% vs -6.3% on identical streak logic.

Deliberately NOT built: the same longshot guardrail on WNBA (verified inert — 2 of 5,773 graded
WNBA overs fall under 25% implied, because WNBA offers no rare-event markets). Football is the
real target for it (Anytime TD), but `build_football_live_prop_board` has no verdict/guardrail
fields yet and props are 0 rows until the season starts.

**Method rule learned the hard way: out-of-sample or it does not count.** Four streak-parlay
rules looked bulletproof in-sample (lower CI bounds +8.3 to +17.8) and every one reversed to
significantly negative out-of-sample. A 3-leg parlay showed +63% ROI at n=21 and -29% at n=2,861.

---

## 8. Open items / not-built-yet

- **NFL/CFB betting — pipeline-complete, waiting on the season (2026-07-22).** Grading
  (football stat map), archiving (dry-run 24/24), game lines and player props (§6) are all
  wired and self-gating on prod. The only wait is external: the Odds API posts NFL player
  props ~early Aug (preseason) → early Sep (Week 1). Two things to FINISH once props flow
  (cannot verify against an empty feed): (1) a **`LONGSHOT OVER` guardrail for football** —
  `build_football_live_prop_board` has no verdict/guardrail fields yet, and Anytime TD
  (+300..+900) is where the rule earns its keep; (2) confirm **`NFL_FeaturedResults.csv`**
  archiving populates when real games resolve (the 99 scorecard flags it missing off-season).
- Parlay floor-reliability for football: the pipeline is fully multi-sport
  (`build_floor_play_index.py` merges all five sports' AllPropResults; buckets group by Sport;
  saved tickets carry a `Sport` column — legacy rows default NBA), but NFL/CFB have no logged
  floor-play history yet, so their tiers rank on confidence/build score until football season
  generates resolved floor plays. Nothing to build — it fills in automatically.
- College hoops (ncaamb/ncaawb): real live data. The Command Center hub and the themed
  pre-season shells for Props/Market/Trends/Parlay are all built (see §4); what remains is
  wiring actual college data/boards when the season tips off.
- **NFL Fantasy — LIVE (2026-07-17).** Real PPR/Half-PPR/Standard rankings now render.
  `FOOTBALL_SCORING_SYSTEMS` + `_fantasy_points_nfl` + a sport-aware
  `_build_fantasy_projection_rows`/`get_fantasy_projection_rows`/`fantasy_league`
  route + sport-aware `fantasy_league.html` (QB/RB/WR/TE chips, no NBA
  minutes/PBP/tracking on football). Data: `build_nfl_gamelogs.py` builds
  `data/gamelogs/NFL_GameLogs.csv` from `data/historical/NFL_PlayerStats_<yr>.csv`
  (last 3 seasons; normalizes the 2025 extract's abbreviated names back to full via
  team; resolves position), wired into `run_daily.py` `_active_refresh_steps`.
  Preseason baseline = last seasons; recency weighting converges as 2026 games land.
  **STILL OPEN:** the SOURCE `NFL_PlayerStats_<yr>.csv` is built LOCALLY (from pbp)
  and is gitignored — I one-time scp'd 2023-25 to prod. For IN-SEASON freshness,
  a current-season `NFL_PlayerStats_2026.csv` must flow to prod (wire
  `build_nfl_player_stats_from_pbp.py` for the current season into the prod
  football refresh) so the daily gamelog rebuild has fresh input; today it's static
  off 2023-25. Calibration benchmark vs FantasyPros (old step 4) still not built.
- **(historical) NFL Fantasy build plan (for season approach — agreed 2026-06-10).** Build order:
  1. Scoring formats: add PPR / Half-PPR / Standard to `FANTASY_SCORING_SYSTEMS` (season-long
     NFL equivalent of the DK/FD/Yahoo switcher; same pattern, football weights).
  2. Football FP formula in `_build_fantasy_projection_rows` once `NFL_GameLogs.csv` has
     passing/rushing/receiving columns — the NFL hub's rankings light up automatically.
  3. **Preseason mode** (key structural difference per industry research): can't recency-weight
     a season that hasn't started, so at launch baseline = LAST season's logs adjusted by macro
     Vegas signals we already pull (team win totals / game totals from the odds feed). The
     existing exponential recency weighting then converges to the mid-season model naturally
     as current-season games accumulate. Injury + matchup layers already work unchanged.
  4. Calibration benchmark: compare weekly output vs FantasyPros consensus; publish accuracy,
     surface disagreements as edge content ("our sim likes X 15% over consensus, here's why").
  Positioning notes: our differentiators vs ESPN/Yahoo/Sleeper = distributions not point
  estimates (Proj/Ceiling/Floor/Boom%), and market-informed projections (live odds context).
  Our reactive/upside profile ≈ Sleeper, not ESPN's regress-to-mean.
- Fantasy SOON columns (Salary / Value / Own%) need a DFS slate provider decision
  (SportsDataIO / FantasyData are the clean paid options) — USER decision, then wiring.
- Premium icons are PNG (raster, from generated art) — not vectorizable to SVG without a redraw.

## Membership & pricing (single-plan era, 2026-06-12)

**One paid plan: `all_access` — $19.99/mo, monthly only. No tiers.** `free` is the
unpaid account state (preview surfaces). The old multi-tier system (pro/sharp/elite +
six sport passes) is GONE; `LEGACY_PAID_PLAN_KEYS` in app.py maps any old plan key still
on a user row or in an old link to `all_access` (`normalize_plan_key`/`normalize_user_plan`).
Gating is now binary: `get_required_plan_for_endpoint` returns `free` or `all_access`;
PRO_ENDPOINTS/SHARP_ENDPOINTS sets both just mean "paid". Owners/admins bypass as before;
comp list renamed `COMP_ALL_ACCESS_EMAILS`.

**Founders promo:** first **100 paying subscribers** get **$10/mo for their first 12
months** (then standard $19.99). Flow: `/checkout/start` reserves a slot
(`FounderOffer=1` while `founder_slots_remaining()>0`) → activation (webhook/success/demo)
converts it to `IsFounder=1` + `FounderActivatedAt` inside `update_user_membership` (the
single chokepoint); cancel/abandon releases the reservation. Slots are never recycled
(founders keep theirs even if they later cancel). Pricing/signup pages show live
remaining-slot counts. `FOUNDER_PROMO` constant holds slots/price/duration.

**Stripe env (old STRIPE_PRO_*/passes keys are dead):**
- `STRIPE_ALL_ACCESS_MONTHLY_URL` — payment link for the $19.99/mo price.
- `STRIPE_ALL_ACCESS_FOUNDER_MONTHLY_URL` — payment link for the SAME price with a
  $9.99-off ×12-months coupon attached; set `max_redemptions=100` on the coupon in Stripe
  as the hard backstop against concurrent-checkout overshoot.
Neither set → demo checkout (auto-activates, founder logic still works). Users CSV gained
`IsFounder`/`FounderOffer`/`FounderActivatedAt` columns (flag columns are normalized from
pandas' `'1.0'` float round-trip in `load_users`). QC: `qc_membership_regression.py`
(checkout/founder flow) and `qc_plan_access_matrix.py` (free vs all_access vs legacy keys).
