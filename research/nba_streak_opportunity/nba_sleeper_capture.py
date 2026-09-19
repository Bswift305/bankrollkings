# -*- coding: utf-8 -*-
"""
Kings Sleeper — forward-capture harness for the NBA streak+opportunity edge test.

WHAT IT DOES
  Finds "opportunity" candidates = a player on a 2-game over-streak WHO also has a
  star teammate OUT and a soft matchup (the filter validated in FINDINGS.md), then
  captures each with its line+price, grades it after the game, and reports walk-forward
  ROI. Doubles as a live "Kings Sleeper" feed.

TWO MODES
  simulate   -> runs the WHOLE pipeline over the historical 2025-26 gamelogs to prove
                the plumbing end-to-end. Uses a form-line proxy + a flat -110 price
                (no real lines exist off-season), so its ROI is a SIGNAL check, not the
                real-money answer. This is what we can verify today.
  live       -> in-season, daily: read the upcoming slate's props (real closing line +
                price), tag streak/star-out/soft-matchup from fresh gamelogs + injuries,
                append to the capture log. Then grade + report as games resolve. This is
                the gold-standard walk-forward test (zero hindsight).

USAGE
  python nba_sleeper_capture.py simulate          # verify now (historical)
  python nba_sleeper_capture.py capture 2026-10-21 # in-season: log today's candidates
  python nba_sleeper_capture.py grade             # grade resolved captures vs gamelogs
  python nba_sleeper_capture.py report            # walk-forward ROI from the log
"""
import sys, pathlib
import pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]           # repo root
GAMELOGS   = ROOT / "data" / "gamelogs" / "NBA_GameLogs.csv"
PROPS      = ROOT / "data" / "props" / "NBA_Props.csv"        # in-season props feed (schema documented below)
INJURIES   = ROOT / "data" / "injuries" / "NBA_Injuries.csv"  # in-season injury feed (optional; gamelog-absence fallback)
HERE       = pathlib.Path(__file__).resolve().parent
CAPTURE_LOG = HERE / "sleeper_capture_log.csv"
SIM_PICKS   = HERE / "sim_picks_2025_26.csv"

STATS = ["PTS", "REB", "AST"]
ROLL = 10            # trailing games for the form line
ROT_MIN = 18         # avg minutes to count as a rotation player
ROT_GAMES = 10       # min games to qualify as rotation
BREAK_EVEN = -110    # price assumed in simulate mode

# ----------------------------------------------------------------------------- prep
def _to_min(x):
    x = str(x).strip()
    if ":" in x:
        try:
            a, b = x.split(":")[:2]; return float(a) + float(b) / 60.0
        except Exception:
            return np.nan
    try:
        return float(x)
    except Exception:
        return np.nan

def load_gamelogs(path=GAMELOGS):
    g = pd.read_csv(path, dtype=str, low_memory=False)
    g["Date"] = pd.to_datetime(g["Date"], errors="coerce")
    g["MINf"] = g["MIN"].map(_to_min)
    for s in STATS:
        g[s] = pd.to_numeric(g[s], errors="coerce")
    g["home"] = ~g["Matchup"].astype(str).str.contains("@")
    g = g.dropna(subset=["Date", "PlayerID", "Team", "Game_ID"])
    g = g[g["MINf"] > 0].sort_values(["PlayerID", "Date"]).reset_index(drop=True)
    return g

def team_rotation_stars(g):
    prof = g.groupby(["Team", "PlayerID"]).agg(
        games=("MINf", "size"), avgmin=("MINf", "mean"), avgpts=("PTS", "mean")).reset_index()
    rotation, stars = {}, {}
    for team, sub in prof.groupby("Team"):
        rot = sub[(sub["avgmin"] >= ROT_MIN) & (sub["games"] >= ROT_GAMES)]
        rotation[team] = set(rot["PlayerID"])
        stars[team] = set(rot.sort_values("avgpts", ascending=False).head(2)["PlayerID"])
    return rotation, stars

def _def_allowed(g, stat):
    allowed = g.groupby("Opp")[stat].mean()
    return allowed, allowed.quantile(2 / 3)  # soft = allows >= top third

