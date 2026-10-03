#!/usr/bin/env python3
"""Reusable signal-grading framework: Signal -> Resolve -> Measure -> Scoreboard.

The honest moat is measuring our own ideas AFTER the fact. This grades any captured signal
archive the same way: for each archived signal, a per-family RESOLVER fetches the subject's
OUTCOME after the snapshot and reports whether it moved the way the signal implied -- never a
claim it will, only the graded record once games resolve. New signal archives plug in by
adding a resolver; the aggregation/scoreboard is shared.

First archive wired: BuyLow_Archive.csv (the opportunity-vs-recent-production lens).
  - NFL (player): did the stat REVERT? buy-low expects production ABOVE the captured recent
    baseline in later games; sell-high expects it BELOW. (We grade the underlying stat, which
    is the lens's actual claim -- no prop line was captured.)
  - CFB (team): did the team COVER the captured spread in its next game? buy-low expects a
    cover; sell-high (a fade) expects the team NOT to cover.

Honest by construction: rows with no post-snapshot game yet are PENDING (not counted); small
samples are flagged; nothing here is an edge claim until the sample is real and out-of-sample.
Outputs data/tracking/Signal_Grades.csv (per-row) + Signal_Grades_Summary.json (scoreboard).
Idempotent full re-grade each run so PENDING resolves as games fill in. Wire into run_daily.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
ARCHIVE = BASE_DIR / "data" / "tracking" / "BuyLow_Archive.csv"
OUT_ROWS = BASE_DIR / "data" / "tracking" / "Signal_Grades.csv"
OUT_SUMMARY = BASE_DIR / "data" / "tracking" / "Signal_Grades_Summary.json"
MIN_SAMPLE = 20          # below this, a cohort's hit rate is "too few to read"


# --------------------------------------------------------------------------- resolvers
def resolve_nfl_player(row) -> dict | None:
    """Did the player's stat revert toward his role? Later-games mean vs the captured recent
    baseline. Returns {resolved, hit, outcome, move, detail} or {resolved: False} if pending."""
    try:
        from app import _nfl_player_week_data, _BL_LENSES
    except Exception:
        return None
    lens = {l["key"]: l for l in _BL_LENSES}.get(str(row.get("StatKey")))
    if lens is None:
        return None
    try:
        baseline = float(row.get("RecentVal"))
        asof = int(float(row.get("AsOfWeek")))
        season = int(float(row.get("Season")))
    except (TypeError, ValueError):
        return None
    log = _nfl_player_week_data()
    if log.empty:
        return {"resolved": False}
    g = log[(pd.to_numeric(log["season"], errors="coerce") == season) &
            (log["_full"].astype(str) == str(row.get("Subject")))].copy()
    if g.empty:
        return {"resolved": False}
    for c in ("week", "rushing_yards", "receiving_yards", "receptions", "targets",
              "carries", "passing_yards", "attempts"):
        g[c] = pd.to_numeric(g.get(c), errors="coerce").fillna(0.0)
    g = g[(g["week"] > asof) & lens["active"](g)]
    if g.empty:
        return {"resolved": False}                       # no later game yet -> pending
    later = float(lens["series"](g).mean())
    kind = str(row.get("Kind"))
    hit = (later > baseline) if kind == "buy_low" else (later < baseline)
    return {"resolved": True, "hit": bool(hit), "outcome": round(later, 1),
            "move": round(later - baseline, 1),
            "detail": f"{len(g)} g after wk{asof}: {round(later, 1)} vs {round(baseline, 1)} baseline"}


def resolve_cfb_team(row) -> dict | None:
    """Did the team cover the captured spread in its next game? buy-low expects a cover,
    sell-high (fade) expects no cover. Pending if the game hasn't been played."""
    try:
        import cfb_current_form as cff
    except Exception:
        return None
    opp = str(row.get("Opponent") or "").strip()
    try:
        line = float(row.get("Line"))
        asof = int(float(row.get("AsOfWeek")))
    except (TypeError, ValueError):
        return {"resolved": False}                       # no captured line -> can't grade ATS
    if not opp:
        return {"resolved": False}
    games = cff.team_games(str(row.get("Subject")))
    want = cff._resolve(opp)
    cand = [g for g in games if g.get("week", 0) > asof and cff._resolve(g.get("opp", "")) == want]
    if not cand:
        return {"resolved": False}                       # not played yet -> pending
    g = cand[0]
    cover = g["margin"] + line                           # team spread: >0 covered, <0 missed
    kind = str(row.get("Kind"))
    if abs(cover) < 1e-9:
        return {"resolved": True, "hit": None, "push": True, "outcome": g["margin"], "move": 0.0,
                "detail": f"wk{g['week']} vs {opp}: push"}
    covered = cover > 0
    hit = covered if kind == "buy_low" else (not covered)
    return {"resolved": True, "hit": bool(hit), "outcome": g["margin"], "move": round(cover, 1),
            "detail": f"wk{g['week']} vs {opp}: margin {g['margin']:+}, ATS {cover:+.1f}"}


