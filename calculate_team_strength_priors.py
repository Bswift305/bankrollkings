"""
Team_Strength_Priors — a lightweight team-strength CONTEXT signal for prop rows.

IMPORTANT BOUNDARY: this score is partly built FROM the betting market (moneyline /
spread / totals), so it is suitable only as display context on a prop board. It must
NOT be used for any model-vs-market edge — comparing a market-derived number against
the market is circular and produces fake edges. For an honest model-vs-market edge,
use power_ratings.py (Elo from actual game results, market-independent).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRACKING_DIR = DATA_DIR / "tracking"
ODDS_DIR = DATA_DIR / "odds"

OUTPUT_PATH = TRACKING_DIR / "Team_Strength_Priors.csv"
NOTES_PATH = TRACKING_DIR / "Team_Strength_Prior_Notes.txt"


SPORTS = ["NBA", "WNBA", "MLB", "NFL"]


def american_to_prob(value):
    try:
        odds = float(value)
    except Exception:
        return np.nan
    if odds == 0 or np.isnan(odds):
        return np.nan
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def safe_float(value, default=np.nan):
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if not np.isnan(parsed) else default


def label_for_score(score):
    if score >= 62:
        return "STRONG PRIOR"
    if score >= 55:
        return "POSITIVE PRIOR"
    if score <= 38:
        return "WEAK PRIOR"
    if score <= 45:
        return "NEGATIVE PRIOR"
    return "NEUTRAL PRIOR"


def team_key(value):
    return " ".join(str(value or "").strip().upper().split())


def display_team(value):
    text = str(value or "").strip()
    if text.isupper() and len(text) > 4:
        return text.title()
    return text


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def build_market_priors_for_sport(sport):
    path = ODDS_DIR / f"{sport}_Odds.csv"
    df = read_csv(path)
    if df.empty:
        return []

    rows = []
    for _, row in df.iterrows():
        away = str(row.get("AwayFull") or row.get("Away") or "").strip()
        home = str(row.get("HomeFull") or row.get("Home") or "").strip()
        if not away or not home:
            continue
        total = safe_float(row.get("Total"))
        spread = safe_float(row.get("Spread"))
        away_prob = american_to_prob(row.get("AwayML"))
        home_prob = american_to_prob(row.get("HomeML"))
        rows.append({
            "Sport": sport,
            "Team": away,
            "MarketWinProb": away_prob * 100 if pd.notna(away_prob) else np.nan,
            "AvgGameTotal": total,
            "AvgSpread": -spread if pd.notna(spread) else np.nan,
            "ActiveGames": 1,
        })
        rows.append({
            "Sport": sport,
            "Team": home,
            "MarketWinProb": home_prob * 100 if pd.notna(home_prob) else np.nan,
            "AvgGameTotal": total,
            "AvgSpread": spread,
            "ActiveGames": 1,
        })

    if not rows:
        return []
    market = pd.DataFrame(rows)
    grouped = market.groupby(["Sport", "Team"], dropna=False).agg(
        MarketWinProb=("MarketWinProb", "mean"),
        AvgGameTotal=("AvgGameTotal", "mean"),
        AvgSpread=("AvgSpread", "mean"),
        ActiveGames=("ActiveGames", "sum"),
    ).reset_index()
    grouped["TeamKey"] = grouped["Team"].apply(team_key)
    return grouped.to_dict("records")


def build_prop_team_priors():
    rows = []
    for sport in SPORTS:
        path = TRACKING_DIR / f"{sport}_AllPropResults.csv"
        df = read_csv(path)
        if df.empty or "Team" not in df.columns:
            continue
        working = df.copy()
        working["Team"] = working["Team"].fillna("").astype(str).str.strip()
        working = working[working["Team"].ne("")]
        if working.empty:
            continue
        if "OutcomeState" not in working.columns:
            continue
        working["OutcomeState"] = working["OutcomeState"].fillna("").astype(str).str.strip()
        resolved = working[working["OutcomeState"].isin(["Hit", "Miss"])].copy()
        if resolved.empty:
            continue
        resolved["HitBinary"] = resolved["OutcomeState"].map({"Hit": 1, "Miss": 0})
        if "Confidence" in resolved.columns:
            resolved["Confidence"] = pd.to_numeric(resolved["Confidence"], errors="coerce")
        else:
            resolved["Confidence"] = np.nan
        grouped = resolved.groupby("Team", dropna=False).agg(
            PropResolved=("HitBinary", "count"),
            PropHitRate=("HitBinary", "mean"),
            AvgConfidence=("Confidence", "mean"),
        ).reset_index()
        grouped["Sport"] = sport
        grouped["TeamKey"] = grouped["Team"].apply(team_key)
        rows.extend(grouped.to_dict("records"))
    return pd.DataFrame(rows)


def build_nba_net_rating_priors():
    path = TRACKING_DIR / "NBA_Advanced.csv"
    df = read_csv(path)
    if df.empty or "TEAM_ABBREVIATION" not in df.columns or "NET_RATING" not in df.columns:
        return pd.DataFrame()
    working = df.copy()
    working["TEAM_ABBREVIATION"] = working["TEAM_ABBREVIATION"].fillna("").astype(str).str.strip()
    working["NET_RATING"] = pd.to_numeric(working["NET_RATING"], errors="coerce")
    working["MIN"] = pd.to_numeric(working.get("MIN", 0), errors="coerce").fillna(0)
    working = working[working["TEAM_ABBREVIATION"].ne("")]
    if working.empty:
        return pd.DataFrame()
    rows = []
    for team, sub in working.groupby("TEAM_ABBREVIATION"):
        weights = sub["MIN"].clip(lower=0)
        if weights.sum() > 0:
            net = float(np.average(sub["NET_RATING"].fillna(0), weights=weights))
        else:
            net = float(sub["NET_RATING"].mean())
        rows.append({"Sport": "NBA", "Team": team, "TeamKey": team_key(team), "NetRatingPrior": net})
    return pd.DataFrame(rows)


def build_team_strength_priors():
    market_rows = []
    for sport in SPORTS:
        market_rows.extend(build_market_priors_for_sport(sport))
    market = pd.DataFrame(market_rows)
    prop = build_prop_team_priors()
    nba_net = build_nba_net_rating_priors()

    if market.empty and prop.empty and nba_net.empty:
        return pd.DataFrame(columns=[
            "Sport", "Team", "TeamPriorScore", "PriorLabel", "MarketWinProb",
            "PropResolved", "PropHitRate", "AvgConfidence", "NetRatingPrior",
            "AvgGameTotal", "AvgSpread", "ActiveGames", "Source",
        ])

    frames = []
    if not market.empty:
        frames.append(market[["Sport", "TeamKey", "Team"]])
    if not prop.empty:
        frames.append(prop[["Sport", "TeamKey", "Team"]])
    if not nba_net.empty:
        frames.append(nba_net[["Sport", "TeamKey", "Team"]])
    base = pd.concat(frames, ignore_index=True)
    base["Team"] = base["Team"].apply(display_team)
    base = base.groupby(["Sport", "TeamKey"], dropna=False).agg(Team=("Team", "first")).reset_index()

    if not market.empty:
        base = base.merge(market.drop(columns=["Team"]), on=["Sport", "TeamKey"], how="left")
    if not prop.empty:
        base = base.merge(prop.drop(columns=["Team"]), on=["Sport", "TeamKey"], how="left")
    if not nba_net.empty:
        base = base.merge(nba_net.drop(columns=["Team"]), on=["Sport", "TeamKey"], how="left")

    for col in ["MarketWinProb", "PropResolved", "PropHitRate", "AvgConfidence", "NetRatingPrior", "AvgGameTotal", "AvgSpread", "ActiveGames"]:
        if col not in base.columns:
            base[col] = np.nan

    scores = []
    sources = []
    for _, row in base.iterrows():
        score = 50.0
        source_parts = []
        if pd.notna(row.get("MarketWinProb")):
            score += (float(row["MarketWinProb"]) - 50.0) * 0.45
            source_parts.append("market")
        if pd.notna(row.get("PropHitRate")) and float(row.get("PropResolved") or 0) >= 10:
            score += ((float(row["PropHitRate"]) * 100.0) - 50.0) * 0.25
            source_parts.append("resolved_props")
        if pd.notna(row.get("NetRatingPrior")):
            score += max(-8.0, min(8.0, float(row["NetRatingPrior"]) * 0.55))
            source_parts.append("net_rating")
        if pd.notna(row.get("AvgSpread")):
            score += max(-4.0, min(4.0, -float(row["AvgSpread"]) * 0.35))
            source_parts.append("spread")
        scores.append(round(max(0.0, min(100.0, score)), 1))
        sources.append("+".join(source_parts) or "thin")

    base["TeamPriorScore"] = scores
    base["PriorLabel"] = base["TeamPriorScore"].apply(label_for_score)
    base["Source"] = sources
    base["PropHitRate"] = (base["PropHitRate"] * 100).round(1)
    base["MarketWinProb"] = base["MarketWinProb"].round(1)
    base["AvgConfidence"] = base["AvgConfidence"].round(1)
    base["NetRatingPrior"] = base["NetRatingPrior"].round(1)
    base["AvgGameTotal"] = base["AvgGameTotal"].round(1)
    base["AvgSpread"] = base["AvgSpread"].round(1)
    base["PropResolved"] = base["PropResolved"].fillna(0).astype(int)
    base["ActiveGames"] = base["ActiveGames"].fillna(0).astype(int)

    output_cols = [
        "Sport", "Team", "TeamPriorScore", "PriorLabel", "MarketWinProb",
        "PropResolved", "PropHitRate", "AvgConfidence", "NetRatingPrior",
        "AvgGameTotal", "AvgSpread", "ActiveGames", "Source",
    ]
    base = base[output_cols].sort_values(["Sport", "TeamPriorScore", "Team"], ascending=[True, False, True])
    return base


def write_notes(priors):
    lines = [
        "Team Strength Priors v1",
        "=" * 28,
        "Purpose: provide a lightweight team-strength prior for game environment before deeper ELO is available.",
        "Inputs: live moneyline/spread/total, resolved prop team texture when available, and NBA player-weighted net rating.",
        "",
    ]
    if priors.empty:
        lines.append("No priors generated. Check odds and result files.")
    else:
        for sport, sub in priors.groupby("Sport"):
            top = sub.head(3)
            lines.append(f"{sport}: {len(sub)} teams")
            for _, row in top.iterrows():
                lines.append(f"- {row['Team']}: {row['TeamPriorScore']} ({row['PriorLabel']}) via {row['Source']}")
            lines.append("")
    NOTES_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    priors = build_team_strength_priors()
    priors.to_csv(OUTPUT_PATH, index=False)
    write_notes(priors)
    print(f"Wrote {len(priors)} team priors -> {OUTPUT_PATH}")
    if not priors.empty:
        print(priors.groupby("Sport").size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
