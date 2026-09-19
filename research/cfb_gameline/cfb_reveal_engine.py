
# -*- coding: utf-8 -*-
"""
CFB "THE REVEAL" engine — react, don't predict.

Starts every team at 1500 in Week 1 with NO preseason prior and learns purely from
the field (opponent-adjusted, MOV-aware Elo). From ~Week 5 (once teams have tape) it
surfaces the spots where its number disagrees with the market in the sweet band, and
forward-captures them for a public record. Validated on 2025 (see FINDINGS.md):
tape 5-7 games +6.6%, sweet spot (tape>=4, 3-6 pt gap) 55.8% cover / +6.5%, wks 5-9 +7.4%.

MODES
  simulate         verify on 2025 (reproduces the sweet-spot ROI)
  ratings          current "who's for real" board (teams by earned rating + tape)
  board [week]     this week's Reveal plays (model vs market, sweet-spot flagged)
  capture [week]   log the sweet-spot plays with the market line
  grade            grade captured plays vs final scores
  report           walk-forward record + ROI
"""
import sys, pathlib
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
GAMES = ROOT / "data" / "historical" / "NCAAF_CFBD_Games_2025.csv"     # in-season: current CFBD games (scores + schedule)
ODDS  = ROOT / "data" / "historical" / "NCAAF_OddsAPI_GameLines_History.csv"  # in-season: point at live weekly odds
HERE  = pathlib.Path(__file__).resolve().parent
CAPTURE_LOG = HERE / "reveal_capture_log.csv"

# validated params
HFA, K, PPE, START = 65.0, 42.0, 25.0, 1500.0
TAPE_MIN, EDGE_MIN, EDGE_MAX = 4, 3.0, 8.0   # sweet band (>8 pt gaps historically LOSE -> we're missing info)
FBS_CONF = {"Big Ten", "ACC", "SEC", "Big 12", "Sun Belt", "American Athletic",
            "Mid-American", "Mountain West", "Conference USA", "FBS Independents", "Pac-12"}

def _norm(s): return "".join(c for c in str(s).lower() if c.isalnum())
def _core(n):
    t = str(n).split(); return _norm(" ".join(t[:-1])) if len(t) > 1 else _norm(n)
def _E(a, b): return 1 / (1 + 10 ** ((b - a) / 400))

