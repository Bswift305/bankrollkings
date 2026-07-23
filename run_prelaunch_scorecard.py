from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

# Each section runs in its own process. Running all twelve in one interpreter
# accumulated every sport's boards, gamelogs and caches at once and peaked around
# 850 MB RSS -- above earlyoom's threshold on this box, which SIGTERM'd the run
# before it printed a single line. The suite then read "no output" as a crash and
# reported FAIL, so prelaunch verification was silently dead while the code was
# fine. Per-section processes cap peak memory at the largest single section and
# reclaim it in between.
SECTION_RUNNERS = {
    "platform_routes": lambda: run_platform_routes(tier="fast"),
    "source_audit": run_source_audit,
    "nba_injuries": run_nba_injuries,
    "nba_contradictions": run_nba_contradictions,
    "nfl_injuries": run_nfl_injuries,
    "nfl_contradictions": run_nfl_contradictions,
    "wnba_injuries": run_wnba_injuries,
    "mlb_injuries": run_mlb_injuries,
    "cfb_injuries": run_cfb_injuries,
    "checkout_qc": run_checkout_qc,
    "wnba_readiness": run_wnba_readiness,
    "cfb_readiness": run_cfb_readiness,
}

SECTION_TIMEOUT_SECONDS = 420


def _incomplete_report(key: str, reason: str) -> dict:
    """Stand-in for a section that could not run.

    Deliberately NOT zero-filled. A section that did not execute is unverified,
    not passing -- zeros would read as a clean result and hide exactly the
    failure this split exists to fix. `_incomplete` is surfaced as its own FAIL
    row in the scorecard.
    """
    return {
        "failure_count": 0,
        "warning_count": 0,
        "notes": f"{key} did not complete: {reason}",
        "failures": [],
        "warnings": [],
        "clean": False,
        "_incomplete": True,
        "_reason": reason,
    }


def _run_section_in_subprocess(key: str) -> dict:
    """Run one section in a fresh interpreter and return its report dict."""
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--section", key],
            capture_output=True,
            text=True,
            timeout=SECTION_TIMEOUT_SECONDS,
            cwd=str(BASE_DIR),
        )
    except subprocess.TimeoutExpired:
        return _incomplete_report(key, f"timed out after {SECTION_TIMEOUT_SECONDS}s")
    except Exception as exc:                                  # pragma: no cover
        return _incomplete_report(key, f"could not start ({type(exc).__name__})")

    if proc.returncode == -15 or proc.returncode == 143:
        # SIGTERM. On this box that is earlyoom reclaiming memory, not a code bug.
        return _incomplete_report(key, "killed by SIGTERM (out-of-memory reaper)")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return _incomplete_report(key, f"exit {proc.returncode}: {tail[-1][:120] if tail else 'no stderr'}")

    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return _incomplete_report(key, "no JSON payload on stdout")


def _collect_sections() -> dict:
    return {key: _run_section_in_subprocess(key) for key in SECTION_RUNNERS}


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


def _active_sports() -> set:
    """Sports that currently have live data.

    Off-season sports (no props loaded) are treated as N/A by the launch gate
    instead of hard FAILs, so an in-season launch (NBA/MLB/WNBA) can certify GO.
    Each off-season check reactivates automatically when that sport's props return.
    """
    mapping = {
        "NBA": "NBA_Props.csv",
        "WNBA": "WNBA_Props.csv",
        "MLB": "MLB_Props.csv",
        "NFL": "NFL_Props.csv",
        "NCAAF": "NCAAF_Props.csv",
    }
    active = set()
    for sport, fname in mapping.items():
        path = BASE_DIR / "data" / "props" / fname
        try:
            if path.exists() and not pd.read_csv(path).empty:
                active.add(sport)
        except Exception:
            pass
    return active


def _route_sport(path: str):
    """Map a route path to its sport, or None for general/cross-sport routes."""
    p = str(path or "").lower()
    for seg, sport in (
        ("/ncaaf", "NCAAF"), ("/nfl", "NFL"), ("/wnba", "WNBA"), ("/mlb", "MLB"),
        ("/ncaamb", "NCAAMB"), ("/ncaawb", "NCAAWB"), ("/nba", "NBA"),
    ):
        if seg in p:
            return sport
    return None


