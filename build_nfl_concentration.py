"""
build_nfl_concentration.py  -- Wisdomism lens: CONCENTRATION

The question none of the other lenses ask: WHEN scoring happens, WHO gets it?

Season averages and even target/rush share hide this -- a back can own 60% of the carries
and still cede every goal-line carry to a short-yardage specialist; a WR can see 25% of the
targets and almost none inside the 10. Concentration is where production ACCUMULATES, and it
is what actually drives the anytime-TD / goal-line markets, which casual money spreads evenly
across names while one player quietly vultures the scores.

Built from 2019-25 nflverse PBP (garbage-time removed), aggregated per player for a stable
tendency. Emits data/scenarios/nfl_concentration.json (committed, so it ships to prod without
the PBP source) keyed by PBP 'F.Last' name -> the Concentration lens + anytime-TD context.

Doctrine: de-averages, does not predict. Votes on scoring markets only (on yardage it would
collapse into Opportunity). See docs/wisdomism_lens_families.md (Concentration).
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PBP_PATH = BASE / "data" / "pbp" / "nfl_pbp_2019_2025_slim.parquet"
OUT_CSV = BASE / "data" / "tracking" / "NFL_Concentration.csv"
FLAGS_PATH = BASE / "data" / "scenarios" / "nfl_concentration.json"

RECENT_SEASONS = [2023, 2024, 2025]
GARBAGE_WP_LOW, GARBAGE_WP_HIGH = 0.05, 0.95
RZ_YARDS = 20                 # red zone
GL_YARDS = 5                  # goal line (inside the 5)
MIN_TEAM_RZ = 30              # need a real denominator before a share means anything
# flag thresholds (own share of the team's scoring-area work)
GL_BACK = 0.55                # owns the goal line
RZ_TGT_HOG = 0.22             # red-zone target magnet
TD_CONC = 0.28                # share of the team's offensive TDs


def load() -> pd.DataFrame:
    df = pd.read_parquet(PBP_PATH, columns=[
        "season", "posteam", "wp", "yardline_100", "rush_attempt", "pass_attempt",
        "rusher_player_name", "receiver_player_name", "rush_touchdown", "pass_touchdown"])
    df = df[df["season"].isin(RECENT_SEASONS) & df["posteam"].notna()].copy()
    wp = pd.to_numeric(df["wp"], errors="coerce")
    df = df[wp.between(GARBAGE_WP_LOW, GARBAGE_WP_HIGH)].copy()
    df["yl"] = pd.to_numeric(df["yardline_100"], errors="coerce")
    df["is_rush"] = pd.to_numeric(df["rush_attempt"], errors="coerce").fillna(0) == 1
    df["is_pass"] = pd.to_numeric(df["pass_attempt"], errors="coerce").fillna(0) == 1
    df["rtd"] = pd.to_numeric(df["rush_touchdown"], errors="coerce").fillna(0) == 1
    df["ptd"] = pd.to_numeric(df["pass_touchdown"], errors="coerce").fillna(0) == 1
    return df


def _share(part_key, team_key, df, who_col, mask):
    """player count / team count within `mask`, grouped by posteam for the team denom."""
    sub = df[mask & df[who_col].fillna("").ne("")]
    pl = sub.groupby([who_col, "posteam"]).size().rename("n").reset_index()
    tm = sub.groupby("posteam").size().rename("team").reset_index()
    m = pl.merge(tm, on="posteam", how="left").rename(columns={who_col: "player"})
    m["share"] = m["n"] / m["team"]
    return m


def build() -> pd.DataFrame:
    df = load()
    rz, gl = df["yl"] <= RZ_YARDS, df["yl"] <= GL_YARDS
    gl_rush = _share("p", "t", df, "rusher_player_name", gl & df["is_rush"]).rename(
        columns={"n": "gl_rush", "team": "gl_rush_team", "share": "gl_rush_share"})
    rz_rush = _share("p", "t", df, "rusher_player_name", rz & df["is_rush"]).rename(
        columns={"n": "rz_rush", "team": "rz_rush_team", "share": "rz_rush_share"})
    rz_tgt = _share("p", "t", df, "receiver_player_name", rz & df["is_pass"]).rename(
        columns={"n": "rz_tgt", "team": "rz_tgt_team", "share": "rz_tgt_share"})

    # TD share: player (rush+rec) TDs over the team's offensive TDs
    rtd = df[df["rtd"]].groupby(["rusher_player_name", "posteam"]).size().rename("rtd").reset_index().rename(columns={"rusher_player_name": "player"})
    ptd = df[df["ptd"]].groupby(["receiver_player_name", "posteam"]).size().rename("ptd").reset_index().rename(columns={"receiver_player_name": "player"})
    td = rtd.merge(ptd, on=["player", "posteam"], how="outer").fillna(0)
    td["player_td"] = td["rtd"] + td["ptd"]
    team_td = (df[df["rtd"]].groupby("posteam").size()
               .add(df[df["ptd"]].groupby("posteam").size(), fill_value=0)).rename("team_td").reset_index()
    td = td.merge(team_td, on="posteam", how="left")
    td["td_share"] = td["player_td"] / td["team_td"]

    out = gl_rush.merge(rz_rush, on=["player", "posteam"], how="outer")
    out = out.merge(rz_tgt, on=["player", "posteam"], how="outer")
    out = out.merge(td[["player", "posteam", "player_td", "team_td", "td_share"]], on=["player", "posteam"], how="outer")
    out = out.rename(columns={"posteam": "team"})
    # keep rows with a real scoring-area sample
    out = out[(out["rz_rush_team"].fillna(0) + out["rz_tgt_team"].fillna(0)) >= MIN_TEAM_RZ].copy()
    for c in out.columns:
        if c not in ("player", "team"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.sort_values(["player", "team"]).reset_index(drop=True)


def compute_flags(out: pd.DataFrame) -> dict:
    """Per-player concentration signal (aggregated across teams), emitted for players with a
    genuine scoring-area concentration. The ~majority with no standout role get no flag."""
    flags = {}
    for name, g in out.groupby("player"):
        gl_s = (g["gl_rush"].sum() / g["gl_rush_team"].sum()) if g["gl_rush_team"].sum() else None
        tgt_s = (g["rz_tgt"].sum() / g["rz_tgt_team"].sum()) if g["rz_tgt_team"].sum() else None
        td_s = (g["player_td"].sum() / g["team_td"].sum()) if g["team_td"].sum() else None
        notes = []
        if gl_s is not None and gl_s >= GL_BACK:
            notes.append(f"owns the goal line ({round(gl_s*100)}% of inside-5 carries)")
        if tgt_s is not None and tgt_s >= RZ_TGT_HOG:
            notes.append(f"red-zone target magnet ({round(tgt_s*100)}% of RZ targets)")
        if td_s is not None and td_s >= TD_CONC:
            notes.append(f"scores {round(td_s*100)}% of the team's TDs")
        if notes:
            flags[str(name)] = {
                "note": "; ".join(notes),
                "gl_rush_share": round(gl_s, 3) if gl_s is not None else None,
                "rz_tgt_share": round(tgt_s, 3) if tgt_s is not None else None,
                "td_share": round(td_s, 3) if td_s is not None else None,
            }
    return flags


def main() -> None:
    out = build()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.round(3).to_csv(OUT_CSV, index=False)
    flags = compute_flags(out)
    FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLAGS_PATH.write_text(json.dumps(flags, indent=1), encoding="utf-8")
    print(f"Wrote {OUT_CSV} ({len(out)} player-team rows)")
    print(f"Wrote {FLAGS_PATH} ({len(flags)} concentrated players)\n")

    print("GOAL-LINE backs (own inside-5 carries) -- the anytime-TD signal volume share hides:")
    gg = out.groupby("player").apply(
        lambda g: pd.Series({"gl": g["gl_rush"].sum() / g["gl_rush_team"].sum() if g["gl_rush_team"].sum() else 0,
                             "n": g["gl_rush"].sum()}), include_groups=False)
    for p, r in gg[gg["n"] >= 10].sort_values("gl", ascending=False).head(10).iterrows():
        print(f"   {p:<22} {r['gl']:.0%} of goal-line carries ({int(r['n'])})")
    print("\nTD-concentration leaders (share of team's offensive TDs):")
    tt = out.groupby("player").apply(
        lambda g: pd.Series({"td": g["player_td"].sum() / g["team_td"].sum() if g["team_td"].sum() else 0,
                             "n": g["player_td"].sum()}), include_groups=False)
    for p, r in tt[tt["n"] >= 8].sort_values("td", ascending=False).head(10).iterrows():
        print(f"   {p:<22} {r['td']:.0%} of team TDs ({int(r['n'])})")


if __name__ == "__main__":
    main()
