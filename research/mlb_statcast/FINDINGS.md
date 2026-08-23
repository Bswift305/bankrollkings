# MLB — what's honest and buildable (2026-08-22)

## The data reality (checked, not assumed)
- **No historical totals/line data locally.** `data/odds/MLB_Odds.csv` is only today's
  ~90-game slate; game logs (`data/gamelogs/MLB_GameLogs.csv`, 69k rows) are **2026-only**.
  → We **cannot honestly backtest an MLB totals or NRFI betting edge** — that needs historical
  closing lines joined to results, the same bar the NFL/CFB research met with `*History*` files.
  MLB has none locally. Don't sell a totals/NRFI edge until we capture lines forward or import history.
- **Umpire profiles are empty** (`MLB_UmpireProfiles.csv` = 0 rows); assignments reference blank
  zone/run-impact. The umpire-on-totals angle is dead until that feed is populated.
- **Props are efficiently priced** (our 178k-graded-prop study — streaks/defense/steam all in the
  number; only avoidance rules survive). See project_market_efficiency_findings.

## What IS honest and buildable right now: "Real vs Luck" (Statcast expected stats)
`data/statcast/MLB_Statcast_{Hitters,Pitchers}_2026.csv` carry **actual vs expected** BA/SLG/wOBA
plus hard-hit%, barrel%, K/whiff percentiles (553 hitters / 608 pitchers, 2026 season).

`research/mlb_statcast/mlb_luck_board.py` computes **gap = xwOBA − wOBA**:
- **Hitter gap < 0** (wOBA >> xwOBA) → production is luck, regression **down** likely (sell-high).
- **Hitter gap > 0** (xwOBA >> wOBA) → hit into bad luck, **bounce-back** likely (buy-low).
- Pitchers mirror it (results better than contact quality → ERA likely to rise).

This is honest CONTENT, not a claimed ROI edge — and it's the legitimate answer to the streak
question our research showed is priced ("is this bat hot for real, or luck?").

### Verified output (min 300 PA, 2026) — the signal self-corroborates via hard-hit%
- **Overperformers (luck):** Jake McCarthy (.361 wOBA / .308 xwOBA, **4% hard-hit**), Luis Arraez
  (**1% hard-hit**), Ernie Clement, Chandler Simpson (**1% hard-hit**) — classic low-contact-quality
  BABIP luck. Regression-down candidates.
- **Underperformers (unlucky):** Bobby Witt Jr (.346 / .386, **94% hard-hit**), Yordan Alvarez
  (**96%**), Mike Trout, Tatis, Vlad Jr, Nimmo — elite contact hitting into bad luck. Bounce-back.
- Hard-hit% moves exactly the right way in both lists → the read is real, not noise.

## UPDATE — MLB Situational Lab BUILT (2026-08-22) ✅
Grabbed pitch-by-pitch via **pybaseball** (already installed): `fetch_mlb_pbp.py` pulled
2025 → `data/pbp/MLB_statcast_pbp_2025.parquet` (**761,524 pitches / 195,823 PA**, 34 cols;
gitignored). `mlb_situational.py` (CLI engine) + `build_mlb_situational_export.py` (site
JSON) grade hitters & pitchers by situation from real PAs:
- **Hitters:** overall · vs RHP · vs LHP · RISP · bases empty. Metrics wOBA / K% / BB% /
  Hard-Hit% / HR. Verified: Judge #1 vs LHP (.569 wOBA, 64% hard-hit), #1 overall (.496, 54 HR).
- **Pitchers (wOBA against):** overall · vs RHB · vs LHB · 1st/3rd+ time through order ·
  first inning. Verified: Chapman #1 overall (.199, 38% K); Eovaldi/Crochet/Yamamoto hold
  up 3rd time through. Batter names resolved via `playerid_reverse_lookup` (cached).
Site page `/tools/mlb-situational` (all_access), export `data/scenarios/mlb_situational.json`.
To add seasons: `python fetch_mlb_pbp.py 2023 2024`, then rerun the export builder.

## Recommendation
1. **Productize "Real vs Luck"** as an MLB module (same shape as the NFL Scenario Lab: a clean
   sortable board, "for real" vs "fool's gold", corroborated by hard-hit%/barrel%). Data is on disk.
2. **Full MLB Situational Lab** (count 0-2/3-1, vs LHP/RHP, RISP, pitch type, times-through-order,
   first inning/NRFI) needs **pitch-by-pitch Statcast** (via `pybaseball.statcast(start, end)` → the
   raw pitch table with balls/strikes/on-base/pitch_type/events). That's the MLB equivalent of the
   NFL pbp — grab it, then the engine is the same pattern.
3. **Do NOT** ship totals/NRFI as edges until historical lines exist to prove them.
