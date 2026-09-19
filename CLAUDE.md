# CLAUDE.md — Bankroll Kings

Auto-loaded context for every Claude session in this repo, on any machine. Read it
before touching anything. When something here goes stale, fix it here — this file is
supposed to stop us re-deriving the same facts every session.

Deep detail lives in `docs/`; this file is the map and the rules.

---

## 0. This repository is PUBLIC

`github.com/Bswift305/bankrollkings` clones anonymously. Treat every commit as a
press release.

- **Never commit** `.env`, `*.pem`, `*.key`, `*.ppk`, `sk_live_*`, `sk_test_*`,
  `*secret*.txt`, or anything with a live credential. `.gitignore` already blocks
  these — it is load-bearing, not housekeeping. Do not weaken it.
- `bankroll-key.pem` (the EC2 SSH key) sits untracked in the repo root on the dev
  box. It is one `git add -f` away from being public forever. Never force-add it.
- `.env.example` is the only env file that belongs in git.
- Bulky generated data (`data/cache/`, `data/gamelogs/`, `data/odds/`, …) is
  ignored on purpose. It belongs on the box or in S3, not in git history.
- Before any `git add -A`, run `git status --short` and look. A commit that
  leaks a key cannot be undone by `git rm` — the blob stays in history, in forks,
  and in every scraper that indexed it. Rotation is the only fix.

---

## 1. What this is

A Flask sports-betting **analytics** platform. It is not a sportsbook: it accepts no
wagers and custodies no funds.

Core pipeline — keep it in mind when touching any page:

```
game context → market context → prop context → confidence / risk label
```

It should read like a betting intelligence terminal, not a picks page. A prop row
stripped of its market pricing, game environment, injury context, calibration history
and risk warnings is a **regression, not a simplification**.

| Sport | Status |
|---|---|
| NBA | Full — flagship |
| MLB | Full |
| WNBA | Full |
| NFL | Full |
| CFB / NCAAF | Full |
| Men's / Women's CBB | Themed pre-season shells only — no real board data yet |

---

## 2. Two environments — do not confuse them

| | Local dev | Production |
|---|---|---|
| URL | `http://localhost:5000` | `https://bankrollkings.com` |
| Host | the Windows box, repo in OneDrive | AWS EC2, `ubuntu@`, `/opt/bankrollkings` |
| Server | Flask dev via `start_server.ps1` | gunicorn (`preload_app=True`) behind nginx, systemd unit `bankrollkings` |
| Data | its own, refreshed by Windows Scheduled Tasks | its own, refreshed by systemd timers |

**They are separate machines with separate data.** Editing locally and restarting
`:5000` does nothing to the live site. The user looks at **bankrollkings.com** —
always establish which one you are debugging before theorising. Prop counts moving on
prod are prod's own refresh jobs, not your local edits.

`:8080` locally is EnterpriseDB Postgres PEM, unrelated to this app.

### Repo root moves between machines

The workstation and the laptop/tablet use different Windows usernames, so absolute
paths in `.claude/settings.local.json` and `.claude/launch.json` are machine-specific
and do not travel. `.claude/` is gitignored for that reason. Never hardcode a
`C:\Users\<name>\...` path into tracked code — derive it, or read it from env.

### The prod box does NOT auto-scale

A single fixed EC2 instance, `t3.large` (2 vCPU / 8 GB), `us-east-1`, resized up from
`t3.medium`. Nothing about it grows on its own. "It scales up when I need it" is not
true here — that is managed services, not a plain EC2 box.

- **RAM is the ceiling.** `earlyoom` is armed and SIGTERMs processes when available
  memory drops below 12%. A job that dies with **exit 143** and no output is earlyoom,
  not a code bug. Check first:
  `sudo journalctl -u <unit> --since -10min | grep -i sigterm`
- **Disk is not a concern, but measure the right volume.** Root `/` is a small OS disk
  running ~82% and basically static. All app data is on a separate 50 GB volume at
  `/opt/bankrollkings` at ~3%. Use `df /opt/bankrollkings`, never `df /`.
- **Speed is fine.** Warm responses ~5–10 ms. The only slow path is the ~8 s cold-cache
  rebuild on the first request after idle — a prewarm concern, not a capacity one.

Instance id, Elastic IP and SSH details are recorded in `docs/PROJECT_MAP.md` §1.
⚠️ An older, different IP appears in `.claude/settings.local.json`; PROJECT_MAP is the
newer record. Verify against the AWS console before relying on either.

---

## 3. Deploy = `git push origin master`

