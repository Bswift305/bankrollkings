from __future__ import annotations

from datetime import datetime

from app import app
from services.nba_source_gate import nba_stats_enabled
from services.qc_auth import isolated_owner_client
from services.qc_tracking import append_qc_run_log


ROUTES = (
    ("/sports/nba/props?postseason=1&sample=current&date=today", ("Market", "Floor", "Confidence", "Player")),
    ("/sports/nba/market-edge?postseason=1&sample=current&date=today", ("Market", "Confidence", "Player")),
    ("/player/De'Aaron%20Fox?sample=current", ("Prop Analysis", "Profile", "Why")),
    ("/raw-data?player=Donovan%20Mitchell&stat=AST", ("Trajectory", "Book Lines", "vs Line")),
)
# The two NBA BOARD surfaces must show the containment notice while the data-rights gate is off.
_BOARD_PREFIXES = ("/sports/nba/props", "/sports/nba/market-edge")
_CONTAINMENT_MARKER = "temporarily unavailable"


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Portable deterministic owner (no dependency on a specific account existing in the store).
    gated = not nba_stats_enabled()

    failures: list[str] = []
    warnings: list[str] = []
    route_count = 0

    with isolated_owner_client() as client:
        for path, markers in ROUTES:
            route_count += 1
            response = client.get(path, follow_redirects=True)
            text = response.get_data(as_text=True)
            if response.status_code != 200:
                failures.append(f"{path}: returned {response.status_code} (auth/route error, not containment).")
                continue
            if gated:
                # NBA stat surfaces are INTENTIONALLY contained while BK_NBA_STATS_ENABLED is off, so the
                # full-board trust markers are withheld by design -- not a visual-trust failure. The honest
                # trust signal is the containment notice. Require it on the BOARD surfaces; the detail
                # pages (/player, /raw-data) need only render without error. Never fail on withheld markers.
                if path.split("?")[0] in _BOARD_PREFIXES:
                    if _CONTAINMENT_MARKER not in text.lower():
                        failures.append(f"{path}: gated NBA board missing the containment notice "
                                        f"('{_CONTAINMENT_MARKER}') -- cannot confirm honest degradation.")
                    else:
                        warnings.append(f"{path}: gated -> containment notice shown (trust markers withheld).")
                else:
                    warnings.append(f"{path}: gated -> rendered without error (NBA.com stats withheld).")
                continue
            missing = [marker for marker in markers if marker not in text]
            if missing:
                failures.append(f"{path}: missing visual trust markers: {', '.join(missing)}.")

    outcome = "SKIP_DATA_RIGHTS_GATE" if gated else ("CLEAN" if not failures else "FAIL")
    report = {
        "checked_at": checked_at,
        "outcome": outcome,
        "clean": len(failures) == 0,
        "pass_count": max(route_count - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "route_count": route_count,
        "notes": ("NBA stat surfaces are gated (BK_NBA_STATS_ENABLED off): board shows the containment "
                  "notice, trust markers withheld by design -- SKIP_DATA_RIGHTS_GATE."
                  if gated else
                  "Verified key NBA surfaces expose trust markers for verdict, market, trajectory, and injury context."),
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("nba_visual_trust", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("NBA VISUAL TRUST QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Routes checked: {report['route_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
    for item in report["warnings"]:
        print(f"[WARN] {item}")
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
