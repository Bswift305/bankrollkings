# Bankroll Kings — Developer Handoff

Last updated: `2026-06-03`

---

## 1. What This Product Is

Bankroll Kings is a Flask sports-betting analytics platform. It is not a sportsbook and does not accept wagers or custody funds.

**Core pipeline — keep this in mind when touching any page:**

```
game context → market context → prop context → confidence / risk label
```

The app should feel like a betting intelligence terminal, not a picks page. Props carry market pricing, game environment, injury/officiating context, calibration history, and risk warnings. A prop row that loses that context is a regression, not a simplification.

**Active sports coverage:**

| Sport | Status |
| --- | --- |
| NBA | Full — flagship sport |
| MLB | Full |
| WNBA | Full |
| NFL | Full — some historical stat categories flagged on-page |
| CFB / NCAAF | Full — same caveat as NFL |
| Men's CBB | Intentionally thin — under construction |
| Women's CBB | Intentionally thin — under construction |

---

## 2. Technical Shape

| Area | Current state |
| --- | --- |
| Backend | Flask, `app.py` (~30k lines — refactor gradually, checkpoint first) |
| Authenticated shell | `templates/bk_base.html` |
| Public shell | `templates/public_base.html` (frontpage, login, signup, legal) |
| Primary CSS | `static/css/bk-theme.css` — active theme |
| Legacy CSS | `static/site.css` was removed after confirming templates no longer linked it |
| Data storage | CSV / JSON files under `data/` |
| Runtime cache | JSON and pickle files under `data/cache/` |
| Daily orchestration | `run_daily.py` and sport-specific refresh scripts |
| QC / scorecards | `qc_*.py` scripts, `run_all_scorecards.py` |
| Payments | Stripe — see Section 7 |
| Legal pages | Live routes — see Section 8 |

---

## 3. Data Flow

Understanding this before touching anything will save hours.

```
Fetch scripts          → data/props/, data/odds/, data/gamelogs/, etc.
  (fetch_*.py)

Refresh scripts        → reads fetch output, runs QC, writes clean files
  (refresh_*.py)           also writes data/tracking/ manifests

Runtime snapshot job   → pre-renders expensive route computations
  (refresh_runtime_       stores in data/cache/
   snapshots.py)

Flask routes           → load from data/ or data/cache/
  (app.py)               cache miss falls back to live computation

Templates              → render what the route passes in
  (templates/)
```

**Key rule:** Runtime snapshots are cache-warmers, not the source of truth. If a snapshot is missing or stale, the route falls back to live computation. Snapshot failures should be treated as degraded cache, not broken data.

---

## 4. Access Control

The access model has two layers: plan tier and sport pass.

**Plans (single-plan era, 2026-06-12)** (`PLAN_RANKS` in `app.py`):

```python
'free':       0   # unpaid account state (preview surfaces)
'all_access': 1   # the one paid plan — $19.99/mo, everything unlocked
# legacy keys (pro, sharp, elite, *_pass) remain in PLAN_RANKS at rank 1 and
# normalize_plan_key() resolves them to 'all_access' — old user rows and old
# links keep working.
```

There are no tiers and no sport passes anymore. `ALL_SPORT_PLAN_KEYS = {'all_access'}`.

**Founders promo:** the first 100 paying subscribers get $10/mo for their first year
(`FOUNDER_PROMO`, `founder_slots_remaining()`, `FounderOffer`/`IsFounder` CSV columns —
see docs/PROJECT_MAP.md "Membership & pricing").

**Owner access:** Emails in `OWNER_EMAILS` bypass all plan checks. Currently one entry. Do not add more without intentional review.

**Key functions:**
- `normalize_user_plan(user)` — resolves a user object to `'free'` or `'all_access'`
- `normalize_plan_key(key)` — resolves any (legacy) plan key to `'free'`/`'all_access'`
- `get_plan_rank(plan_key)` — returns the integer rank
- `is_owner_user(user)` — returns True for owner-email/admin users
- `user_is_founder(user)` — True when the founders rate is locked in

**Pattern for gating a route:**

```python
current_plan = normalize_user_plan(current_user)
if get_plan_rank(current_plan) < get_plan_rank('all_access'):
    return redirect(url_for('pricing'))
```

Every new gated route must use this pattern. Do not invent a new gate mechanism.

---

## 5. Route Map

