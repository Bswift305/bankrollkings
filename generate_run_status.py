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
from services import operator_run
from services.run_outcomes import partition_child_outcomes


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
TRACKING_DIR = BASE_DIR / "data" / "tracking"
JSON_PATH = TRACKING_DIR / "Run_Status.json"
CSV_PATH = TRACKING_DIR / "Run_Status.csv"
OPERATOR_SUMMARY_PATH = TRACKING_DIR / "Last_Operator_Summary.json"
# D11: the operator's current-run marker (services/operator_run.py). "Current" is keyed on its run id.
OPERATOR_MARKER_PATH = TRACKING_DIR / operator_run.MARKER_FILENAME
# Patchable seams (offline QC): process liveness + this host's name for the killed-run check.
_PID_ALIVE = operator_run.pid_alive
_HOSTNAME = None   # None -> socket.gethostname()
# Log checks whose current-run log is written by the operator run itself (attributed by the
# "Operator run: <id>" header line), mapped to the row status used while that run has not produced it.
_OPERATOR_LOG_PENDING_STATUS = {"Daily Operator": "IN_PROGRESS", "Edge Engine": "PENDING", "Scorecards": "PENDING"}


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
        "IN_PROGRESS": "In progress",
        "PENDING": "Pending (this run)",
        "INCOMPLETE": "Incomplete (run did not finish)",
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


def _summary_reasons(payload: dict) -> tuple[list[str], dict]:
    """(reasons, info) from ONE operator summary -- the pre-D11 fold, unchanged."""
    reasons: list[str] = []
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


def _previous_run_block(summary: dict | None) -> dict | None:
    """The last FINISHED run, kept visibly separate from the current run (never folded into its reasons)."""
    if not summary:
        return None
    reasons, info = _summary_reasons(summary)
    return {
        "label": "previous run",
        "run_id": summary.get("run_id"),          # None for a pre-D11 (unidentified) summary
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at", ""),
        "log": summary.get("log", ""),
        "reasons": reasons,
        **{k: v for k, v in info.items() if k != "finished_at"},
    }


def _operator_context(now: datetime | None = None) -> tuple[list[str], dict]:
    """Decide WHICH operator run is current (by run id, from the marker) and what may be reported as its
    state. Returns (current degraded reasons, operator info).

    operator.state:
      LEGACY      no marker (pre-D11 tree): the summary is folded exactly as before.
      PENDING     the marker's run is RUNNING and has not written its final summary -> status IN PROGRESS;
                  the previous run's summary is shown only under `previous_run`, never as current.
      INCOMPLETE  RUNNING past its deadline / its process is gone, with no matching summary.
      COMPLETE/FAILED  the summary carries the marker's run id -> its reasons are current.
      UNKNOWN     the marker is unreadable -> nothing is folded as current.
    """
    now = now or datetime.now(timezone.utc)
    m_status, marker = operator_run.read_json_status(OPERATOR_MARKER_PATH)
    if m_status == "ok" and not (operator_run.valid_run_id(marker.get("run_id"))
                                 and marker.get("state") in (operator_run.RUNNING, *operator_run.TERMINAL)
                                 and operator_run.parse_utc(marker.get("started_at"))):
        m_status, marker = "corrupt", None
    s_status, summary = operator_run.read_json_status(OPERATOR_SUMMARY_PATH)
    if s_status != "ok":
        summary = None

    if m_status == "absent":
        # Pre-D11 behaviour, unchanged (no run identity exists on this tree yet).
        if summary is None:
            return [], {}
        reasons, info = _summary_reasons(summary)
        info["state"] = "LEGACY"
        info["run_id"] = summary.get("run_id")
        return reasons, info

    if m_status == "corrupt":
        return (["operator run marker unreadable (current run unknown)"],
                {"state": "UNKNOWN", "status_label": "UNKNOWN", "current_run": None,
                 "previous_run": _previous_run_block(summary)})

    run_id = marker["run_id"]
    env_id = operator_run.env_run_id()
    if env_id and env_id != run_id:
        # This caller belongs to run `env_id` but the marker names another run: report THIS caller's run
        # as pending; never borrow the other run's state.
        marker = {"run_id": env_id, "state": operator_run.RUNNING, "started_at": None, "deadline_at": None}
        run_id = env_id
    current = {
        "run_id": run_id,
        "started_at": marker.get("started_at"),
        "deadline_at": marker.get("deadline_at"),
        "finished_at": marker.get("finished_at"),
        "log": marker.get("log"),
    }
    matching = summary if (summary and summary.get("run_id") == run_id) else None
    previous = None if matching else _previous_run_block(summary)

    if matching:
        # The final summary of THIS run exists (it is what closes the run): its reasons are current.
        reasons, info = _summary_reasons(matching)
        state = matching.get("state") if matching.get("state") in operator_run.TERMINAL else (
            operator_run.FAILED if info["blocking_failure"] else operator_run.COMPLETE)
        current["started_at"] = matching.get("started_at") or current["started_at"]
        current["finished_at"] = matching.get("finished_at")
        info.update({"state": state, "status_label": state, "run_id": run_id, "current_run": current,
                     "not_run_this_run": matching.get("not_run_this_run") or {}})
        return reasons, info

    if marker.get("state") in operator_run.TERMINAL:
        # Closed, but its summary is missing/foreign: never substitute the older summary.
        return ([f"operator run {run_id} closed {marker.get('state')} but its final summary is missing"],
                {"state": marker.get("state"), "status_label": marker.get("state"), "run_id": run_id,
                 "current_run": current, "previous_run": previous})

    if marker.get("started_at") is None:   # env-only identity (marker names another run)
        verdict, why = operator_run.RUNNING, "in progress"
    else:
        verdict, why = operator_run.assess_running(marker, now, host=_HOSTNAME, alive_fn=_PID_ALIVE)
    if verdict == operator_run.INCOMPLETE:
        return ([f"operator run {run_id} (started {current['started_at']}) did not finish (INCOMPLETE: {why})"],
                {"state": "INCOMPLETE", "status_label": "INCOMPLETE", "run_id": run_id,
                 "incomplete_reason": why, "current_run": current, "previous_run": previous})

    # RUNNING: interim child outcomes of THIS run are shown as interim only -- not final, not folded.
    try:
        interim, _ = partition_child_outcomes(BASE_DIR, run_id)
    except OSError:
        interim = {}
    return ([], {"state": "PENDING", "status_label": "IN PROGRESS", "run_id": run_id,
                 "current_run": current, "previous_run": previous,
                 "in_progress_child_outcomes": {p: (v.get("outcomes") or {}) for p, v in interim.items()}})


