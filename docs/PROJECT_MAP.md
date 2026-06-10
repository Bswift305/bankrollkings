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

---

## 2. Deploy to production

No CI/CD. Manual:

```bash
git push origin master
ssh -i ~/.ssh/bankroll-key.pem ubuntu@32.195.123.245
cd /opt/bankrollkings && git pull origin master
sudo systemctl restart bankrollkings        # NOT reload
```

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
  probabilities, not fantasy production.) Lineups persist to `data/tracking/Fantasy_Lineups.csv`
  (per-user, 8 slots, 50-lineup cap, owner-checked delete; POST endpoints CSRF-protected).
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
  magenta), gated like every other sport (Pro / sport pass / owner). All share
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

---

## 7. Timezone

Game commence times come from providers in UTC. Convert to **fixed US/Eastern** via
`services/timeutils.py` (`to_eastern_datetime_str` / `to_eastern_date_str`) — NOT a bare
`.astimezone()` (that uses the process's ambient zone and lands games on the wrong day).

---

## 8. Open items / not-built-yet

- Parlay floor-reliability for football: the pipeline is fully multi-sport
  (`build_floor_play_index.py` merges all five sports' AllPropResults; buckets group by Sport;
  saved tickets carry a `Sport` column — legacy rows default NBA), but NFL/CFB have no logged
  floor-play history yet, so their tiers rank on confidence/build score until football season
  generates resolved floor plays. Nothing to build — it fills in automatically.
- College hoops (ncaamb/ncaawb): real live data. The Command Center hub and the themed
  pre-season shells for Props/Market/Trends/Parlay are all built (see §4); what remains is
  wiring actual college data/boards when the season tips off.
- **NFL Fantasy build plan (for season approach — agreed 2026-06-10).** Build order:
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
