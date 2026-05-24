from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import load_nfl_floor_board, load_nfl_gamelogs
from services.qc_tracking import append_qc_run_log


BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv"

NFL_STAT_COLUMN_MAP = {
    "Pass Yds": "PassYds",
    "Pass TDs": "PassTD",
    "Rush Yds": "RushYds",
    "Rec Yds": "RecYds",
    "Receptions": "Receptions",
}


def _load_existing() -> pd.DataFrame:
    if RESULTS_PATH.exists():
        return pd.read_csv(RESULTS_PATH)
    return pd.DataFrame()


def _replace(df: pd.DataFrame) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_PATH, index=False)


def _grade_rows(df: pd.DataFrame, gamelogs: pd.DataFrame) -> pd.DataFrame:
    if df.empty or gamelogs is None or gamelogs.empty or "Player" not in gamelogs.columns or "Date" not in gamelogs.columns:
        return df
    logs = gamelogs.copy()
    logs["Date"] = pd.to_datetime(logs["Date"], errors="coerce")
    for idx, row in df.iterrows():
        stat = str(row.get("Stat", "")).strip()
        stat_col = NFL_STAT_COLUMN_MAP.get(stat)
        if not stat_col or stat_col not in logs.columns:
            continue
        player = str(row.get("Player", "")).strip()
        team = str(row.get("Team", "")).strip().upper()
        snapshot_date = pd.to_datetime(row.get("SnapshotDate"), errors="coerce")
        line = pd.to_numeric(row.get("Line"), errors="coerce")
        if not player or pd.isna(snapshot_date) or pd.isna(line):
            continue

        player_logs = logs[logs["Player"].astype(str) == player].copy()
        if team and "Team" in player_logs.columns:
            team_logs = player_logs[player_logs["Team"].astype(str).str.upper() == team].copy()
            if not team_logs.empty:
                player_logs = team_logs
        next_logs = player_logs[player_logs["Date"] > snapshot_date].sort_values("Date", ascending=True)
        if next_logs.empty:
            continue
        next_game = next_logs.iloc[0]
        value = pd.to_numeric(next_game.get(stat_col), errors="coerce")
        if pd.isna(value):
            continue

        state = "Hit" if float(value) > float(line) else "Miss" if float(value) < float(line) else "Push"
        df.at[idx, "ResultDate"] = next_game["Date"].strftime("%Y-%m-%d") if pd.notna(next_game["Date"]) else ""
        df.at[idx, "ResultValue"] = round(float(value), 1)
        df.at[idx, "DaysToResult"] = int((next_game["Date"] - snapshot_date).days) if pd.notna(next_game["Date"]) else None
        df.at[idx, "OutcomeState"] = state
    return df


def main() -> int:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    board = load_nfl_floor_board()
    plays = list(board.get("top_plays", []) or [])
    snapshot_date = datetime.now().date().isoformat()

    rows = []
    for play in plays:
        rows.append({
            "SnapshotDate": snapshot_date,
            "SavedAt": checked_at,
            "Player": play.get("player"),
            "Team": play.get("team"),
            "Stat": play.get("stat"),
            "Direction": "OVER",
            "Line": play.get("line"),
            "Floor": play.get("floor"),
            "Avg": play.get("avg"),
            "HitPct": play.get("hit_pct"),
            "Streak": play.get("streak"),
            "GovernanceTier": play.get("governance_tier"),
            "GovernanceBadge": play.get("governance_badge"),
            "GovernanceResolved": play.get("governance_resolved"),
            "GovernanceHitRate": play.get("governance_hit_rate"),
            "TrustScore": play.get("trust_score"),
            "TrustVerdict": play.get("trust_verdict"),
            "ResultDate": "",
            "ResultValue": None,
            "DaysToResult": None,
            "OutcomeState": "Pending",
            "SnapshotWrittenAt": checked_at,
        })

    existing = _load_existing()
    entry = pd.DataFrame(rows)
    updated = entry if existing.empty else pd.concat([existing, entry], ignore_index=True)
    if not updated.empty:
        dedupe_cols = ["SnapshotDate", "Player", "Team", "Stat", "Line"]
        updated = updated.drop_duplicates(subset=dedupe_cols, keep="last").copy()
        updated = _grade_rows(updated, load_nfl_gamelogs())
        updated = updated.sort_values(["SnapshotDate", "TrustScore"], ascending=[False, False], na_position="last")
    _replace(updated)

    resolved = updated[updated["OutcomeState"].isin(["Hit", "Miss", "Push"])].copy() if not updated.empty else pd.DataFrame()
    report = {
        "checked_at": checked_at,
        "clean": True,
        "pass_count": int(len(updated)),
        "warning_count": 0,
        "failure_count": 0,
        "featured_prop_count": int(len(plays)),
        "notes": f"Wrote {len(rows)} NFL featured rows. Resolved {len(resolved)} rows.",
    }
    append_qc_run_log("nfl_featured_results", report)

    print("=" * 60)
    print("NFL FEATURED RESULTS SNAPSHOT")
    print("=" * 60)
    print(f"Checked at: {checked_at}")
    print(f"Rows written: {len(rows)}")
    print(f"Stored rows: {len(updated)}")
    print(f"Resolved rows: {len(resolved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
