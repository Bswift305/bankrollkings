python - <<'PY'
import os, json, pandas as pd, requests

URL_TMPL = "https://github.com/nflverse/nflfastR-data/raw/master/data/play_by_play/parquet/play_by_play_{season}.parquet"
SUPA_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
SUPA_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
assert SUPA_URL and SUPA_KEY, "Set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first."

HEADERS = {
  "apikey": SUPA_KEY,
  "Authorization": f"Bearer {SUPA_KEY}",
  "Content-Type": "application/json",
  "Prefer": "resolution=merge-duplicates"
}

def upsert(rows):
    if not rows: return
    url = f"{SUPA_URL}/rest/v1/pbp_raw?on_conflict=game_id,play_id"
    r = requests.post(url, headers=HEADERS, data=json.dumps(rows), timeout=120)
    if r.status_code not in (200,201,204): raise SystemExit(f"Upsert failed: {r.status_code} {r.text}")

def transform(df):
    cols = ["game_id","play_id","season","week","posteam","defteam","qtr",
            "game_seconds_remaining","play_type","yards_gained","rush","pass",
            "passer_player_name","rusher_player_name","receiver_player_name"]
    df = df[cols]
    out = []
    for t in df.itertuples(index=False, name=None):
        (game_id, play_id, season, week, posteam, defteam, qtr, gsr,
         play_type, yards_gained, rush, ppass, passer, rusher, receiver) = t
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
            "json_row": {},  # keep small to reduce payload size
            "src": "nflverse",
        })
    return out

def load_season(season):
    url = URL_TMPL.format(season=season)
    print(f"Downloading {season} … {url}", flush=True)
    df = pd.read_parquet(url)  # requires pyarrow installed
    rows = transform(df)
    print(f"Upserting {len(rows):,} plays for {season}", flush=True)
    # batches of 1000
    for i in range(0, len(rows), 1000):
        upsert(rows[i:i+1000])
    print(f"Done {season}", flush=True)

# ---- change this list to load more years ----
for yr in [2020]:
    load_season(yr)

print("Backfill complete.")
PY