Full list: `grep "@app.route" app.py` — there are 100+ routes. The categories below are the working mental model.

**Public (no auth required):**
```
/                       Frontpage
/pricing                Pricing page
/signup                 Account creation
/login                  Login
/logout                 Logout
/terms                  Terms of service
/privacy                Privacy policy
/refund-policy          Refund policy
/responsible-gambling   Responsible gambling page
```

**Account / billing:**
```
/account                Account settings
/billing                Subscription management (Stripe portal)
/checkout/start         Initiate Stripe checkout
/checkout/success       Post-payment success handler
/checkout/cancel        Abandoned checkout handler
```

**Sport homes (Pro+ or matching sport pass):**
```
/sports/nba
/sports/wnba
/sports/mlb
/sports/nfl
/sports/ncaaf
/sports/ncaamb          Under construction — renders under_construction.html
/sports/ncaawb          Under construction — renders under_construction.html
/sports/<league>        Catch-all for unmapped leagues
```

**Sport sub-surfaces** (follow `/sports/<sport>/` pattern):
```
props, market-edge, floor, trends, game-lines, totals,
matchup/<slug>, injuries
```
Not every sport has every sub-surface. NBA and MLB are the most complete.

**Cross-sport tools:**
```
/props                  NBA props board (also /sports/nba/props — same handler)
/props/<filter_type>    Filtered view: floor, locks, strong, avoid
/market-edge            NBA market edge (also /sports/nba/market-edge)
/game-lines             Game lines across sports
/schedule               Upcoming games
/parlay                 Parlay builder
/parlay/tickets         Saved ticket list
/candidate-review       Archived prop grading
/missed-opportunities   Plays that were close but didn't surface
/floor-plays            Floor-specific board (distinct from /props/floor)
/heat-map               Streak Lab Heat View
/heatmap/<stat>         Legacy/stat-scoped streak view
/trends/<stat>          Legacy/stat-scoped streak redirect
/trend-board            Streak Lab Pattern View
/tendencies             Conditional hit-rate tendency definition surface
/bet-review             Ticket tracking and ROI
```

**Analysis surfaces:**
```
/matchup/<matchup>      Game matchup detail
/matchup-lens           NBA matchup dashboard
/sports/nba/matchup-lens
/series/<series_id>     Playoff series
/player/<player_name>   Player intelligence
/team/<team>            Team page
/season-review
/season-review/team/<team>
/raw-data
/glossary
```

**Labs (Sharp/Elite):**
```
/elite                  Elite dashboard
/elite/matchup-builder
/elite/mlb-lab
/elite/learn
/calibration-lab
/nfl-formula-lab
/mlb-formula-lab
/quant-systems
/systems-lab
/derivatives
```

**Legacy redirects (kept for URL compatibility — do not remove):**
```
/smart-picks        →  /sports/nba/market-edge
/parlay-builder     →  /parlay
```

**Admin/owner only:**
```
/ops                Operations dashboard
/test-drive         Owner testing interface
```

---

## 6. Page Architecture and Known Redundancy

Several surfaces overlap. Before adding a new page, check whether an existing one already covers the use case.

**Known overlaps to be aware of:**

| Routes | Relationship |
| --- | --- |
| `/props` and `/sports/nba/props` | Same handler, different URL entry points |
| `/market-edge` and `/sports/nba/market-edge` | Same handler |
| `/floor-plays` and `/props/floor` | Two surfaces for floor data — `/props/floor` is the paginated board, `/floor-plays` is a standalone view. Consolidation is a future task. |
| `/heat-map` and `/heatmap/<stat>` | `/heat-map` is the cross-sport entry, `/heatmap/<stat>` is stat-scoped. Related but not identical. |
| `/dashboard` and `/matchup-lens` | Dashboard renders the Matchup Lens view. `/matchup-lens` is a redirect or alias — verify before touching. |
| `/heat-map` and `/trend-board` | Both belong to Streak Lab. `/heat-map` is Heat View for current runs. `/trend-board` is Pattern View for follow-through and consistency depth. Do not rename either one to Tendencies. |
| `/trend-board` and `/trends/<stat>` | `/trends/<stat>` is a legacy/stat-scoped streak URL; `/trend-board` is the combined Streak Patterns view. Both are live for compatibility. |
| `/tendencies` | Reserved for real conditional hit-rate research: home/away, rest, favorite/underdog, game-total band, opponent type, and officiating/umpire context. |

