# -*- coding: utf-8 -*-
"""
CFB "Regression Watch" — the Phil-Steele-style preseason lens, built from our OWN
public data (no magazine content copied). Flags teams whose 2025 RECORD outran
their underlying quality (yards-per-play margin), corroborated by the two classic
luck signals Steele made famous: turnover margin and one-score-game record. Adds
2026 returning production (CFBD) as the experience layer.

This is honest CONTEXT, not a claimed edge: "the math says last year was partly
luck." It complements The Reveal (which earns the in-season CFB edge once games
are played). Every number traces to real data.

    python research/cfb_regression/cfb_regression_watch.py
"""
import pathlib, unicodedata
import pandas as pd, numpy as np

ROOT  = pathlib.Path(__file__).resolve().parents[2]
GAMES = ROOT / "data" / "historical" / "NCAAF_CFBD_Games_2025.csv"
STATS = ROOT / "data" / "historical" / "NCAAF_TeamRankings_2025_TeamStats.csv"
RET   = ROOT / "data" / "historical" / "NCAAF_CFBD_ReturningProduction_2026.csv"
FBS_CONF = {"Big Ten","ACC","SEC","Big 12","Sun Belt","American Athletic",
            "Mid-American","Mountain West","Conference USA","FBS Independents","Pac-12"}

def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii","ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())

def team_records():
    g = pd.read_csv(GAMES, dtype=str)
    for c in ("HomeScore","AwayScore"): g[c] = pd.to_numeric(g[c], errors="coerce")
    g = g.dropna(subset=["HomeScore","AwayScore"])
    rec = {}
    def bump(team, conf, won, margin):
        d = rec.setdefault(norm(team), {"team":team,"conf":conf,"w":0,"l":0,"osc_w":0,"osc_l":0})
        d["w" if won else "l"] += 1
        if abs(margin) <= 8: d["osc_w" if won else "osc_l"] += 1
    for _, r in g.iterrows():
        m = r["HomeScore"] - r["AwayScore"]
        bump(r["Home"], r.get("HomeConference"), m > 0, m)
        bump(r["Away"], r.get("AwayConference"), m < 0, -m)
    return pd.DataFrame(rec.values())

def load_stats():
    s = pd.read_csv(STATS)
    col = {c.lower(): c for c in s.columns}
    def pick(name): return col.get(name.lower())
    s["k"] = s["Team"].map(norm)
    out = pd.DataFrame({"k": s["k"],
        "ypp": pd.to_numeric(s[pick("yards_per_play_SeasonValue")], errors="coerce"),
        "opp_ypp": pd.to_numeric(s[pick("opponent_yards_per_play_SeasonValue")], errors="coerce"),
        "to_margin": pd.to_numeric(s[pick("turnover_margin_per_game_SeasonValue")], errors="coerce")})
    out["ypp_margin"] = out["ypp"] - out["opp_ypp"]
    return out

def load_returning():
    r = pd.read_csv(RET); r["k"] = r["team"].map(norm)
    return r[["k","percentPPA"]].rename(columns={"percentPPA":"ret"})

def build():
    rec = team_records(); rec["k"] = rec["team"].map(norm)
    rec = rec[rec["conf"].isin(FBS_CONF)]                    # FBS only
    df = rec.merge(load_stats(), on="k", how="left").merge(load_returning(), on="k", how="left")
    df["gp"] = df["w"] + df["l"]
    df = df[df["gp"] >= 8]
    df["win_pct"] = df["w"] / df["gp"]
    df["osc_gp"] = df["osc_w"] + df["osc_l"]
    df["osc_pct"] = np.where(df["osc_gp"] > 0, df["osc_w"]/df["osc_gp"], np.nan)
    # "luck" = how far the record outran underlying quality (yards-per-play margin)
    df["win_pctile"] = df["win_pct"].rank(pct=True)
    df["ypp_pctile"] = df["ypp_margin"].rank(pct=True)
    df["luck"] = df["win_pctile"] - df["ypp_pctile"]
    return df.dropna(subset=["ypp_margin"])

def show(df, asc, title):
    d = df.sort_values("luck", ascending=asc).head(12)
    print(f"\n{title}")
    print("="*84)
    print(f"{'Team':<20}{'Rec':>7}{'Win%':>7}{'YPPmar':>8}{'TOmar':>7}{'1-score':>9}{'Ret%':>7}{'Luck':>7}")
    for _, r in d.iterrows():
        osc = f"{int(r['osc_w'])}-{int(r['osc_l'])}" if r["osc_gp"]>0 else "-"
        ret = f"{r['ret']*100:.0f}%" if pd.notna(r["ret"]) else "-"
        print(f"{r['team'][:19]:<20}{int(r['w'])}-{int(r['l']):<5}{r['win_pct']*100:>6.0f}%"
              f"{r['ypp_margin']:>+8.2f}{r['to_margin']:>+7.2f}{osc:>9}{ret:>7}{r['luck']:>+7.2f}")

if __name__ == "__main__":
    df = build()
    print(f"CFB REGRESSION WATCH — 2025 season, {len(df)} FBS teams  (2026 returning prod attached)")
    show(df, asc=False, title="REGRESSION DOWN — record outran the yards (won close/turnover-lucky)")
    show(df, asc=True,  title="BOUNCE-BACK UP — better than their record (lost close/turnover-unlucky)")