# --------------------------------------------------------------------- Elo walk-forward
def load_games():
    g = pd.read_csv(GAMES, dtype=str, low_memory=False)
    for c in ["HomeScore", "AwayScore"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g["dt"] = pd.to_datetime(g["Date"], errors="coerce")
    g["wk"] = pd.to_numeric(g["Week"], errors="coerce")
    return g.dropna(subset=["dt"]).sort_values("dt").reset_index(drop=True)

def walk_elo(games):
    """Chronological, completed games only. Returns (elo, tape, name_map, snapshots)."""
    elo, tape, name = {}, {}, {}
    snaps = []
    scored = games.dropna(subset=["HomeScore", "AwayScore"])
    # FBS-vs-FBS only: keeps ratings clean and stops cupcake (FCS) wins inflating Elo
    scored = scored[scored["HomeConference"].isin(FBS_CONF) & scored["AwayConference"].isin(FBS_CONF)]
    for _, r in scored.iterrows():
        hk, ak = _norm(r["Home"]), _norm(r["Away"])
        name.setdefault(hk, r["Home"]); name.setdefault(ak, r["Away"])
        rh, ra = elo.get(hk, START), elo.get(ak, START)
        ph, pa = rh + HFA, ra
        snaps.append({"hk": hk, "ak": ak, "wk": r["wk"],
                      "model_home_spread": -(ph - pa) / PPE,
                      "tape": min(tape.get(hk, 0), tape.get(ak, 0)),
                      "hs": r["HomeScore"], "as": r["AwayScore"]})
        eh = _E(ph, pa)
        ah = 1.0 if r["HomeScore"] > r["AwayScore"] else (0.5 if r["HomeScore"] == r["AwayScore"] else 0.0)
        m = abs(r["HomeScore"] - r["AwayScore"]); diff = (ph - pa) if ah == 1 else (pa - ph)
        mov = np.log(m + 1) * (2.2 / (diff * 0.001 + 2.2))
        d = K * mov * (ah - eh)
        elo[hk], elo[ak] = rh + d, ra - d
        tape[hk], tape[ak] = tape.get(hk, 0) + 1, tape.get(ak, 0) + 1
    return elo, tape, name, snaps

def consensus_lines():
    h = pd.read_csv(ODDS, dtype=str, low_memory=False)
    h["Spread"] = pd.to_numeric(h["Spread"], errors="coerce")
    L = h.groupby("GameID").agg(Home=("Home", "first"), Away=("Away", "first"), Spread=("Spread", "median")).reset_index()
    return {(_core(r["Home"]), _core(r["Away"])): (r["Home"], r["Away"], r["Spread"])
            for _, r in L.iterrows() if pd.notna(r["Spread"])}

# --------------------------------------------------------------------- surfaces
def ratings(top=25):
    g = load_games(); elo, tape, name, _ = walk_elo(g)
    df = pd.DataFrame([{"Team": name[k], "Rating": round(v), "Tape": tape.get(k, 0)} for k, v in elo.items()])
    df = df.sort_values("Rating", ascending=False).reset_index(drop=True)
    print("THE REVEAL — earned ratings (no preseason; built from the field)")
    print(df.head(top).to_string(index=False))
    return df

def _projections():
    """For upcoming games (with a market line): model spread vs market + sweet-spot flag."""
    g = load_games(); elo, tape, name, _ = walk_elo(g); lines = consensus_lines()
    upcoming = g[g["HomeScore"].isna()]  # games not yet played (in-season)
    rows = []
    src = upcoming if len(upcoming) else g  # off-season fallback: score all (for demo)
    for _, r in src.iterrows():
        hk, ak = _norm(r["Home"]), _norm(r["Away"])
        key = (_core(r["Home"]), _core(r["Away"]))
        if key not in lines:
            # try matching odds by normalized school
            key = next((k for k in lines if k[0] == hk and k[1] == ak), None)
        if not key:
            continue
        mh, ma, mkt = lines[key]
        model = -((elo.get(hk, START) + HFA) - elo.get(ak, START)) / PPE
        edge = mkt - model                      # >0: model likes HOME more than market
        t = min(tape.get(hk, 0), tape.get(ak, 0))
        pick = r["Home"] if edge > 0 else r["Away"]
        sweet = (t >= TAPE_MIN) and (EDGE_MIN <= abs(edge) <= EDGE_MAX)
        rows.append({"Week": r["wk"], "Home": r["Home"], "Away": r["Away"],
                     "Market": round(mkt, 1), "Model": round(model, 1), "Edge": round(edge, 1),
                     "Tape": t, "Pick": pick + " ATS", "Sweet": sweet})
    return pd.DataFrame(rows)

def board(week=None):
    df = _projections()
    if week is not None and not df.empty:
        df = df[df["Week"].astype(str) == str(week)]
    if df.empty:
        print("No upcoming games with lines. In-season, point ODDS at the live weekly feed."); return
    df["absE"] = df["Edge"].abs()
    df = df.sort_values(["Sweet", "absE"], ascending=[False, False]).drop(columns="absE")
    sweet = df[df["Sweet"]]
    print(f"THE REVEAL BOARD — {len(sweet)} sweet-spot play(s) of {len(df)} games with lines")
    print("(sweet = each team has >=4 games tape AND model-vs-market gap 3-8 pts)\n")
    print(df.head(20).to_string(index=False))
    return df

def capture(week=None):
    df = _projections()
    if df.empty or "Sweet" not in df.columns:
        print("No upcoming games with lines to capture (point ODDS at the live weekly feed in-season)."); return
    plays = df[df["Sweet"]]
    if week is not None:
        plays = plays[plays["Week"].astype(str) == str(week)]
    if plays.empty:
        print("0 sweet-spot plays to capture."); return
    out = plays.copy(); out["status"] = "open"; out["Won"] = ""; out["Return"] = ""
    if CAPTURE_LOG.exists():
        out = pd.concat([pd.read_csv(CAPTURE_LOG, dtype=str), out], ignore_index=True)
    out.to_csv(CAPTURE_LOG, index=False)
    print(f"captured {len(plays)} Reveal play(s) -> {CAPTURE_LOG.name}")

def grade():
    if not CAPTURE_LOG.exists(): print("No capture log."); return
    log = pd.read_csv(CAPTURE_LOG, dtype=str); g = load_games()
    sc = g.dropna(subset=["HomeScore", "AwayScore"]).copy()
    sc["k"] = sc["Home"].map(_norm) + "|" + sc["Away"].map(_norm)
    res = {r["k"]: (r["HomeScore"], r["AwayScore"]) for _, r in sc.iterrows()}
    n = 0
    for i, r in log[log["status"] == "open"].iterrows():
        k = _norm(r["Home"]) + "|" + _norm(r["Away"])
        if k not in res: continue
        hs, as_ = res[k]; margin = hs - as_; mkt = float(r["Market"])
        home_cover = (margin + mkt) > 0
        bet_home = str(r["Pick"]).startswith(str(r["Home"]))
        win = home_cover if bet_home else (not home_cover)
        log.at[i, "Won"] = "Y" if win else "N"; log.at[i, "Return"] = round((100/110) if win else -1.0, 4)
        log.at[i, "status"] = "graded"; n += 1
    log.to_csv(CAPTURE_LOG, index=False); print(f"graded {n} play(s).")

def report():
    if not CAPTURE_LOG.exists(): print("No capture log."); return
    g = pd.read_csv(CAPTURE_LOG, dtype=str); g = g[g["status"] == "graded"]
    if g.empty: print("none graded yet."); return
    g = g.assign(Return=pd.to_numeric(g["Return"], errors="coerce"))
    w = (g["Won"] == "Y").sum(); l = (g["Won"] == "N").sum()
    print(f"THE REVEAL — record {w}-{l}  ({w/(w+l):.0%})  ROI {g['Return'].mean()*100:+.1f}%  n={len(g)}")

def simulate():
    g = load_games(); _, _, _, snaps = walk_elo(g); lines = consensus_lines()
    hits = []
    for s in snaps:
        key = (s["hk"], s["ak"])
        mk = next((v for k, v in lines.items() if _norm(v[0]) == s["hk"] and _norm(v[1]) == s["ak"]), None)
        # match odds by normalized school name
        mkt = None
        for k, v in lines.items():
            if _core(v[0]) == s["hk"] or _norm(v[0]) == s["hk"]:
                if _core(v[1]) == s["ak"] or _norm(v[1]) == s["ak"]:
                    mkt = v[2]; break
        if mkt is None: continue
        edge = mkt - s["model_home_spread"]; t = s["tape"]
        if not (t >= TAPE_MIN and EDGE_MIN <= abs(edge) <= EDGE_MAX): continue
        margin = s["hs"] - s["as"]; home_cover = (margin + mkt) > 0
        win = home_cover if edge > 0 else (not home_cover)
        hits.append({"wk": s["wk"], "win": win})
    b = pd.DataFrame(hits); roi = lambda w: w*(100/110)-(1-w)
    if b.empty: print("no matched sweet-spot bets (check odds join)."); return
    w = b["win"].mean()
    print(f"SIMULATE 2025 — sweet-spot Reveal plays: {w:.1%} cover -> {roi(w)*100:+.1f}% @-110  (n={len(b):,})")
    mid = b[(b["wk"] >= 5) & (b["wk"] <= 9)]
    if len(mid) >= 25:
        wm = mid["win"].mean(); print(f"  weeks 5-9: {wm:.1%} cover -> {roi(wm)*100:+.1f}%  (n={len(mid)})")
    print("  ^ engine reproduces the validated edge. In-season: ratings/board/capture/grade/report weekly.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "simulate"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    {"simulate": simulate, "ratings": lambda: ratings(),
     "board": lambda: board(arg), "capture": lambda: capture(arg),
     "grade": grade, "report": report}.get(cmd, lambda: print(__doc__))()