**Streak vs. Tendency taxonomy:**

- Streak means consecutive momentum: a player or bucket has hit several games in a row.
- Streak Patterns means deeper follow-through research: did 3+ or 5+ runs continue often enough to matter?
- Tendency means a conditional hit rate: when a specific condition is true, how often does the player/team/market perform?
- Officiating tendencies are real tendencies and should surface on `/tendencies`, `/derivatives`, and eventually each relevant sport dashboard when assignments are confirmed.

Operational note: `/trend-board` now defaults to `stat=PTS` so Pattern View opens as a usable page. The `stat=all` filter is still available, but it should eventually be snapshot-backed or capped because it can be expensive on a cold request.

**Individual page repetition to clean up (not urgent, but noted):**

- The dashboard still carries an "NBA Data Pulse" card (operational status) and a "How To Use Matchup Lens" card. Both are candidates for collapse or removal in a future pass.
- Sport pages (NBA, MLB, WNBA) each have a sport profile/focus intro block. These follow the same structure but are not shared components — changes need to be applied to each.
- Teaching notes in Market Watch rows were replaced by the synthesis panel. If `move_teaching_note` and `split_teaching_note` fields appear in a template, they are legacy content that can be removed.

---

## 7. Payments (Stripe)

**Current status:** Stripe is wired. All URLs in `.env.local` are **test mode** (`test_` prefix). Before public launch, swap every URL to the live equivalent.

**Environment variables** (`.env.local` for local, hosting dashboard for production):

```
STRIPE_PRO_MONTHLY_URL
STRIPE_PRO_ANNUAL_URL
STRIPE_SHARP_MONTHLY_URL
STRIPE_SHARP_ANNUAL_URL
STRIPE_ELITE_MONTHLY_URL
STRIPE_ELITE_ANNUAL_URL
STRIPE_BILLING_PORTAL_URL
STRIPE_BILLING_PORTAL_CONFIG_ID
```

**Checkout flow:**
1. User hits `/checkout/start` — reads the relevant `STRIPE_*_URL` from env and redirects to Stripe
2. Stripe redirects back to `/checkout/success` (paid) or `/checkout/cancel` (abandoned)
3. `/checkout/success` updates the session plan

**Webhook:** Verify the webhook endpoint is registered in the Stripe dashboard before go-live. The handler needs to process `customer.subscription.updated` and `customer.subscription.deleted` so plan downgrades take effect server-side, not just client-side.

**Pre-launch checklist for Stripe:**
- [ ] Flip Stripe account to live mode
- [ ] Replace all `test_` URLs in production environment variables
- [ ] Run a real test payment using a Stripe test card on the live host
- [ ] Verify billing portal opens and subscription management works
- [ ] Verify webhook fires and updates session plan correctly

---

## 8. Legal Pages

All four legal routes are live:

```
/terms                  Terms of service
/privacy                Privacy policy
/refund-policy          Refund policy
/responsible-gambling   Responsible gambling disclosure
```

Template: `templates/legal_page.html` (shared across all four)

Review all four with a lawyer or at minimum carefully before public launch. The responsible gambling page is especially important given the product category.

---

## 9. Recent Design Decisions

These were made during the June 2026 stabilization pass. Preserve the intent when touching affected files.

**Performance architecture:**
- CSS lives in `static/css/bk-theme.css` — do not move back to inline `<style>` in templates
- Team logos: prefer `.webp` over `.png` — the app checks for WebP first
- Route caching: MLB, dashboard, and WNBA use runtime snapshots to avoid cold-load computation. If a route feels slow, check whether a snapshot exists before adding logic.

**Props carry game context:**
Every prop row should surface: game environment label, matchup, and whether line movement aligns with the model. A prop row that strips this context is a regression. The field names are `game_environment_label` and `game_environment_summary`.

**Market Watch synthesis:**
The dashboard Market Watch section now has a three-column layout: Line Movers / What It Means / Action Read. This is generated by `_build_market_watch_synthesis()` in `app.py`. The raw teaching notes (`move_teaching_note`, `split_teaching_note`) on individual mover rows are now legacy — do not re-expand them into prominent display.

