from __future__ import annotations

from datetime import datetime

import pandas as pd

from app import load_featured_results_snapshot_for_sport
from services.qc_tracking import append_qc_run_log


def _bucket_summary(df: pd.DataFrame, column: str) -> list[dict]:
    rows: list[dict] = []
    if df.empty or column not in df.columns:
        return rows
    for label, group in df.groupby(column, dropna=False):
        decisive = group[group["OutcomeState"].isin(["Hit", "Miss"])].copy()
        hit_rate = round(float(decisive["OutcomeState"].eq("Hit").mean()) * 100, 1) if not decisive.empty else None
        rows.append({
            "label": str(label or "Unknown"),
            "candidates": int(len(group)),
            "resolved": int(len(group[group["OutcomeState"].isin(["Hit", "Miss", "Push"])])),
            "hit_rate": hit_rate,
        })
    return sorted(rows, key=lambda item: ((item["hit_rate"] if item["hit_rate"] is not None else -1), item["candidates"]), reverse=True)


def run_report() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = load_featured_results_snapshot_for_sport("NFL")
    if df is None or df.empty:
        report = {
            "checked_at": checked_at,
            "clean": True,
            "pass_count": 0,
            "warning_count": 0,
            "failure_count": 0,
            "notes": "No NFL featured results snapshot rows available.",
            "totals": {},
            "by_governance": [],
            "by_stat": [],
            "by_team": [],
            "by_direction": [],
        }
        append_qc_run_log("nfl_featured_report", report)
        return report

    working = df.copy()
    working["OutcomeState"] = working.get("OutcomeState", "Pending").fillna("Pending").astype(str)
    working["GovernanceTier"] = working.get("GovernanceTier", "").fillna("").astype(str).replace("", "UNSPECIFIED")
    working["Stat"] = working.get("Stat", "").fillna("").astype(str).replace("", "UNSPECIFIED")
    working["Team"] = working.get("Team", "").fillna("").astype(str).replace("", "UNSPECIFIED")
    working["Direction"] = working.get("Direction", "").fillna("").astype(str).replace("", "UNSPECIFIED")

    resolved = working[working["OutcomeState"].isin(["Hit", "Miss", "Push"])].copy()
    decisives = resolved[resolved["OutcomeState"].isin(["Hit", "Miss"])].copy()
    totals = {
        "candidates": int(len(working)),
        "resolved": int(len(resolved)),
        "hits": int((working["OutcomeState"] == "Hit").sum()),
        "misses": int((working["OutcomeState"] == "Miss").sum()),
        "pushes": int((working["OutcomeState"] == "Push").sum()),
        "pending": int((working["OutcomeState"] == "Pending").sum()),
        "hit_rate": round(float(decisives["OutcomeState"].eq("Hit").mean()) * 100, 1) if not decisives.empty else None,
    }

    report = {
        "checked_at": checked_at,
        "clean": True,
        "pass_count": int(len(working)),
        "warning_count": 0,
        "failure_count": 0,
        "notes": (
            f"Resolved {totals['resolved']} of {totals['candidates']} NFL featured rows. "
            f"Decisive hit rate: {totals['hit_rate']}."
        ),
        "totals": totals,
        "by_governance": _bucket_summary(working, "GovernanceTier"),
        "by_stat": _bucket_summary(working, "Stat"),
        "by_team": _bucket_summary(working, "Team"),
        "by_direction": _bucket_summary(working, "Direction"),
    }
    append_qc_run_log("nfl_featured_report", report)
    return report


def main() -> int:
    report = run_report()
    totals = report.get("totals", {})
    print("=" * 60)
    print("NFL FEATURED RESULTS REPORT")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Candidates: {totals.get('candidates', 0)}")
    print(f"Resolved: {totals.get('resolved', 0)}")
    print(f"Hits: {totals.get('hits', 0)}")
    print(f"Misses: {totals.get('misses', 0)}")
    print(f"Pushes: {totals.get('pushes', 0)}")
    print(f"Pending: {totals.get('pending', 0)}")
    print(f"Hit rate: {totals.get('hit_rate')}")
    print()
    for section, rows in [
        ("By governance", report.get("by_governance", [])),
        ("By stat", report.get("by_stat", [])),
        ("By team", report.get("by_team", [])),
        ("By direction", report.get("by_direction", [])),
    ]:
        print(section)
        if not rows:
            print("  (no rows)")
            continue
        for row in rows[:10]:
            print(f"  {row['label']}: {row['resolved']} resolved, hit rate {row['hit_rate']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
