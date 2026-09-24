from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app import build_nfl_spots_context
from services.qc_tracking import append_qc_run_log

# Resolve against real nflverse weekly actuals (the reliable path the weekly grader
# uses) instead of the static 2023-25 gamelogs, which lack the current fall season and
# whose column names ('PassYd') never matched the old map ('PassYds'). This is what
# makes the 99 scorecard's LIVE-resolved count actually move in-season.
from grade_nfl_week import _season_df, STAT_COL

BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "data" / "tracking" / "NFL_FeaturedResults.csv"

# Featured = the validated PropScore tier. >=20 is "premium".
FEATURED_MIN_SCORE = 20.0

RESULT_COLUMNS = [
    "SnapshotDate", "SavedAt", "Player", "Team", "Stat", "Direction", "Line",
    "Floor", "Avg", "HitPct", "Streak", "GovernanceTier", "GovernanceBadge",
    "GovernanceResolved", "GovernanceHitRate", "TrustScore", "TrustVerdict",
    "ResultDate", "ResultValue", "DaysToResult", "OutcomeState", "SnapshotWrittenAt",
]


def _current_week(d):
    try:
        from nfl_early_season_gate import current_week
        return current_week(d)
    except Exception:
        return None


def _load_existing() -> pd.DataFrame:
    if RESULTS_PATH.exists():
        try:
            return pd.read_csv(RESULTS_PATH)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    return pd.DataFrame()


def _replace(df: pd.DataFrame) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        df = pd.DataFrame(columns=RESULT_COLUMNS)
    df.to_csv(RESULTS_PATH, index=False)


def _grade_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Resolve Pending rows against nflverse weekly actuals. A play snapshotted in the
    week of its game resolves against that week's box score (Hit/Miss/Push, honoring
    Direction). Dedupe-safe: already-resolved rows are left alone."""
    if df.empty:
        return df
    seasons: dict[int, pd.DataFrame] = {}
    for idx, row in df.iterrows():
        if str(row.get("OutcomeState", "")) in ("Hit", "Miss", "Push"):
            continue
        stat = str(row.get("Stat", "")).strip()
        col = STAT_COL.get(stat)
        snap = pd.to_datetime(row.get("SnapshotDate"), errors="coerce")
        line = pd.to_numeric(row.get("Line"), errors="coerce")
        player = str(row.get("Player", "")).strip()
        direction = str(row.get("Direction", "OVER")).strip().upper()
        if not col or not player or pd.isna(snap) or pd.isna(line):
            continue
        wk = _current_week(snap.date())
        if wk is None:
            continue
        season = snap.year if snap.month >= 3 else snap.year - 1
        if season not in seasons:
            try:
                seasons[season] = _season_df(season)
            except Exception:
                seasons[season] = None
        sdf = seasons[season]
        if sdf is None or col not in sdf.columns:
            continue
        m = sdf[(sdf["week"] == wk) &
                (sdf["player_display_name"].astype(str).str.lower() == player.lower())]
        if m.empty:
            continue
        val = pd.to_numeric(m.iloc[0][col], errors="coerce")
        if pd.isna(val):
            continue
        if float(val) == float(line):
            state = "Push"
        else:
            over = float(val) > float(line)
            state = "Hit" if (over if direction == "OVER" else not over) else "Miss"
        df.at[idx, "ResultValue"] = round(float(val), 1)
        df.at[idx, "ResultDate"] = f"{season} wk{wk}"
        df.at[idx, "OutcomeState"] = state
    return df


def main() -> int:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot_date = datetime.now().date().isoformat()

    plays = [p for p in (build_nfl_spots_context(limit=500).get("sp_top") or [])
             if (p.get("prop_score") or 0) >= FEATURED_MIN_SCORE]

    rows = []
    for p in plays:
        rows.append({
            "SnapshotDate": snapshot_date, "SavedAt": checked_at,
            "Player": p.get("player"), "Team": p.get("team"),
            "Stat": p.get("stat"), "Direction": str(p.get("direction") or "OVER").upper(),
            "Line": p.get("line"), "Floor": None, "Avg": None, "HitPct": None, "Streak": None,
            "GovernanceTier": None, "GovernanceBadge": None, "GovernanceResolved": None,
            "GovernanceHitRate": None, "TrustScore": p.get("prop_score"),
            "TrustVerdict": p.get("detail"), "ResultDate": "", "ResultValue": None,
            "DaysToResult": None, "OutcomeState": "Pending", "SnapshotWrittenAt": checked_at,
        })

    existing = _load_existing()
    # Drop stale pre-current-season Pending cruft so the archive stays clean.
    if not existing.empty and "SnapshotDate" in existing.columns:
        cutoff = pd.Timestamp(datetime.now().year if datetime.now().month >= 3 else datetime.now().year - 1, 8, 1)
        sd = pd.to_datetime(existing["SnapshotDate"], errors="coerce")
        keep_resolved = existing["OutcomeState"].isin(["Hit", "Miss", "Push"]) if "OutcomeState" in existing else False
        existing = existing[(sd >= cutoff) | keep_resolved].copy()

    entry = pd.DataFrame(rows)
    updated = entry if existing.empty else pd.concat([existing, entry], ignore_index=True)
    if not updated.empty:
        updated = updated.drop_duplicates(subset=["SnapshotDate", "Player", "Team", "Stat", "Line"], keep="last").copy()
        updated = _grade_rows(updated)
        updated = updated.sort_values(["SnapshotDate", "TrustScore"], ascending=[False, False], na_position="last")
    _replace(updated)

    resolved = updated[updated["OutcomeState"].isin(["Hit", "Miss", "Push"])] if not updated.empty else pd.DataFrame()
    report = {
        "checked_at": checked_at, "clean": True, "pass_count": int(len(updated)),
        "warning_count": 0, "failure_count": 0, "featured_prop_count": int(len(plays)),
        "notes": f"Wrote {len(rows)} NFL featured rows. Resolved {len(resolved)} rows.",
    }
    append_qc_run_log("nfl_featured_results", report)

    print("=" * 60)
    print("NFL FEATURED RESULTS SNAPSHOT")
    print("=" * 60)
    print(f"Checked at: {checked_at}")
    print(f"Rows written: {len(rows)} | Stored: {len(updated)} | Resolved: {len(resolved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