**Filter controls — pill vs dropdown:**
- **Pills:** binary or 3-way mode switches that users toggle constantly (Over/Under, Today/All, Floor/All/Locks)
- **Dropdowns:** 5+ option filters, ordered lists, filters the user sets and moves on (stat type, team, confidence threshold, sort column)
- Do not convert mode-switch pills to dropdowns. Do not use pills for long option lists.

**Page structure intent:**
Each page markets one decision, not a data set:
- Dashboard → "What needs attention tonight?"
- Game Lines → "What does the game environment expect?"
- Matchup → "Which props fit this specific game?"
- Props board → "Which props are playable right now?"
- Candidate Review → "What did the model suggest vs. what happened?"
- Elite → "Why is this edge real?"

When adding a card or section, ask whether it answers the page's core question. If it doesn't, it belongs on a different page or not at all.

---

## 10. MLB Refresh Architecture

The MLB refresh was reworked because the prior flow could hang before writing the freshness manifest.

**Key files:**
- `refresh_mlb_daily.py` — main entry point
- `refresh_mlb_runtime_snapshots.py` — snapshot-only job
- `refresh_runtime_snapshots.py` — all-sport snapshot runner (supports `--sports` scoping)
- `write_mlb_refresh_manifest.py` — manifest writer
- `qc_mlb_readiness.py`
- `qc_mlb_contradictions.py`

**Current behavior:**
- Each step has a timeout
- QC runs in `--fast` / `--skip-routes` mode in the daily lane
- Live manifest is written immediately after live data passes QC
- Final manifest is written again at the end
- Heavy archive/governance work is out of the live lane
- Runtime snapshots are non-blocking

**Manifest file:**
```
data/tracking/MLB_DailyRefresh_Manifest.json
```

---

## 11. AWS Deployment Guidance

Do not deploy one giant all-purpose refresh job.

**Preferred shape:**

| Job | Trigger |
| --- | --- |
| `refresh_mlb_daily.py` | Scheduled — runs before game time |
| `refresh_nba_daily.py` | Scheduled |
| `refresh_wnba_daily.py` | Scheduled |
| `refresh_football_line_movement.py` | Scheduled daily once NFL/CFB early lines are open |
| `refresh_futures_odds.py` | Scheduled daily for championship/futures movement tracking |
| `refresh_ngs_stats.py` | Scheduled weekly during NFL season or run manually for historical NGS backfills |
| `refresh_mlb_statcast.py` | Scheduled daily during MLB season after game context and before MLB QC/snapshots |
| `refresh_runtime_snapshots.py --sports mlb` | Scheduled — after MLB refresh |
| `refresh_runtime_snapshots.py --sports nba,wnba` | Scheduled — after NBA/WNBA refresh |
| Flask app | Always-on — EC2 or container behind reverse proxy |

**Infrastructure notes:**
- EC2 or container-hosted Flask behind nginx or ALB
- CloudWatch logs for app stdout/stderr and scheduled jobs
- EBS or mounted persistent storage for the CSV data model
- Nonzero exit from live refresh → alarm
- Snapshot timeout/failure → degraded cache warning, not a failed refresh
- Environment variables set in the hosting dashboard, not in any committed file
- `SECRET_KEY` must be set explicitly — the fallback `secrets.token_urlsafe(48)` generates a new key on every restart, which logs all users out

**Planned migration path (not yet started):**
- Current: CSV/JSON files on disk
- Future: Postgres for structured data, Redis for cache layer
- Do not design AWS storage assuming the CSV model is permanent

**Local vs AWS command differences:**
- Local: `py -3` (Windows launcher)
- AWS: `python` (real interpreter in the container path)

---

## 12. Local Commands

**Syntax check:**
```powershell
py -3 -m py_compile app.py
py -3 -m py_compile refresh_mlb_daily.py refresh_mlb_runtime_snapshots.py refresh_runtime_snapshots.py
```

**Run the app:**
```powershell
.\start_server.ps1 -Port 5000
```

**Stop the app:**
```powershell
.\stop_server.ps1 -Port 5000
```

**Daily refresh:**
```powershell
py -3 run_daily.py --sports nba,wnba,mlb
```

**MLB refresh only:**
```powershell
py -3 refresh_mlb_daily.py
```

**MLB snapshots only:**
```powershell
py -3 refresh_mlb_runtime_snapshots.py
```