# ------------------------------------------------------ the shared filter (validated)
def tag_filter(g, stat):
    """Return g with columns: line, over, streak2 (leakage-free), star_out, soft."""
    d = g.copy()
    d["line"] = d.groupby("PlayerID")[stat].transform(
        lambda x: x.shift(1).rolling(ROLL, min_periods=ROLL).median())
    d["over"] = (d[stat] > d["line"]).astype(float)
    ov = d.groupby("PlayerID")["over"]
    d["streak2"] = (ov.shift(1) == 1) & (ov.shift(2) == 1)
    rotation, stars = team_rotation_stars(d)
    present = d.groupby(["Team", "Game_ID"])["PlayerID"].apply(set).to_dict()
    def _so(r):
        pres = present.get((r["Team"], r["Game_ID"]), set())
        out = (rotation.get(r["Team"], set()) - {r["PlayerID"]}) - pres
        return bool((stars.get(r["Team"], set()) - {r["PlayerID"]}) & out)
    d["star_out"] = d.apply(_so, axis=1)
    allowed, thr = _def_allowed(d, stat)
    d["soft"] = d["Opp"].map(allowed) >= thr
    return d

def is_candidate(d):
    """The final Kings-Sleeper filter."""
    return d["streak2"] & d["star_out"] & d["soft"] & d["line"].notna()

# ----------------------------------------------------------------- simulate (verify)
def _roi_at(price, win):
    dec = 1 + (price / 100 if price > 0 else 100 / abs(price))
    return (dec - 1) if win else -1.0

def simulate():
    g = load_gamelogs()
    picks = []
    for stat in STATS:
        d = tag_filter(g, stat)
        cand = d[is_candidate(d)].copy()
        cand["Stat"] = stat
        cand["win"] = cand["over"] == 1  # over bet grades vs the (proxy) line
        cand["ret"] = [_roi_at(BREAK_EVEN, w) for w in cand["win"]]
        picks.append(cand[["Date", "Player", "Team", "Opp", "Stat", "line",
                            stat, "over", "win", "ret"]].rename(columns={stat: "actual"}))
    allp = pd.concat(picks).sort_values("Date").reset_index(drop=True)
    allp.to_csv(SIM_PICKS, index=False)
    n = len(allp); hit = allp["win"].mean(); roi = allp["ret"].mean()
    # split by season half for out-of-sample honesty
    mid = allp["Date"].quantile(0.5)
    h2 = allp[allp["Date"] > mid]
    print("="*64)
    print("SIMULATE (historical 2025-26, form-line proxy, flat -110)")
    print("  This validates the pipeline end-to-end. It is a SIGNAL check,")
    print("  NOT the real-money answer (no true closing lines off-season).")
    print("="*64)
    print(f"  candidates (streak+star-out+soft): {n:,}")
    print(f"  hit rate: {hit:.1%}   (break-even at -110 = 52.4%)")
    print(f"  ROI @ -110 proxy: {roi*100:+.1f}%")
    print(f"  out-of-sample half: {len(h2):,} picks, hit {h2['win'].mean():.1%}, ROI {h2['ret'].mean()*100:+.1f}%")
    print(f"  by stat:")
    for stat, sub in allp.groupby("Stat"):
        print(f"    {stat}: {len(sub):,} picks, hit {sub['win'].mean():.1%}, ROI {sub['ret'].mean()*100:+.1f}%")
    print(f"\n  sample picks written to: {SIM_PICKS.name}")
    print("\n  ^ Pipeline verified. In-season, swap the proxy line for the real")
    print("    closing line+price via `capture` and this becomes the true test.")
    return allp

# --------------------------------------------------------------- live capture (season)
def _read_optional(path):
    try:
        return pd.read_csv(path, dtype=str, low_memory=False)
    except Exception:
        return None

