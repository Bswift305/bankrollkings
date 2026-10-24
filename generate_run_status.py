from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

# Odds-feed FAMILY freshness is the signal that was MISSING from Run Status during the Oct 2026
# incident: these 14 analysis artifacts were all within their age windows, so overall read GREEN while
# the current-market Odds feeds (props by sport) were days stale. Reuse the same per-family helpers the
# odds-feed QC uses so the two surfaces agree (file-mtime only; no network call here).
from qc_odds_feed import (
    GAME_LINE_FEEDS,
    PROPS_FEEDS,
    FUTURES_FEED,
    _age_hours as _odds_age,
    _state as _odds_state,
)
from services.freshness_contract import LIVE_MARKET_MAX_AGE_HOURS, refresh_cadence_hours


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
TRACKING_DIR = BASE_DIR / "data" / "tracking"
JSON_PATH = TRACKING_DIR / "Run_Status.json"
CSV_PATH = TRACKING_DIR / "Run_Status.csv"
OPERATOR_SUMMARY_PATH = TRACKING_DIR / "Last_Operator_Summary.json"


CHECKS = [
    {
        "name": "Daily Operator",
        "kind": "log",
        "patterns": ["daily_operator_*.log", "daily_refresh_*.log"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Full refresh wrapper for active sports plus analysis.",
    },
    {
        "name": "Edge Engine",
        "kind": "log",
        "patterns": ["bk_edge_engine_pipeline_*.log"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Formula, calibration, streak heat, drift, and status chain.",
    },
    {
        "name": "Scorecards",
        "kind": "log",
        "patterns": ["all_scorecards_*.log"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "NBA/WNBA/MLB/NFL/prelaunch readiness checks.",
    },
    {
        "name": "NBA Results",
        "kind": "artifact",
        "paths": ["data/tracking/NBA_AllPropResults.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Resolved NBA prop history used by review and calibration.",
    },
    {
        "name": "WNBA Results",
        "kind": "artifact",
        "paths": ["data/tracking/WNBA_AllPropResults.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Resolved WNBA prop history used by review and calibration.",
    },
    {
        "name": "MLB Results",
        "kind": "artifact",
        "paths": ["data/tracking/MLB_AllPropResults_Scored.csv", "data/tracking/MLB_AllPropResults.csv"],
        "fresh_hours": 24,
        "aging_hours": 42,
        "note": "Scored MLB prop history and context scores.",
    },
    {
        "name": "Injury Refresh",
        "kind": "artifact",
        "paths": [
            "data/injuries/NBA_Injuries.csv",
            "data/injuries/WNBA_Injuries.csv",
            "data/injuries/NFL_Injuries.csv",
            "data/injuries/MLB_Injuries.csv",
        ],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "All-sport injury files. WATCH can still mean source preserved last-good data.",
    },
    {
        "name": "Formula Status",
        "kind": "artifact",
        "paths": ["data/tracking/Formula_Status.json"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Board-facing formula and model status badge source.",
    },
    {
        "name": "Driver Calibration",
        "kind": "artifact",
        "paths": ["data/tracking/Sport_Driver_Calibration.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Sport-specific promote/reduce driver buckets.",
    },
    {
        "name": "Streak Heat",
        "kind": "artifact",
        "paths": ["data/tracking/Streak_Heat_Index.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Hot-hand streak chart index.",
    },
    {
        "name": "Active Simulations",
        "kind": "artifact",
        "paths": ["data/tracking/Active_Sport_Simulation_Summary.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "NBA/WNBA/MLB simulated hit probability summary.",
    },
    {
        "name": "Team Priors",
        "kind": "artifact",
        "paths": ["data/tracking/Team_Strength_Priors.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Market and result based team-strength priors for game environment.",
    },
    {
        "name": "MLB Umpires",
        "kind": "artifact",
        "paths": ["data/context/MLB_UmpireAssignments.csv"],
        "fresh_hours": 24,
        "aging_hours": 42,
        "note": "Home plate umpire sidecar used by MLB context scoring.",
    },
    {
        "name": "Drift Alerts",
        "kind": "artifact",
        "paths": ["data/tracking/Live_Drift_Alerts.csv"],
        "fresh_hours": 30,
        "aging_hours": 54,
        "note": "Featured vs unplayed drift warnings.",
    },
]


def _latest_file(patterns: list[str], base: Path) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(base.glob(pattern))
    files = [path for path in matches if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _latest_artifact(paths: list[str]) -> Path | None:
    files = [BASE_DIR / path for path in paths]
    existing = [path for path in files if path.exists() and path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _age_hours(path: Path, now: datetime) -> float:
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return max(0.0, (now - modified).total_seconds() / 3600)


def _classify(age: float | None, fresh_hours: int, aging_hours: int) -> str:
    if age is None:
        return "MISSING"
    if age <= fresh_hours:
        return "FRESH"
    if age <= aging_hours:
        return "AGING"
    return "STALE"


def _status_note(status: str) -> str:
    return {
        "FRESH": "Green",
        "AGING": "Watch",
        "STALE": "Needs refresh",
        "MISSING": "Missing",
    }.get(status, "Unknown")


def _render_tier(age, family: str, sport: str | None = None) -> tuple[str, str, str]:
    """TWO clocks for a current-market feed (directive #2 of the Oct-24 follow-up). Returns
    (tier, status_chip, note) where tier is one of:
      SERVEABLE               age <= 6h   -- within the customer live-render window        (chip FRESH)
      OVERDUE_FOR_LIVE_RENDER 6h < age <= cadence -- customer fails closed, but the refresh
                              is still on schedule: NOT 'healthy', but not a missed cycle    (chip AGING)
      REFRESH_MISSED          age > cadence (30h) -- a refresh cycle was actually missed     (chip STALE)
      MISSING                 no file.
    The render window is the same LIVE_MARKET_MAX_AGE_HOURS (6h) the customer board uses, so Run Status
    can never label a customer-unavailable feed 'healthy'."""
    if age is None:
        return "MISSING", "MISSING", "Missing"
    cadence = refresh_cadence_hours(family, sport)
    if age > cadence:
        return "REFRESH_MISSED", "STALE", "REFRESH_MISSED (a refresh cycle was missed)"
    if age > LIVE_MARKET_MAX_AGE_HOURS:
        return "OVERDUE_FOR_LIVE_RENDER", "AGING", (f"OVERDUE_FOR_LIVE_RENDER (>{LIVE_MARKET_MAX_AGE_HOURS:.0f}h: "
                                                    "customer renders unavailable; refresh still on schedule)")
    return "SERVEABLE", "FRESH", f"SERVEABLE (<={LIVE_MARKET_MAX_AGE_HOURS:.0f}h customer live window)"


def _odds_family_signals() -> tuple[list[dict], list[str]]:
    """Per-family Odds-feed rows on the TWO-clock model + the DEGRADED reasons they imply. A
    current-market feed past its refresh cadence (REFRESH_MISSED) degrades the overall status; a feed
    only past the 6h render window (OVERDUE_FOR_LIVE_RENDER) is surfaced as AGING (overall WATCH, never
    GREEN) so a customer-unavailable feed is never reported 'healthy'. When BOTH a sport's game lines and
    props are REFRESH_MISSED the sport is off-season; when lines are serveable but props are
    REFRESH_MISSED the props pipeline is broken (or no markets posted)."""
    rows: list[dict] = []
    reasons: list[str] = []

    def _row(name: str, status_chip: str, age, note: str) -> dict:
        return {
            "Name": name,
            "Status": status_chip,
            "StatusNote": note,
            "LastRunAt": "",
            "AgeHours": round(age, 2) if age is not None else "",
            "Artifact": "",
            "Note": note,
        }

    for sport in GAME_LINE_FEEDS:
        gl_age = _odds_age(BASE_DIR / GAME_LINE_FEEDS[sport])
        pr_age = _odds_age(BASE_DIR / PROPS_FEEDS[sport])
        gl_tier, gl_chip, gl_note = _render_tier(gl_age, "game_lines", sport)
        pr_tier, pr_chip, pr_note = _render_tier(pr_age, "props", sport)
        rows.append(_row(f"{sport} game lines", gl_chip, gl_age, gl_note))
        rows.append(_row(f"{sport} props", pr_chip, pr_age, pr_note))
        # REFRESH_MISSED on a current-market feed is actionable -> DEGRADED.
        if gl_tier == "REFRESH_MISSED" and pr_tier != "REFRESH_MISSED":
            reasons.append(f"{sport} game lines REFRESH_MISSED (refresh cycle missed)")
        if pr_tier in ("REFRESH_MISSED",):
            if gl_tier in ("SERVEABLE", "OVERDUE_FOR_LIVE_RENDER"):
                reasons.append(f"{sport} props REFRESH_MISSED while game lines are current "
                               "(props pipeline broken or no markets posted)")
            # when BOTH are REFRESH_MISSED the sport is off-season -> not degraded here.

    fut_age = _odds_age(BASE_DIR / FUTURES_FEED)
    fut_state = _odds_state(fut_age, "futures")   # futures: cadence only (not a 6h live-render surface)
    rows.append(_row("Futures", fut_state if fut_state != "FRESH" else "FRESH", fut_age,
                     f"Always-on futures feed (stale>{refresh_cadence_hours('futures'):.0f}h)."))
    if fut_state in ("STALE", "MISSING"):
        reasons.append(f"Futures feed {fut_state} (always-on)")
    return rows, reasons


def _operator_signals() -> tuple[list[str], dict]:
    """Read the structured operator summary (written by run_daily) for blocking failures and provider
    exhaustion. Machine-readable -- never parse the free-text operator log."""
    reasons: list[str] = []
    info: dict = {}
    try:
        payload = json.loads(OPERATOR_SUMMARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return reasons, info
    info = {
        "finished_at": payload.get("finished_at", ""),
        "blocking_failure": bool(payload.get("blocking_failure")),
        "failed_steps": list(payload.get("failed_steps") or []),
        "provider_exhausted_steps": list(payload.get("provider_exhausted_steps") or []),
        "degraded_child_outcomes": list(payload.get("degraded_child_outcomes") or []),
    }
    if info["blocking_failure"] and info["failed_steps"]:
        reasons.append("operator blocking failure: " + ", ".join(info["failed_steps"]))
    if info["provider_exhausted_steps"]:
        reasons.append("provider quota exhausted: " + ", ".join(info["provider_exhausted_steps"]))
    if info["degraded_child_outcomes"]:
        reasons.append("child outcome(s) alerting: " + ", ".join(info["degraded_child_outcomes"]))
    return reasons, info


def build_run_status() -> dict:
    now = datetime.now(timezone.utc)
    rows = []
    for check in CHECKS:
        if check["kind"] == "log":
            artifact = _latest_file(check.get("patterns", []), LOG_DIR)
        else:
            artifact = _latest_artifact(check.get("paths", []))

        age = _age_hours(artifact, now) if artifact else None
        status = _classify(age, int(check["fresh_hours"]), int(check["aging_hours"]))
        modified = datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc) if artifact else None
        rows.append({
            "Name": check["name"],
            "Status": status,
            "StatusNote": _status_note(status),
            "LastRunAt": modified.astimezone().isoformat(timespec="seconds") if modified else "",
            "AgeHours": round(age, 2) if age is not None else "",
            "Artifact": str(artifact.relative_to(BASE_DIR)) if artifact else "",
            "Note": check["note"],
        })

    # Fold in the Odds-feed families + the structured operator summary -- the signals whose absence let
    # the Oct 2026 incident read GREEN while props were days stale and CFBD was quota-exhausted.
    odds_rows, odds_reasons = _odds_family_signals()
    op_reasons, op_info = _operator_signals()
    rows.extend(odds_rows)
    degraded_reasons = odds_reasons + op_reasons

    counts = {status: sum(1 for row in rows if row["Status"] == status) for status in ["FRESH", "AGING", "STALE", "MISSING"]}
    # Severity: RED (nothing fresh at all) > DEGRADED (a current-market feed is stale, a required refresh
    # was skipped by provider exhaustion, or a blocking step failed) > WATCH (aging artifacts) > GREEN.
    # DEGRADED supersedes a false GREEN/WATCH -- that is the whole point of the incident fix.
    if counts["FRESH"] == 0:
        overall = "RED"
    elif degraded_reasons:
        overall = "DEGRADED"
    elif counts["STALE"] == 0 and counts["MISSING"] == 0:
        overall = "GREEN"
    else:
        overall = "WATCH"
    return {
        "generated_at": now.astimezone().isoformat(timespec="seconds"),
        "overall": overall,
        "counts": counts,
        "degraded_reasons": degraded_reasons,
        "operator": op_info,
        "rows": rows,
    }


def write_outputs(payload: dict) -> None:
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows = payload.get("rows", [])
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Name", "Status", "StatusNote", "LastRunAt", "AgeHours", "Artifact", "Note"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    payload = build_run_status()
    write_outputs(payload)
    print("=" * 60)
    print("BANKROLL KINGS - RUN STATUS")
    print("=" * 60)
    print(f"Overall: {payload['overall']}")
    for reason in payload.get("degraded_reasons", []):
        print(f"  DEGRADED: {reason}")
    print(f"Output: {JSON_PATH}")
    for row in payload["rows"]:
        print(f"{row['Status']:<7} {row['Name']:<24} {row['AgeHours']}h {row['Artifact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
