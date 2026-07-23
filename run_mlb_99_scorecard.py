from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import BASE_DIR
from qc_mlb_contradictions import run_qc as run_mlb_contradictions
from qc_mlb_injuries import run_qc as run_mlb_injuries
from qc_mlb_readiness import run_qc as run_mlb_readiness
from qc_mlb_visual_trust import run_qc as run_mlb_visual_trust
from services.qc_tracking import append_qc_run_log


OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "MLB_99_Scorecard.csv"
FEATURED_RESULTS_PATH = BASE_DIR / "data" / "tracking" / "MLB_FeaturedResults.csv"
REFRESH_LOG_PATH = BASE_DIR / "logs" / "refresh_mlb.log"


def _load_featured_results() -> pd.DataFrame:
    if not FEATURED_RESULTS_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(FEATURED_RESULTS_PATH)
    except Exception:
        return pd.DataFrame()


def _resolved_counts(df: pd.DataFrame) -> tuple[int, int]:
    if df.empty or "OutcomeState" not in df.columns:
        return 0, 0
    outcomes = df["OutcomeState"].fillna("").astype(str)
    resolved = int(outcomes.isin(["Hit", "Miss", "Push"]).sum())
    pending = int(outcomes.eq("Pending").sum())
    return resolved, pending


def _refresh_reliability_status() -> tuple[str, str]:
    log_candidates = [REFRESH_LOG_PATH]
    log_candidates.extend((BASE_DIR / "logs").glob("daily_refresh*mlb*.log"))
    log_candidates.extend((BASE_DIR / "logs").glob("daily_refresh*.log"))
    manifest_path = BASE_DIR / "data" / "tracking" / "MLB_DailyRefresh_Manifest.json"
    if manifest_path.exists():
        log_candidates.append(manifest_path)
    existing = [path for path in log_candidates if path.exists()]
    if not existing:
        return "WATCH", "MLB refresh log/manifest is missing."
    latest = max(existing, key=lambda path: path.stat().st_mtime)
    age_hours = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds() / 3600.0
    if age_hours <= 36:
        return "PASS", f"MLB refresh artifact is fresh ({latest.name}, {age_hours:.1f}h old)."
    return "WATCH", f"MLB refresh artifact is aging ({latest.name}, {age_hours:.1f}h old)."


def _newest_snapshot(path, sport: str | None = None):
    """Newest SnapshotDate in a tracking CSV, optionally filtered to one sport."""
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    if sport and "Sport" in df.columns:
        df = df[df["Sport"].astype(str).str.upper() == sport.upper()]
    if "SnapshotDate" not in df.columns or df.empty:
        return None
    dates = pd.to_datetime(df["SnapshotDate"], errors="coerce").dropna()
    return dates.max() if not dates.empty else None


def _featured_freshness(featured_path, candidate_path, max_lag_days: int = 3) -> tuple[str, str]:
    """Featured results must stay within max_lag_days of the candidate archive.

    Comparing the two rather than 'now' is season-robust: in the offseason both
    stop advancing together, so the lag stays ~0 and there is no false WATCH.
    """
    featured = _newest_snapshot(featured_path)
    candidate = _newest_snapshot(candidate_path, sport="MLB")
    if featured is None:
        return "WATCH", "MLB featured results carry no readable SnapshotDate to verify freshness."
    if candidate is None:
        return "PASS", f"MLB featured results present (newest {featured.date()}); no candidate archive to compare."
    lag = (candidate - featured).days
    if lag > max_lag_days:
        return "WATCH", (
            f"MLB featured results are STALE: newest {featured.date()} is {lag} days behind the "
            f"candidate archive ({candidate.date()}). The featured/grading snapshot pipeline is not "
            f"keeping pace -- existence is not completeness."
        )
    return "PASS", f"MLB featured results are current (newest {featured.date()}, {max(lag,0)}d behind archive)."


