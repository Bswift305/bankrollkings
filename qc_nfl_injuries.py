from __future__ import annotations

from services.injury_feed_qc import run_injury_feed_qc


def run_qc(persist: bool = True) -> dict:
    return run_injury_feed_qc("nfl", persist=persist)


def main() -> int:
    report = run_qc()
    print("NFL INJURY FEED QC")
    print(f"Checked at: {report['checked_at']}")
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