That is the whole procedure. The server pulls for you: `bk-deploy.timer` runs
`/usr/local/bin/bk-auto-deploy.sh` every 2 minutes, fetches `origin/master`, and only
when it has moved does `git pull --ff-only` + `systemctl restart bankrollkings`, then
probes the app to confirm it came back.

Watch it land:

```bash
journalctl -u bk-deploy.service -n 20 --no-pager
```

Why pull and not push: SSH is IP-allowlisted in the security group, and a churning
egress IP (hotel wifi, cellular) silently blocks port 22 — which repeatedly stranded
pushed commits undeployed. Pulling removes SSH from the deploy path entirely.

The script lives **outside** the repo at `/usr/local/bin/bk-auto-deploy.sh`
deliberately: bash reads scripts incrementally, so a pull rewriting the running script
mid-execution corrupts it. Source of record is `ops/bk-auto-deploy.sh`; install with
`sudo install -m 755 ops/bk-auto-deploy.sh /usr/local/bin/bk-auto-deploy.sh`.

A failed tick exits non-zero and leaves the service on the old commit. It never
half-deploys and it retries next tick.

### `restart`, never `reload`

gunicorn runs `preload_app=True`, so `systemctl reload` (HUP) does **not** reliably
pick up `app.py` **or** template changes — new workers fork from the master and inherit
its loaded code and cached Jinja templates (`auto_reload` is off in prod). Use
`restart` for any `app.py` or template change. Only true static assets (CSS/JS/SVG/PNG
off disk) are fresh without one — bust the *browser* cache for those with `?v=…` and a
service-worker version bump.

Some systemd units are **not in the repo** (`bk-linemove.*`, the `WEB_CONCURRENCY`
drop-in). If the box is rebuilt, recreate them from `docs/PROJECT_MAP.md` §6.

---

## 4. Caching — the #1 source of "I changed it and nothing happened"

Five layers. Work down this list before debugging logic.

1. **`DATAFRAME_CACHE`** — per-process, keyed by file mtime. Re-parses a CSV when it changes.
2. **`RUNTIME_TTL_CACHE` + disk pkl** (`data/cache/*.pkl`) — keyed by a
   `_build_file_token(...)` version. **If a cached builder reads a file that is not in
   its version token, it serves stale forever.** Always include every input file.
   Stampede-protected: cold keys rebuild under a per-key lock, concurrent requests get
   the stale value rather than all running the builder at once.

   > ⚠️ **A code-only change to a cached builder is invisible.** The version token
   > covers *data files*, not source. Edit board logic, leave the CSVs alone, and the
   > builder serves pre-edit rows for the full 12h TTL — the change looks broken when
   > it is fine. This burned three rounds of debugging on the `LONGSHOT OVER`
   > guardrail. When verifying a change to `build_*_prop_board` / `build_*_method_board`:
   > `rm -f data/cache/*<sport>_prop_board*` first (and restart on prod), or pass a
   > fresh `cache_namespace=`. Same after deploying, or users see the old board until
   > the TTL expires.

3. **Service worker** (`static/service-worker.js`) — caches `/static/css/`,
   `/static/logos/`, brand assets. Bump `BK_CACHE` shell-vN on shell-asset changes.
4. **HTTP cache** — Flask static `max-age`. Bust with `?v=…`.
5. **CSS** — `bk_base.html` loads `bk-theme.css?v=YYYYMMDD-…`; bump that string on CSS edits.

---

## 5. Timezone — anchor to Eastern, never `datetime.now()`

Provider commence times are UTC. Convert via `services/timeutils.py`
(`to_eastern_datetime_str` / `to_eastern_date_str`), **not** a bare `.astimezone()`,
which uses the process's ambient zone and lands games on the wrong day.

"Today" is also Eastern: use `sports_today_ts()` / `sports_today_date()`. Board game
dates are Eastern calendar dates, so on the **UTC prod server** a plain
`datetime.now()` rolls to the next day at 8pm ET while that evening's slate is still
"today" — `date_filter='today'` then matched **zero** games every evening, silently
emptying the live board and starving curated archiving. **A US-timezone dev box agrees
with Eastern and never reproduces this. It is prod-only.**

---

## 6. Repo layout

