"""QC: build_game_market_lookup fail-closed on a wholesale-stale odds feed (Oct 23 containment).

build_game_market_lookup is THE shared chokepoint that annotates games with the current spread/total/ML
across every board + command center (NBA/WNBA/MLB/NFL/CFB). When the WHOLE odds feed is stale (its
freshest LastUpdated older than the live-market window -- a halted capture, the incident condition), it
returns an empty lookup so no stale current line/price is shown as live -- but a normal feed with ANY
recent update is NOT suppressed, and a feed with no LastUpdated (age unknowable) is NOT suppressed.
Pure; no network. Exit 0 / 1.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

import app


def _df(age_hours, extra_recent=False):
    ts = (datetime.now() - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = [{"Away": "Boston Celtics", "Home": "Los Angeles Lakers", "Date": "2026-11-01",
             "Spread": -3.5, "Total": 220.5, "AwayML": 120, "HomeML": -140, "Book": "DraftKings",
             "LastUpdated": ts}]
    if extra_recent:
        rows.append({**rows[0], "Home": "Miami Heat",
                     "LastUpdated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
    return pd.DataFrame(rows)


def run_qc():
    issues, notes = [], []

    fresh = app.build_game_market_lookup(_df(1))
    if not fresh:
        issues.append("fresh feed produced an EMPTY market lookup (false suppression)")
    else:
        notes.append("fresh feed -> current lines annotated")

    stale = app.build_game_market_lookup(_df(55))
    if stale:
        issues.append(f"wholesale-stale feed STILL annotated {len(stale)} current line(s) (not suppressed)")
    else:
        notes.append("wholesale-stale feed -> empty lookup (stale current lines suppressed)")

    mixed = app.build_game_market_lookup(_df(55, extra_recent=True))
    if not mixed:
        issues.append("feed with a recent line wrongly suppressed (over-suppression)")
    else:
        notes.append("feed with ANY recent update -> not suppressed (feed not wholesale-stale)")

    nocol = app.build_game_market_lookup(_df(55).drop(columns=["LastUpdated"]))
    if not nocol:
        issues.append("feed with no LastUpdated wrongly suppressed (age unknowable -> must not suppress)")
    else:
        notes.append("feed with no LastUpdated -> not suppressed (cannot determine age)")

    if not issues:
        notes.append("build_game_market_lookup wholesale-stale containment verified (all 8 board callers)")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS MARKET-LOOKUP FRESHNESS QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("Market-lookup freshness containment verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
