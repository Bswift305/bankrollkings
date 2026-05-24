# CFB Player Data Model

This is the clean model for college-football player continuity and transfer tracking inside Bankroll Kings.

## Core Idea

For CFB, the right order is:

1. historical game-line and totals context
2. current team roster
3. last-season and career player production
4. transfer and returning-production logic

The site should not rely on player props first, but player production still matters because returning quarterbacks, running backs, receivers, and defensive contributors affect sides, totals, and matchup confidence.

## Source Files

Current roster:

- `data/rosters/NCAAF_CurrentRoster.csv`

Historical player stats:

- `data/historical/NCAAF_PlayerStats_History.csv`

Generated master table:

- `data/tracking/NCAAF_PlayerMaster.csv`

## Current Roster Columns

- `PlayerID`
- `Player`
- `CurrentTeam`
- `Position`
- `Class`
- `Height`
- `Weight`
- `Jersey`
- `Status`

## Historical Player Stats Columns

- `PlayerID`
- `Player`
- `Team`
- `Position`
- `Class`
- `Season`
- `Games`
- `PassYds`
- `PassTD`
- `PassInt`
- `RushYds`
- `RushTD`
- `Receptions`
- `RecYds`
- `RecTD`
- `Tackles`
- `Sacks`
- `DefInt`

## Output Logic

The generated player master table should answer:

- where is the player now?
- where did he play last season?
- is he a transfer?
- what production is he bringing with him?
- what is his career production?

Important fields:

- `CurrentTeam`
- `LastSeasonTeam`
- `TransferFlag`
- `CareerGames`
- `CareerPassYds`
- `CareerPassTD`
- `CareerPassInt`
- `CareerRushYds`
- `CareerRushTD`
- `CareerReceptions`
- `CareerRecYds`
- `CareerRecTD`
- `CareerTackles`
- `CareerSacks`
- `CareerDefInt`

## Build Command

Once the two source files are populated:

```powershell
py build_ncaaf_player_master.py
```

Optional:

```powershell
py build_ncaaf_player_master.py --last-season 2025
```

## Import Workflow

If your source exports are messy, normalize them first:

Current roster:

```powershell
py normalize_ncaaf_current_roster.py path\to\raw_roster.csv
```

Player stats:

```powershell
py normalize_ncaaf_player_stats.py path\to\raw_player_stats.csv
```

Then build the master table:

```powershell
py build_ncaaf_player_master.py --last-season 2025
```

## CFBD Direct Workflow

If you want to skip manual exports and pull straight from CollegeFootballData:

```powershell
py fetch_cfbd_current_roster.py --year 2026
py fetch_cfbd_player_stats.py --year 2025
py fetch_cfbd_returning_production.py --year 2026
py fetch_cfbd_transfer_portal.py --year 2026
py build_ncaaf_player_master.py --last-season 2025
```

These scripts expect a server-side key via `CFBD_API_KEY` or `--api-key`.

## Why This Matters

This lets the college-football engine answer questions like:

- how much offensive production returns for this team?
- how much production transferred in?
- did the team lose its quarterback, lead back, or WR1?
- is this a continuity offense or a rebuild offense?
- does the returning defensive production support an under or ATS angle?