| Path | What |
|---|---|
| `app.py` | Flask monolith, ~41k lines. Refactor gradually; checkpoint first. |
| `franchise_kings.py` (~10k), `franchise_league.py`, `franchise_offseason.py` | Franchise mode |
| `services/` | Extracted helpers — `timeutils`, `review_center`, `model_calibration`, `football_intelligence`, `season_markets`, per-sport contradiction QC, loaders |
| `sport_registry.py` | Declares every sport's parts. Start here to add a sport. |
| `fetch_*.py` | Pull from providers → `data/props/`, `data/odds/`, `data/gamelogs/` |
| `refresh_*.py` | Read fetch output, run QC, write clean files + `data/tracking/` manifests |
| `run_daily.py` | Daily operator: refreshes + Edge Engine + scorecards + `Run_Status.json` |
| `qc_*.py` (33 scripts) | The test suite. See §8. |
| `run_*_scorecard.py`, `run_all_scorecards.py` | Scorecards |
| `templates/` | Jinja. `bk_base.html` = authed shell, `public_base.html` = public shell |
| `static/css/bk-theme.css` | The active theme |
| `deploy/`, `ops/` | systemd units, nginx conf, auto-deploy script |
| `marketing/` | Content pack + `generators/weekly_cards.py`, `video_engine.py` |
| `docs/` | 25+ deep references — see §12 |
| `_attic/` | Gitignored local scratch. Never deployed, safe to delete. |

**Stack:** Flask 3 · pandas 2.2 · numpy · gunicorn (Linux) / waitress (Windows) ·
Stripe · `nba_api` · `pybaseball` · `openpyxl` · `pypdf`. Storage is **CSV/JSON under
`data/`** — there is no database. Runtime cache is JSON/pickle in `data/cache/`.

**Local entry points:** `start_server.ps1` / `stop_server.ps1` (port 5000),
`launch_bankroll_kings.ps1`, `install_task_schedules.ps1` (registers the Windows
Scheduled Tasks). `Procfile` is `web: gunicorn app:app`.

---

## 7. Data pipeline

```
fetch_*.py       → data/props/, data/odds/, data/gamelogs/, …
refresh_*.py     → QC + clean files + data/tracking/ manifests
runtime snapshot → pre-renders expensive routes into data/cache/
Flask routes     → read data/ or data/cache/; cache miss falls back to live compute
templates/       → render what the route passes
```

> ### ⚠️ The rule that has cost real time twice
> **If a feed is not wired into `run_daily.py`, it never runs on prod.**
> The football/CFB fetchers historically lived only in
> `batch/REFRESH_FOOTBALL_DATA.bat`, which runs on the **Windows box, not the server**.
> The batch files are dev-only. When adding any sport's feed, add it to `run_daily.py`.

- **Prod:** systemd timers. `refresh_live_scores.py` polls ~60s, self-gating to game
  windows *and* to signed-in user activity (heartbeat file written by the web app) to
  save API spend, plus a one-time catch-up poll to finalize games that ended while
  idle. Stale 'live' rows render as "Final".
- **Local:** Windows Scheduled Tasks ("Bankroll Kings — …") driving `batch/`.
- **Line movement:** `bk-linemove.timer` runs `refresh_line_movement_snapshots.py`
  every 4h (MLB + WNBA game lines). This is what makes **Market Movers** viable —
  once-daily capture gave a near-term game 1–2 snapshots and no visible movement.
  Football stays daily: advance lines are weeks out and move slowly.
- **Prelaunch scorecard** runs each of its 12 sections in its **own subprocess**
  (`--section <key>`). In one interpreter it peaked ~850 MB and earlyoom killed it
  before it printed a line, so `run_all_scorecards` read "no output" as FAIL and
  prelaunch verification was silently dead while the code was fine. A section that
  cannot run yields an **incomplete** report — never zero-filled, because zeros read
  as a pass.

---

## 8. Testing = the QC scripts

There is no `tests/` directory and no pytest suite. The 33 `qc_*.py` scripts are the
test suite; `run_all_scorecards.py` is the runner. `qc_sport_registry.py` runs **first**
and fails when a sport is missing a part.

Run the relevant `qc_*.py` for whatever you touched, and `py -3 -m py_compile app.py`
before committing a change to the monolith.

Naming is not uniform — **NCAAF's QC and calibrator use the `cfb` prefix**, so grepping
`ncaaf` misses them.

---

## 9. Adding a sport — start at `sport_registry.py`

It declares props/gamelog/schedule/odds loaders, the loader **grading** uses, the
stat-column map, archive gates, QC prefix and calibrator. Data only, no `app` import,
so `app.py` imports it without a cycle.

Two fields carry what a grep cannot:

- **`identity_ok`** — NBA/WNBA legitimately need no stat map (their prop stats already
  *are* their gamelog column names). `stat_column_map=None` with `identity_ok=False`
  is a failure.
