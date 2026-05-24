# 🏀 Floor Play Engine - Data Refresh Guide

## Quick Start

### Option 1: Automatic Refresh (Recommended)
1. Double-click `REFRESH_DATA.bat`
2. Wait 10-20 minutes for all data to download
3. Run `RUN.bat` to start the app with fresh data

### Option 2: Manual Python Run
```
pip install nba_api
python refresh_data.py
```

---

## What Gets Updated

| File | Source | Auto-Updates? |
|------|--------|---------------|
| `data/rosters/NBA_Rosters.csv` | NBA.com | ✅ Yes |
| `data/gamelogs/NBA_GameLogs.csv` | NBA.com | ✅ Yes |
| `data/schedules/NBA_Schedule.csv` | NBA.com | ✅ Yes |
| `data/injuries/NBA_Injuries.csv` | ESPN | ❌ Manual |
| `data/props/NBA_Props.csv` | DraftKings | ❌ Manual |

---

## Manual Updates (Injuries & Props)

### Injuries
The nba_api doesn't provide injury data. Update manually:

1. Go to: https://www.espn.com/nba/injuries
2. Copy data into `data/injuries/NBA_Injuries.csv`
3. Format: `Player,Team,Position,Status,Injury,Date`

Example:
```
Player,Team,Position,Status,Injury,Date
LeBron James,LAL,F,OUT,Left Foot Soreness,2025-01-18
Stephen Curry,GSW,G,GTD,Knee,2025-01-18
```

Status values: OUT, DOUBTFUL, QUESTIONABLE, GTD (Game Time Decision), PROBABLE

### Props (DraftKings Lines + Market Tracking)
1. Go to: https://sportsbook.draftkings.com/leagues/basketball/nba
2. Select a game → Player Props
3. Export or copy data into `data/props/NBA_Props.csv`
4. Minimum format: `Player,Team,Stat,Line,Game`
5. Recommended sharp format: use `data/props/NBA_Props_template.csv`
6. Fast import option:
```
py import_props.py --input raw_props.csv
```
7. Live Odds API pull:
```
$env:ODDS_API_KEY="your_rotated_key"
py fetch_player_props.py --bookmakers draftkings --days 5
```

Example:
```
Player,Team,Stat,Line,Game,Book,LastUpdated,OpenLine,CurrentLine,CloseLine,OpenOverOdds,OpenUnderOdds,OverOdds,UnderOdds,CloseOverOdds,CloseUnderOdds,BetLine,BetOverOdds,BetUnderOdds,BetBook,BetTime
LeBron James,LAL,PTS,25.5,LAL@DEN,DraftKings,2026-04-15 18:30,24.5,25.5,, -110,-110,-115,-105,,,25.5,-110,,DraftKings,2026-04-15 18:42
Stephen Curry,GSW,3PM,5.5,GSW@LAC,FanDuel,2026-04-15 18:31,5.5,5.5,, -102,-125,-104,-122,,,5.5,-104,,FanDuel,2026-04-15 18:45
```

What the new columns do:
- `OpenLine` / `CurrentLine` / `CloseLine`: line movement tracking
- `OverOdds` / `UnderOdds`: current book price for EV math
- `BetLine` / `BetOverOdds` / `BetUnderOdds`: your actual entry, used for CLV
- `Book` / `BetBook`: source book
- `import_props.py`: converts rough CSV/XLS/XLSX exports into the app format

---

## Rate Limits

The nba_api has rate limits. If you see errors:
- Wait 30-60 seconds and try again
- The script automatically pauses between requests
- Full refresh takes 10-20 minutes

---

## Troubleshooting

### "nba_api not found"
```
pip install nba_api
```

### "Rate limited" or timeout errors
- Wait a few minutes
- Run the script again (it's safe to re-run)

### Player on wrong team
- Run `REFRESH_DATA.bat` to get current rosters
- This pulls directly from NBA.com with correct team assignments

---

## Recommended Refresh Schedule

| When | What to Update |
|------|----------------|
| Daily (before betting) | Props, Injuries |
| Weekly | Game logs, Rosters |
| After trades | Rosters immediately |

---

## File Locations

```
C:\NBA_Floor_Plays\
├── app.py                 # Main application
├── refresh_data.py        # Data refresh script
├── RUN.bat               # Start the app
├── REFRESH_DATA.bat      # Refresh all data
├── data\
│   ├── gamelogs\NBA_GameLogs.csv
│   ├── props\NBA_Props.csv
│   ├── injuries\NBA_Injuries.csv
│   ├── schedules\NBA_Schedule.csv
│   └── rosters\NBA_Rosters.csv
└── templates\            # HTML templates
```

---

## Going Live (Paid APIs)

When you're ready for real-time data:

| Service | Price | Features |
|---------|-------|----------|
| BALLDONTLIE | ~$20-50/mo | Stats + Props + Odds + Injuries |
| The Odds API | Free tier + paid | Odds from multiple sportsbooks |
| SportsDataIO | $99+/mo | Enterprise-level data |

For now, the free nba_api + manual prop updates works great for development!
