from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import BASE_DIR
from qc_checkout_readiness import run_qc as run_checkout_qc
from qc_mlb_injuries import run_qc as run_mlb_injuries
from qc_nba_contradictions import run_qc as run_nba_contradictions
from qc_nba_injuries import run_qc as run_nba_injuries
from qc_nba_sources import run_source_audit
from qc_nfl_injuries import run_qc as run_nfl_injuries
from qc_nfl_contradictions import run_qc as run_nfl_contradictions
from qc_wnba_injuries import run_qc as run_wnba_injuries
from qc_cfb_injuries import run_qc as run_cfb_injuries
from qc_platform_routes import run_qc as run_platform_routes
from qc_wnba_readiness import run_qc as run_wnba_readiness
from qc_cfb_readiness import run_qc as run_cfb_readiness
from services.qc_tracking import append_qc_run_log


OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "Prelaunch_Scorecard.csv"


def _resolved_count(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    df = pd.read_csv(path)
    if df.empty or "OutcomeState" not in df.columns:
        return 0, 0
    outcomes = df["OutcomeState"].fillna("").astype(str)
    resolved = int(outcomes.isin(["Hit", "Miss", "Push"]).sum())
    pending = int(outcomes.eq("Pending").sum())
    return resolved, pending


def _archive_readiness_status() -> tuple[str, str]:
    required_paths = [
        BASE_DIR / "refresh_featured_results.py",
        BASE_DIR / "refresh_nfl_featured_results.py",
        BASE_DIR / "refresh_wnba_featured_results.py",
        BASE_DIR / "refresh_ncaaf_featured_results.py",
        BASE_DIR / "data" / "tracking" / "NBA_FeaturedResults.csv",
        BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv",
    ]
    missing = [path.name for path in required_paths if not path.exists()]
    if missing:
        return "FAIL", f"Missing archive/result artifacts: {', '.join(missing)}"
    return "PASS", "Core featured snapshot and results artifacts exist for active sports."


def _calibration_status() -> tuple[str, str]:
    sports = {
        "NBA": BASE_DIR / "data" / "tracking" / "NBA_FeaturedResults.csv",
        "NFL": BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv",
        "WNBA": BASE_DIR / "data" / "tracking" / "WNBA_FeaturedResults.csv",
        "NCAAF": BASE_DIR / "data" / "tracking" / "NCAAF_FeaturedResults.csv",
    }
    notes = []
    actionable = 0
    for sport, path in sports.items():
        resolved, pending = _resolved_count(path)
        notes.append(f"{sport} {resolved} resolved / {pending} pending")
        if resolved >= 50:
            actionable += 1
    if actionable > 0:
        return "PASS", "; ".join(notes)
    return "WATCH", "Calibration loop is operational but still NOT YET MEANINGFUL on resolved volume. " + "; ".join(notes)


def _visual_trust_status() -> tuple[str, str]:
    return "WATCH", "Manual visual trust review is still required even after route and auth test-drive passes."


def _rollback_status() -> tuple[str, str]:
    doc_path = BASE_DIR / "docs" / "platform_prelaunch_checklist.md"
    if not doc_path.exists():
        return "FAIL", "Prelaunch checklist document is missing."
    text = doc_path.read_text(encoding="utf-8", errors="ignore")
    if "Rollback And Incident Response" not in text:
        return "FAIL", "Rollback section is missing from the prelaunch checklist."
    return "PASS", "Rollback and incident response procedure is documented."


def build_scorecard() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    route_report = run_platform_routes(tier="fast")
    nba_source_report = run_source_audit()
    nba_injury_report = run_nba_injuries()
    nba_contradiction_report = run_nba_contradictions()
    nfl_injury_report = run_nfl_injuries()
    nfl_contradiction_report = run_nfl_contradictions()
    wnba_injury_report = run_wnba_injuries()
    mlb_injury_report = run_mlb_injuries()
    cfb_injury_report = run_cfb_injuries()
    checkout_report = run_checkout_qc()
    wnba_report = run_wnba_readiness()
    cfb_report = run_cfb_readiness()

    sections: list[dict] = []

    sections.append({
        "Section": "Platform Reliability",
        "Status": "PASS" if route_report["failure_count"] == 0 else "FAIL",
        "Reason": f"Fast route smoke failures: {route_report['failure_count']}.",
    })

    sections.append({
        "Section": "Data Freshness And Source Truth",
        "Status": "PASS" if (
            nba_source_report["failure_count"] == 0
            and nba_injury_report["failure_count"] == 0
            and nfl_injury_report["failure_count"] == 0
            and wnba_injury_report["failure_count"] == 0
            and mlb_injury_report["failure_count"] == 0
            and cfb_injury_report["failure_count"] == 0
        ) else "FAIL",
        "Reason": (
            nba_source_report["notes"] + " | Injury feeds: "
            f"NBA f={nba_injury_report['failure_count']}/w={nba_injury_report['warning_count']}, "
            f"NFL f={nfl_injury_report['failure_count']}/w={nfl_injury_report['warning_count']}, "
            f"WNBA f={wnba_injury_report['failure_count']}/w={wnba_injury_report['warning_count']}, "
            f"MLB f={mlb_injury_report['failure_count']}/w={mlb_injury_report['warning_count']}, "
            f"CFB f={cfb_injury_report['failure_count']}/w={cfb_injury_report['warning_count']}"
        ),
    })

    integrity_status = "PASS"
    integrity_reason = (
        f"NBA warnings={nba_contradiction_report['warning_count']}, failures={nba_contradiction_report['failure_count']}; "
        f"NFL warnings={nfl_contradiction_report['warning_count']}, failures={nfl_contradiction_report['failure_count']}."
    )
    if nba_contradiction_report["failure_count"] > 0 or nfl_contradiction_report["failure_count"] > 0:
        integrity_status = "FAIL"
    elif nba_contradiction_report["warning_count"] > 0 or nfl_contradiction_report["warning_count"] > 0:
        integrity_status = "WATCH"
    sections.append({
        "Section": "Suggestion Integrity",
        "Status": integrity_status,
        "Reason": integrity_reason,
    })

    archive_status, archive_reason = _archive_readiness_status()
    sections.append({
        "Section": "Archive And Replay Readiness",
        "Status": archive_status,
        "Reason": archive_reason,
    })

    calibration_status, calibration_reason = _calibration_status()
    sections.append({
        "Section": "Calibration Readiness",
        "Status": calibration_status,
        "Reason": calibration_reason,
    })

    visual_status, visual_reason = _visual_trust_status()
    sections.append({
        "Section": "Visual Trust",
        "Status": visual_status,
        "Reason": visual_reason,
    })

    pricing_status = "PASS"
    pricing_reason = checkout_report["notes"]
    if checkout_report["failure_count"] > 0:
        pricing_status = "FAIL"
    elif checkout_report["warning_count"] > 0:
        pricing_status = "WATCH"
    sections.append({
        "Section": "Pricing And Membership Boundary",
        "Status": pricing_status,
        "Reason": pricing_reason,
    })

    sport_status = "PASS"
    sport_reason = (
        f"WNBA warnings={wnba_report['warning_count']}, failures={wnba_report['failure_count']}; "
        f"CFB warnings={cfb_report['warning_count']}, failures={cfb_report['failure_count']}."
    )
    if wnba_report["failure_count"] > 0 or cfb_report["failure_count"] > 0:
        sport_status = "FAIL"
    elif wnba_report["warning_count"] > 0 or cfb_report["warning_count"] > 0:
        sport_status = "WATCH"
    sections.append({
        "Section": "Sport-Specific Launch Questions",
        "Status": sport_status,
        "Reason": sport_reason,
    })

    rollback_status, rollback_reason = _rollback_status()
    sections.append({
        "Section": "Rollback And Incident Response",
        "Status": rollback_status,
        "Reason": rollback_reason,
    })

    fail_count = sum(1 for row in sections if row["Status"] == "FAIL")
    watch_count = sum(1 for row in sections if row["Status"] == "WATCH")
    go_live = fail_count == 0 and watch_count < 3
    decision = "GO" if go_live else "NO-GO"

    df = pd.DataFrame(sections)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    report = {
        "checked_at": checked_at,
        "clean": fail_count == 0,
        "pass_count": sum(1 for row in sections if row["Status"] == "PASS"),
        "warning_count": watch_count,
        "failure_count": fail_count,
        "notes": f"Prelaunch decision: {decision} | WATCH={watch_count} | FAIL={fail_count}",
        "decision": decision,
        "rows": sections,
        "output_path": str(OUTPUT_PATH),
    }
    append_qc_run_log("prelaunch_scorecard", report)
    return report


def main() -> int:
    report = build_scorecard()
    print("=" * 60)
    print("BANKROLL KINGS PRELAUNCH SCORECARD")
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
    return 0 if report["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
