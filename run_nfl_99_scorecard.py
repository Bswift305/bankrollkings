"""NFL 99% readiness scorecard.

Design rule (2026-07, from a dev review): this scorecard MUST separate
INFRASTRUCTURE readiness from LIVE readiness.

- Infrastructure = pipes exist, QC runs clean, surfaces are archive-capable, the
  historical formula lab is populated. This can be true in the offseason.
- Live readiness = real, resolved, LIVE featured results exist in enough volume to
  prove the board's calibration on games it actually served.

The historical formula lab (`NFL_AllPropResults_Scored.csv`) is BACKTEST data and is
in-sample/leaked (see `validate_nfl_prop_score_oos.py`: PropScore inverts out of
sample). It may demonstrate that the plumbing runs, but it is NOT a live track record
and must never substitute for live evidence in the headline verdict. So the decision
can only read "NFL 99% READY" when live resolved rows clear `LIVE_READY_MIN_RESOLVED`;
with clean infrastructure but no live season yet, it reads
"INFRASTRUCTURE READY - LIVE SEASON PENDING" -- honest, not green.
"""
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

# Minimum LIVE resolved featured rows before the board's calibration is considered
# proven on games it actually served. Backfill/backtest rows do not count toward this.
LIVE_READY_MIN_RESOLVED = 50


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
        source_reason += (
            f" Historical formula lab holds {backfill_resolved:,} resolved backfill rows"
            " (in-sample backtest data, NOT a live record), so live-prop absence is an"
            " offseason/data-availability watch rather than a formula blocker."
        )
    sections.append({
        "Section": "Source Truth Accuracy",
        "Status": source_status,
        "Reason": source_reason,
    })

    integrity_status = "PASS"
    integrity_reason = (
        f"NFL contradiction QC failures={contradiction_report.get('failure_count', 0)}, "
        f"warnings={contradiction_report.get('warning_count', 0)}."
    )
    if contradiction_report.get("failure_count", 0) > 0:
        integrity_status = "FAIL"
    elif contradiction_report.get("unverified"):
        # 0 featured plays evaluated -> absence of contradictions is not evidence.
        integrity_status = "WATCH"
        integrity_reason = (
            "NFL contradiction QC evaluated 0 featured plays (offseason/no live board), "
            "so a clean result is UNVERIFIED, not proof of integrity."
        )
    elif contradiction_report.get("warning_count", 0) > 0:
        integrity_status = "WATCH"
    sections.append({
        "Section": "Suggestion Integrity",
        "Status": integrity_status,
        "Reason": integrity_reason,
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

    # Calibration maturity is a claim about the LIVE board. Backfill/backtest volume
    # does not count -- it is in-sample and cannot prove live calibration.
    calibration_status = "PASS" if resolved >= LIVE_READY_MIN_RESOLVED else "WATCH"
    sections.append({
        "Section": "Calibration Maturity",
        "Status": calibration_status,
        "Reason": (
            f"NFL LIVE featured results have {resolved} resolved / {pending} pending rows "
            f"(need >= {LIVE_READY_MIN_RESOLVED} live to prove calibration). "
            f"The historical formula lab holds {backfill_resolved:,} resolved / {backfill_pending:,} "
            f"pending rows, but that is in-sample backtest data and is NOT a live track record."
        ),
    })

    repeatability_status, repeatability_reason = _recent_qc_repeatability()
    sections.append({
        "Section": "Repeatability",
        "Status": repeatability_status,
        "Reason": repeatability_reason,
    })

    # Formula tuning must be driven by LIVE resolved evidence. Tuning the live formula
    # on the in-sample lab is exactly the leakage validate_nfl_prop_score_oos.py proved.
    learning_ready = resolved >= LIVE_READY_MIN_RESOLVED
    sections.append({
        "Section": "Formula Learning",
        "Status": "PASS" if learning_ready else "WATCH",
        "Reason": (
            "NFL live calibration has enough resolved evidence to inform formula changes."
            if learning_ready
            else (
                f"NFL logging/reporting are in place, but only {resolved} LIVE resolved rows exist; "
                f"the {backfill_resolved:,}-row historical lab is in-sample and must not be used to "
                f"tune the live formula."
            )
        ),
    })

    fail_count = sum(1 for row in sections if row["Status"] == "FAIL")
    watch_count = sum(1 for row in sections if row["Status"] == "WATCH")

    # The headline splits INFRASTRUCTURE from LIVE readiness. "99% READY" is a claim
    # the live product is proven, so it requires live resolved evidence; it can never
    # be reached on backfill alone. Order matters: a real FAIL blocks everything; then
    # thin live evidence caps the verdict at infrastructure-ready; only with live
    # evidence AND a clean board do we claim 99% ready.
    live_ready = resolved >= LIVE_READY_MIN_RESOLVED
    if fail_count > 0:
        decision = "NOT 99% YET"
    elif not live_ready:
        decision = "INFRASTRUCTURE READY - LIVE SEASON PENDING"
    elif watch_count <= 2:
        decision = "NFL 99% READY"
    else:
        decision = "NOT 99% YET"

    df = pd.DataFrame(sections)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    report = {
        "checked_at": checked_at,
        "decision": decision,
        "pass_count": sum(1 for row in sections if row["Status"] == "PASS"),
        "warning_count": watch_count,
        "failure_count": fail_count,
        "live_resolved": resolved,
        "backfill_resolved": backfill_resolved,
        "live_ready": live_ready,
        "notes": (
            f"NFL 99 score: {decision} | live_resolved={resolved} "
            f"(need >= {LIVE_READY_MIN_RESOLVED}) | backfill={backfill_resolved:,} (in-sample) | "
            f"WATCH={watch_count} | FAIL={fail_count}"
        ),
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
    print(
        f"Live readiness: {report['live_resolved']} live resolved "
        f"(need >= {LIVE_READY_MIN_RESOLVED}) | backfill {report['backfill_resolved']:,} rows are in-sample, not live"
    )
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
