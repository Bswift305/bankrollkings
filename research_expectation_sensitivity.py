"""
research_expectation_sensitivity.py  -- AUDIT (not a feature)

Research question (NOT a conclusion): do some teams SYSTEMATICALLY under/over-perform the
market's EXPECTATION, split by favorite tier? The "let-down team" narrative (Dallas looks
elite vs good teams, plays down to bad ones) is folklore until measured. We measure the gap
between expected margin (the spread) and actual margin, per team per situation -- then run the
test that matters: does it PERSIST? If a team's over/under-performance in one split predicts
the other, it's a real trait; if not, it's variance we remember selectively (the doctrine's guard).

Data: nflverse games 1999-2026 (spread_line = home expected margin; result = home margin).
ATS margin = actual - expected (how much a team beat/missed the number by). Market is efficient,
so the league mean is ~0 by construction; the question is whether INDIVIDUAL teams deviate
persistently. Prints findings; builds nothing. See BANKROLL_KINGS_DOCTRINE.md S10.

VERDICT (2026-10-10 run, 14,064 team-games): DO NOT BUILD. The persistence test is decisive --
corr(odd-season favorite ATS, even-season favorite ATS) = +0.04 across 35 teams. A team's
over/under-performance as a favorite in one set of seasons does NOT predict the other, so the
"let-down" / expectation-sensitivity effect is NOT a stable team trait -- it's variance plus a
non-persistent quality/regime artifact (NE/BAL over-performed in their dynasties, CLE/WAS in
dysfunction; the market caught up). The DALLAS narrative specifically is folklore: as a favorite
Dallas is slightly POSITIVE ATS (heavy +0.76 / slight +0.24); only pick-ems are negative. The
doctrine's variance/narrative guard (Q2-C) wins. Re-run if we ever want to test a COACH-level
version, but franchise-level persistence ~0 argues even that is mostly captured quality.
"""
from __future__ import annotations
import io
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
GAMES = BASE / "data" / "historical" / "nflverse_games.parquet"
MIN_SPLIT = 12          # min favored games per split before a team's number is trusted


def team_games() -> pd.DataFrame:
    if not GAMES.exists():   # self-contained: pull nflverse schedule if the (gitignored) cache is absent
        url = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=60).read()
        GAMES.parent.mkdir(parents=True, exist_ok=True)
        pd.read_csv(io.BytesIO(raw)).to_parquet(GAMES)
    df = pd.read_parquet(GAMES)
    df = df[(df["game_type"] == "REG")].dropna(subset=["spread_line", "result"]).copy()
    rows = []
    for _, g in df.iterrows():
        sp, res, sea = float(g["spread_line"]), float(g["result"]), int(g["season"])
        # home: expected = spread_line, actual = result ; away: both negated (zero-sum)
        rows.append({"team": g["home_team"], "season": sea, "exp": sp, "ats": res - sp})
        rows.append({"team": g["away_team"], "season": sea, "exp": -sp, "ats": -(res) - (-sp)})
    t = pd.DataFrame(rows)
    t["tier"] = np.select(
        [t["exp"] >= 7, t["exp"] >= 3, t["exp"] > -3, t["exp"] <= -3],
        ["heavy_fav", "slight_fav", "pickem", "dog"], default="pickem")
    t["favored"] = t["exp"] > 0
    return t


def main() -> None:
    t = team_games()
    print(f"Team-game rows: {len(t):,} (1999-2026 REG)\n")

    print("1) LEAGUE-WIDE ATS margin by tier -- efficiency sanity (should all be ~0):")
    for tier in ["heavy_fav", "slight_fav", "pickem", "dog"]:
        s = t[t["tier"] == tier]["ats"]
        print(f"   {tier:<11} n={len(s):>5}  mean ATS margin {s.mean():+.2f}")
    print("   -> if a tier is far from 0, that's a MARKET bias, not a team trait.\n")

    # per-team ATS margin when FAVORED (the 'let-down' claim), full history + recent era
    print("2) Biggest FAVORITE over/under-performers (ATS margin when favored, min 40 gms):")
    fav = t[t["favored"]]
    agg = fav.groupby("team")["ats"].agg(["mean", "count"])
    agg = agg[agg["count"] >= 40].sort_values("mean")
    print("   UNDER-perform as favorites (the 'let-down' end):")
    for tm, r in agg.head(6).iterrows():
        print(f"     {tm:<4} {r['mean']:+.2f} ATS margin over {int(r['count'])} favored games")
    print("   OVER-perform as favorites:")
    for tm, r in agg.tail(6).iloc[::-1].iterrows():
        print(f"     {tm:<4} {r['mean']:+.2f} over {int(r['count'])}")
    # Dallas, the narrative test case
    dal = t[t["team"] == "DAL"]
    print("\n   DALLAS (the narrative), ATS margin by tier:")
    for tier in ["heavy_fav", "slight_fav", "pickem", "dog"]:
        s = dal[dal["tier"] == tier]["ats"]
        if len(s):
            print(f"     {tier:<11} n={len(s):>3}  {s.mean():+.2f}")

    # 3) THE AUDIT: does favorite over/under-performance PERSIST? odd vs even seasons.
    print("\n3) PERSISTENCE TEST -- does a team's favorite ATS margin in ODD seasons predict EVEN?")
    fav = fav.assign(parity=np.where(fav["season"] % 2 == 1, "odd", "even"))
    piv = fav.groupby(["team", "parity"])["ats"].agg(["mean", "count"]).unstack("parity")
    both = piv.dropna()
    both = both[(both[("count", "odd")] >= MIN_SPLIT) & (both[("count", "even")] >= MIN_SPLIT)]
    corr = both[("mean", "odd")].corr(both[("mean", "even")])
    print(f"   teams with >= {MIN_SPLIT} favored gms each split: {len(both)}")
    print(f"   corr(odd-season fav ATS, even-season fav ATS) = {corr:+.2f}")
    print("   ~0  -> NO persistence: 'let-down' is variance/narrative, not a team trait (doctrine wins).")
    print("   >.3 -> a real, persistent lean worth a second look.\n")

    # recent-era cut (more roster/coaching-stable) for honesty
    rec = t[(t["season"] >= 2015) & (t["favored"])]
    ragg = rec.groupby("team")["ats"].agg(["mean", "count"])
    ragg = ragg[ragg["count"] >= 25].sort_values("mean")
    print("4) 2015-2026 only (more stable), biggest favorite under-performers:")
    for tm, r in ragg.head(5).iterrows():
        print(f"     {tm:<4} {r['mean']:+.2f} over {int(r['count'])} favored gms")
    print(f"   (DAL 2015-26 favored ATS margin: {ragg.loc['DAL','mean']:+.2f} over {int(ragg.loc['DAL','count'])})"
          if 'DAL' in ragg.index else "")


if __name__ == "__main__":
    main()