**Scoped snapshot groups:**
```powershell
py -3 refresh_runtime_snapshots.py --sports mlb --skip-prewarm
py -3 refresh_runtime_snapshots.py --sports nba,wnba --skip-prewarm
```

**Football line movement:**
```powershell
py -3 refresh_football_line_movement.py
```
This fetches NFL and NCAAF game lines with a 130-day window so early Week 1 markets are captured. The latest odds still write to `data/odds/*_Odds.csv`; movement history is append-only under `data/tracking/`.

**Futures odds movement:**
```powershell
py -3 refresh_futures_odds.py
```
This fetches active football, basketball, and baseball `outrights` markets from The Odds API. The first captured price becomes the opener/baseline in `data/tracking/Futures_LineMovementCurrent.csv`; later runs show movement vs that first-seen price. This is the foundation for championship futures and award/futures pages. Season win totals still require a separate data source if they are not offered as API markets.

**NFL Next Gen Stats:**
```powershell
py -3 refresh_ngs_stats.py
```
This fetches public Next Gen Stats statboards for passing, receiving, and rushing from `nextgenstats.nfl.com/api/statboard/*`. Regular-season aggregate files are available. Postseason aggregate calls can return zero rows from the source, so playoff samples should use the weekly combined files.

**MLB Statcast:**
```powershell
py -3 refresh_mlb_statcast.py
```
This fetches public Baseball Savant aggregate data through `pybaseball`, then writes merged hitter and pitcher profiles under `data/statcast/`. It uses expected stats, barrels/exit velo, percentile ranks, sprint speed, and pitcher arsenal data.

**All scorecards:**
```powershell
py -3 run_all_scorecards.py
```

**Targeted QC:**
```powershell
py -3 qc_plan_access_matrix.py
py -3 qc_universal_tool_hubs.py
py -3 qc_membership_regression.py
py -3 qc_mlb_readiness.py --skip-routes
py -3 qc_mlb_contradictions.py --fast --report-only
```

---

## 13. Key Data Files

| File / folder | Purpose |
| --- | --- |
| `data/props/` | Live prop feeds |
| `data/odds/` | Game-line odds |
| `data/schedules/` | Schedules and schedule aliases |
| `data/gamelogs/` | Player game logs |
| `data/context/` | Weather, umpire, officiating, game context |
| `data/tracking/` | QC logs, scorecards, calibration, manifests |
| `data/cache/` | Runtime snapshots and disk TTL caches |
| `data/tracking/QC_Run_Log.csv` | QC history |
| `data/tracking/MLB_DailyRefresh_Manifest.json` | MLB freshness manifest |
| `data/tracking/Combined_Prop_Coverage.csv` | Cross-sport coverage summary |
| `data/tracking/Formula_Status.json` | Formula status |
| `data/tracking/Run_Status.json` | Daily run status |
| `data/tracking/NFL_LineMovementHistory.csv` | Timestamped NFL odds snapshots for opener/current movement tracking |
| `data/tracking/NFL_LineMovementCurrent.csv` | Current NFL line movement summary vs first-seen opener |
| `data/tracking/NCAAF_LineMovementHistory.csv` | Timestamped CFB odds snapshots for opener/current movement tracking |
| `data/tracking/NCAAF_LineMovementCurrent.csv` | Current CFB line movement summary vs first-seen opener |
| `data/futures/Futures_Sports.csv` | Discovered futures-capable sport keys from The Odds API |
| `data/futures/Futures_Odds.csv` | Latest championship/futures odds from active outright markets |
| `data/tracking/Futures_LineMovementHistory.csv` | Timestamped futures snapshots for opener/current movement tracking |
| `data/tracking/Futures_LineMovementCurrent.csv` | Current futures movement summary vs first-seen opener |
| `data/ngs/NGS_*_2025_REG.csv` | Regular-season aggregate Next Gen passing/receiving/rushing statboards |
| `data/ngs/NGS_*_2025_REG_Weekly.csv` | Combined regular-season weekly Next Gen statboards |
| `data/ngs/NGS_*_2025_POST_Weekly.csv` | Combined postseason weekly Next Gen statboards |
| `data/ngs/weekly/NGS_*_Week*.csv` | Per-week Next Gen statboard snapshots |
| `data/statcast/MLB_Statcast_Hitters_2026.csv` | Merged hitter Statcast profile: expected stats, barrels, hard contact, sprint speed |
| `data/statcast/MLB_Statcast_Pitchers_2026.csv` | Merged pitcher Statcast profile: expected stats, contact allowed, percentiles, arsenal |

