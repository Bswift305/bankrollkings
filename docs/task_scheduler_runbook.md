# Bankroll Kings Task Scheduler Runbook

This is the recommended Windows Task Scheduler cadence for local automated refreshes.

## Installed Tasks

- `Bankroll Kings - Football Refresh` at `05:30`
- `Bankroll Kings - NBA Daily Refresh` at `06:00`
- `Bankroll Kings - Prelaunch Scorecard` at `06:45`
- `Bankroll Kings - WNBA Refresh` at `07:00`
- `Bankroll Kings - MLB Refresh` at `08:00`
- `Bankroll Kings - All Sport Injuries AM` at `10:30`
- `Bankroll Kings - All Sport Injuries PM` at `15:30`
- `Bankroll Kings - All Sport Injuries Evening` at `18:30`

## Why This Cadence

- Morning refreshes rebuild the main sport data before the workday.
- Injury refreshes run multiple times because GTD / lineup context moves during the day.
- The scorecard runs after the morning data layer so readiness issues show up early.

## Install

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
powershell -ExecutionPolicy Bypass -File .\install_task_schedules.ps1
```

## Silent Task Scripts

- [TASK_refresh_nba_daily.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_refresh_nba_daily.bat)
- [TASK_refresh_wnba_data.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_refresh_wnba_data.bat)
- [TASK_refresh_mlb_data.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_refresh_mlb_data.bat)
- [TASK_refresh_football_data.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_refresh_football_data.bat)
- [TASK_refresh_all_sport_injuries.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_refresh_all_sport_injuries.bat)
- [TASK_run_prelaunch_scorecard.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\TASK_run_prelaunch_scorecard.bat)

## Verify

```powershell
schtasks /Query /TN "Bankroll Kings - NBA Daily Refresh"
schtasks /Query /TN "Bankroll Kings - All Sport Injuries PM"
```

## Logs

Task logs are written under:

- `logs\refresh_nba_daily.log`
- `logs\refresh_wnba.log`
- `logs\refresh_mlb.log`
- `logs\refresh_football.log`
- `logs\injuries_all_sports_YYYYMMDD.log`
- `logs\prelaunch_scorecard.log`

## Notes

- If live Stripe is not configured yet, the scorecard can still stay `NO-GO`; that is expected.
- CFB injury feed is still manual-only until a live source is added.
