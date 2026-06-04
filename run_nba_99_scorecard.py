from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import BASE_DIR
from qc_nba_contradictions import run_qc as run_nba_contradictions
from qc_nba_injuries import run_qc as run_nba_injuries
from qc_nba_visual_trust import run_qc as run_nba_visual_trust
from qc_nba_sources import run_source_audit
from services.qc_tracking import append_qc_run_log


OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NBA_99_Scorecard.csv"
FEATURED_RESULTS_PATH = BASE_DIR / "data" / "tracking" / "NBA_FeaturedResults.csv"
ALL_RESULTS_PATH = BASE_DIR / "data" / "tracking" / "NBA_AllPropResults.csv"
REFRESH_LOG_PATH = BASE_DIR / "logs" / "refresh_nba_daily.log"


def _load_featured_results() -> pd.DataFrame:
    if not FEATURED_RESULTS_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(FEATURED_RESULTS_PATH)
    except Exception:
        return pd.DataFrame()


def _load_all_results() -> pd.DataFrame:
    if not ALL_RESULTS_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(ALL_RESULTS_PATH)
    except Exception:
        return pd.DataFrame()


def _resolved_counts(df: pd.DataFrame) -> tuple[int, int]:
    if df.empty or "OutcomeState" not in df.columns:
        return 0, 0
    outcomes = df["OutcomeState"].fillna("").astype(str)
    resolved = int(outcomes.isin(["Hit", "Miss", "Push"]).sum())
    pending = int(outcomes.eq("Pending").sum())
    return resolved, pending


def _recent_qc_repeatability() -> tuple[str, str]:
    path = BASE_DIR / "data" / "tracking" / "QC_Run_Log.csv"
    if not path.exists():
        return "WATCH", "QC run log is missing, so repeatability is not yet provable."
    try:
        df = pd.read_csv(path)
    except Exception:
        return "WATCH", "QC run log could not be parsed cleanly."
    if df.empty or "Scope" not in df.columns or "Clean" not in df.columns:
        return "WATCH", "QC run log does not yet contain enough structured history."

    def _clean_slice(scope: str, minimum: int = 3) -> tuple[bool, int]:
        scoped = df[df["Scope"].astype(str) == scope].copy()
        if scoped.empty:
            return False, 0
        if "CheckedAt" in scoped.columns:
            scoped["CheckedAtParsed"] = pd.to_datetime(scoped["CheckedAt"], errors="coerce")
            scoped = scoped.sort_values("CheckedAtParsed")
        recent = scoped.tail(minimum)
        clean_flags = recent["Clean"].astype(str).isin(["1", "True", "true"])
        return bool(len(recent) >= minimum and clean_flags.all()), len(recent)

    source_ok, source_n = _clean_slice("nba_sources")
    contradiction_ok, contradiction_n = _clean_slice("nba_contradictions")
    board_ok, board_n = _clean_slice("nba_board")

    if source_ok and contradiction_ok and board_ok:
        return "PASS", f"Recent repeated NBA QC is clean (sources={source_n}, contradictions={contradiction_n}, board={board_n})."
    return "WATCH", f"Repeatability is improving, but sustained clean cycles are not fully proven yet (sources={source_n}, contradictions={contradiction_n}, board={board_n})."


def _refresh_reliability_status() -> tuple[str, str]:
    candidates = [REFRESH_LOG_PATH, ALL_RESULTS_PATH, BASE_DIR / "data" / "props" / "NBA_Props.csv"]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return "WATCH", "NBA refresh artifacts are missing."
    latest = max(existing, key=lambda path: path.stat().st_mtime)
    age_hours = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds() / 3600.0
    if age_hours <= 36:
        return "PASS", f"NBA refresh artifact is fresh ({latest.name}, {age_hours:.1f}h old)."
    return "WATCH", f"NBA refresh artifact is aging ({latest.name}, {age_hours:.1f}h old)."


