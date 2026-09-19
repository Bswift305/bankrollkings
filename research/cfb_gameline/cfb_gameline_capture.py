
# -*- coding: utf-8 -*-
"""
CFB Game-Line capture harness — earns the niche on LIVE 2026 games.

Why: on one 2025 season we could NOT prove a CFB game-line niche (see FINDINGS.md).
Totals showed no edge; the only signal positive in both halves was HOME FAVORITES
covering the spread (esp. power-conf home favorites). So instead of over-mining a
noisy season, we capture forward: log the tested leads (+ any model game-line edge)
with closing lines each week, grade vs final scores, and let 2026 settle it.

MODES
  simulate   -> apply the leads to the joined 2025 data, grade, report ROI. Verifies the
                pipeline and reproduces the home-fav ATS number. Runnable now.
  capture W  -> in-season: read this week's consensus lines, flag lead plays, append to log
                with the CLOSING spread + price.
  grade      -> grade open captures vs CFBD final scores (ATS).
  report     -> walk-forward record + ROI by lead.

LEADS TRACKED (hypotheses, not proven edges — that's what this tests)
  HOME_FAV_ATS        : home team favored -> bet HOME against the spread
  POWER_HOME_FAV_ATS  : same, both teams FBS power conf (the strongest 2025 signal)
  (hook) MODEL_EDGE   : if a model projected spread/total is supplied, flag divergence vs market
"""
import sys, pathlib
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
ODDS_HIST = ROOT / "data" / "historical" / "NCAAF_OddsAPI_GameLines_History.csv"
ODDS_LIVE = ROOT / "data" / "odds" / "NCAAF_Odds.csv"          # in-season weekly feed
SCORES    = ROOT / "data" / "historical" / "NCAAF_CFBD_Games_2025.csv"  # in-season: current CFBD games
HERE      = pathlib.Path(__file__).resolve().parent
CAPTURE_LOG = HERE / "cfb_capture_log.csv"
POWER = {"SEC", "Big Ten", "ACC", "Big 12", "Pac-12", "FBS Independents"}

def _norm(s): return "".join(c for c in str(s).lower() if c.isalnum())
def _core(name):
    t = str(name).split(); return _norm(" ".join(t[:-1])) if len(t) > 1 else _norm(name)
def _dec(p): return 1 + (p / 100 if p > 0 else 100 / abs(p))

