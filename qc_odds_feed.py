"""
Bankroll Kings - Odds feed health check
=======================================

The Odds API key silently died on ~2026-07-28 and the whole platform served
11-day-stale lines/props because every fetch fails quietly and preserves the last
good file. This check makes that failure LOUD instead of silent:

1. Key validity — a free `/v4/sports` call (no quota). A dead/expired/rotated key
   returns 401; this is the single unambiguous "the feed is broken" signal.
2. Freshness of the ALWAYS-ON odds files (NFL + NCAAF game lines, Futures) — these
   refresh every day year-round, so >40h old means the fetch pipeline is broken.
   Season-gated files (MLB/WNBA/NBA) are deliberately excluded to avoid off-season
   false positives (their fetch legitimately doesn't run out of season).

Exits non-zero on any failure so the daily run logs it as [FAIL] and the prelaunch
scorecard's Data Freshness section flips to NO-GO.
"""

from __future__ import annotations

import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from services.qc_tracking import append_qc_run_log

BASE_DIR = Path(__file__).resolve().parent
ALWAYS_ON_ODDS = {
    "NFL game lines": "data/odds/NFL_Odds.csv",
    "NCAAF game lines": "data/odds/NCAAF_Odds.csv",
    "Futures": "data/futures/Futures_Odds.csv",
}
STALE_HOURS = 40  # daily refresh cadence + margin


def _odds_api_key() -> str:
    return (os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY") or "").strip()


def _key_valid() -> tuple[bool, str]:
    key = _odds_api_key()
    if not key:
        return False, "ODDS_API_KEY / THE_ODDS_API_KEY is not set in the environment."
    url = f"https://api.the-odds-api.com/v4/sports?apiKey={key}"
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            response.read()
        return True, "Odds API key is valid (/v4/sports responded OK)."
    except Exception as exc:  # includes HTTP 401 for a dead/expired key
        return False, f"Odds API key REJECTED by The Odds API: {type(exc).__name__}: {exc}"


def run_qc(check_key: bool = True) -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failures: list[str] = []

    if check_key:
        ok, key_note = _key_valid()
        if not ok:
            failures.append(key_note)
    else:
        key_note = "Key validity check skipped."

    stale: list[str] = []
    for label, rel in ALWAYS_ON_ODDS.items():
        path = BASE_DIR / rel
        if not path.exists():
            failures.append(f"{label}: file missing ({rel}).")
            continue
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
        if age_hours > STALE_HOURS:
            stale.append(f"{label} {age_hours:.0f}h old")
    if stale:
        failures.append("Always-on odds feeds are STALE (fetch pipeline likely broken): " + "; ".join(stale))

    notes = key_note + (" | STALE: " + "; ".join(stale) if stale else " | Always-on odds files are fresh.")
    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": 0 if failures else 1,
        "warning_count": 0,
        "failure_count": len(failures),
        "notes": notes,
        "failures": failures,
        "warnings": [],
    }
    append_qc_run_log("odds_feed", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("ODDS FEED HEALTH")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Failures: {report['failure_count']}")
    print(report["notes"])
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    if report["clean"]:
        print("[OK] Odds feed is healthy — key valid and always-on feeds are fresh.")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