def build_scorecard() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_report = run_source_audit()
    contradiction_report = run_nba_contradictions()
    injury_report = run_nba_injuries(persist=False)
    visual_report = run_nba_visual_trust()
    featured_df = _load_featured_results()
    all_results_df = _load_all_results()
    resolved, pending = _resolved_counts(featured_df)
    all_resolved, all_pending = _resolved_counts(all_results_df)

    sections: list[dict] = []

    refresh_status, refresh_reason = _refresh_reliability_status()
    sections.append({"Section": "Refresh Reliability", "Status": refresh_status, "Reason": refresh_reason})

    source_status = "PASS" if source_report.get("failure_count", 0) == 0 else "FAIL"
    sections.append({
        "Section": "Source Truth Accuracy",
        "Status": source_status,
        "Reason": source_report.get("notes", "NBA source audit unavailable."),
    })

    integrity_status = "PASS"
    if contradiction_report.get("failure_count", 0) > 0:
        integrity_status = "FAIL"
    elif contradiction_report.get("warning_count", 0) > 0:
        integrity_status = "WATCH"
    sections.append({
        "Section": "Suggestion Integrity",
        "Status": integrity_status,
        "Reason": (
            f"NBA contradiction QC failures={contradiction_report.get('failure_count', 0)}, "
            f"warnings={contradiction_report.get('warning_count', 0)}."
        ),
    })

    injury_status = "PASS"
    if injury_report.get("failure_count", 0) > 0:
        injury_status = "FAIL"
    elif injury_report.get("warning_count", 0) > 0:
        injury_status = "WATCH"
    sections.append({
        "Section": "Injury And Return Context",
        "Status": injury_status,
        "Reason": injury_report.get("notes", "NBA injury feed QC unavailable."),
    })

    visual_status = "PASS" if visual_report.get("failure_count", 0) == 0 else "FAIL"
    sections.append({
        "Section": "Visual Trust",
        "Status": visual_status,
        "Reason": visual_report.get("notes", "NBA visual trust QC unavailable."),
    })

    archive_status = "PASS"
    archive_reason = "Featured/method suggestion surfaces are archived and replayable."
    required_paths = [
        BASE_DIR / "refresh_featured_results.py",
        BASE_DIR / "data" / "tracking" / "NBA_FeaturedResults.csv",
        BASE_DIR / "data" / "tracking" / "NBA_CandidateArchive.csv",
    ]
    missing = [path.name for path in required_paths if not path.exists()]
    if missing:
        archive_status = "FAIL"
        archive_reason = "Missing archive artifacts: " + ", ".join(missing)
    sections.append({
        "Section": "Archive And Replay Completeness",
        "Status": archive_status,
        "Reason": archive_reason,
    })

    calibration_status = "PASS" if max(resolved, all_resolved) >= 50 else "WATCH"
    sections.append({
        "Section": "Calibration Maturity",
        "Status": calibration_status,
        "Reason": f"NBA featured results have {resolved} resolved / {pending} pending; all results have {all_resolved} resolved / {all_pending} pending.",
    })

    repeatability_status, repeatability_reason = _recent_qc_repeatability()
    sections.append({
        "Section": "Repeatability",
        "Status": repeatability_status,
        "Reason": repeatability_reason,
    })

    formula_status = "PASS" if max(resolved, all_resolved) >= 50 else "WATCH"
    formula_reason = (
        "Calibration has enough resolved evidence to begin formula learning."
        if max(resolved, all_resolved) >= 50
        else "Logging/reporting are in place, but there is not enough resolved evidence yet to justify real formula changes."
    )
    sections.append({
        "Section": "Formula Learning",
        "Status": formula_status,
        "Reason": formula_reason,
    })

    fail_count = sum(1 for row in sections if row["Status"] == "FAIL")
    watch_count = sum(1 for row in sections if row["Status"] == "WATCH")
    decision = "NBA 99% READY" if fail_count == 0 and watch_count <= 2 else "NOT 99% YET"

    df = pd.DataFrame(sections)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    report = {
        "checked_at": checked_at,
        "decision": decision,
        "pass_count": sum(1 for row in sections if row["Status"] == "PASS"),
        "warning_count": watch_count,
        "failure_count": fail_count,
        "notes": f"NBA 99 score: WATCH={watch_count} | FAIL={fail_count}",
        "rows": sections,
        "output_path": str(OUTPUT_PATH),
    }
    append_qc_run_log(
        "nba_99_scorecard",
        {
            "checked_at": checked_at,
            "clean": fail_count == 0,
            "pass_count": report["pass_count"],
            "warning_count": watch_count,
            "failure_count": fail_count,
            "notes": report["notes"],
        },
    )
    return report


def main() -> int:
    report = build_scorecard()
    print("=" * 60)
    print("NBA 99% SCORECARD")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Decision: {report['decision']}")
    print(f"PASS: {report['pass_count']}")
    print(f"WATCH: {report['warning_count']}")
    print(f"FAIL: {report['failure_count']}")
    print(f"Saved: {report['output_path']}")
    print()
    for row in report["rows"]:
        print(f"[{row['Status']}] {row['Section']} | {row['Reason']}")
    return 0 if report["decision"] == "NBA 99% READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
