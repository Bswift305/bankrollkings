import os, json, argparse
from typing import List, Dict
import pandas as pd
import requests

# ---------- Config ----------
# Public NFLverse parquet per season (free)
URL_TMPL = "https://github.com/nflverse/nflfastR-data/raw/master/data/play_by_play/parquet/play_by_play_{season}.parquet"

# Supabase env (must be set in your terminal before running)
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")  # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")  # service_role key

if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("Set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars first.")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

# ---------- Helpers ----------
def chunks(rows: List[Dict], n: int = 1000):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]

def upsert_pbp(rows: List[Dict]):
    """Upsert a batch into pbp_raw via Supabase REST."""
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/pbp_raw?on_conflict=game_id,play_id"
    r = requests.post(url, headers=HEADERS, data=json.dumps(rows), timeout=120)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"Upsert failed: {r.status_code} {r.text}")

def transform(df: pd.DataFrame) -> List[Dict]:
    """Pick the columns we need and map to pbp_raw schema."""
    cols = [
        "game_id",
        "play_id",
        "season",
        "week",
        "posteam",
        "defteam",
        "qtr",
        "game_seconds_remaining",
        "play_type",
        "yards_gained",
        "rush",
        "pass",
        "passer_player_name",
        "rusher_player_name",
        "receiver_player_name",
    ]
    df = df[cols]
    out: List[Dict] = []
    for (
        game_id,
        play_id,
        season,
        week,
        posteam,
        defteam,
        qtr,
        gsr,
        play_type,
        yards_gained,
        rush,
        ppass,
        passer,
        rusher,
        receiver,
    ) in df.itertuples(index=False, name=None):
        out.append(
            {
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
                "json_row": {},  # keep payload smal_