def _operator_signals() -> tuple[list[str], dict]:
    """Read the structured operator summary (written by run_daily) for blocking failures and provider
    exhaustion. Machine-readable -- never parse the free-text operator log. Run-aware since D11: only the
    CURRENT run's summary contributes reasons (see _operator_context)."""
    return _operator_context()


def _find_tagged_log(patterns: list[str], run_id: str) -> Path | None:
    """The log attributed to `run_id` by its "Operator run: <id>" header -- identity, not mtime/filename."""
    for pattern in patterns:
        for path in LOG_DIR.glob(pattern):
            if path.is_file() and operator_run.read_log_tag(path) == run_id:
                return path
    return None


def _artifact_row(check: dict, artifact: Path | None, now: datetime) -> dict:
    age = _age_hours(artifact, now) if artifact else None
    status = _classify(age, int(check["fresh_hours"]), int(check["aging_hours"]))
    modified = datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc) if artifact else None
    return {
        "Name": check["name"],
        "Status": status,
        "StatusNote": _status_note(status),
        "LastRunAt": modified.astimezone().isoformat(timespec="seconds") if modified else "",
        "AgeHours": round(age, 2) if age is not None else "",
        "Artifact": str(artifact.relative_to(BASE_DIR)) if artifact else "",
        "Note": check["note"],
    }


