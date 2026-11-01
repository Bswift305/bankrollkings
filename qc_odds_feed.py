"""
Bankroll Kings - Odds feed health check
=======================================

The Odds API key silently died on ~2026-07-28 and the whole platform served
11-day-stale lines/props because every fetch fails quietly and preserves the last
good file. This check makes that failure LOUD instead of silent:

1. Key validity — a free `/v4/sports` call (no quota). A dead/expired/rotated key
   returns 401; this is the single unambiguous "the feed is broken" signal.
2. Per-sport game-lines + props freshness (CLOCK B, >30h = a missed cycle), judged
   against the GOVERNED season state (season_utils.season_state, the same state the
   daily operator gates its refresh steps on): OFF_SEASON feeds are reported
   "OFF_SEASON (not judged)" -- never a false FAIL; ACTIVE and UNKNOWN are strict
   (STALE/MISSING fails; UNKNOWN never silently passes). Futures are always-on.

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


OFF_SEASON_LABEL = "OFF_SEASON (not judged)"


def _fmt(state: str, age) -> str:
    return f"{state} ({age:.0f}h)" if age is not None else "MISSING"


def judge_sport_feeds(sport: str, gl_age, pr_age, season) -> tuple[dict, list[str]]:
    """Season-aware CLOCK-B judgement of one sport's game-lines + props families (pure, no I/O).

    `season` is the governed season_utils.SeasonState (ACTIVE / OFF_SEASON / UNKNOWN) -- the SAME state
    the daily operator uses to decide whether this sport's refresh steps run at all:
      OFF_SEASON -> both families reported "OFF_SEASON (not judged)" with their age, never a failure:
                    the operator deliberately did not refresh them, so their staleness is expected.
      ACTIVE     -> strict: a STALE or MISSING family is a failure.
      UNKNOWN    -> strict as well (fail-open means "judge it", never a silent pass).
      None       -> treated as UNKNOWN.
    Returns ({family_label: display}, [failures])."""
    gl_state = _state(gl_age, "game_lines", sport)
    pr_state = _state(pr_age, "props", sport)
    families: dict[str, str] = {}
    failures: list[str] = []
    st_name = getattr(season, "state", None) or "UNKNOWN"
    if st_name == "OFF_SEASON":
        reason = getattr(season, "reason", "")
        for fam, age in (("game lines", gl_age), ("props", pr_age)):
            age_txt = f"{age:.0f}h" if age is not None else "missing"
            families[f"{sport} {fam}"] = f"{OFF_SEASON_LABEL} ({age_txt}; {reason})"
        return families, failures
    families[f"{sport} game lines"] = _fmt(gl_state, gl_age)
    families[f"{sport} props"] = _fmt(pr_state, pr_age)
    stale = [(fam, s) for fam, s in (("game lines", gl_state), ("props", pr_state)) if s in ("STALE", "MISSING")]
    if stale:
        what = " and ".join(f"{fam} {s}" for fam, s in stale)
        hint = ""
        if gl_state == "FRESH" and pr_state in ("STALE", "MISSING"):
            # Lines are being refreshed but props are not: props pipeline broken or no markets posted
            # (the availability report classifies which). Either way, not a healthy feed.
            hint = " -- props pipeline broken or no markets posted (verify with the availability report)"
        failures.append(f"{sport} {what} while season state is {st_name}{hint}.")
    return families, failures


def run_qc(check_key: bool = True, states: dict | None = None) -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failures: list[str] = []

    if check_key:
        ok, key_note = _key_valid()
        if not ok:
            failures.append(key_note)
    else:
        key_note = "Key validity check skipped."

    # Governed season state (season_utils.season_state: schedule/calendar evidence, Eastern date) -- the
    # SAME snapshot logic the daily operator used to decide which refresh steps ran. Off-season feeds are
    # not refreshed by design, so judging them stale would be a false FAIL (the Nov 2026 "Odds feed
    # health (post-refresh)" failure on 89-96h MLB/WNBA files). ACTIVE/UNKNOWN stay strict.
    if states is None:
        from season_utils import season_states
        states = season_states(tuple(GAME_LINE_FEEDS), base_dir=BASE_DIR)

    # ---- per-family feed health ----
    warnings: list[str] = []
    families: dict[str, str] = {}
    not_judged: list[str] = []
    for sport in GAME_LINE_FEEDS:
        gl_age = _age_hours(BASE_DIR / GAME_LINE_FEEDS[sport])
        pr_age = _age_hours(BASE_DIR / PROPS_FEEDS[sport])
        season = states.get(sport)
        fams, fails = judge_sport_feeds(sport, gl_age, pr_age, season)
        families.update(fams)
        failures.extend(fails)
        if getattr(season, "state", None) == "OFF_SEASON":
            not_judged.append(sport)
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
        "season_states": {s: getattr(st, "state", "UNKNOWN") for s, st in states.items()},
        "not_judged_off_season": not_judged,
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
    for sport, st in report["season_states"].items():
        tag = OFF_SEASON_LABEL if st == "OFF_SEASON" else f"{st} (judged strictly)"
        print(f"[SEASON] {sport}: {tag}")
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    if report["clean"]:
        print("[OK] Odds feed is healthy — key valid, in-season and always-on feeds are fresh"
              + (f"; not judged (off-season): {', '.join(report['not_judged_off_season'])}."
                 if report["not_judged_off_season"] else "."))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
