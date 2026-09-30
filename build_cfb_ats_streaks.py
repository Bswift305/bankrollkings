#!/usr/bin/env python3
"""CFB ATS cover streaks -- per-team CURRENT-SEASON against-the-spread results in
CHRONOLOGICAL order, so we can see who's on an active cover streak and who can't beat the
number. College player props are thin, so CFB keys on team/game-line angles; this is the
ATS equivalent of a hot-hand board.

For each team: walk its games oldest->newest, mark each a cover (C), no-cover (L) or push
(P) vs the closing consensus spread, and count the current run from the most recent game
backward. Joined to this week's upcoming line.

HONEST BY DESIGN: an ATS streak is a trend the market already PRICES -- our graded work
shows streaks live in the number -- so this is "who's been beating the spread lately," a
starting point and eye-test, NOT a proven edge. Presented as context, best-first.

Source: CFBD lines API (game-by-game spreads + finals). Writes
data/scenarios/cfb_ats_streaks.json. Needs CFBD_API_KEY (.env / .env.local).
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
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_ats_streaks.json"


def _median_spread(lines):
    sp = [l["spread"] for l in (lines or []) if l.get("spread") is not None]
    return statistics.median(sp) if sp else None


def _streak_of(games):
    """From the most recent completed game backward: the current same-result run.
    Pushes are neutral (skipped, don't break a run). Returns type/len/last-string/avg."""
    games = sorted(games, key=lambda x: (x["week"] or 0, x["start"]))
    seq = [g for g in games if g["res"] in ("C", "L")]
    if not seq:
        return None
    last = seq[-1]["res"]
    run = []
    for g in reversed(seq):
        if g["res"] == last:
            run.append(g)
        else:
            break
    avg = round(sum(g["margin"] for g in run) / len(run), 1)
    return {"type": "cover" if last == "C" else "fade", "len": len(run),
            "last": " ".join(g["res"] for g in seq[-6:]), "avg_margin": avg}


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    req = urllib.request.Request(
        f"https://api.collegefootballdata.com/lines?year={season}&seasonType=regular",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)

    hist = defaultdict(list)   # team -> completed games (chronological once sorted)
    upcoming = {}              # team -> soonest future game + current line
    for g in data:
        spread = _median_spread(g.get("lines"))
        h, a = g.get("homeTeam"), g.get("awayTeam")
        hc = str(g.get("homeClassification") or "").lower()
        ac = str(g.get("awayClassification") or "").lower()
        wk, start = g.get("week"), g.get("startDate") or ""
        completed = g.get("homeScore") is not None and g.get("awayScore") is not None
        if completed and spread is not None:
            cov = (g["homeScore"] - g["awayScore"]) + spread  # >0 -> home covers
            for team, opp, margin, home, cls in ((h, a, cov, True, hc), (a, h, -cov, False, ac)):
                if cls != "fbs":
                    continue
                res = "C" if margin > 0.001 else ("L" if margin < -0.001 else "P")
                hist[team].append({"week": wk, "start": start, "opp": opp, "home": home,
                                   "res": res, "margin": round(margin, 1)})
        elif not completed:
            for team, opp, home, cls in ((h, a, True, hc), (a, h, False, ac)):
                if cls != "fbs":
                    continue
                cur = upcoming.get(team)
                if cur is None or (start and start < cur["start"]):
                    upcoming[team] = {"week": wk, "start": start, "opp": opp, "home": home,
                                      "line": (round((spread if home else -spread), 1)
                                               if spread is not None else None)}

    rows = []
    for t, games in hist.items():
        c = sum(1 for g in games if g["res"] == "C")
        l = sum(1 for g in games if g["res"] == "L")
        p = sum(1 for g in games if g["res"] == "P")
        n = c + l
        if n < 2:
            continue
        st = _streak_of(games)
        if not st:
            continue
        nxt = upcoming.get(t)
        rows.append({
            "team": t, "streak_type": st["type"], "streak": st["len"],
            "last": st["last"], "streak_acm": st["avg_margin"],
            "ats": f"{c}-{l}" + (f"-{p}" if p else ""),
            "cover_pct": round(100 * c / n) if n else None,
            "acm": round(sum(g["margin"] for g in games) / len(games), 1), "n": n,
            "next_opp": (nxt["opp"] if nxt else None),
            "next_home": (nxt["home"] if nxt else None),
            "next_line": (nxt["line"] if nxt else None),
            "next_week": (nxt["week"] if nxt else None),
        })

    cover = sorted([r for r in rows if r["streak_type"] == "cover" and r["streak"] >= 2],
                   key=lambda r: (-r["streak"], -r["streak_acm"]))
    fade = sorted([r for r in rows if r["streak_type"] == "fade" and r["streak"] >= 2],
                  key=lambda r: (-r["streak"], r["streak_acm"]))
    weeks = sorted(set(g["week"] for gs in hist.values() for g in gs if g["week"]))
    return {"season": season, "through_week": weeks[-1] if weeks else None,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "boards": {"cover": cover, "fade": fade}}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    b = data["boards"]
    print(f"[build_cfb_ats_streaks] {args.season} thru wk {data['through_week']}: "
          f"{len(b['cover'])} cover streaks, {len(b['fade'])} fade streaks -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
