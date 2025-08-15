import os, json
from typing import List, Dict
import pandas as pd
import requests
import argparse

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("Set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars.")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# nflverse season parquet (public parquet per season)
URL_TMPL = "https://github.com/nflverse/nflfastR-data/raw/master/data/play_by_play/parquet/play_by_play_{season}.parquet"

def chunks(rows: List[Dict], n: int = 1000):
    for i in range(0, len(rows), n):
        yield rows[i:i+n]

def upsert_pbp(rows: List[Dict]):
    url = f"{SUPABASE_URL}/rest/v1/pbp_raw?on_conflict=game_id,play_id"
    r = requests.post(url, headers={**HEADERS, "Prefer": "resolution=merge-duplicates"}, data=json.dumps(rows))
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"Upsert failed: {r.status_code} {r.text}")

def transform(df: pd.DataFrame):
    out: List[Dict] = []
    it = df[["game_id","play_id","season","week","posteam","defteam","qtr","game_seconds_remaining",
             "play_type","yards_gained","rush","pass","passer_player_name","rusher_player_name","receiver_player_name"]].itertuples(index=False, name=None)
    for (game_id, play_id, season, week, posteam, defteam, qtr, gsr,
         play_type, yards_gained, rush, ppass, passer, rusher, receiver) in it:
        out.append({
            "game_id": str(game_id),
            "play_id": int(play_id),
            "season": int(season),
            "week": int(week) if pd.notna(week) else None,
            "posteam": str(posteam) if pd.notna(posteam) else None,
            "defteam": str(defteam) if pd.notna(defteam) else None,
            "qtr": int(qtr) if pd.notna(qtr) else None,
            "clock": str(gsr) if pd.notna(gsr) else None,
            "play_type": str(play_type) if pd.notna(play_type) else None,
            "yards_gained": float(yards_gained) if pd.notna(yards_gained) else None,
            "rush_attempt": int(rush) if pd.notna(rush) else 0,
            "pass_attempt": int(ppass) if pd.notna(ppass) else 0,
            "passer": str(passer) if pd.notna(passer) else None,
            "rusher": str(rusher) if pd.notna(rusher) else None,
            "receiver": str(receiver) if pd.notna(receiver) else None,
            # Keep a compact json for future transforms if needed
            "json_row": {
                "game_id": game_id, "play_id": play_id, "season": season, "week": week,
                "posteam": posteam, "defteam": defteam, "qtr": qtr, "gsr": gsr,
                "play_type": play_type, "yards_gained": yards_gained,
                "rush": rush, "pass": ppass, "passer": passer, "rusher": rusher, "receiver": receiver
            },
            "src": "nflverse",
        })
    return out

def load_season(season: int):
    url = URL_TMPL.format(season=season)
    print(f"Downloading {season} from {url}")
    df = pd.read_parquet(url)  # requires pyarrow
    rows = transform(df)
    print(f"Upserting {len(rows):,} plays for {season}")
    for batch in chunks(rows, 1000):
        upsert_pbp(batch)
    print(f"Done {season}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="season_from", type=int, default=2020)
    parser.add_argument("--to", dest="season_to", type=int, default=2024)
    args = parser.parse_args()
    for season in range(args.season_from, args.season_to + 1):
        load_season(season)
    print("Backfill complete.")

if __name__ == "__main__":
    main()
