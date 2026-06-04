from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.review_center import STREAK_HEAT_INDEX_PATH, build_streak_heat_chart


def main() -> int:
    path = Path(STREAK_HEAT_INDEX_PATH)
    if path.exists():
        path.unlink()
    rows = build_streak_heat_chart(limit=1000)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(path, index=False)

    df = pd.DataFrame(rows)
    hot = df[df.get("current_streak", pd.Series(dtype=float)).fillna(0).astype(float) >= 3] if not df.empty else pd.DataFrame()
    print("=" * 60)
    print("BANKROLL KINGS - STREAK HEAT INDEX")
    print("=" * 60)
    print(f"Rows written: {len(df):,}")
    print(f"3+ hit streak buckets: {len(hot):,}")
    print(f"Output: {path}")
    if not df.empty:
        display_cols = ["player", "sport", "stat", "direction", "current_streak", "heat_score", "total_resolved"]
        print(df[display_cols].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
