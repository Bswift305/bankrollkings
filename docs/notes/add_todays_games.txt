from nba_api.live.nba.endpoints import scoreboard
import pandas as pd
from datetime import datetime

print("Fetching today's games from NBA.com...")

b = scoreboard.ScoreBoard().get_dict()

games = []
for g in b['scoreboard']['games']:
    games.append({
        'Date': datetime.now().strftime('%Y-%m-%d'),
        'Time': g.get('gameStatusText', ''),
        'Away': g['awayTeam']['teamTricode'],
        'Home': g['homeTeam']['teamTricode'],
        'Total': '',
        'Spread': ''
    })

print(f"Found {len(games)} games:")
for g in games:
    print(f"  {g['Away']} @ {g['Home']}")

df = pd.DataFrame(games)
old = pd.read_csv('data/schedules/NBA_Schedule.csv')
combined = pd.concat([df, old], ignore_index=True)
combined = combined.drop_duplicates(subset=['Date', 'Away', 'Home'], keep='first')
combined.to_csv('data/schedules/NBA_Schedule.csv', index=False)
print("\nSaved to schedule!")
