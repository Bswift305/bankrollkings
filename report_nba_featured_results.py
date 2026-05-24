from __future__ import annotations

from datetime import datetime

import pandas as pd

from app import (
    classify_featured_rule_family,
    load_featured_results_snapshot,
)
from services.qc_tracking import append_qc_run_log


def _bucket_summary(df: pd.DataFrame, column: str) -> list[dict]:
    rows: list[dict] = []
    if df.empty or column not in df.columns:
        return rows
    for label, group in df.groupby(column, dropna=False):
        decisive = group[group["OutcomeState"].isin(["Hit", "Miss"])].copy()
        if decisive.empty:
            hit_rate = None
        else:
            hit_rate = round(float(decisive["OutcomeState"].eq("Hit").mean()) * 100, 1)
        rows.append({
            "label": str(label or "Unknown"),
            "candidates": int(len(group)),
            "resolved": int(len(group[group["OutcomeState"].isin(["Hit", "Miss", "Push"])])),
            "hit_rate": hit_rate,
        })
    return sorted(rows, key=lambda item: ((item["hit_rate"] if item["hit_rate"] is not None else -1), item["candidates"]), reverse=True)


def run_report() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = load_featured_results_snapshot()
    if df is None or df.empty:
        report = {
            "checked_at": checked_at,
            "clean": True,
            "pass_count": 0,
            "warning_count": 0,
            "failure_count": 0,
            "notes": "No featured results snapshot rows available.",
            "totals": {},
            "by_profile": [],
            "by_rule_family": [],
            "by_player_tier": [],
            "by_market_gate": [],
        }
        append_qc_run_log("nba_featured_report", report)
        return report

    working = df.copy()
    working["OutcomeState"] = working.get("OutcomeState", "Pending").fillna("Pending").astype(str)
    working["WeightProfile"] = working.get("WeightProfile", "").fillna("").astype(str).replace("", "regular")
    working["RoleLabel"] = working.get("RoleLabel", "").fillna("").astype(str).replace("", "UNSPECIFIED")
    working["MarketGate"] = working.get("MarketGate", "").fillna("").astype(str).replace("", "CLEAR")
    working["RuleFamily"] = working.get("Situations", "").apply(classify_featured_rule_family)

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
            f"Resolved {totals['resolved']} of {totals['candidates']} featured rows. "
            f"Decisive hit rate: {totals['hit_rate']}."
        ),
        "totals": totals,
        "by_profile": _bucket_summary(working, "WeightProfile"),
        "by_rule_family": _bucket_summary(working, "RuleFamily"),
        "by_player_tier": _bucket_summary(working, "RoleLabel"),
        "by_market_gate": _bucket_summary(working, "MarketGate"),
    }
    append_qc_run_log("nba_featured_report", report)
    return report


def main() -> int:
    report = run_report()
    totals = report.get("totals", {})
    print("=" * 60)
    print("NBA FEATURED RESULTS REPORT")
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
        ("By profile", report.get("by_profile", [])),
        ("By rule family", report.get("by_rule_family", [])),
        ("By player tier", report.get("by_player_tier", [])),
        ("By market gate", report.get("by_market_gate", [])),
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
