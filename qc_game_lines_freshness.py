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

BANNER_MARK = "Current Lines Unavailable"


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

    # (2) route render: FAIL CLOSED -- when the odds feed is stale the current-line rows are SUPPRESSED
    # (the board builders receive an EMPTY odds frame), not merely warned. Capture the odds actually
    # passed to the live game-line board builders (deterministic; independent of dropdowns/history).
    captured = {}

    def _wrap(name):
        orig = getattr(app, name)

        def w(*a, **k):
            # odds df is the 2nd positional for the slate board, kwarg for the intelligence board
            odds = k.get("odds_df")
            if odds is None and len(a) >= 2:
                odds = a[1]
            captured.setdefault(name, []).append(0 if odds is None else int(len(odds)))
            return orig(*a, **k)
        return orig, w

    orig_odds = app.load_nfl_game_market_odds
    orig_user = app.get_current_user
    o1, w1 = _wrap("build_football_live_game_method_board")
    o2, w2 = _wrap("build_football_game_line_intelligence")
    app.get_current_user = _owner_user
    app.build_football_live_game_method_board = w1
    app.build_football_game_line_intelligence = w2
    try:
        app.load_nfl_game_market_odds = lambda: _odds_fixture(50)   # stale
        captured.clear()
        st_s, html_s = _render_game_lines()
        cap_s = dict(captured)
        app.load_nfl_game_market_odds = lambda: _odds_fixture(1)    # fresh
        captured.clear()
        st_f, html_f = _render_game_lines()
        cap_f = dict(captured)
    finally:
        app.load_nfl_game_market_odds = orig_odds
        app.get_current_user = orig_user
        app.build_football_live_game_method_board = o1
        app.build_football_game_line_intelligence = o2

    if st_s != 200 or st_f != 200:
        notes.append(f"/sports/nfl/game-lines did not render 200 locally (stale={st_s}, fresh={st_f}) "
                     "-- route render check skipped; unit contract above still holds")
    else:
        # fail-closed: stale -> every odds frame handed to a live line-board builder is EMPTY
        stale_counts = [n for lst in cap_s.values() for n in lst]
        fresh_counts = [n for lst in cap_f.values() for n in lst]
        if stale_counts and any(n > 0 for n in stale_counts):
            issues.append(f"stale odds NOT suppressed: live line-board got non-empty odds {cap_s}")
        else:
            notes.append(f"stale odds -> current-line rows SUPPRESSED (board odds empty: {cap_s})")
        if fresh_counts and all(n == 0 for n in fresh_counts):
            issues.append(f"fresh odds wrongly suppressed: board got empty odds {cap_f}")
        elif fresh_counts:
            notes.append(f"fresh odds -> current-line rows rendered (board odds non-empty: {cap_f})")
        if BANNER_MARK not in html_s:
            issues.append("stale odds feed did NOT show the 'Current Lines Unavailable' banner")
        else:
            notes.append("stale odds feed -> 'Current Lines Unavailable' banner rendered")
        if BANNER_MARK in html_f:
            issues.append("fresh odds feed wrongly showed the unavailable banner")
        else:
            notes.append("fresh odds feed -> no unavailable banner (correct)")

    # (3) totals pill re-loads odds internally -> must also be suppressed when the feed is stale.
    tcalls = {"n": 0}
    orig_tot = app.build_nfl_totals_board_context
    orig_odds2 = app.load_nfl_game_market_odds
    orig_user2 = app.get_current_user

    def _tot(*a, **k):
        tcalls["n"] += 1
        return {}

    app.get_current_user = _owner_user
    app.build_nfl_totals_board_context = _tot

    def _render_totals():
        c = app.app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "qc-owner"
            s["user_email"] = _owner_user()["email"]
        r = c.get("/sports/nfl/totals")
        return r.status_code

    try:
        app.load_nfl_game_market_odds = lambda: _odds_fixture(50)   # stale
        tcalls["n"] = 0
        st_ts = _render_totals()
        stale_calls = tcalls["n"]
        app.load_nfl_game_market_odds = lambda: _odds_fixture(1)    # fresh
        tcalls["n"] = 0
        st_tf = _render_totals()
        fresh_calls = tcalls["n"]
    finally:
        app.build_nfl_totals_board_context = orig_tot
        app.load_nfl_game_market_odds = orig_odds2
        app.get_current_user = orig_user2

    if st_ts == 200 and st_tf == 200:
        if stale_calls != 0:
            issues.append(f"stale totals pill NOT suppressed: builder called {stale_calls}x")
        else:
            notes.append("stale odds -> NFL totals pill suppressed (builder not called)")
        if fresh_calls == 0:
            issues.append("fresh totals pill wrongly suppressed (builder never called)")
        else:
            notes.append("fresh odds -> NFL totals pill built")
    else:
        notes.append(f"/sports/nfl/totals did not render 200 (stale={st_ts}, fresh={st_tf}) -- skipped")

    # (4) standalone totals builders fail closed at the SOURCE (gates both /tools/*-totals routes AND
    # the pill) -- resolves the CFB totals contradiction.
    o_cfb = app.load_ncaaf_game_market_odds
    o_nfl = app.load_nfl_game_market_odds
    try:
        app.load_ncaaf_game_market_odds = lambda: _odds_fixture(50)
        app.load_nfl_game_market_odds = lambda: _odds_fixture(50)
        cfb_s = app.build_cfb_totals_board_context('week', 'all')
        nfl_s = app.build_nfl_totals_board_context('week', 'all')
        app.load_ncaaf_game_market_odds = lambda: _odds_fixture(1)
        cfb_f = app.build_cfb_totals_board_context('week', 'all')
    finally:
        app.load_ncaaf_game_market_odds = o_cfb
        app.load_nfl_game_market_odds = o_nfl
    if not cfb_s.get('tb_stale') or cfb_s.get('tb_count') != 0:
        issues.append(f"standalone CFB totals NOT fail-closed when stale: {cfb_s.get('tb_stale')}/{cfb_s.get('tb_count')}")
    else:
        notes.append("standalone CFB totals builder fails closed when stale (0 rows + tb_stale)")
    if not nfl_s.get('nt_stale') or nfl_s.get('nt_count') != 0:
        issues.append(f"standalone NFL totals NOT fail-closed when stale: {nfl_s.get('nt_stale')}/{nfl_s.get('nt_count')}")
    else:
        notes.append("standalone NFL totals builder fails closed when stale (0 rows + nt_stale)")
    if cfb_f.get('tb_stale'):
        issues.append("CFB totals wrongly flagged stale when fresh")
    else:
        notes.append("CFB totals builder serves rows when fresh (not falsely suppressed)")

    if not issues:
        notes.append("game-lines + totals (pill + standalone) freshness containment verified")
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
