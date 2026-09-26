#!/usr/bin/env python3
"""
Capture NFL opening game lines by forward ledger.

Unlike CFB (CFBD serves opening lines directly), The Odds API only gives the CURRENT
number, so there's no free way to know where an NFL line opened. This records the FIRST
consensus line we see per game and never overwrites it -- so open->current movement
accrues from the moment we start watching a game, instead of being lost.

Reads data/odds/NFL_Odds.csv (the current snapshot). Writes/updates
data/tracking/NFL_LineOpen.csv, adding only GameIDs it hasn't seen before. Run in the
NFL refresh lane, ideally more than once a week so opens are caught early.
"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
ODDS_PATH = BASE_DIR / "data" / "odds" / "NFL_Odds.csv"
LEDGER_PATH = BASE_DIR / "data" / "tracking" / "NFL_LineOpen.csv"
FIELDS = ["GameID", "Date", "Away", "Home", "OpenSpread", "OpenTotal",
          "OpenAwayML", "OpenHomeML", "FirstSeen"]


def _consensus(df):
    """One row per game with the median line across books."""
    out = {}
    for gid, g in df.groupby("GameID"):
        r0 = g.iloc[0]
        out[str(gid)] = {
            "GameID": str(gid), "Date": r0.get("Date", ""),
            "Away": r0.get("Away", ""), "Home": r0.get("Home", ""),
            "OpenSpread": pd.to_numeric(g["Spread"], errors="coerce").median(),
            "OpenTotal": pd.to_numeric(g["Total"], errors="coerce").median(),
            "OpenAwayML": pd.to_numeric(g["AwayML"], errors="coerce").median(),
            "OpenHomeML": pd.to_numeric(g["HomeML"], errors="coerce").median(),
        }
    return out


def main() -> int:
    if not ODDS_PATH.exists():
        print(f"[nfl-line-open] no odds file at {ODDS_PATH} -- nothing to capture.")
        return 0
    df = pd.read_csv(ODDS_PATH)
    if df.empty or "GameID" not in df.columns:
        print("[nfl-line-open] odds file empty or missing GameID -- skipping.")
        return 0
    current = _consensus(df)

    seen = set()
    existing_rows = []
    if LEDGER_PATH.exists():
        with LEDGER_PATH.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                seen.add(str(row.get("GameID")))
                existing_rows.append(row)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    added = 0
    for gid, c in current.items():
        if gid in seen:
            continue  # keep the true open; never overwrite
        existing_rows.append({
            "GameID": gid, "Date": c["Date"], "Away": c["Away"], "Home": c["Home"],
            "OpenSpread": "" if pd.isna(c["OpenSpread"]) else c["OpenSpread"],
            "OpenTotal": "" if pd.isna(c["OpenTotal"]) else c["OpenTotal"],
            "OpenAwayML": "" if pd.isna(c["OpenAwayML"]) else c["OpenAwayML"],
            "OpenHomeML": "" if pd.isna(c["OpenHomeML"]) else c["OpenHomeML"],
            "FirstSeen": now,
        })
        added += 1

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for row in existing_rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})
    print(f"[nfl-line-open] {added} new game opens captured, {len(existing_rows)} total -> {LEDGER_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
