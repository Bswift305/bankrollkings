# Football Historical Data Guide

Use these files to build the football section from prior seasons instead of waiting on the current live feed.

## Props History

Files:

- `data/historical/NFL_Props_History.csv`
- `data/historical/NCAAF_Props_History.csv`

Required columns:

- `Date`
- `Season`
- `Week`
- `Player`
- `Team`
- `Opponent`
- `Stat`
- `Line`
- `Actual`
- `Book`
- `Game`

Meaning:

- one row per historical prop market
- `Line` is the Vegas/book number that was offered
- `Actual` is what the player actually finished with
- `Stat` should match football prop labels such as:
  - `Pass Yds`
  - `Pass TDs`
  - `Pass Completions`
  - `Rush Yds`
  - `Rush Att`
  - `Receptions`
  - `Rec Yds`
  - `Anytime TD`

This powers:

- hot-hand continuation testing
- over/under streak follow rates
- last-season and last-5-season prop pattern analysis

## Game Lines History

Files:

- `data/historical/NFL_GameLines_History.csv`
- `data/historical/NCAAF_GameLines_History.csv`

Required columns:

- `Date`
- `Season`
- `Week`
- `Away`
- `Home`
- `Spread`
- `Total`
- `AwayScore`
- `HomeScore`

Meaning:

- one row per historical game
- `Spread` is the closing or tracked game spread from the home team perspective currently used by the site
- `Total` is the posted game total
- scores are final results

This powers:

- ATS streak follow-through
- over/under streak follow-through
- last 5 games vs last season vs last 5 seasons pattern work

### Quick College Import Path

If you find a raw college-football historical lines CSV from another source, normalize it with:

```powershell
py normalize_ncaaf_historical_game_lines.py path\to\source.csv
```

That writes a cleaned file to:

- `data/historical/NCAAF_GameLines_History.csv`

The importer already tries to map common source column names like:

- `away_team` / `home_team`
- `spread_line`
- `total_line`
- `away_score` / `home_score`

and it also normalizes many CFB team-name variants into the names the site expects.

## Current Football Build Goal

The football section is being built around:

1. `Hot hand` first
2. `Game lines / totals` as co-primary with props
3. `Last 5 games`
4. `Last season`
5. `Last 5 seasons`

Once these files are populated, the football method pages will stop being framework-only and start showing real historical research summaries.