Do not delete or regenerate `data/` files without knowing which routes depend on them. Some files are inputs for multiple routes across multiple sports.

---

## 14. Player and Team Page Decision Layer

Recent product direction: player and team pages should answer betting questions first, then show raw detail underneath.

Implemented first pass:
- `app.py` now builds `player_decision_context` for `/player/<player_name>`.
- `app.py` now builds `team_decision_context` for `/team/<team>`.
- `templates/player.html` now leads with three fixed blocks: Tonight's Context, Prop Hit Rates, and Matchup Layer.
- `templates/team.html` now leads with three fixed blocks: What This Team Does, What This Team Allows, and What Tonight Looks Like.
- Shared styles live in `static/css/bk-theme.css` under the `bk-decision-*` class family.

Current scope:
- The live implementation is NBA-first because the existing `/player/<player_name>` and `/team/<team>` routes are NBA data routes.
- The context builders already accept `sport_key`, so MLB, NFL, and WNBA can plug in without redesigning the template pattern.
- Player-vs-defense is surfaced as a first-class Matchup Layer row. Full defender/player-vs-player history should remain a Sharp/Elite layer when that data is available.
- Team pages intentionally put roster stats below the decision layer. Do not move generic tutorial content back above live context.

Recommended next expansion:
- Add MLB pitcher/batter route contexts that populate the same player block shape with K environment, batter-vs-pitcher, pitch mix, park, umpire, weather, and lineup-handedness fields.
- Add NFL player/team contexts using game script, pass/run tendency, snap share, target share, weather, and position-allowed fields.
- Add WNBA rotation volatility and market-depth warnings to the same NBA-style card shape.

---

## 15. Launch Feature Roadmap

Recent product direction prioritizes retention, trustworthy data gates, and mobile app feel.

Implemented first pass:
- Frontend interaction layer:
  - Alpine.js is loaded once in `templates/bk_base.html`.
  - Bet slip tab switching is the first Alpine conversion.
  - Use Alpine for new dropdowns, tabs, modals, show/hide panels, and small UI state. Keep Flask + Jinja2 as the rendering architecture.
  - HTMX, Tailwind, and Chart.js remain post-launch candidates. Do not migrate the site framework before launch.
