from __future__ import annotations

from qc_cfb_board import run_qc as run_cfb_qc
from qc_nfl_board import run_qc as run_nfl_qc
from services.qc_tracking import append_qc_run_log


def main() -> int:
    nfl = run_nfl_qc()
    cfb = run_cfb_qc()
    append_qc_run_log("football_summary", {
        "checked_at": nfl.get("checked_at") or cfb.get("checked_at"),
        "failure_count": int(nfl["issue_count"]) + int(cfb["issue_count"]),
        "notes": f"NFL issues={nfl['issue_count']} | CFB issues={cfb['issue_count']}",
    })

    print("=" * 60)
    print("BANKROLL KINGS FOOTBALL QC SUMMARY")
    print("=" * 60)
    print(f"NFL issues: {nfl['issue_count']}")
    print(f"CFB issues: {cfb['issue_count']}")
    print()

    for note in nfl.get("notes", []):
        print(f"[NFL NOTE] {note}")
    for note in cfb.get("notes", []):
        print(f"[CFB NOTE] {note}")
    if nfl.get("notes") or cfb.get("notes"):
        print()

    total_issues = int(nfl["issue_count"]) + int(cfb["issue_count"])
    if total_issues == 0:
        print("No blocking football QC issues detected.")
        return 0

    print("Blocking issues remain in football QC.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
