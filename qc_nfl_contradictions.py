from __future__ import annotations

from datetime import datetime

from app import load_nfl_floor_board
from services.nfl_contradiction_qc import audit_plays
from services.qc_tracking import (
    append_qc_run_log,
    build_warning_history_map,
    update_warning_history,
)


def build_runtime() -> dict:
    board = load_nfl_floor_board()
    plays = list(board.get("top_plays", []) or [])
    for play in plays:
        play["_is_featured"] = True
    return {
        "plays": plays,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "board_available": bool(board.get("available")),
        "source_file": board.get("source_file", ""),
        "warning_history_map": build_warning_history_map("nfl_contradictions"),
    }


def run_qc() -> dict:
    runtime = build_runtime()
    audit = audit_plays(runtime["plays"], runtime=runtime)
    report = {
        "checked_at": runtime["checked_at"],
        "clean": audit["clean"],
        "pass_count": audit["pass_count"],
        "warning_count": audit["warning_count"],
        "failure_count": audit["failure_count"],
        "featured_prop_count": len(runtime["plays"]),
        "notes": f"Board available: {runtime['board_available']} | Source: {runtime['source_file']}",
        "warnings": audit["warnings"],
        "failures": audit["failures"],
    }
    update_warning_history("nfl_contradictions", report["warnings"], report["failures"], report["checked_at"])
    append_qc_run_log("nfl_contradictions", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("NFL CONTRADICTION QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Featured plays: {report['featured_prop_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
    print()
    for item in report["failures"]:
        print(f"[FAIL] {item.player} | {item.stat} | {item.rule} | {item.message}")
    for item in report["warnings"]:
        print(f"[WARN] {item.player} | {item.stat} | {item.rule} | {item.message}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