- Launch polish and security:
  - Base shells now include favicon links, description metadata, PWA manifest links, and public Open Graph/Twitter preview tags.
  - `/favicon.ico` is served from `static/favicon.png` to avoid wasted browser 404s.
  - Branded `404` and `500` handlers render `templates/error.html`; page-level not-found returns should use `render_error_page()`.
  - Security headers are applied in `app.py` with `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and a conservative CSP.
  - Login has a lightweight in-memory 10/minute throttle per IP/email. Replace with Redis-backed Flask-Limiter or equivalent before multi-instance production.
  - `static/site.css` was removed because no templates linked it.
  - Shell/sidebar images now use lazy loading except for the primary brand mark.
  - A small top loading bar activates on normal link/form navigation so slow pages provide immediate feedback.
- PWA shell support:
  - `static/manifest.webmanifest`
  - `static/service-worker.js`
  - `/manifest.webmanifest` and `/service-worker.js` root routes in `app.py`
  - `bk_base.html` links the manifest and registers the service worker.
- MLB lineup gate:
  - `build_mlb_prop_board()` now attaches `lineup_gate_status`, `lineup_gate_label`, `lineup_gate_note`, and `lineup_confirmed`.
  - MLB batter props default to `LINEUP PENDING` unless a feed column confirms the lineup/starting status.
  - MLB pitcher props default to `PITCHER PROBABLE` because they can be reviewed before batting orders lock, but still need starter confirmation.
  - Pending batter lineup status turns otherwise clean MLB plays into `CONFLICTED`, preventing the board from presenting them as fully final.
  - `templates/mlb_dashboard.html` and `templates/mlb_method_board.html` show the lineup gate pill and note.
- MLB performance guardrails:
  - `build_mlb_prop_board()` prefilters `today`/`tomorrow`, stat, and search before grouping prop rows.
  - Web routes call MLB board builders in `fast_mode=True`, keeping market/reliability/lineup context while leaving expensive simulation/calibration enrichment to refresh snapshots and offline jobs.
  - Web `date=all` requests now fall back to today's live/snapshot board instead of building the full multi-thousand-row MLB universe in a browser request.
  - `refresh_mlb_runtime_snapshots.py` now writes `mlb_dashboard_today`, `mlb_props_today`, and `mlb_market_edge_today` using `fast_mode=True`.
  - `refresh_mlb_daily.py` runs the dedicated MLB snapshot job after source files, QC, manifest, and calibration steps, before the final manifest.
  - Cold MLB fallback is still slower than warm cache, so AWS should keep this snapshot step after every refresh and deploy.

Priority order after this pass:
1. Personal performance tracker: expand saved tickets into a user-level ROI/leak dashboard by sport, method, stat, and date range.
2. Real-time line movement alerts: detect 0.5+ line moves on tracked/watchlisted players and create in-app alert records first, then email/push.
3. Saved watchlist: star players/teams/props and attach line movement, injury, and lineup-confirmed events.
4. Free trial timer: add trial start/end fields and trial-expiry messaging in account/pricing flows.
5. Umpire database: enrich MLB game context with umpire K/run environment impact and historical over/under tendencies.
6. Injury impact simulator: convert injury status into what-if teammate usage/line movement projections.
7. Sharp vs public split: add a signal label when public lean and line movement disagree.
8. Weekly sharp report: automated digest from saved results, model watchlist, and best/worst buckets.

Implementation notes:
- Alerts should start as durable in-app records before email or push. Do not begin with browser push alone.
- Lineup-gate logic should use real feed fields when available: `LineupStatus`, `ConfirmedLineup`, `StartingStatus`, or `BattingOrder`.
- PWA service worker intentionally caches shell assets only. Do not cache live prop pages or JSON feeds without a freshness strategy.

---

## 16. Betting Intelligence Expansion

The next product expansion is documented in `docs/betting_intelligence_expansion.md`.

Short version:
- Bankroll Kings should expand from a prop screener into a complete betting intelligence platform.
- Fastest new surface is season win totals once a futures odds source is added.
- Next highest-value surfaces are first-half analysis, player season prop pace tracking, awards/futures, and MLB F5.
- Do not build these pages with placeholder data. Add the source ingestion and movement tracking first, then expose the UI.
- Keep archive/futures calculations out of live prop refresh lanes so slow season-long work cannot block daily boards.

Recommended build order:
1. Season win totals page.
2. First-half lines on matchup pages.
3. Player season prop pace tracker on player pages.
4. Award contender tracker.
5. MLB F5 board.

---

## 17. NFL Next Gen Stats Layer

Implemented foundation:
- `fetch_ngs_stats.py` pulls public NGS passing, receiving, and rushing statboards.
- `refresh_ngs_stats.py` refreshes 2025 REG/POST aggregate and weekly files.
- `services/ngs_loader.py` loads NGS season profiles, weekly trends, and team ID crosswalks.
- `templates/_ngs_player_profile.html` renders the shared player-page NGS profile card.
- `/player/<player_name>` now passes `ngs_context` into normal player pages and archive fallback pages.
- NFL-only players present in NGS, such as Caleb Williams or Bijan Robinson, can render an NGS archive profile even without NBA gamelog rows.
- Live NFL prop rows now attach an explainable `ngs_signal`, `ngs_score_delta`, and `ngs_note`.
- `calculate_nfl_prop_score.py` now writes `NGSModifier` and `NGSNote` into `NFL_AllPropResults_Scored.csv`.

Current NGS display coverage:
- QB passing: CPOE, average time to throw, aggressiveness, intended air yards, air-yards differential, L4 trend.
- WR/TE receiving: air-yards share, separation, aDOT, cushion, YAC over expected, L4 trend.
- RB rushing: RYOE per attempt, rush percent over expected, stacked-box rate, time to line of scrimmage, efficiency, L4 trend.

Current prop scoring scope:
- Receiving props: air-yards share, separation, aDOT, and YAC over expected.
- Rushing props: RYOE per attempt, rush percent over expected, and stacked-box rate.
- Passing props: CPOE, time to throw, aggressiveness, and intended air yards.
- The modifier is capped at +/-6 points so NGS sharpens the read without overpowering market price, game script, or historical reliability.

Next integration step:
- Backtest the NGS modifier bands once more scored NFL prop rows exist and tune thresholds if +/-6 is too strong or too weak.

---

## 18. MLB Statcast Layer

Implemented foundation:
- `fetch_mlb_statcast.py` pulls public Baseball Savant aggregates through `pybaseball`.
- `refresh_mlb_statcast.py` writes merged 2026 hitter and pitcher profiles.
- `services/statcast_loader.py` loads Statcast profiles and emits capped prop signals.
- `templates/_statcast_player_profile.html` renders the shared Statcast profile card.
- `/player/<player_name>` now passes `statcast_context` into normal player pages and archive fallback pages.
- `calculate_mlb_context_scores.py` now writes `MLBStatcastModifier` and `MLBStatcastNote`.
- Live MLB prop rows now attach `statcast_signal`, `statcast_score_delta`, and `statcast_note`.
- `refresh_mlb_daily.py` runs `refresh_mlb_statcast.py` after game context and before MLB QC/snapshots.

Current Statcast display coverage:
- Hitters: xwOBA, xSLG, Barrel %, hard-hit percentile, sprint speed.
- Pitchers: xERA, xwOBA allowed, K percentile, whiff percentile, best whiff pitch.

Current prop scoring scope:
- Hitter power/contact props: xwOBA percentile, barrel percentile, hard-hit percentile, K profile, sprint speed.
- Pitcher props: K percentile, whiff percentile, arsenal whiff, xERA percentile, hard-contact allowed.
- The modifier is capped at +/-6 points so Statcast sharpens the player-quality read without overpowering market, park, weather, umpire, or reliability layers.

Next integration step:
- Backtest Statcast modifier bands after the next MLB score run and tune hitter/pitcher thresholds by stat family.

---

## 19. Known Risks and Cautions

- `app.py` is large. Refactor gradually after checkpointing. Do not do broad cleanup on an unverified working tree.
- Do not revert unrelated dirty working-tree changes without understanding what they contain.
- Some templates still have legacy naming — preserve route compatibility before renaming anything.
- Missing MLB markets (Batter Strikeouts, Pitcher Walks) can be valid book availability issues, not code failures.
- Weather context may be absent while ballpark and umpire context remain usable — this is expected.
- Runtime snapshots are cache-warmers. Their absence degrades performance but does not break the app.
- The `OWNER_EMAILS` set in `app.py` bypasses all plan checks. Do not expand this set casually.

---

## 20. Pre-Launch Checklist

**Infrastructure:**
- [ ] Clean git checkpoint from known-good state
- [ ] `SECRET_KEY` set explicitly in production environment (not relying on random fallback)
- [ ] All Stripe URLs swapped to live mode
- [ ] Stripe webhook registered and verified
- [ ] Test payment end-to-end on the live host
- [ ] App deployed with HTTPS and a real domain
- [ ] Scheduled refresh jobs configured in AWS
- [ ] CloudWatch logging active

**Product:**
- [ ] Visual trust pass across all paid surfaces (NBA, MLB, WNBA boards, Elite, Parlay Builder)
- [ ] Legal pages reviewed (`/terms`, `/privacy`, `/refund-policy`, `/responsible-gambling`)
- [ ] College basketball surfaces explicitly marked as under construction
- [ ] Pricing page tested for correct plan upgrade/downgrade flow

---

## 21. Suggested First-Pass Order (New Developer)

1. `git status` — understand current working tree before touching anything
2. Syntax check: `py -3 -m py_compile app.py`
3. Targeted QC: access matrix, membership regression, MLB readiness
4. `py -3 refresh_mlb_daily.py` — verify manifest updates
5. Visual trust pass: `/dashboard`, `/sports/mlb`, `/sports/nba/props`, `/props/floor`, `/elite`
6. Read Sections 4 (Access Control) and 6 (Page Architecture) before adding any new routes or surfaces
7. Confirm Stripe and env before any payment-related changes
8. AWS deployment only after steps 1–7 are clean

---

## 22. Product Philosophy

Bankroll Kings helps users understand when to play, when to pass, and why a line is risky.

The strongest parts of the product are the context layers: market agreement, injury and officiating context, player reliability, calibration history, floor plays, and bankroll/correlation thinking.

Keep that philosophy intact when changing code. The app should never make a weak or conflicted play look premium just because it has a number attached to it. If a prop row loses its game context, market alignment, or reliability signal, that is a regression regardless of how clean the UI looks.
