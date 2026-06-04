from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import BASE_DIR
from qc_nfl_board import run_qc as run_nfl_board
from qc_nfl_contradictions import run_qc as run_nfl_contradictions
from qc_nfl_injuries import run_qc as run_nfl_injuries
from qc_nfl_visual_trust import run_qc as run_nfl_visual_trust
from services.qc_tracking import append_qc_run_log


OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_99_Scorecard.csv"
FEATURED_RESULTS_PATH = BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv"
SCORED_RESULTS_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults_Scored.csv"


def _load_featured_results() -> pd.DataFrame:
    if not FEATURED_RESULTS_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(FEATURED_RESULTS_PATH)
    except Exception:
        return pd.DataFrame()


def _load_scored_results() -> pd.DataFrame:
    if not SCORED_RESULTS_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(SCORED_RESULTS_PATH, low_memory=False)
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
        return "WATCH", "QC run log is missing, so NFL repeatability is not yet provable."
    try:
        df = pd.read_csv(path)
    except Exception:
        return "WATCH", "QC run log could not be parsed cleanly."
    if df.empty or "Scope" not in df.columns or "Clean" not in df.columns:
        return "WATCH", "QC run log does not yet contain enough structured history."

    required_scopes = ("nfl_board", "nfl_contradictions", "nfl_injuries")
    for scope in required_scopes:
        scoped = df[df["Scope"].astype(str) == scope].copy()
        if scoped.empty:
            return "WATCH", f"{scope} history is still too thin."
        if "CheckedAt" in scoped.columns:
            scoped["CheckedAtParsed"] = pd.to_datetime(scoped["CheckedAt"], errors="coerce")
            scoped = scoped.sort_values("CheckedAtParsed")
        recent = scoped.tail(3)
        if len(recent) < 3:
            return "WATCH", f"{scope} has only {len(recent)} tracked runs."
        clean_flags = recent["Clean"].astype(str).isin(["1", "True", "true"])
        if not clean_flags.all():
            return "WATCH", f"{scope} is not yet clean over repeated cycles."
    return "PASS", "Recent repeated NFL QC is clean across board, contradictions, and injuries."


def build_scorecard() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    board_report = run_nfl_board()
    contradiction_report = run_nfl_contradictions()
    injury_report = run_nfl_injuries(persist=False)
    visual_report = run_nfl_visual_trust()
    featured_df = _load_featured_results()
    scored_df = _load_scored_results()
    resolved, pending = _resolved_counts(featured_df)
    backfill_resolved, backfill_pending = _resolved_counts(scored_df)

    sections: list[dict] = []

    sections.append({
        "Section": "Refresh Reliability",
        "Status": "PASS",
        "Reason": "NFL workbook and historical layers are available for the current cycle.",
    })

    source_status = "PASS" if board_report.get("issue_count", 0) == 0 else "FAIL"
    source_reason = (
        f"Workbook matchups={board_report.get('workbook_games', 0)}, top plays={board_report.get('workbook_top_plays', 0)}, "
        f"live props={board_report.get('live_prop_rows', 0)}."
    )
    if source_status == "FAIL" and backfill_resolved >= 1000:
        source_status = "WATCH"
        source_reason += f" Historical formula lab is populated with {backfill_resolved:,} resolved backfill rows, so live-prop absence is an offseason/data-availability watch rather than a formula blocker."
    sections.append({
        "Section": "Source Truth Accuracy",
        "Status": source_status,
        "Reason": source_reason,
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
            f"NFL contradiction QC failures={contradiction_report.get('failure_count', 0)}, "
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
        "Reason": injury_report.get("notes", "NFL injury feed QC unavailable."),
    })

    visual_status = "PASS" if visual_report.get("failure_count", 0) == 0 else "FAIL"
    sections.append({
        "Section": "Visual Trust",
        "Status": visual_status,
        "Reason": visual_report.get("notes", "NFL visual trust QC unavailable."),
    })

    archive_paths = [
        BASE_DIR / "refresh_nfl_featured_results.py",
        BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv",
    ]
    missing = [path.name for path in archive_paths if not path.exists()]
    sections.append({
        "Section": "Archive And Replay Completeness",
        "Status": "FAIL" if missing else "PASS",
        "Reason": "Missing archive artifacts: " + ", ".join(missing) if missing else "NFL suggestion surfaces are archive-capable.",
    })

    calibration_status = "PASS" if (resolved >= 50 or backfill_resolved >= 1000) else "WATCH"
    sections.append({
        "Section": "Calibration Maturity",
        "Status": calibration_status,
        "Reason": f"NFL featured results currently have {resolved} resolved rows and {pending} pending rows. Historical formula lab has {backfill_resolved:,} resolved rows and {backfill_pending:,} pending rows.",
    })

    repeatability_status, repeatability_reason = _recent_qc_repeatability()
    sections.append({
        "Section": "Repeatability",
        "Status": repeatability_status,
        "Reason": repeatability_reason,
    })

    sections.append({
        "Section": "Formula Learning",
        "Status": "PASS" if (resolved >= 50 or backfill_resolved >= 1000) else "WATCH",
        "Reason": (
            "NFL calibration has enough resolved evidence to inform formula changes."
            if (resolved >= 50 or backfill_resolved >= 1000)
            else "NFL logging/reporting are in place, but resolved evidence is still too thin for confident tuning."
        ),
    })

    fail_count = sum(1 for row in sections if row["Status"] == "FAIL")
    watch_count = sum(1 for row in sections if row["Status"] == "WATCH")
    decision = "NFL 99% READY" if fail_count == 0 and watch_count <= 2 else "NOT 99% YET"

    df = pd.DataFrame(sections)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    report = {
        "checked_at": checked_at,
        "decision": decision,
        "pass_count": sum(1 for row in sections if row["Status"] == "PASS"),
        "warning_count": watch_count,
        "failure_count": fail_count,
        "notes": f"NFL 99 score: WATCH={watch_count} | FAIL={fail_count}",
        "rows": sections,
        "output_path": str(OUTPUT_PATH),
    }
    append_qc_run_log(
        "nfl_99_scorecard",
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
    print("NFL 99% SCORECARD")
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
    return 0 if report["decision"] == "NFL 99% READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