def _operator_log_row(check: dict, now: datetime, op: dict) -> dict:
    """A log row while an identified operator run is current. The current run's own log (by run id) is
    classified normally; otherwise the row states the current run's status and the newest other log is
    shown ONLY as `Previous*` fields, labelled previous run."""
    state = op.get("state")
    cur = op.get("current_run") or {}
    run_id = cur.get("run_id")
    patterns = check.get("patterns", [])
    own = _find_tagged_log(patterns, run_id) if run_id else None
    if own is not None:
        row = _artifact_row(check, own, now)
        row["RunId"] = run_id
        return row
    if state in (operator_run.COMPLETE, operator_run.FAILED) and check["name"] != "Daily Operator":
        # Finished run that legitimately did not produce this log (--skip-edge/--skip-scorecards, an
        # aborted chain, or a standalone run): pre-D11 newest-by-mtime behaviour.
        return _artifact_row(check, _latest_file(patterns, LOG_DIR), now)
    if state == "PENDING":
        status = _OPERATOR_LOG_PENDING_STATUS.get(check["name"], "PENDING")
        note = (f"{'In progress' if status == 'IN_PROGRESS' else 'Pending'}: run {run_id}, "
                f"started {cur.get('started_at')}")
    elif state == "INCOMPLETE":
        status = "INCOMPLETE"
        note = f"Incomplete: run {run_id} started {cur.get('started_at')} did not finish"
    else:   # finished run whose own operator log is missing
        status = "MISSING"
        note = f"Missing: no log attributed to run {run_id}"
    started = operator_run.parse_utc(cur.get("started_at"))
    row = {
        "Name": check["name"],
        "Status": status,
        "StatusNote": note,
        "LastRunAt": started.astimezone().isoformat(timespec="seconds") if started else "",
        "AgeHours": round(max(0.0, (now - started).total_seconds() / 3600), 2) if started else "",
        "Artifact": "",
        "Note": check["note"],
        "RunId": run_id,
    }
    prev = _latest_file(patterns, LOG_DIR)
    if prev is not None:
        prev_row = _artifact_row(check, prev, now)
        row.update({
            "PreviousRunLabel": "previous run",
            "PreviousRunId": operator_run.read_log_tag(prev),
            "PreviousArtifact": prev_row["Artifact"],
            "PreviousLastRunAt": prev_row["LastRunAt"],
            "PreviousAgeHours": prev_row["AgeHours"],
        })
    return row


def build_run_status(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    # D11: decide which operator run is CURRENT (by run id) before classifying the operator's own logs.
    op_reasons, op_info = _operator_context(now)
    identified = op_info.get("state") in ("PENDING", "INCOMPLETE", "COMPLETE", "FAILED")
    rows = []
    for check in CHECKS:
        if check["kind"] == "log" and identified and check["name"] in _OPERATOR_LOG_PENDING_STATUS:
            rows.append(_operator_log_row(check, now, op_info))
            continue
        if check["kind"] == "log":
            artifact = _latest_file(check.get("patterns", []), LOG_DIR)
        else:
            artifact = _latest_artifact(check.get("paths", []))
        rows.append(_artifact_row(check, artifact, now))

    # Fold in the Odds-feed families + the structured operator summary -- the signals whose absence let
    # the Oct 2026 incident read GREEN while props were days stale and CFBD was quota-exhausted.
    odds_rows, odds_reasons = _odds_family_signals()
    rows.extend(odds_rows)
    degraded_reasons = odds_reasons + op_reasons

    counts = {status: sum(1 for row in rows if row["Status"] == status) for status in ["FRESH", "AGING", "STALE", "MISSING"]}
    for extra in ("IN_PROGRESS", "PENDING", "INCOMPLETE"):   # D11 run-state rows (additive keys)
        counts[extra] = sum(1 for row in rows if row["Status"] == extra)
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
    operator_run.atomic_write_json(JSON_PATH, payload)   # the site reads this file; never a torn read
    rows = payload.get("rows", [])
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Name", "Status", "StatusNote", "LastRunAt", "AgeHours", "Artifact", "Note"],
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    payload = build_run_status()
    write_outputs(payload)
    print("=" * 60)
    print("BANKROLL KINGS - RUN STATUS")
    print("=" * 60)
    print(f"Overall: {payload['overall']}")
    op = payload.get("operator") or {}
    cur = op.get("current_run") or {}
    if op.get("state") and op.get("state") != "LEGACY":
        print(f"Operator: {op.get('status_label') or op.get('state')} -- current run {cur.get('run_id')} "
              f"started {cur.get('started_at')}" + (f" finished {cur.get('finished_at')}" if cur.get("finished_at") else ""))
    for reason in payload.get("degraded_reasons", []):
        print(f"  DEGRADED: {reason}")
    prev = op.get("previous_run")
    if prev:
        print(f"Previous run (not current): {prev.get('run_id') or 'unidentified'} finished {prev.get('finished_at')}")
        for reason in prev.get("reasons") or []:
            print(f"  previous run: {reason}")
    print(f"Output: {JSON_PATH}")
    for row in payload["rows"]:
        print(f"{row['Status']:<7} {row['Name']:<24} {row['AgeHours']}h {row['Artifact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
