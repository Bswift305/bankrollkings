#!/usr/bin/env python3
"""CFB team streaks vs the number -- ATS cover streaks AND totals (over/under) streaks,
per-team in CHRONOLOGICAL order, so we can see who's on an active run against the closing
spread and against the closing total. College player props are thin, so CFB keys on the
team/game-line side; this is the ATS + totals equivalent of a hot-hand board.

For each team: walk its games oldest->newest, mark each vs the closing consensus spread
(cover C / no-cover L / push P) and vs the closing consensus total (over O / under U /
push P), count the current run on each, and join this week's line + total.

HONEST BY DESIGN: a streak is a trend the market already PRICES -- our graded work shows
streaks live in the number -- so this is "who's been beating the number lately," a
starting point and eye-test, NOT a proven edge. Presented as context, best-first.

Source: CFBD lines API (game-by-game spreads, totals + finals). Writes
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


def _median(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def _streak(games, field, pos, neg, pos_label, neg_label):
    """Current same-result run from the most recent completed game backward, on `field`
    (values pos/neg, plus 'P' push which is neutral/skipped). Returns type/len/last/avg."""
    games = sorted(games, key=lambda x: (x["week"] or 0, x["start"]))
    seq = [g for g in games if g[field] in (pos, neg)]
    if not seq:
        return None
    last = seq[-1][field]
    run = []
    for g in reversed(seq):
        if g[field] == last:
            run.append(g)
        else:
            break
    mfield = "m_" + field
    avg = round(sum(g[mfield] for g in run) / len(run), 1)
    return {"type": pos_label if last == pos else neg_label, "len": len(run),
            "last": " ".join(g[field] for g in seq[-6:]), "avg_margin": avg}


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
    upcoming = {}              # team -> soonest future game + current line/total
    for g in data:
        lines = g.get("lines") or []
        spread = _median([l.get("spread") for l in lines])
        total = _median([l.get("overUnder") for l in lines])
        h, a = g.get("homeTeam"), g.get("awayTeam")
        hc = str(g.get("homeClassification") or "").lower()
        ac = str(g.get("awayClassification") or "").lower()
        wk, start = g.get("week"), g.get("startDate") or ""
        completed = g.get("homeScore") is not None and g.get("awayScore") is not None
        if completed:
            fin_total = g["homeScore"] + g["awayScore"]
            ou_margin = (fin_total - total) if total is not None else None
            res_ou = None
            if ou_margin is not None:
                res_ou = "O" if ou_margin > 0.001 else ("U" if ou_margin < -0.001 else "P")
            cov = (g["homeScore"] - g["awayScore"] + spread) if spread is not None else None
            for team, margin, home, cls in ((h, cov, True, hc), (a, (-cov if cov is not None else None), False, ac)):
                if cls != "fbs":
                    continue
                res_ats = None
                if margin is not None:
                    res_ats = "C" if margin > 0.001 else ("L" if margin < -0.001 else "P")
                hist[team].append({
                    "week": wk, "start": start,
                    "res_ats": res_ats, "m_res_ats": (round(margin, 1) if margin is not None else 0.0),
                    "res_ou": res_ou, "m_res_ou": (round(ou_margin, 1) if ou_margin is not None else 0.0),
                })
        else:
            for team, home, cls in ((h, True, hc), (a, False, ac)):
                if cls != "fbs":
                    continue
                cur = upcoming.get(team)
                if cur is None or (start and start < cur["start"]):
                    upcoming[team] = {
                        "week": wk, "start": start, "opp": (a if home else h), "home": home,
                        "line": (round((spread if home else -spread), 1) if spread is not None else None),
                        "total": (round(total, 1) if total is not None else None)}

    def _season_rec(games, field, pos, neg):
        p = sum(1 for g in games if g[field] == pos)
        n = sum(1 for g in games if g[field] == neg)
        pu = sum(1 for g in games if g[field] == "P")
        return p, n, pu

    ats_rows, ou_rows = [], []
    for t, games in hist.items():
        nxt = upcoming.get(t)
        base = {"team": t,
                "next_opp": (nxt["opp"] if nxt else None),
                "next_home": (nxt["home"] if nxt else None),
                "next_line": (nxt["line"] if nxt else None),
                "next_total": (nxt["total"] if nxt else None),
                "next_week": (nxt["week"] if nxt else None)}
        # ATS
        c, l, p = _season_rec(games, "res_ats", "C", "L")
        st = _streak(games, "res_ats", "C", "L", "cover", "fade") if (c + l) >= 2 else None
        if st:
            ats_rows.append({**base, "streak_type": st["type"], "streak": st["len"],
                             "last": st["last"], "streak_acm": st["avg_margin"],
                             "rec": f"{c}-{l}" + (f"-{p}" if p else ""),
                             "pct": round(100 * c / (c + l)) if (c + l) else None, "n": c + l})
        # Totals (O/U)
        o, u, pu = _season_rec(games, "res_ou", "O", "U")
        sto = _streak(games, "res_ou", "O", "U", "over", "under") if (o + u) >= 2 else None
        if sto:
            ou_rows.append({**base, "streak_type": sto["type"], "streak": sto["len"],
                            "last": sto["last"], "streak_acm": sto["avg_margin"],
                            "rec": f"{o}-{u}" + (f"-{pu}" if pu else ""),
                            "pct": round(100 * o / (o + u)) if (o + u) else None, "n": o + u})

    cover = sorted([r for r in ats_rows if r["streak_type"] == "cover" and r["streak"] >= 2],
                   key=lambda r: (-r["streak"], -r["streak_acm"]))
    fade = sorted([r for r in ats_rows if r["streak_type"] == "fade" and r["streak"] >= 2],
                  key=lambda r: (-r["streak"], r["streak_acm"]))
    over = sorted([r for r in ou_rows if r["streak_type"] == "over" and r["streak"] >= 2],
                  key=lambda r: (-r["streak"], -r["streak_acm"]))
    under = sorted([r for r in ou_rows if r["streak_type"] == "under" and r["streak"] >= 2],
                   key=lambda r: (-r["streak"], r["streak_acm"]))
    weeks = sorted(set(g["week"] for gs in hist.values() for g in gs if g["week"]))
    return {"season": season, "through_week": weeks[-1] if weeks else None,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "boards": {"cover": cover, "fade": fade, "over": over, "under": under}}


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
          f"ATS {len(b['cover'])}C/{len(b['fade'])}F, totals {len(b['over'])}O/{len(b['under'])}U "
          f"-> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