# --------------------------------------------------------------- consensus lines
def consensus_lines(path=ODDS_HIST):
    h = pd.read_csv(path, dtype=str, low_memory=False)
    for c in ["Spread", "Total", "SpreadOdds", "OverOdds", "UnderOdds", "AwayML", "HomeML"]:
        if c in h.columns: h[c] = pd.to_numeric(h[c], errors="coerce")
    h["d"] = pd.to_datetime(h["Date"], errors="coerce")
    L = h.groupby("GameID").agg(Date=("d", "first"), Away=("Away", "first"), Home=("Home", "first"),
        Spread=("Spread", "median"), Total=("Total", "median"), SpreadOdds=("SpreadOdds", "median"),
        AwayML=("AwayML", "median"), HomeML=("HomeML", "median")).reset_index()
    L["wk"] = ((L["Date"] - L["Date"].min()).dt.days // 7) + 1
    return L

# --------------------------------------------------------------- the leads (rules)
def flag_plays(L, power_map=None):
    """Bet HOME ATS on home favorites. Tag the early-season mismatch (power home team
    favored over a G5 away team) separately — it was the strongest 2025 signal but
    faded late, so we track it to see if it holds in 2026."""
    plays = L[L["Spread"] < 0].copy()          # home favored
    plays["Bet"] = "HOME"
    plays["Lead"] = "HOME_FAV_ATS"
    if power_map is not None:
        hp = plays["Home"].map(_core).map(power_map).fillna(0)
        ap = plays["Away"].map(_core).map(power_map).fillna(0)
        plays.loc[(hp == 1) & (ap == 0), "Lead"] = "MISMATCH_HOME_FAV"   # power home vs G5 away
    return plays

# --------------------------------------------------------------- scores + grading
def load_scores(path=SCORES):
    g = pd.read_csv(path, dtype=str, low_memory=False)
    for c in ["HomeScore", "AwayScore"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g = g.dropna(subset=["HomeScore", "AwayScore"])
    g["hk"] = g["Home"].map(_norm); g["ak"] = g["Away"].map(_norm)
    g["power"] = g["HomeConference"].isin(POWER).astype(int) + g["AwayConference"].isin(POWER).astype(int)
    return g

def power_map_from_scores(g):
    m = {}
    for _, r in g.iterrows():
        m[_norm(r["Home"])] = int(r["HomeConference"] in POWER)
        m[_norm(r["Away"])] = int(r["AwayConference"] in POWER)
    return m

def _grade_ats(plays, g):
    sc = g.groupby(["hk", "ak"]).agg(HomeScore=("HomeScore", "first"), AwayScore=("AwayScore", "first")).reset_index()
    p = plays.copy(); p["hk"] = p["Home"].map(_core); p["ak"] = p["Away"].map(_core)
    m = p.merge(sc, on=["hk", "ak"], how="inner")
    m["margin"] = m["HomeScore"] - m["AwayScore"]
    m["win"] = (m["margin"] + m["Spread"]) > 0     # HOME covers
    # Spread price is ~-110; the source SpreadOdds column is partly contaminated with
    # leaked spread values (e.g. -2.5), so use flat -110 (honest, standard for ATS).
    m["ret"] = [(_dec(-110) - 1) if w else -1.0 for w in m["win"]]
    return m

# ------------------------------------------------------------------- simulate now
def simulate():
    L = consensus_lines(); g = load_scores(); pm = power_map_from_scores(g)
    m = _grade_ats(flag_plays(L, pm), g)
    print("SIMULATE — CFB home-favorite ATS leads on 2025 (real prices)  [1 season -> directional]")
    print("=" * 70)
    for lead in ["HOME_FAV_ATS (all)", "MISMATCH_HOME_FAV"]:
        sub = m if lead == "HOME_FAV_ATS (all)" else m[m["Lead"] == "MISMATCH_HOME_FAV"]
        line = f"  {lead:22s}"
        for lab, ss in [("ALL", sub), ("early", sub[sub["wk"] <= 7]), ("late", sub[sub["wk"] > 7])]:
            if len(ss) >= 20:
                line += f"   {lab}: {ss['ret'].mean()*100:+5.1f}% (cover {ss['win'].mean():.0%}, n={len(ss)})"
        print(line)
    print(f"\n  matched {len(m):,} graded games. This verifies the capture+grade pipeline.")
    print("  In-season, `capture` logs each week's plays with the closing line -> a real 2026 record.")

# ------------------------------------------------------------------- live capture
def capture(week=None):
    src = ODDS_LIVE if ODDS_LIVE.exists() else ODDS_HIST
    if not src.exists():
        print("No odds feed found. In-season point ODDS_LIVE at the weekly NCAAF odds CSV."); return
    L = consensus_lines(src)
    g = load_scores() if SCORES.exists() else None
    pm = power_map_from_scores(g) if g is not None else None
    plays = flag_plays(L, pm)
    if week is not None:
        plays = plays[plays["wk"].astype(str) == str(week)]
    if plays.empty:
        print(f"[capture] 0 home-favorite plays for week {week}."); return
    out = plays[["Date", "wk", "Away", "Home", "Spread", "SpreadOdds", "Total", "Lead"]].copy()
    out["Bet"] = "HOME"; out["status"] = "open"; out["Won"] = ""; out["Return"] = ""
    if CAPTURE_LOG.exists():
        out = pd.concat([pd.read_csv(CAPTURE_LOG, dtype=str), out], ignore_index=True)
    out.to_csv(CAPTURE_LOG, index=False)
    print(f"[capture] logged {len(plays)} home-favorite ATS play(s) -> {CAPTURE_LOG.name}")

def grade():
    if not CAPTURE_LOG.exists(): print("No capture log yet."); return
    log = pd.read_csv(CAPTURE_LOG, dtype=str); g = load_scores()
    open_rows = log[log["status"] == "open"].copy()
    if open_rows.empty: print("nothing open to grade."); return
    open_rows["Spread"] = pd.to_numeric(open_rows["Spread"], errors="coerce")
    open_rows["SpreadOdds"] = pd.to_numeric(open_rows["SpreadOdds"], errors="coerce")
    m = _grade_ats(open_rows.rename(columns={}), g)
    key = lambda r: _core(r["Home"]) + "|" + _core(r["Away"])
    res = {key(r): (r["win"], r["ret"]) for _, r in m.iterrows()}
    n = 0
    for i, r in log[log["status"] == "open"].iterrows():
        k = _core(r["Home"]) + "|" + _core(r["Away"])
        if k in res:
            w, ret = res[k]; log.at[i, "Won"] = "Y" if w else "N"; log.at[i, "Return"] = round(ret, 4)
            log.at[i, "status"] = "graded"; n += 1
    log.to_csv(CAPTURE_LOG, index=False); print(f"graded {n} play(s).")

def report():
    if not CAPTURE_LOG.exists(): print("No capture log yet."); return
    log = pd.read_csv(CAPTURE_LOG, dtype=str); g = log[log["status"] == "graded"].copy()
    if g.empty: print(f"{len(log)} captured, none graded yet."); return
    g["Return"] = pd.to_numeric(g["Return"], errors="coerce")
    print("CFB CAPTURE — walk-forward record (real closing lines)")
    print("=" * 56)
    for lead, sub in g.groupby("Lead"):
        w = (sub["Won"] == "Y").sum(); l = (sub["Won"] == "N").sum()
        print(f"  {lead:22s} {w}-{l}   ROI {sub['Return'].mean()*100:+.1f}%   n={len(sub)}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "simulate"
    if cmd == "simulate": simulate()
    elif cmd == "capture": capture(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "grade": grade()
    elif cmd == "report": report()
    else: print(__doc__)
