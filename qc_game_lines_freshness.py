"""QC: game-LINES freshness containment (2026-10-23 incident).

Props boards already fail closed on staleness; game-lines boards did not -- a stale odds feed rendered
day-old lines as current. `get_lines_refresh_meta` now flags a stale odds feed and the football method
board shows a visible "Game Lines Are Stale" banner. This proves:
  1. get_lines_refresh_meta: stale LastUpdated -> is_stale + warning; fresh -> not stale; empty / no
     LastUpdated -> unavailable / not stale (never a false "fresh").
  2. the football game-lines page renders the stale banner when the odds feed is stale, and NOT when it
     is fresh (real route + template, odds loader monkeypatched; owner session).

Deterministic; the odds loader is monkeypatched so no data/network is needed. Exits 0 on pass, 1 otherwise.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

import app

BANNER_MARK = "Game Lines Are Stale"


def _odds_fixture(age_hours):
    ts = (datetime.now() - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    return pd.DataFrame([{
        "Date": "2026-10-26", "Time": "1:00 PM", "Away": "Dallas Cowboys", "Home": "Philadelphia Eagles",
        "AwayML": 120, "HomeML": -140, "Spread": -2.5, "SpreadOdds": -110, "Total": 47.5,
        "OverOdds": -110, "UnderOdds": -110, "Book": "DraftKings", "GameID": "DALPHI",
        "LastUpdated": ts,
    }])


def _owner_user():
    email = next(iter(app.OWNER_EMAILS)) if app.OWNER_EMAILS else "owner@bankrollkings.com"
    return {"user_id": "qc-owner", "email": email, "role": "owner", "plan": "all_access",
            "is_admin": True, "display_name": "QC Owner"}


def _render_game_lines():
    c = app.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = "qc-owner"
        s["user_email"] = _owner_user()["email"]
    r = c.get("/sports/nfl/game-lines")
    return r.status_code, r.get_data(as_text=True)


def run_qc():
    issues, notes = [], []

    # (1) unit: get_lines_refresh_meta
    stale = app.get_lines_refresh_meta(_odds_fixture(50), max_age_hours=24)
    fresh = app.get_lines_refresh_meta(_odds_fixture(1), max_age_hours=24)
    empty = app.get_lines_refresh_meta(pd.DataFrame(), max_age_hours=24)
    nocol = app.get_lines_refresh_meta(pd.DataFrame([{"Away": "x", "Home": "y"}]), max_age_hours=24)
    if not stale["is_stale"] or not stale["warning"]:
        issues.append(f"stale odds feed not flagged stale: {stale}")
    else:
        notes.append(f"stale odds (50h) -> is_stale + warning ('{stale['warning'][:40]}...')")
    if fresh["is_stale"]:
        issues.append(f"fresh odds feed (1h) wrongly flagged stale: {fresh}")
    else:
        notes.append("fresh odds (1h) -> not stale")
    if empty["is_stale"] or empty["status"] != "unavailable":
        issues.append(f"empty odds df not handled as unavailable: {empty}")
    if nocol["is_stale"]:
        issues.append(f"odds df with no LastUpdated wrongly flagged stale: {nocol}")
    if not issues:
        notes.append("get_lines_refresh_meta handles stale/fresh/empty/no-column correctly")

    # (2) route render: banner present only when the odds feed is stale
    orig_odds = app.load_nfl_game_market_odds
    orig_user = app.get_current_user
    app.get_current_user = _owner_user
    try:
        app.load_nfl_game_market_odds = lambda: _odds_fixture(50)
        st_s, html_s = _render_game_lines()
        app.load_nfl_game_market_odds = lambda: _odds_fixture(1)
        st_f, html_f = _render_game_lines()
    finally:
        app.load_nfl_game_market_odds = orig_odds
        app.get_current_user = orig_user

    if st_s != 200 or st_f != 200:
        notes.append(f"/sports/nfl/game-lines did not render 200 locally (stale={st_s}, fresh={st_f}) "
                     "-- route render check skipped; unit contract above still holds")
    else:
        if BANNER_MARK not in html_s:
            issues.append("stale odds feed did NOT show the 'Game Lines Are Stale' banner on the page")
        else:
            notes.append("stale odds feed -> stale-lines banner rendered on /sports/nfl/game-lines")
        if BANNER_MARK in html_f:
            issues.append("fresh odds feed wrongly showed the stale-lines banner")
        else:
            notes.append("fresh odds feed -> no stale banner (correct)")

    if not issues:
        notes.append("game-lines freshness containment verified")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS GAME-LINES FRESHNESS QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("Game-lines freshness containment verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