def capture(as_of):
    """In-season: log today's Kings-Sleeper candidates with REAL line+price.

    Inputs expected in-season:
      * fresh NBA_GameLogs.csv (completed games up to yesterday) -> streak/form/star-out/soft
      * NBA_Props.csv with today's slate. Expected columns (rename to match your feed):
          Player, Team, Opp, Stat, Direction, Line, Price   (+ optional Book, CloseFlag)
        The Line/Price captured should be the CLOSING number (run this near lock).
    Writes matching candidates to sleeper_capture_log.csv (status='open').
    """
    as_of = pd.to_datetime(as_of)
    g = load_gamelogs()
    props = _read_optional(PROPS)
    if props is None or props.empty:
        print(f"[capture {as_of.date()}] No props feed at {PROPS} (off-season / not built yet).")
        print("  In-season, point PROPS at your daily NBA player-prop CSV with columns")
        print("  Player,Team,Opp,Stat,Direction,Line,Price and re-run near lock.")
        return
    rows = []
    for stat in STATS:
        d = tag_filter(g, stat)
        # latest state per player as of the prior game (streak/star-out carry into today)
        last = d.sort_values("Date").groupby("PlayerID").tail(1)
        hot = last[last["streak2"] & last["star_out"]]  # soft depends on TODAY's opp -> check via props
        pr = props[props["Stat"].astype(str).str.upper() == stat.upper()]
        allowed, thr = _def_allowed(d, stat)
        for _, p in pr.iterrows():
            pid_match = hot[hot["Player"].astype(str).str.lower() == str(p.get("Player", "")).lower()]
            if pid_match.empty:
                continue
            opp = str(p.get("Opp", ""))
            soft = allowed.get(opp, np.nan)
            if not (pd.notna(soft) and soft >= thr):
                continue
            rows.append({
                "CapturedAt": as_of.strftime("%Y-%m-%d"), "Player": p.get("Player"),
                "Team": p.get("Team"), "Opp": opp, "Stat": stat,
                "Direction": p.get("Direction", "OVER"), "Line": p.get("Line"),
                "Price": p.get("Price"), "Book": p.get("Book", ""),
                "Filter": "streak2+star_out+soft", "status": "open",
                "ResultValue": "", "Outcome": "", "Return": "",
            })
    if not rows:
        print(f"[capture {as_of.date()}] 0 candidates today.")
        return
    new = pd.DataFrame(rows)
    if CAPTURE_LOG.exists():
        new = pd.concat([pd.read_csv(CAPTURE_LOG, dtype=str), new], ignore_index=True)
    new.to_csv(CAPTURE_LOG, index=False)
    print(f"[capture {as_of.date()}] logged {len(rows)} candidate(s) -> {CAPTURE_LOG.name}")

def grade():
    """Grade open captures against completed gamelogs (actual stat vs the captured line)."""
    if not CAPTURE_LOG.exists():
        print("No capture log yet."); return
    log = pd.read_csv(CAPTURE_LOG, dtype=str)
    g = load_gamelogs()
    g["key"] = g["Player"].str.lower() + "|" + g["Date"].dt.strftime("%Y-%m-%d")
    graded = 0
    for i, r in log[log["status"] == "open"].iterrows():
        # find the player's game ON or AFTER capture date (first upcoming game)
        gm = g[(g["Player"].str.lower() == str(r["Player"]).lower()) &
               (g["Date"] >= pd.to_datetime(r["CapturedAt"]))].sort_values("Date").head(1)
        if gm.empty:
            continue
        actual = float(gm.iloc[0][r["Stat"]]); line = float(r["Line"])
        over = actual > line
        win = over if str(r["Direction"]).upper() == "OVER" else (not over)
        price = float(r["Price"]) if str(r["Price"]).strip() not in ("", "nan") else BREAK_EVEN
        log.at[i, "ResultValue"] = actual
        log.at[i, "Outcome"] = "Hit" if win else "Miss"
        log.at[i, "Return"] = round(_roi_at(price, win), 4)
        log.at[i, "status"] = "graded"; graded += 1
    log.to_csv(CAPTURE_LOG, index=False)
    print(f"graded {graded} capture(s).")

def report():
    if not CAPTURE_LOG.exists():
        print("No capture log yet."); return
    log = pd.read_csv(CAPTURE_LOG, dtype=str)
    g = log[log["status"] == "graded"].copy()
    if g.empty:
        print(f"{len(log)} captured, none graded yet."); return
    g["Return"] = pd.to_numeric(g["Return"], errors="coerce")
    hit = (g["Outcome"] == "Hit").mean(); roi = g["Return"].mean()
    print("="*64)
    print("KINGS SLEEPER — walk-forward record (REAL captured lines)")
    print("="*64)
    print(f"  record: {(g['Outcome']=='Hit').sum()}-{(g['Outcome']=='Miss').sum()}   hit {hit:.1%}   ROI {roi*100:+.1f}%")
    print(f"  break-even at -110 = 52.4%. n={len(g):,}")
    for stat, sub in g.groupby("Stat"):
        print(f"    {stat}: {len(sub)} picks, hit {(sub['Outcome']=='Hit').mean():.1%}, ROI {sub['Return'].mean()*100:+.1f}%")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "simulate"
    if cmd == "simulate": simulate()
    elif cmd == "capture": capture(sys.argv[2] if len(sys.argv) > 2 else pd.Timestamp.today())
    elif cmd == "grade": grade()
    elif cmd == "report": report()
    else: print(__doc__)
