# -*- coding: utf-8 -*-
"""
MLB "Real vs Luck" board — separate contact-earned production from luck, per Statcast.

Our 178k-graded-prop study proved MLB streaks are already in the price (see
project_market_efficiency_findings). Expected-stats gaps are a DIFFERENT, legitimate
read: a hitter whose wOBA sits far above his xwOBA is riding luck (results better than
his contact quality) and is a regression-DOWN candidate; one whose xwOBA sits above his
wOBA has hit into bad luck and is a bounce-back candidate. This is honest, provably-
computed CONTENT (not a claimed ROI edge) from data already on disk.

Data: data/statcast/MLB_Statcast_{Hitters,Pitchers}_2026.csv (season aggregates:
actual vs expected BA/SLG/wOBA, barrels, hard-hit%, K/whiff percentiles).

    python research/mlb_statcast/mlb_luck_board.py hitters
    python research/mlb_statcast/mlb_luck_board.py pitchers
    python research/mlb_statcast/mlb_luck_board.py hitters --min 250
"""
import sys, argparse, pathlib
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
HIT  = ROOT / "data" / "statcast" / "MLB_Statcast_Hitters_2026.csv"
PIT  = ROOT / "data" / "statcast" / "MLB_Statcast_Pitchers_2026.csv"

def load(path):
    df = pd.read_csv(path)
    # gap = xwOBA - wOBA. >0 unlucky (bounce-back); <0 lucky (regress toward worse output)
    df["gap"] = pd.to_numeric(df["Expected_est_woba"], errors="coerce") - pd.to_numeric(df["Expected_woba"], errors="coerce")
    df["ba_gap"] = pd.to_numeric(df["Expected_est_ba"], errors="coerce") - pd.to_numeric(df["Expected_ba"], errors="coerce")
    df["pa"] = pd.to_numeric(df["Expected_pa"], errors="coerce")
    return df

def _row(r, side):
    hh = r.get("Percentile_hard_hit_percent"); brl = r.get("Barrel_brl_percent")
    return (f"{str(r['Player'])[:20]:<20}{int(r['pa']):>5}"
            f"{r['Expected_woba']:>8.3f}{r['Expected_est_woba']:>8.3f}{r['gap']:>+8.3f}"
            f"{(hh if pd.notna(hh) else float('nan')):>7.0f}{(brl if pd.notna(brl) else float('nan')):>7.1f}")

def board(kind, minpa):
    df = load(HIT if kind=="hitters" else PIT)
    df = df[df["pa"] >= minpa].dropna(subset=["gap"])
    if df.empty: print("no qualifiers."); return
    who = "HITTER" if kind=="hitters" else "PITCHER (wOBA against)"
    # For hitters: gap<0 = lucky (sell-high), gap>0 = unlucky (buy-low).
    # For pitchers it's flipped in meaning: wOBA-against below xwOBA (gap>0) = pitcher lucky.
    hdr = f"{'Player':<20}{'PA':>5}{'wOBA':>8}{'xwOBA':>8}{'Gap':>8}{'HardH%':>7}{'Brl%':>7}"
    if kind=="hitters":
        lucky = df.sort_values("gap").head(15)          # most negative gap
        unlucky = df.sort_values("gap", ascending=False).head(15)
        print(f"MLB {who} — OVERPERFORMING (wOBA >> xwOBA = luck, regression DOWN likely)   min {minpa} PA")
        print("="*65); print(hdr)
        for _,r in lucky.iterrows(): print(_row(r,kind))
        print(f"\nMLB {who} — UNDERPERFORMING (xwOBA >> wOBA = unlucky, BOUNCE-BACK likely)")
        print("="*65); print(hdr)
        for _,r in unlucky.iterrows(): print(_row(r,kind))
    else:
        # pitcher: gap = xwOBA_against - wOBA_against. gap>0 -> results better than contact -> LUCKY (worsen)
        lucky = df.sort_values("gap", ascending=False).head(15)
        unlucky = df.sort_values("gap").head(15)
        print(f"MLB {who} — OUTPERFORMING CONTACT (results better than xwOBA = luck, ERA likely to RISE)   min {minpa} BF")
        print("="*65); print(hdr)
        for _,r in lucky.iterrows(): print(_row(r,kind))
        print(f"\nMLB {who} — UNLUCKY (worse results than contact = due to IMPROVE)")
        print("="*65); print(hdr)
        for _,r in unlucky.iterrows(): print(_row(r,kind))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("kind", nargs="?", default="hitters", choices=["hitters","pitchers"])
    ap.add_argument("--min", type=int, default=200)
    a = ap.parse_args()
    board(a.kind, a.min)
