# NCAAF Game-Line Formula

NCAAF is a sides/totals product first. Player props are optional support, not the primary formula surface.

## Data Responsibilities

CFBD:

- historical games and final scores
- historical lines when available
- returning production
- transfer portal movement
- player/team production history
- roster continuity

The Odds API:

- current board
- live sportsbook spreads
- live sportsbook totals
- moneylines
- book disagreement and market movement snapshots

TeamRankings historical research import:

- last-season team scoring/offensive/defensive stat tables
- historical formula research only
- not a live 2026 customer-facing dependency

## Core Formula

```text
BK CFB EdgeScore =
Roster Continuity Edge
+ Returning Production Edge
+ Transfer Stability Edge
+ Team Context Edge
+ Market Line Value
- Volatility Penalty
```

## Current Scripts

- `fetch_cfbd_game_lines_history.py`
  - pulls historical NCAAF game lines from CFBD `/lines`
  - writes `data/historical/NCAAF_GameLines_History.csv`

- `fetch_ncaaf_historical_game_lines_oddsapi.py`
  - pulls historical NCAAF sportsbook line snapshots from The Odds API
  - writes `data/historical/NCAAF_OddsAPI_GameLines_History.csv`
  - this supplies market history; final scores still come from CFBD or imported team/game stats

- `build_ncaaf_game_line_backfill.py`
  - grades historical spreads and totals
  - writes `data/tracking/NCAAF_GameLineResults.csv`
  - stamps `IsBackfill=True`

- `calculate_ncaaf_edge_score.py`
  - merges game-line rows with returning production, portal, and player-master context
  - uses historical TeamRankings research stats when available
  - writes `data/tracking/NCAAF_GameLineResults_Scored.csv`
  - stamps `ModelVersion=NCAAF_EdgeScore_v1`

- `import_teamrankings_ncaaf_historical_stats.py`
  - imports historical NCAAF team stats from TeamRankings stat pages
  - writes a long research file and a team-wide formula file
  - stamps `Source=teamrankings_historical_research` and `IsBackfill=True`
  - intended only for last-season formula research, not the 2026 live product

- `calibrate_cfb_model.py`
  - now prefers scored game-line rows over prop-only featured rows
  - writes `data/tracking/NCAAF_Calibration_Report.csv`

## Backfill Workflow

```powershell
$env:CFBD_API_KEY="..."
py fetch_cfbd_game_lines_history.py --start-year 2024 --end-year 2025
py build_ncaaf_game_line_backfill.py
py calculate_ncaaf_edge_score.py
py calibrate_cfb_model.py
```

Historical TeamRankings supplement:

```powershell
py import_teamrankings_ncaaf_historical_stats.py --season 2025 --delay 0.8
```

If CFBD lines are unavailable or we want sportsbook-specific snapshots from The Odds API:

```powershell
$env:ODDS_API_KEY="..."
py fetch_ncaaf_historical_game_lines_oddsapi.py --start-date 2025-08-23 --end-date 2026-01-20 --interval-days 1 --days-ahead 7
```

Important: Odds API historical line snapshots do not grade themselves. To turn those rows into hit/miss ATS and total results, we still need final scores from CFBD games or an imported game-result/team-stat file.

## Live Workflow

```powershell
$env:ODDS_API_KEY="..."
py fetch_ncaaf_game_lines.py --days 14
```

The live row path stays separate from the historical backfill path. Historical rows are `IsBackfill=True`; live/current board rows remain live market context until they are graded.

## Current State

- CFBD API key is not configured on this machine yet.
- Current Odds API NCAAF board returned zero rows because the sport is offseason.
- Existing team context can already load from NCAAF roster/returning/portal data.
- TeamRankings historical research import is active and currently writes `136` team rows across `20` curated stat pages.
- CBB remains a separate future lane while the source stats are being collected.
