# -*- coding: utf-8 -*-
"""
Pull Statcast pitch-by-pitch for a season via pybaseball, slim it, save to
data/pbp/MLB_statcast_pbp_<year>.parquet — the flat event table the MLB
Situational Lab is built from (count / base-out / handedness / pitch type /
outcome on every pitch). Chunked by month so a hiccup only loses one month.

    python research/mlb_statcast/fetch_mlb_pbp.py 2025
    python research/mlb_statcast/fetch_mlb_pbp.py 2023 2024 2025
"""
import sys, pathlib, warnings
warnings.filterwarnings("ignore")
import pandas as pd
from pybaseball import statcast
try:
    from pybaseball import cache; cache.enable()
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT  = ROOT / "data" / "pbp"; OUT.mkdir(parents=True, exist_ok=True)

KEEP = ["game_date","game_pk","home_team","away_team","inning","inning_topbot",
        "at_bat_number","pitch_number","balls","strikes","outs_when_up",
        "on_1b","on_2b","on_3b","stand","p_throws","pitch_type","pitch_name",
        "events","description","type","zone","batter","pitcher","player_name",
        "bat_score","fld_score","post_bat_score","post_fld_score",
        "estimated_woba_using_speedangle","woba_value",
        "woba_denom","babip_value","launch_speed","launch_angle"]

# regular-season windows (spring training + postseason trimmed by these bounds)
MONTHS = [("03-15","04-30"),("05-01","05-31"),("06-01","06-30"),
          ("07-01","07-31"),("08-01","08-31"),("09-01","10-05")]

def pull_year(yr):
    frames = []
    for a, b in MONTHS:
        start, end = f"{yr}-{a}", f"{yr}-{b}"
        try:
            d = statcast(start_dt=start, end_dt=end)
        except Exception as e:
            print(f"  {start}..{end}  ERROR {e}"); continue
        if d is None or d.empty:
            print(f"  {start}..{end}  (0)"); continue
        d = d[[c for c in KEEP if c in d.columns]].copy()
        frames.append(d)
        print(f"  {start}..{end}  {len(d):,}")
    if not frames:
        print(f"{yr}: no data"); return
    allp = pd.concat(frames, ignore_index=True)
    allp["season"] = yr
    dest = OUT / f"MLB_statcast_pbp_{yr}.parquet"
    allp.to_parquet(dest, index=False)
    print(f"WROTE {dest}  ({len(allp):,} pitches, {allp.shape[1]} cols, {dest.stat().st_size/1e6:.1f} MB)")

if __name__ == "__main__":
    years = [int(y) for y in sys.argv[1:]] or [2025]
    for y in years:
        print(f"=== {y} ==="); pull_year(y)