- **`requires_play_verdict`** — MLB/WNBA gate archiving on `play_verdict=='PLAY'`;
  football does not. A verdict that can never be `PLAY` silently zeroes out archiving.

Known irregularity: **NBA uses unprefixed loaders** (`load_props`, `load_schedule`,
`load_gamelogs`, `load_game_market_odds`) and **NBA grading uses
`load_nba_review_gamelogs`** (includes playoffs), not `load_gamelogs` (regular season
only).

The registry exists because two season-costing bugs were both "this sport is missing a
part the others have" — football had no stat map so nothing graded, MLB's lineup gate
could never be satisfied so nothing archived. Neither showed up in the UI.

**Soccer needs more than a registry entry** — archivers and graders assume OVER/UNDER,
and 3-way/draw markets break that.

### Candidate archive columns

Rows persist the drivers, so model quality is measurable after the fact:
`ModelProb` `SimProb` `MarketProb` `LeanGap` `PlayVerdict` `LineupStatus` `PatternHits`
`PatternWindow` `StreakLen` `ConsistencyIndex` `Follow3Rate` `Follow5Rate`
`Follow3Chances` `Follow5Chances` `ActiveStreaks` `AvgGap` `MarketRate` `TrendScore`
`FloorHitRate` `ConsistencyLabel` `LongestRun`

`load_candidate_archive()` ends in `return df[default_columns]` — **a column missing
from that list is silently dropped on read even after it is written.** Add it there too.

---

## 10. Betting guardrails — what the graded record actually supports

Backtested on **171,476 graded MLB + WNBA props** at real lines and real prices.

**Every predictive factor tested is already in the price.** Streak depth, opponent
defence, venue, rest, line movement and expected plate appearances all move the hit
rate hard — and the market's implied probability moves with them, leaving the edge flat
at roughly the vig. Streaks are real (NBA streak ≥3 continues +15.1 points above base
over 122,888 obs, rolling line, no lookahead); the market simply knows.
**Do not sell streak depth as an edge.**

What survives, and is enforced in code:

1. **`LONGSHOT OVER` guardrail** (`build_mlb_prop_board`) — overs under 25% implied.
   OVER ROI by implied band is monotonic: `<15% → -40.9%`, `15–25% → -20.4%`,
   `70%+ → -6.5%`. The *edge* is near-constant (−2.6 to −4.8) in every band; what
   changes is what a miss costs at long odds.
2. **All-over parlay warning** (`analyze_saved_parlay`) — all-over tickets returned
   **−22% (2 legs) to −61% (5 legs) out-of-sample**. Warning only, not a grade penalty:
   the evidence is MLB/WNBA and the builder is NBA-centric.
3. **`SINGLE BOOK` → CONFLICTED** — 1 book returns −15.2% vs −3.9% at 5 books.
4. **Prefer UNDER** — −0.6% vs −6.3% on identical streak logic.

> **Out-of-sample or it does not count.** Four streak-parlay rules looked bulletproof
> in-sample (lower CI bounds +8.3 to +17.8) and every one reversed to significantly
> negative out-of-sample. A 3-leg parlay showed +63% ROI at n=21 and −29% at n=2,861.