def _archive_readiness_status(active: set) -> tuple[str, str]:
    required_paths = [
        BASE_DIR / "refresh_featured_results.py",
        BASE_DIR / "refresh_nfl_featured_results.py",
        BASE_DIR / "refresh_wnba_featured_results.py",
        BASE_DIR / "refresh_ncaaf_featured_results.py",
    ]
    featured_results = {
        "NBA": BASE_DIR / "data" / "tracking" / "NBA_FeaturedResults.csv",
        "NFL": BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv",
        "WNBA": BASE_DIR / "data" / "tracking" / "WNBA_FeaturedResults.csv",
        "NCAAF": BASE_DIR / "data" / "tracking" / "NCAAF_FeaturedResults.csv",
    }
    for sport, path in featured_results.items():
        if sport in active:
            required_paths.append(path)
    missing = [path.name for path in required_paths if not path.exists()]
    if missing:
        return "FAIL", f"Missing archive/result artifacts: {', '.join(missing)}"
    return "PASS", "Featured snapshot and results artifacts exist for all in-season sports."


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

    collected = _collect_sections()
    route_report = collected["platform_routes"]
    nba_source_report = collected["source_audit"]
    nba_injury_report = collected["nba_injuries"]
    nba_contradiction_report = collected["nba_contradictions"]
    nfl_injury_report = collected["nfl_injuries"]
    nfl_contradiction_report = collected["nfl_contradictions"]
    wnba_injury_report = collected["wnba_injuries"]
    mlb_injury_report = collected["mlb_injuries"]
    cfb_injury_report = collected["cfb_injuries"]
    checkout_report = collected["checkout_qc"]
    wnba_report = collected["wnba_readiness"]
    cfb_report = collected["cfb_readiness"]

    # Some downstream sections read keys the QC modules always provide but an
    # incomplete stand-in may not; keep access total so one dead section cannot
    # take down the whole report.
    for _key, _rep in collected.items():
        _rep.setdefault("failure_count", 0)
        _rep.setdefault("warning_count", 0)
        _rep.setdefault("notes", "")
        _rep.setdefault("failures", [])

    sections: list[dict] = []
    active = _active_sports()

    offseason_route_fails = [
        f for f in route_report.get("failures", [])
        if _route_sport(f.get("path", "")) is not None and _route_sport(f.get("path", "")) not in active
    ]
    inseason_route_fail_count = max(route_report["failure_count"] - len(offseason_route_fails), 0)
    sections.append({
        "Section": "Platform Reliability",
        "Status": "PASS" if inseason_route_fail_count == 0 else "FAIL",
        "Reason": f"Fast route smoke failures (in-season): {inseason_route_fail_count}; off-season skipped: {len(offseason_route_fails)}.",
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
    # A contradiction check that evaluated zero plays did not verify integrity --
    # its zero failure count is vacuous. Only count it as a clean PASS when it
    # actually had plays to check; otherwise WATCH.
    both_unverified = bool(nba_contradiction_report.get("unverified")) and bool(nfl_contradiction_report.get("unverified"))
    if nba_contradiction_report["failure_count"] > 0 or nfl_contradiction_report["failure_count"] > 0:
        integrity_status = "FAIL"
    elif nba_contradiction_report["warning_count"] > 0 or nfl_contradiction_report["warning_count"] > 0:
        integrity_status = "WATCH"
    elif both_unverified:
        integrity_status = "WATCH"
        integrity_reason += " Both sports evaluated 0 plays (offseason) -- integrity is UNVERIFIED, not clean."
    sections.append({
        "Section": "Suggestion Integrity",
        "Status": integrity_status,
        "Reason": integrity_reason,
    })

    archive_status, archive_reason = _archive_readiness_status(active)
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

    wnba_fail = wnba_report["failure_count"] if "WNBA" in active else 0
    wnba_warn = wnba_report["warning_count"] if "WNBA" in active else 0
    cfb_fail = cfb_report["failure_count"] if "NCAAF" in active else 0
    cfb_warn = cfb_report["warning_count"] if "NCAAF" in active else 0
    sport_status = "PASS"
    sport_reason = (
        f"WNBA warnings={wnba_warn}, failures={wnba_fail}; "
        f"CFB warnings={cfb_warn}, failures={cfb_fail}"
        + ("" if "NCAAF" in active else " (CFB off-season: N/A)")
    )
    if wnba_fail > 0 or cfb_fail > 0:
        sport_status = "FAIL"
    elif wnba_warn > 0 or cfb_warn > 0:
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

    # A section that could not run is unverified, which is not the same as clean.
    # Report it explicitly so a dead section can never be mistaken for a pass.
    incomplete = [key for key, rep in collected.items() if rep.get("_incomplete")]
    if incomplete:
        sections.append({
            "Section": "Scorecard Completeness",
            "Status": "FAIL",
            "Reason": (
                f"{len(incomplete)} of {len(collected)} section(s) did not run: "
                + "; ".join(f"{k} ({collected[k].get('_reason', 'unknown')})" for k in incomplete)
            ),
        })
    else:
        sections.append({
            "Section": "Scorecard Completeness",
            "Status": "PASS",
            "Reason": f"All {len(collected)} sections ran in isolated processes.",
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


def _run_single_section(key: str) -> int:
    """Child-process entry point: run one section, print its report as JSON.

    Printed as a single JSON line on stdout so the parent can pick it out of any
    incidental logging the QC modules emit. default=str keeps numpy/pandas
    scalars from breaking serialisation.
    """
    runner = SECTION_RUNNERS.get(key)
    if runner is None:
        print(f"unknown section: {key}", file=sys.stderr)
        return 2
    report = runner()
    print(json.dumps(report, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bankroll Kings prelaunch scorecard.")
    parser.add_argument("--section", choices=sorted(SECTION_RUNNERS), default=None,
                        help="Run a single section and emit its report as JSON (used internally "
                             "to keep each section in its own process).")
    args = parser.parse_args()
    if args.section:
        return _run_single_section(args.section)

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