def _recent_qc_repeatability() -> tuple[str, str]:
    path = BASE_DIR / "data" / "tracking" / "QC_Run_Log.csv"
    if not path.exists():
        return "WATCH", "QC run log is missing, so MLB repeatability is not yet provable."
    try:
        df = pd.read_csv(path)
    except Exception:
        return "WATCH", "QC run log could not be parsed cleanly."
    if df.empty or "Scope" not in df.columns or "Clean" not in df.columns:
        return "WATCH", "QC run log does not yet contain enough structured history."

    required_scopes = ("mlb_contradictions", "mlb_readiness", "mlb_injuries")
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
    return "PASS", "Recent repeated MLB QC is clean across contradictions, readiness, and injuries."


def build_scorecard() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    readiness_report = run_mlb_readiness()
    contradiction_report = run_mlb_contradictions()
    injury_report = run_mlb_injuries(persist=False)
    visual_report = run_mlb_visual_trust()
    featured_df = _load_featured_results()
    resolved, pending = _resolved_counts(featured_df)

    sections: list[dict] = []

    refresh_status, refresh_reason = _refresh_reliability_status()
    sections.append({"Section": "Refresh Reliability", "Status": refresh_status, "Reason": refresh_reason})

    sections.append({
        "Section": "Source Truth Accuracy",
        "Status": "PASS" if readiness_report.get("failure_count", 0) == 0 else "FAIL",
        "Reason": readiness_report.get("notes", "MLB readiness notes unavailable."),
    })

    coverage_path = BASE_DIR / "data" / "tracking" / "MLB_Props_MarketCoverage.csv"
    if coverage_path.exists():
        try:
            coverage_df = pd.read_csv(coverage_path)
        except Exception:
            coverage_df = pd.DataFrame()
    else:
        coverage_df = pd.DataFrame()
    if coverage_df.empty:
        coverage_status = "FAIL"
        coverage_reason = "MLB market coverage file is missing or empty."
    else:
        missing = coverage_df[coverage_df["Status"].fillna("").astype(str).str.upper() == "MISSING"].copy()
        one_sided = coverage_df[coverage_df.get("PriceFormat", pd.Series(dtype=str)).fillna("").astype(str).str.upper() == "ONE_SIDED_YES"].copy()
        coverage_status = "PASS" if missing.empty else "WATCH"
        coverage_reason = f"{len(coverage_df) - len(missing)}/{len(coverage_df)} required markets live; {len(one_sided)} one-sided market(s)."
        if not missing.empty:
            coverage_reason += " Missing: " + ", ".join(missing["Stat"].fillna("").astype(str).tolist())
    sections.append({
        "Section": "Market Coverage",
        "Status": coverage_status,
        "Reason": coverage_reason,
    })

    context_path = BASE_DIR / "data" / "context" / "MLB_GameContext.csv"
    context_df = pd.read_csv(context_path) if context_path.exists() else pd.DataFrame()
    if context_df.empty:
        context_status = "WATCH"
        context_reason = "MLB game context is empty; weather, umpire, and ballpark tags are not live."
    else:
        missing_weather = "Temperature" not in context_df.columns or context_df["Temperature"].fillna("").astype(str).str.strip().eq("").all()
        missing_umpires = "Umpire" not in context_df.columns or context_df["Umpire"].fillna("").astype(str).str.strip().eq("").all()
        missing_ballpark = "Ballpark" not in context_df.columns or context_df["Ballpark"].fillna("").astype(str).str.strip().eq("").any()
        if missing_ballpark:
            context_status = "FAIL"
        elif missing_weather or missing_umpires:
            context_status = "WATCH"
        else:
            context_status = "PASS"
        missing_bits = []
        if missing_weather:
            missing_bits.append("weather")
        if missing_umpires:
            missing_bits.append("umpires")
        if missing_ballpark:
            missing_bits.append("ballparks")
        context_reason = f"{len(context_df)} game context row(s) loaded."
        if missing_bits:
            context_reason += " Missing: " + ", ".join(missing_bits) + "."
    sections.append({
        "Section": "Game Context Intelligence",
        "Status": context_status,
        "Reason": context_reason,
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
            f"MLB contradiction QC failures={contradiction_report.get('failure_count', 0)}, "
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
        "Reason": injury_report.get("notes", "MLB injury feed QC unavailable."),
    })

    visual_status = "PASS" if visual_report.get("failure_count", 0) == 0 else "FAIL"
    sections.append({
        "Section": "Visual Trust",
        "Status": visual_status,
        "Reason": visual_report.get("notes", "MLB visual trust QC unavailable."),
    })

    featured_path = BASE_DIR / "data" / "tracking" / "MLB_FeaturedResults.csv"
    candidate_path = BASE_DIR / "data" / "tracking" / "NBA_CandidateArchive.csv"
    archive_paths = [
        BASE_DIR / "refresh_mlb_featured_results.py",
        featured_path,
        candidate_path,
    ]
    missing = [path.name for path in archive_paths if not path.exists()]
    if missing:
        archive_status = "FAIL"
        archive_reason = "Missing archive artifacts: " + ", ".join(missing)
    else:
        # Existence is not completeness. The featured-results snapshot must keep
        # pace with the candidate archive it is built from; comparing the two is
        # season-robust (in the offseason both go quiet together, so no false
        # alarm). A 7-16 day lag while the archive is current -- as seen in review
        # -- means the featured/grading snapshot pipeline stalled, and a stale
        # archive must not read as "complete".
        archive_status, archive_reason = _featured_freshness(featured_path, candidate_path)
    sections.append({
        "Section": "Archive And Replay Completeness",
        "Status": archive_status,
        "Reason": archive_reason,
    })

    calibration_status = "PASS" if resolved >= 50 else "WATCH"
    sections.append({
        "Section": "Calibration Maturity",
        "Status": calibration_status,
        "Reason": f"MLB featured results currently have {resolved} resolved rows and {pending} pending rows.",
    })

    repeatability_status, repeatability_reason = _recent_qc_repeatability()
    sections.append({
        "Section": "Repeatability",
        "Status": repeatability_status,
        "Reason": repeatability_reason,
    })

    sections.append({
        "Section": "Formula Learning",
        "Status": "PASS" if resolved >= 50 else "WATCH",
        "Reason": (
            "MLB calibration has enough resolved evidence to inform formula changes."
            if resolved >= 50
            else "MLB logging/reporting are in place, but resolved evidence is still too thin for confident tuning."
        ),
    })

    fail_count = sum(1 for row in sections if row["Status"] == "FAIL")
    watch_count = sum(1 for row in sections if row["Status"] == "WATCH")
    decision = "MLB 99% READY" if fail_count == 0 and watch_count <= 2 else "NOT 99% YET"

    df = pd.DataFrame(sections)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    report = {
        "checked_at": checked_at,
        "decision": decision,
        "pass_count": sum(1 for row in sections if row["Status"] == "PASS"),
        "warning_count": watch_count,
        "failure_count": fail_count,
        "notes": f"MLB 99 score: WATCH={watch_count} | FAIL={fail_count}",
        "rows": sections,
        "output_path": str(OUTPUT_PATH),
    }
    append_qc_run_log(
        "mlb_99_scorecard",
        {
            "checked_at": checked_at,
            "clean": fail_count == 0,
            "pass_count": report["pass_count"],
            "warning_count": 0 if decision == "MLB 99% READY" else watch_count,
            "failure_count": fail_count,
            "notes": report["notes"],
        },
    )
    return report


def main() -> int:
    report = build_scorecard()
    print("=" * 60)
    print("MLB 99% SCORECARD")
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
    return 0 if report["decision"] == "MLB 99% READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
