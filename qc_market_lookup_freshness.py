"""QC: build_game_market_lookup fail-closed on a wholesale-stale odds feed (Oct 23 containment).

build_game_market_lookup is THE shared chokepoint that annotates games with the current spread/total/ML
across every board + command center (NBA/WNBA/MLB/NFL/CFB). When the WHOLE odds feed is stale (its
freshest LastUpdated older than the live-market window -- a halted capture, the incident condition), it
returns an empty lookup so no stale current line/price is shown as live -- but a normal feed with ANY
recent update is NOT suppressed, and a feed with no LastUpdated (age unknowable) is NOT suppressed.
Pure; no network. Exit 0 / 1.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

import app
from services.timeutils import to_eastern_datetime_str

TIME_COLS = ["LastUpdated", "SourceUpdatedAtUTC", "FetchedAtUTC"]


def _stamps(observed, source=None):
    """The writer's L1 time columns from AWARE UTC instants (never the process-local naive clock)."""
    source = source or observed
    return {"LastUpdated": to_eastern_datetime_str(source.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "SourceUpdatedAtUTC": source.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "FetchedAtUTC": observed.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _df(age_hours, extra_recent=False, source_age_hours=None):
    now = datetime.now(timezone.utc)
    obs = now - timedelta(hours=age_hours)
    src = now - timedelta(hours=source_age_hours) if source_age_hours is not None else obs
    rows = [{"Away": "Boston Celtics", "Home": "Los Angeles Lakers", "Date": "2026-11-01",
             "Spread": -3.5, "Total": 220.5, "AwayML": 120, "HomeML": -140, "Book": "DraftKings",
             **_stamps(obs, src)}]
    if extra_recent:
        rows.append({**rows[0], "Home": "Miami Heat", **_stamps(now)})
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

    # recently OBSERVED by BK, but the book last changed the market 55h ago -> still current
    observed = app.build_game_market_lookup(_df(1, source_age_hours=55))
    if not observed:
        issues.append("recently observed quote with an old book source time wrongly suppressed")
    else:
        notes.append("recently observed quote with a 55h-old book source time -> not suppressed (freshness = observation)")

    nocol = app.build_game_market_lookup(_df(55).drop(columns=TIME_COLS))
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
