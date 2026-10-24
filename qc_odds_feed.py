"""
Bankroll Kings - Odds feed health check
=======================================

The Odds API key silently died on ~2026-07-28 and the whole platform served
11-day-stale lines/props because every fetch fails quietly and preserves the last
good file. This check makes that failure LOUD instead of silent:

1. Key validity — a free `/v4/sports` call (no quota). A dead/expired/rotated key
   returns 401; this is the single unambiguous "the feed is broken" signal.
2. Freshness of the ALWAYS-ON odds files (NFL + NCAAF game lines, Futures) — these
   refresh every day year-round, so >30h old (one daily cycle + margin) means the
   fetch pipeline missed a cycle and is likely broken.
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
from services.env_loader import load_local_env
from services.freshness_contract import cadence_state, refresh_cadence_hours

# Load the service .env so a STANDALONE run (not just the systemd service) has the Odds API key.
# Without this, running this QC by hand falsely reported "key not set" even though the key exists.
load_local_env(Path(__file__).resolve().parent)

BASE_DIR = Path(__file__).resolve().parent
# Feed FAMILIES (incident 2026-10-24): health is reported per family, never as one blanket "odds healthy".
GAME_LINE_FEEDS = {s: f"data/odds/{s}_Odds.csv" for s in ("NFL", "NCAAF", "NBA", "WNBA", "MLB")}
PROPS_FEEDS = {s: f"data/props/{s}_Props.csv" for s in ("NFL", "NCAAF", "NBA", "WNBA", "MLB")}
FUTURES_FEED = "data/futures/Futures_Odds.csv"
GRADING_FEEDS = {"NFL graded record": "data/tracking/NFL_AllPropResults.csv"}
# Thresholds live in the ONE declared freshness contract (services/freshness_contract.py, CLOCK B).
# STALE_HOURS kept as a back-compat alias == the props cadence window (other code imports it).
STALE_HOURS = refresh_cadence_hours("props")
# Back-compat (other code imports ALWAYS_ON_ODDS).
ALWAYS_ON_ODDS = {"NFL game lines": GAME_LINE_FEEDS["NFL"], "NCAAF game lines": GAME_LINE_FEEDS["NCAAF"],
                  "Futures": FUTURES_FEED}


def _age_hours(path: Path):
    try:
        return (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return None


def _state(age, family: str = "props", sport: str | None = None):
    """FRESH/STALE/MISSING against the contract's CLOCK-B cadence window for this family/sport."""
    return cadence_state(age, family, sport)


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

    # ---- per-family feed health ----
    warnings: list[str] = []
    families: dict[str, str] = {}
    for sport in GAME_LINE_FEEDS:
        gl_age = _age_hours(BASE_DIR / GAME_LINE_FEEDS[sport])
        pr_age = _age_hours(BASE_DIR / PROPS_FEEDS[sport])
        gl_state = _state(gl_age, "game_lines", sport)
        pr_state = _state(pr_age, "props", sport)
        families[f"{sport} game lines"] = f"{gl_state} ({gl_age:.0f}h)" if gl_age is not None else "MISSING"
        families[f"{sport} props"] = f"{pr_state} ({pr_age:.0f}h)" if pr_age is not None else "MISSING"
        # TRUTH RULE: if a sport's GAME LINES are FRESH (the sport is active -- games are being lined) but
        # its PROPS are STALE, the props pipeline is broken (or markets are not posted). Either way the
        # odds feed is NOT "healthy" for that sport -- flag it. A manifest/availability check classifies
        # it as a genuine break vs a legitimate NO_MARKETS_POSTED window; this guard just refuses a false
        # all-clear. When game lines are ALSO stale/missing, the sport is off-season -> not flagged here.
        if gl_state == "FRESH" and pr_state in ("STALE", "MISSING"):
            failures.append(f"{sport} props are {pr_state} while {sport} game lines are FRESH -- props "
                            f"pipeline broken or no markets posted (verify with the availability report).")
    # futures (always-on)
    fut_age = _age_hours(BASE_DIR / FUTURES_FEED)
    fut_state = _state(fut_age, "futures")
    families["Futures"] = f"{fut_state} ({fut_age:.0f}h)" if fut_age is not None else "MISSING"
    if fut_state in ("STALE", "MISSING"):
        failures.append(f"Futures feed is {fut_state} (always-on; the Odds-health guard tracks it).")
    # historical grading (nflverse-fed, NOT Odds API -> informational WARNING, never a hard odds failure)
    for label, rel in GRADING_FEEDS.items():
        g_age = _age_hours(BASE_DIR / rel)
        g_state = _state(g_age, "grading")
        families[label] = f"{g_state} ({g_age:.0f}h)" if g_age is not None else "MISSING"
        if g_state in ("STALE", "MISSING"):
            warnings.append(f"{label} is {g_state} (nflverse grading, separate from the Odds feed).")

    fam_line = "; ".join(f"{k}={v}" for k, v in families.items())
    notes = key_note + " || FAMILIES: " + fam_line
    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": 0 if failures else 1,
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "notes": notes,
        "families": families,
        "failures": failures,
        "warnings": warnings,
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
