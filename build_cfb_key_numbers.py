#!/usr/bin/env python3
"""CFB Key Numbers & Line Value -- this week's spreads read against the margins CFB games
actually land on, plus where the market has moved across a key number.

Evidence (24,320 FBS games, 2016-2025): final margins spike at 3 (8.2%) and 7 (7.4%), then
14 (4.2%), 10/21 (3.8%), 17 (3.3%). So 3 and 7 are the CFB key numbers -- real, but FLATTER
than the NFL (college has more blowouts), so a half-point matters, just less than in the pros.

For each upcoming game we flag: a spread sitting ON a key number (max leverage + live push
risk), a spread a half-point OFF a key (the best point to buy/sell), and a line that has
MOVED ACROSS a key since it opened. Ranked by leverage (the frequency of the key involved).

Source: CFBD lines API (current spread + spreadOpen). Writes data/scenarios/cfb_key_numbers.json.
Needs CFBD_API_KEY. HONEST: this informs point-buying / teaser decisions, it is NOT a
predictive edge -- the market prices key numbers too.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_key_numbers.json"

# Real CFB final-margin frequency, 2016-2025 (24,320 games). Baked so there's no runtime
# data dependency; recomputed from data/historical/CFBD_Games_2016_2025.csv when present.
MARGIN_FREQ = {3: 8.2, 7: 7.4, 14: 4.2, 10: 3.8, 21: 3.8, 17: 3.3, 4: 3.2, 1: 3.2}
KEYS = [3, 7, 10, 14, 17, 21]


def _recompute_freq():
    try:
        import pandas as pd
        p = BASE_DIR / "data" / "historical" / "CFBD_Games_2016_2025.csv"
        if not p.exists():
            return None
        d = pd.read_csv(p).dropna(subset=["homePts", "awayPts"])
        m = (d["homePts"] - d["awayPts"]).abs()
        n = len(m)
        if n < 500:
            return None
        from collections import Counter
        c = Counter(int(x) for x in m)
        return n, {k: round(100 * c.get(k, 0) / n, 1) for k in KEYS}
    except Exception:
        return None


def _median(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def _key_read(s_now, s_open, freq):
    """Classify a spread magnitude against the key numbers. Returns (situation, key, note,
    leverage) or None if it isn't meaningfully on/near/across a key."""
    a_now = abs(s_now)
    # ON a key (whole number equal to a key)
    for k in KEYS:
        if abs(a_now - k) < 0.1:
            note = (f"Sits on {k} — {freq.get(k, '?')}% of CFB games land exactly here. "
                    f"The most valuable half-point on the board, and live push risk at {k}.")
            return ("on", k, note, freq.get(k, 0) * 1.0)
    # a HALF-point off a key (X.5 adjacent to a key: 2.5/3.5 -> 3, 6.5/7.5 -> 7, ...)
    for k in KEYS:
        if abs(a_now - k) <= 0.5 + 0.01:
            side = "short of" if a_now < k else "past"
            note = (f"At {a_now:g}, a half-point {side} the key {k} ({freq.get(k, '?')}% of games). "
                    f"Buying through {k} (or selling off it) is the highest-value point here.")
            return ("near", k, note, freq.get(k, 0) * 0.8)
    return None


def _crossed(s_open, s_now):
    if s_open is None:
        return None
    lo, hi = sorted([abs(s_open), abs(s_now)])
    for k in KEYS:
        if lo < k < hi:
            return k
    return None


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    req = urllib.request.Request(
        f"https://api.collegefootballdata.com/lines?year={season}&seasonType=regular",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)

    rc = _recompute_freq()
    if rc:
        n_games, freq = rc
        freq = {**MARGIN_FREQ, **freq}
    else:
        n_games, freq = 24320, MARGIN_FREQ

    games = []
    for g in data:
        if g.get("homeScore") is not None:  # completed
            continue
        lines = g.get("lines") or []
        s_now = _median([l.get("spread") for l in lines])
        s_open = _median([l.get("spreadOpen") for l in lines])
        total = _median([l.get("overUnder") for l in lines])
        if s_now is None:
            continue
        hc = str(g.get("homeClassification") or "").lower()
        ac = str(g.get("awayClassification") or "").lower()
        if hc != "fbs" and ac != "fbs":
            continue
        kr = _key_read(s_now, s_open, freq)
        cx = _crossed(s_open, s_now)
        if not kr and not cx:
            continue
        situation, kkey, note, lev = kr if kr else (None, None, None, 0)
        move_note = None
        if cx:
            direction = "toward the favorite" if abs(s_now) > abs(s_open) else "toward the dog"
            move_note = (f"Line moved {s_open:+g} → {s_now:+g}, crossing the key {cx} "
                         f"({freq.get(cx, '?')}% of games) {direction}.")
            lev = max(lev, freq.get(cx, 0) * 0.9)
        games.append({
            "away": g.get("awayTeam"), "home": g.get("homeTeam"),
            "week": g.get("week"), "start": g.get("startDate") or "",
            "spread": round(s_now, 1), "spread_open": (round(s_open, 1) if s_open is not None else None),
            "total": (round(total, 1) if total is not None else None),
            "situation": situation, "key": kkey, "note": note,
            "crossed": cx, "move_note": move_note, "leverage": round(lev, 1),
        })
    games.sort(key=lambda x: -x["leverage"])
    top = sorted(freq.items(), key=lambda kv: -kv[1])
    return {"season": season, "games_sampled": n_games,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "margin_freq": [{"margin": k, "pct": v} for k, v in top if k in KEYS],
            "games": games}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[build_cfb_key_numbers] {args.season}: {len(data['games'])} games on/near/across a "
          f"key number -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