RESOLVERS = {"NFL": resolve_nfl_player, "CFB": resolve_cfb_team}


# --------------------------------------------------------------------------- framework
def grade_archive(df: pd.DataFrame) -> pd.DataFrame:
    recs = []
    for _, row in df.iterrows():
        resolver = RESOLVERS.get(str(row.get("Sport")))
        res = resolver(row) if resolver else None
        r = row.to_dict()
        if not res:
            r.update(Resolved="", Hit="", Outcome="", Move="", GradeDetail="(no resolver)")
        elif not res.get("resolved"):
            r.update(Resolved=0, Hit="", Outcome="", Move="", GradeDetail="pending")
        elif res.get("push"):
            r.update(Resolved=1, Hit="push", Outcome=res.get("outcome"), Move=res.get("move"),
                     GradeDetail=res.get("detail"))
        else:
            r.update(Resolved=1, Hit=int(bool(res["hit"])), Outcome=res.get("outcome"),
                     Move=res.get("move"), GradeDetail=res.get("detail"))
        recs.append(r)
    return pd.DataFrame(recs)


def _cohort(graded: pd.DataFrame, keys: list) -> list:
    out = []
    for vals, g in graded.groupby(keys):
        decided = g[g["Hit"].isin([0, 1])]
        n_res = int((g["Resolved"] == 1).sum())
        n_hit = int((decided["Hit"] == 1).sum())
        n_dec = int(len(decided))
        moves = pd.to_numeric(g.loc[g["Resolved"] == 1, "Move"], errors="coerce").dropna()
        row = dict(zip(keys, vals if isinstance(vals, tuple) else (vals,)))
        row.update(
            n=int(len(g)), resolved=n_res, pending=int((g["Resolved"] == 0).sum()),
            decided=n_dec, hits=n_hit,
            hit_rate=(round(n_hit / n_dec * 100, 1) if n_dec else None),
            avg_move=(round(float(moves.mean()), 1) if len(moves) else None),
            read=("too few to read" if n_dec < MIN_SAMPLE else "out-of-sample"),
        )
        out.append(row)
    return out


def main() -> int:
    if not ARCHIVE.exists():
        print("[grade_signals] no BuyLow_Archive.csv yet -- nothing to grade")
        return 0
    try:
        df = pd.read_csv(ARCHIVE)
    except Exception as exc:
        print(f"[grade_signals] could not read archive: {exc}")
        return 1
    if df.empty:
        print("[grade_signals] archive empty")
        return 0

    graded = grade_archive(df)
    OUT_ROWS.parent.mkdir(parents=True, exist_ok=True)
    graded.to_csv(OUT_ROWS, index=False)

    summary = {
        "by_sport_kind": _cohort(graded, ["Sport", "Kind"]),
        "by_sport_kind_stat": _cohort(graded, ["Sport", "Kind", "Stat"]),
        "totals": {
            "rows": int(len(graded)),
            "resolved": int((graded["Resolved"] == 1).sum()),
            "pending": int((graded["Resolved"] == 0).sum()),
        },
        "min_sample": MIN_SAMPLE,
        "note": ("A graded record, not an edge claim. Pending rows have no post-snapshot game "
                 "yet; cohorts under the sample floor read 'too few'. Out-of-sample or it does "
                 "not count."),
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    t = summary["totals"]
    print(f"[grade_signals] {t['rows']} signals | {t['resolved']} resolved, {t['pending']} pending")
    for c in sorted(summary["by_sport_kind"], key=lambda x: (x["Sport"], x["Kind"])):
        hr = f"{c['hit_rate']}% ({c['hits']}/{c['decided']})" if c["hit_rate"] is not None else "--"
        print(f"  {c['Sport']:<3} {c['Kind']:<9} n={c['n']:<3} resolved={c['resolved']:<3} "
              f"hit={hr:<14} avg_move={c['avg_move']} [{c['read']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
