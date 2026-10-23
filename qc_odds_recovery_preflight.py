"""QC: Odds recovery preflight -- strong feed validation (services.feed_validation) + per-request quota
accounting (services.odds_quota). Pure; no network/app. Exits 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from services.feed_validation import FUTURES_SPEC, GAME_LINES_SPEC, PLAYER_PROPS_SPEC, validate_feed
from services.odds_quota import QuotaRecorder, odds_credit_cost


def _good_lines(n=4, ts="2026-10-26T12:00:00Z"):
    return pd.DataFrame([{
        "Away": f"Away{i}", "Home": f"Home{i}", "Spread": -2.5 - i, "Total": 44.5 + i,
        "SpreadOdds": -110, "OverOdds": -110, "UnderOdds": -110, "AwayML": 120, "HomeML": -140,
        "GameID": f"G{i}", "Book": "DraftKings", "LastUpdated": ts,
    } for i in range(n)])


def run_qc():
    issues, notes = [], []

    # ---------- feed_validation ----------
    ok, errs = validate_feed(_good_lines(), GAME_LINES_SPEC, sport_tokens=("NFL",), path="NFL_Odds.csv")
    if not ok:
        issues.append(f"valid frame rejected: {errs}")
    else:
        notes.append("valid game-lines frame accepted")

    cases = [
        ("missing column", _good_lines().drop(columns=["LastUpdated"]), {}),
        ("empty slice", _good_lines(0), {}),
        ("non-finite line", _good_lines().assign(Spread=lambda d: [np.inf, 1, 2, 3]), {}),
        ("unparseable timestamp", _good_lines().assign(LastUpdated="not-a-date"), {}),
        ("blank identity", _good_lines().assign(Home=["", "H", "H", "H"]), {}),
        ("disallowed? n/a", _good_lines(), {}),  # placeholder kept simple
    ]
    for name, df, kw in cases:
        if name == "disallowed? n/a":
            continue
        ok, errs = validate_feed(df, GAME_LINES_SPEC, sport_tokens=("NFL",), path="NFL_Odds.csv", **kw)
        if ok:
            issues.append(f"{name}: should have FAILED validation but passed")
        else:
            notes.append(f"{name} -> rejected ({errs[0][:46]}...)")

    # timestamp regression
    prior = _good_lines(ts="2026-10-26T18:00:00Z")
    newer = _good_lines(ts="2026-10-26T06:00:00Z")   # older than prior -> regression
    ok, errs = validate_feed(newer, GAME_LINES_SPEC, prior_df=prior, sport_tokens=("NFL",), path="NFL_Odds.csv")
    if ok or not any("REGRESSION" in e for e in errs):
        issues.append(f"timestamp regression not caught: {errs}")
    else:
        notes.append("timestamp regression rejected")

    # conflicting duplicate (same GameID+Book, different Spread)
    conflict = pd.concat([_good_lines(1), _good_lines(1).assign(Spread=99)], ignore_index=True)
    ok, errs = validate_feed(conflict, GAME_LINES_SPEC, sport_tokens=("NFL",), path="NFL_Odds.csv")
    if ok or not any("CONFLICTING" in e for e in errs):
        issues.append(f"conflicting duplicate not caught: {errs}")
    else:
        notes.append("conflicting duplicate rejected")

    # row-count collapse vs prior (+ override)
    big_prior = _good_lines(20)
    tiny = _good_lines(2)
    ok, _ = validate_feed(tiny, GAME_LINES_SPEC, prior_df=big_prior, sport_tokens=("NFL",), path="NFL_Odds.csv")
    if ok:
        issues.append("row-count collapse not caught")
    else:
        notes.append("row-count collapse rejected")
    ok, _ = validate_feed(tiny, GAME_LINES_SPEC, prior_df=big_prior, sport_tokens=("NFL",),
                          path="NFL_Odds.csv", allow_collapse=True)
    if not ok:
        issues.append("explicit collapse override did not allow the publish")
    else:
        notes.append("row-count collapse allowed under explicit override")

    # wrong sport path
    ok, errs = validate_feed(_good_lines(), GAME_LINES_SPEC, sport_tokens=("NFL",), path="NBA_Odds.csv")
    if ok or not any("does not match expected sport" in e for e in errs):
        issues.append("wrong-sport output path not caught")
    else:
        notes.append("wrong-sport output path rejected (NFL fetch cannot overwrite NBA file)")

    # ---------- props spec: alternate lines allowed, bad values rejected ----------
    alt = pd.DataFrame([
        {"Player": "A. Smith", "Stat": "Receiving Yards", "Book": "DK", "Line": 49.5,
         "OverOdds": -110, "UnderOdds": -110, "LastUpdated": "2026-10-26T12:00:00Z"},
        {"Player": "A. Smith", "Stat": "Receiving Yards", "Book": "DK", "Line": 59.5,   # alt line, same key
         "OverOdds": 120, "UnderOdds": -140, "LastUpdated": "2026-10-26T12:00:00Z"},
    ])
    ok, errs = validate_feed(alt, PLAYER_PROPS_SPEC, sport_tokens=("NFL",), path="NFL_Props.csv")
    if not ok:
        issues.append(f"props alternate lines wrongly rejected: {errs}")
    else:
        notes.append("props alternate lines accepted (not flagged as conflicting)")
    badprop = alt.assign(Line=[float("inf"), 59.5])
    ok, _ = validate_feed(badprop, PLAYER_PROPS_SPEC, sport_tokens=("NFL",), path="NFL_Props.csv")
    if ok:
        issues.append("props non-finite Line not rejected")
    else:
        notes.append("props non-finite Line rejected")

    # ---------- futures spec ----------
    fut = pd.DataFrame([{"SportKey": "americanfootball_nfl_super_bowl_winner", "Outcome": "Chiefs",
                         "Price": 550, "LastUpdated": "2026-10-26T12:00:00Z"}])
    ok, errs = validate_feed(fut, FUTURES_SPEC)
    if not ok:
        issues.append(f"valid futures rejected: {errs}")
    else:
        notes.append("valid futures frame accepted")
    ok, _ = validate_feed(fut.assign(Outcome=[""]), FUTURES_SPEC)
    if ok:
        issues.append("futures blank identity not rejected")
    else:
        notes.append("futures blank identity rejected")

    # ---------- odds_quota ----------
    q = QuotaRecorder()
    q.record({"x-requests-last": "1", "x-requests-used": "41", "x-requests-remaining": "99959"})
    q.record({"x-requests-last": "3", "x-requests-used": "44", "x-requests-remaining": "99956"})
    ok, r = q.receipt("game_lines /odds", "americanfootball_nfl", ["h2h", "spreads", "totals"], expected_cost=10)
    if not ok or r["x_requests_last_sum"] != 4 or r["x_requests_remaining"] != 99956:
        issues.append(f"quota receipt wrong: {r}")
    else:
        notes.append(f"quota receipt: cost={r['x_requests_last_sum']} remaining={r['x_requests_remaining']} OK")
    # cost over expected -> fail
    ok, _ = q.receipt("game_lines /odds", "nfl", expected_cost=2)
    if ok:
        issues.append("cost over expected did not fail the receipt")
    else:
        notes.append("cost exceeding expected -> receipt FAILED (stop)")
    # missing headers on a paid call -> fail (never guess)
    q2 = QuotaRecorder()
    q2.record({}, paid=True)
    ok, _ = q2.receipt("game_lines /odds", "nfl")
    if ok:
        issues.append("paid response without usage headers did not fail the receipt")
    else:
        notes.append("paid response with NO usage headers -> receipt FAILED (no guessing)")

    # ---------- documented cost formula (expected-cost derived, not observed) ----------
    if odds_credit_cost(3, 1, 1) != 3:
        issues.append("game-lines documented cost (3 markets x 1 region x 1 call) != 3")
    elif odds_credit_cost(1, 1, 5) != 5:
        issues.append("per-event props documented cost (1x1x5) != 5")
    elif odds_credit_cost(1, 1, 1) != 1:
        issues.append("futures documented cost (1x1x1) != 1")
    else:
        notes.append("documented credit-cost formula (markets x regions x calls) correct")

    if not issues:
        notes.append("Odds recovery preflight (validation + quota accounting + cost formula) verified")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS ODDS RECOVERY PREFLIGHT QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("Odds recovery preflight verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
