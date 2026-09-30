#!/usr/bin/env python3
"""NFL Regression Watch -- who's outrunning (or lagging) their underlying play and is
therefore likely to move toward it. In-season sibling of the CFB regression tool.

Three well-worn, HONEST regression signals, none of them a game prediction:
  * Record vs point differential (Pythagorean wins, exp 2.37) -- point diff predicts a
    team's REST-OF-SEASON record better than its current W-L does. A 3-0 team outscoring
    nobody is living on the edge; a 1-2 team with a fat differential has been unlucky.
  * One-score games (decided by <= 8) -- close-game W-L is close to a coin flip over time,
    so a gaudy one-score record is the least sticky thing on a resume.
  * Turnover margin -- extreme takeaway/giveaway margins swing hard week to week; a big
    plus is rarely sustained.

Reads nflverse games.csv (scores) for the current season's completed games, and reuses the
turnover margins already computed in data/scenarios/nfl_2026_form.json. Writes
data/scenarios/nfl_regression.json (committable, mtime-cached by the app). No key needed.
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
FORM_JSON = BASE_DIR / "data" / "scenarios" / "nfl_2026_form.json"
OUT_PATH = BASE_DIR / "data" / "scenarios" / "nfl_regression.json"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
_UA = {"User-Agent": "Mozilla/5.0"}
TEAM_NORM = {"LA": "LAR"}  # nflverse uses LA for the Rams; our feeds use LAR
PYTHAG_EXP = 2.37  # Football Outsiders' NFL Pythagorean exponent


def current_nfl_season() -> int:
    try:
        from services.timeutils import to_eastern_date_str  # noqa
        s = to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
        y, m = int(s[:4]), int(s[5:7])
    except Exception:
        n = datetime.now()
        y, m = n.year, n.month
    return y if m >= 3 else y - 1


def _norm(t: str) -> str:
    return TEAM_NORM.get(str(t), str(t))


def _load_to_margin() -> dict:
    """team -> turnover margin, from the already-built current-season form JSON."""
    try:
        d = json.loads(FORM_JSON.read_text(encoding="utf-8"))
        return {k: (v.get("to_margin") if isinstance(v, dict) else None)
                for k, v in (d.get("teams") or {}).items()}
    except Exception:
        return {}


def main() -> int:
    season = current_nfl_season()
    try:
        raw = urllib.request.urlopen(urllib.request.Request(GAMES_URL, headers=_UA), timeout=60).read().decode()
        g = pd.read_csv(io.StringIO(raw))
    except Exception as exc:
        print(f"[build_nfl_regression] could not fetch games.csv ({exc})")
        return 1

    g = g[pd.to_numeric(g.get("season"), errors="coerce") == season].copy()
    # regular-season, completed games only
    if "game_type" in g.columns:
        g = g[g["game_type"].astype(str).str.upper().isin(["REG", "REGULAR", ""])]
    for c in ("home_score", "away_score"):
        g[c] = pd.to_numeric(g.get(c), errors="coerce")
    g = g.dropna(subset=["home_score", "away_score"])
    if g.empty:
        print(f"[build_nfl_regression] no completed {season} games yet; nothing to build")
        # leave any prior file in place
        return 0

    to_margin = _load_to_margin()
    weeks = sorted(int(w) for w in pd.to_numeric(g.get("week"), errors="coerce").dropna().unique())

    # accumulate per-team box
    rec: dict[str, dict] = {}

    def team(t):
        return rec.setdefault(_norm(t), {"g": 0, "w": 0.0, "l": 0, "t": 0, "pf": 0, "pa": 0,
                                         "osw": 0, "osl": 0})

    for r in g.to_dict("records"):
        h, a = _norm(r["home_team"]), _norm(r["away_team"])
        hs, as_ = float(r["home_score"]), float(r["away_score"])
        H, A = team(h), team(a)
        H["g"] += 1; A["g"] += 1
        H["pf"] += hs; H["pa"] += as_
        A["pf"] += as_; A["pa"] += hs
        margin = hs - as_
        one_score = abs(margin) <= 8 and margin != 0
        if margin > 0:
            H["w"] += 1; A["l"] += 1
            if one_score:
                H["osw"] += 1; A["osl"] += 1
        elif margin < 0:
            A["w"] += 1; H["l"] += 1
            if one_score:
                A["osw"] += 1; H["osl"] += 1
        else:
            H["t"] += 1; A["t"] += 1

    rows = []
    for t, d in rec.items():
        gp = d["g"]
        if gp < 2:
            continue
        wins = d["w"] + 0.5 * d["t"]
        pf, pa = d["pf"], d["pa"]
        exp_pct = (pf ** PYTHAG_EXP) / ((pf ** PYTHAG_EXP) + (pa ** PYTHAG_EXP)) if (pf + pa) else 0.5
        exp_wins = exp_pct * gp
        win_luck = wins - exp_wins
        tom = to_margin.get(t)
        drivers = []
        if abs(win_luck) >= 0.6:
            more = "more" if win_luck > 0 else "fewer"
            drivers.append(f"{abs(win_luck):.1f} {more} win{'s' if abs(win_luck) >= 1.5 else ''} than its {'+' if (pf - pa) >= 0 else ''}{int(pf - pa)} point diff implies")
        if (d["osw"] + d["osl"]) >= 2 and d["osw"] != d["osl"]:
            drivers.append(f"{d['osw']}-{d['osl']} in one-score games")
        if tom is not None and abs(tom) >= 3:
            drivers.append(f"{'+' if tom > 0 else ''}{int(tom)} turnover margin")
        rows.append({
            "team": t, "g": gp,
            "w": int(d["w"]), "l": int(d["l"]), "t": int(d["t"]),
            "pf": int(pf), "pa": int(pa), "pt_diff": int(pf - pa),
            "exp_wins": round(exp_wins, 1), "win_luck": round(win_luck, 1),
            "os_w": d["osw"], "os_l": d["osl"],
            "to_margin": int(tom) if tom is not None else None,
            "note": "; ".join(drivers) if drivers else "tracking close to its underlying",
        })

    # due to FALL = overperforming (positive luck), best-first = most overperforming on top.
    # due to RISE = underperforming (negative luck), most unlucky on top.
    fall = sorted([r for r in rows if r["win_luck"] > 0.3], key=lambda r: -r["win_luck"])
    rise = sorted([r for r in rows if r["win_luck"] < -0.3], key=lambda r: r["win_luck"])

    out = {
        "meta": {"season": season, "through_week": weeks[-1] if weeks else None,
                 "teams": len(rows), "generated": datetime.utcnow().strftime("%Y-%m-%d")},
        "boards": {"due_to_fall": fall, "due_to_rise": rise},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[build_nfl_regression] {season} through wk {out['meta']['through_week']}: "
          f"{len(fall)} due-to-fall, {len(rise)} due-to-rise -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
