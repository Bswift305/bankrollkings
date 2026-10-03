#!/usr/bin/env python3
"""Append a daily snapshot of the Buy Low / Sell High boards (NFL player lenses + CFB team
lens) to a persistent archive, so the lens can be GRADED later -- the honest bridge to the
Learn step. The boards are live-computed and otherwise thrown away each day; without this
capture we could never answer "did buy-lows actually revert up / did sell-highs fade?".

Each row records the subject, the stat/lens, and the as-of metrics (role/quality score, the
season baseline, and the recent value that diverged from it) so a future grader can join the
subject's SUBSEQUENT games and measure whether production moved the way the lens implied --
NOT a claim that it will, just the data to check.

Idempotent: one row per (SnapshotDate, Sport, Kind, Subject, Stat); re-running the same day
replaces that day's snapshot rather than duplicating it. data/tracking/ is gitignored, so PROD
accumulates its own running record. Wire into run_daily.py so it runs every day in season.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import build_nfl_buy_low_board, build_cfb_buy_low_board

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "tracking" / "BuyLow_Archive.csv"

COLS = ["SnapshotDate", "Season", "Sport", "Kind", "Subject", "Team", "Stat", "Score",
        "SeasonVal", "RecentVal", "RecentW", "Delta", "Note", "Opponent", "OppHome",
        "Line", "Why"]


def _eastern_today() -> str:
    try:
        from services.timeutils import to_eastern_date_str  # noqa
        return to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _nfl_rows(snap: str) -> list:
    out = []
    try:
        b = build_nfl_buy_low_board(stat="all")
    except Exception as exc:
        print(f"[capture_buy_low] NFL board error: {exc}")
        return out
    season = b.get("season") or 2026
    for kind in ("buy_low", "sell_high"):
        for x in b.get("buy_low" if kind == "buy_low" else "sell_high", []):
            out.append({
                "SnapshotDate": snap, "Season": season, "Sport": "NFL", "Kind": kind,
                "Subject": x.get("player"), "Team": x.get("team"), "Stat": x.get("stat_tag"),
                "Score": x.get("opp_score"), "SeasonVal": x.get("season_pg"),
                "RecentVal": x.get("recent_pg"), "RecentW": x.get("recent_w"),
                "Delta": x.get("delta_pct"), "Note": x.get("role"),
                "Opponent": "", "OppHome": "", "Line": "", "Why": x.get("why"),
            })
    return out


def _cfb_rows(snap: str) -> list:
    out = []
    try:
        b = build_cfb_buy_low_board()
    except Exception as exc:
        print(f"[capture_buy_low] CFB board error: {exc}")
        return out
    for kind in ("buy_low", "sell_high"):
        for x in b.get("buy_low" if kind == "buy_low" else "sell_high", []):
            nx = x.get("next") or {}
            out.append({
                "SnapshotDate": snap, "Season": 2026, "Sport": "CFB", "Kind": kind,
                "Subject": x.get("team"), "Team": x.get("team"), "Stat": "Team",
                "Score": x.get("quality"), "SeasonVal": x.get("srs"),
                "RecentVal": x.get("recent_resid"), "RecentW": x.get("recent_w"),
                "Delta": x.get("recent_resid"), "Note": x.get("prior_label"),
                "Opponent": nx.get("opp") or "",
                "OppHome": ("H" if nx.get("home") else "A") if nx.get("opp") else "",
                "Line": nx.get("spread") if nx.get("spread") is not None else "",
                "Why": x.get("why"),
            })
    return out


def main() -> int:
    snap = _eastern_today()
    rows = _nfl_rows(snap) + _cfb_rows(snap)
    if not rows:
        print(f"[capture_buy_low] snapshot {snap}: no board rows (off-season / empty) -- nothing captured")
        return 0
    fresh = pd.DataFrame(rows)

    if OUT_PATH.exists():
        try:
            prior = pd.read_csv(OUT_PATH)
        except Exception:
            prior = pd.DataFrame(columns=COLS)
        keycols = ["SnapshotDate", "Sport", "Kind", "Subject", "Stat"]
        if not prior.empty and set(keycols).issubset(prior.columns):
            pk = prior[keycols].astype(str).agg("|".join, axis=1)
            nk = set(fresh[keycols].astype(str).agg("|".join, axis=1))
            prior = prior[~pk.isin(nk)]
        combined = pd.concat([prior, fresh], ignore_index=True)
    else:
        combined = fresh
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    for c in COLS:
        if c not in combined.columns:
            combined[c] = ""
    combined[COLS].to_csv(OUT_PATH, index=False)
    nb = sum(1 for r in rows if r["Kind"] == "buy_low")
    print(f"[capture_buy_low] snapshot {snap}: {nb} buy / {len(rows) - nb} sell "
          f"({sum(1 for r in rows if r['Sport'] == 'NFL')} NFL, "
          f"{sum(1 for r in rows if r['Sport'] == 'CFB')} CFB) -> {OUT_PATH.name} "
          f"({len(combined)} total rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