**Honest-language rules baked into the product:** report counts by type, never a
composite "risk score" (sports don't share equivalent evidence). No "sharp"/"steam"
labels. Cross-sport is "lower shared-event concentration", **not** "uncorrelated".
Combined implied probability is always labeled "assumes independence". Availability
states (Verified/Partial/Pending/Stale/Unavailable) exist so missing context never
reads as neutral.

**On the "do not build" list, by user direction:** a universal 1–100 score, a
cross-sport "best bets" ranking, a sharp-money tracker, a "lock", an auto-EV list.
Keep them unbuilt.

---

## 11. Membership & pricing

**One paid plan: `all_access`, $19.99/mo, monthly only. No tiers.** `free` is the
unpaid account state. The old pro/sharp/elite + six sport passes system is gone;
`LEGACY_PAID_PLAN_KEYS` maps any surviving old key to `all_access`
(`normalize_plan_key` / `normalize_user_plan`). Gating is binary —
`get_required_plan_for_endpoint` returns `free` or `all_access`; `PRO_ENDPOINTS` /
`SHARP_ENDPOINTS` both just mean "paid". Owners/admins bypass. Comp list is
`COMP_ALL_ACCESS_EMAILS`.

**Founders promo:** first **100 paying subscribers** get **$10/mo for 12 months**, then
standard. `/checkout/start` reserves a slot while `founder_slots_remaining() > 0`;
activation converts it to `IsFounder=1` inside `update_user_membership` — **the single
chokepoint**. Cancel/abandon releases the reservation. Slots are never recycled.
`FOUNDER_PROMO` holds slots/price/duration.

**Stripe env** (old `STRIPE_PRO_*` keys are dead):
`STRIPE_ALL_ACCESS_MONTHLY_URL`, `STRIPE_ALL_ACCESS_FOUNDER_MONTHLY_URL` (same price
with a $9.99-off ×12 coupon — set `max_redemptions=100` on the coupon as the backstop
against concurrent-checkout overshoot). Neither set → demo checkout, which
auto-activates and still exercises founder logic.

QC: `qc_membership_regression.py`, `qc_plan_access_matrix.py`, `qc_checkout_readiness.py`.

---

## 12. Where the deep detail lives

| Doc | For |
|---|---|
| `docs/PROJECT_MAP.md` | **Read first.** Living source-of-truth; most of this file is distilled from it |
| `DEVELOPER_HANDOFF.md` | Product shape, data flow, Stripe, legal pages |
| `SITE_ARCHITECTURE.md` | Routes, templates, nav |
| `docs/aws_runbook.md` | Standing up the EC2 host end to end |
| `docs/deployment.md` | Deploy specifics |
| `PROP_MODEL_V2_SPEC.md`, `BASELINE_PROP_TEMPLATE_COMPARISON.md` | Prop model |
| `docs/bk_edge_engine_master_checklist.md` | Edge Engine (largest doc, 928 lines) |
| `docs/platform_prelaunch_checklist.md`, `docs/platform_qa_checklist.md`, `docs/visual_qa_checklist.md` | Launch + QA gates |
| `docs/best_lines_quick_tool_handoff.md` | Quick Tools reference implementation |
| `docs/cfb_player_data_model.md`, `docs/ncaaf_game_line_formula.md`, `docs/football_historical_data_guide.md` | Football/CFB |
| `docs/FRANCHISE_KINGS_HANDOFF.md`, `docs/franchise_*.md` | Franchise mode |
| `docs/stripe_checkout_setup.md` | Payments setup |
| `DATA_REFRESH_README.md` | Refresh lanes |

---

## 13. Open items

- **Injury Report "impact" (with/without):** NBA + NFL live; **MLB/WNBA not built** —
  needs a per-sport gamelog split engine like `calculate_nfl_teammate_boosts`.
- **Football `LONGSHOT OVER` guardrail — BUILT (61df4ef, 2026-09-03), not open.**
  `build_football_live_prop_board` flags overs under 25% implied: sets `longshot_over`,
  prepends the `LONGSHOT OVER` method tag, appends the cost note, and applies
  `score -= 8.0` so long-odds overs don't headline the board. `docs/PROJECT_MAP.md` §8
  still describes this as unbuilt — that entry is stale; trust the code.
  The football board has no `play_verdict`, but that is **deliberate**, not a gap:
  `sport_registry.py` sets `requires_play_verdict=False` for NFL and NCAAF (only
  MLB/WNBA gate archiving on it). What genuinely remains is **evidence**, not code —
  the 25% threshold is MLB/WNBA-derived, and football needs its own graded ROI to
  confirm or kill it. Per §10, out-of-sample or it does not count.
- **`NFL_PlayerStats_<yr>.csv` is built locally and gitignored.** 2023–25 were one-time
  copied to prod. For in-season freshness, wire
  `build_nfl_player_stats_from_pbp.py` for the current season into the prod football
  refresh — today the gamelog rebuild runs off static 2023–25 input.
- **College hoops:** Command Center and themed Props/Market/Trends/Parlay shells are
  built; real data and boards are not.
- **Fantasy Salary / Value / Own%** need a DFS slate provider decision (SportsDataIO or
  FantasyData) — a user decision, then wiring. **No salaries, no contests** by
  deliberate choice (money-league legal risk).
- **Parlay floor-reliability for football** fills in automatically once the season
  generates resolved floor plays. Nothing to build.
- Premium nav icons are raster PNG from generated art — not vectorizable without a redraw.

---

## 14. Working conventions

- **Establish local vs prod before theorising.** Most "it's broken" reports are one or
  the other, and the fix differs.
- **Suspect the cache before the logic** (§4), and **earlyoom before the code** on prod
  (§2).
- **`app.py` is 41k lines.** Refactor gradually and checkpoint first. Do not attempt a
  sweeping reorganisation in one pass.
- **Run the matching `qc_*.py`** for whatever you changed before committing.
- **Update `docs/PROJECT_MAP.md` and this file** when you learn something that would
  otherwise have to be re-derived. That is the whole point of both.
