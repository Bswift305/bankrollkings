"""
build_nfl_hit_profile_linemeta.py  -- Averaging Audit shortlist A3

De-blend the hit-profile AvgLine.

The profile's AvgLine = mean of EVERY line a player was ever graded at (across all seasons
and line levels). calculate_nfl_prop_score.calculate_line_value then rewards an OVER when
today's line sits below that AvgLine (up to +6 score pts at 1.2/yd). For a player graded at
30.5 and 58.5, AvgLine ~= 44 is a phantom midpoint that matches no real bet -- so the score
term fires off fiction.

This computes per (Player, Team, Stat, Direction): how many DISTINCT lines, the spread, a
median, and a LineBlend flag (TIGHT / MODERATE / WIDE) so AvgLine can be trusted only when
it's a real reference. It merges those columns into NFL_Player_Hit_Profiles.csv in place and
reports (a) how much of the profile base is WIDE, and (b) how much current scoring is driven
by a phantom AvgLine.

Honest framing: because the market prices each line to ~50%, de-blending does NOT reveal a
hidden edge -- it removes a misleading reference. A3 is a correctness fix, not a new signal.
See docs/averaging_audit.md (A3).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "data" / "tracking" / "NFL_AllPropResults.csv"
PROFILES = BASE / "data" / "tracking" / "NFL_Player_Hit_Profiles.csv"

MIN_N = 3                 # need a few lines to judge dispersion
WIDE_PCT = 0.40           # line range > 40% of avg line -> AvgLine is a phantom
TIGHT_PCT = 0.20
VALUE_TERM_MIN_GAP = 1.0  # calculate_line_value starts paying out past ~1 yd of gap


def line_meta() -> pd.DataFrame:
    df = pd.read_csv(RESULTS)
    r = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    r["L"] = pd.to_numeric(r["Line"], errors="coerce")
    r = r.dropna(subset=["L"])
    g = r.groupby(["Player", "Team", "Stat", "Direction"], dropna=False)
    meta = g["L"].agg(LineN="nunique", LineStd="std", LineMin="min",
                      LineMax="max", LineMean="mean", LineMedian="median",
                      Resolved="count").reset_index()
    meta["LineRange"] = (meta["LineMax"] - meta["LineMin"]).round(1)
    meta["LineRangePct"] = (meta["LineRange"] / meta["LineMean"].replace(0, np.nan)).round(3)
    def flag(p):
        if pd.isna(p):
            return "UNKNOWN"
        if p > WIDE_PCT:
            return "WIDE"
        if p <= TIGHT_PCT:
            return "TIGHT"
        return "MODERATE"
    meta["LineBlend"] = np.where(meta["LineN"] < MIN_N, "THIN", meta["LineRangePct"].map(flag))
    for c in ["LineStd", "LineMedian", "LineMean"]:
        meta[c] = meta[c].round(1)
    return meta


def merge_into_profiles(meta: pd.DataFrame) -> pd.DataFrame:
    prof = pd.read_csv(PROFILES)
    add = ["LineN", "LineStd", "LineMin", "LineMax", "LineMedian", "LineRange", "LineRangePct", "LineBlend"]
    prof = prof.drop(columns=[c for c in add if c in prof.columns], errors="ignore")
    merged = prof.merge(meta[["Player", "Team", "Stat", "Direction"] + add],
                        on=["Player", "Team", "Stat", "Direction"], how="left")
    merged.to_csv(PROFILES, index=False)
    return merged


def report(meta: pd.DataFrame, merged: pd.DataFrame) -> None:
    assessable = meta[meta["LineBlend"].isin(["TIGHT", "MODERATE", "WIDE"])]
    n = len(assessable)
    print(f"Profiles assessable (>= {MIN_N} distinct lines): {n}")
    for b in ["TIGHT", "MODERATE", "WIDE"]:
        c = (assessable["LineBlend"] == b).sum()
        print(f"  {b:<9}{c:>5}  ({c/n:.0%})")
    print(f"\n-> {(assessable['LineBlend']=='WIDE').mean():.0%} of multi-line profiles have an "
          f"AvgLine that is a PHANTOM (range > {WIDE_PCT:.0%} of the mean line).\n")

    print("Worst phantoms (widest spread, high sample):")
    w = assessable[(assessable["LineBlend"] == "WIDE") & (assessable["Resolved"] >= 15)]
    w = w.sort_values("LineRange", ascending=False).head(8)
    print(f"   {'player':<20}{'stat':<12}{'dir':<6}{'lines':>6}{'min':>7}{'avg':>7}{'max':>7}")
    for _, r in w.iterrows():
        print(f"   {str(r['Player'])[:20]:<20}{str(r['Stat']):<12}{str(r['Direction']):<6}"
              f"{int(r['LineN']):>6}{r['LineMin']:>7.1f}{r['LineMean']:>7.1f}{r['LineMax']:>7.1f}")

    # (b) how much scoring is phantom-driven: among resolved props, which ones would get the
    # calculate_line_value bonus, and of those, how many come from a WIDE profile.
    res = pd.read_csv(RESULTS)
    res = res[res["OutcomeState"].isin(["Hit", "Miss"])].copy()
    res["L"] = pd.to_numeric(res["Line"], errors="coerce")
    key = ["Player", "Team", "Stat", "Direction"]
    res = res.merge(meta[key + ["LineMean", "LineBlend"]], on=key, how="left")
    over = res["Direction"].str.upper() == "OVER"
    under = res["Direction"].str.upper() == "UNDER"
    gap = np.where(over, res["LineMean"] - res["L"], np.where(under, res["L"] - res["LineMean"], np.nan))
    res["bonus_fires"] = pd.Series(gap, index=res.index) > VALUE_TERM_MIN_GAP
    fired = res[res["bonus_fires"]]
    phantom = fired[fired["LineBlend"] == "WIDE"]
    print(f"\nLineValue 'soft number' bonus fires on {len(fired):,} of {len(res):,} resolved props "
          f"({len(fired)/len(res):.0%}).")
    print(f"Of those, {len(phantom):,} ({len(phantom)/max(len(fired),1):.0%}) come from a WIDE "
          f"(phantom) AvgLine -> the bonus is comparing today's line to fiction.")
    print("Fix: gate the AvgLine term on LineBlend != WIDE (done in calculate_line_value).\n")


def main() -> None:
    meta = line_meta()
    merged = merge_into_profiles(meta)
    print(f"Merged line-meta into {PROFILES.name} ({len(merged)} profiles)\n")
    report(meta, merged)


if __name__ == "__main__":
    main()
