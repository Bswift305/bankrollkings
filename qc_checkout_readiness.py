from __future__ import annotations

from datetime import datetime

from app import get_checkout_configuration_report
from services.qc_tracking import append_qc_run_log


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config = get_checkout_configuration_report()
    warnings: list[str] = []
    failures: list[str] = []

    if config.get("mode") == "partial":
        failures.append(config.get("summary", "Stripe is only partially configured."))
    elif not config.get("all_live"):
        warnings.append(config.get("summary", "Demo membership flow is active."))

    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": int(config.get("configured_count", 0) or 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "notes": config.get("summary", ""),
        "warnings": warnings,
        "failures": failures,
        "configured_count": int(config.get("configured_count", 0) or 0),
        "production_count": int(config.get("production_count", 0) or 0),
        "test_count": int(config.get("test_count", 0) or 0),
        "required_count": int(config.get("required_count", 0) or 0),
        "mode": config.get("mode", "demo"),
        "entries": config.get("entries", []),
    }
    append_qc_run_log("checkout_readiness", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("CHECKOUT READINESS")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Mode: {report['mode']}")
    print(f"Configured URLs: {report['configured_count']}/{report['required_count']}")
    print(f"Production-ready URLs: {report['production_count']}/{report['required_count']}")
    print(f"Test-mode URLs: {report['test_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(report["notes"])
    print()
    test_entries = [
        item for item in report.get("entries", [])
        if str(item.get("stripe_mode", "")).lower() == "test"
    ]
    if test_entries:
        print("Test-mode checkout URLs still configured:")
        for item in test_entries:
            print(f"- {item.get('env_key')} ({item.get('plan')} {item.get('billing_cycle')})")
        print()
    for item in report["warnings"]:
        print(f"[WARN] {item}")
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
