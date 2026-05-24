from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from app import BASE_DIR, _load_cached_csv
from services.qc_tracking import append_qc_run_log


INJURIES_DIR = BASE_DIR / "data" / "injuries"


@dataclass(frozen=True)
class InjuryFeedConfig:
    scope: str
    prefix: str
    live_expected: bool
    stale_hours: float
    min_rows: int
    drop_ratio_warn: float = 0.35
    drop_ratio_fail: float = 0.15


SPORT_CONFIG: dict[str, InjuryFeedConfig] = {
    "nba": InjuryFeedConfig(scope="nba_injuries", prefix="NBA", live_expected=True, stale_hours=18.0, min_rows=1),
    "wnba": InjuryFeedConfig(scope="wnba_injuries", prefix="WNBA", live_expected=True, stale_hours=18.0, min_rows=1),
    "nfl": InjuryFeedConfig(scope="nfl_injuries", prefix="NFL", live_expected=True, stale_hours=36.0, min_rows=25),
    "mlb": InjuryFeedConfig(scope="mlb_injuries", prefix="MLB", live_expected=True, stale_hours=24.0, min_rows=25),
    "ncaaf": InjuryFeedConfig(scope="cfb_injuries", prefix="NCAAF", live_expected=False, stale_hours=72.0, min_rows=0),
    "cfb": InjuryFeedConfig(scope="cfb_injuries", prefix="NCAAF", live_expected=False, stale_hours=72.0, min_rows=0),
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return _load_cached_csv(path, default=pd.DataFrame())
    except Exception:
        return pd.DataFrame()


def _active_manual_override_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    working = df.copy()
    for col in ["Player", "Team", "Status", "Reason", "Updated", "Active", "ExpiresOn"]:
        if col not in working.columns:
            working[col] = ""
        working[col] = working[col].fillna("").astype(str).str.strip()
    working = working[working["Player"] != ""].copy()
    if working.empty:
        return working
    now = pd.Timestamp.now()
    updated_dt = pd.to_datetime(working["Updated"], errors="coerce")
    expires_dt = pd.to_datetime(working["ExpiresOn"], errors="coerce")
    active_flag = working["Active"].str.lower().isin({"1", "true", "yes", "y", "active"})
    recent_flag = updated_dt >= (now - pd.Timedelta(days=3))
    unexpired_flag = expires_dt.isna() | (expires_dt >= now.normalize())
    keep_mask = unexpired_flag & (active_flag | recent_flag)
    return working[keep_mask].copy()


def _latest_timestamp(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty or "Updated" not in df.columns:
        return None
    timestamps = pd.to_datetime(df["Updated"], errors="coerce")
    if timestamps.isna().all():
        return None
    return timestamps.max()


def run_injury_feed_qc(sport_key: str, persist: bool = True) -> dict:
    sport_key = str(sport_key or "").strip().lower()
    if sport_key not in SPORT_CONFIG:
        raise ValueError(f"Unsupported sport for injury QC: {sport_key}")

    config = SPORT_CONFIG[sport_key]
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_path = INJURIES_DIR / f"{config.prefix}_Injuries.csv"
    backup_path = INJURIES_DIR / f"{config.prefix}_Injuries_last_good.csv"
    manual_path = INJURIES_DIR / f"{config.prefix}_Injuries_Manual.csv"

    current_df = _read_csv(current_path)
    backup_df = _read_csv(backup_path)
    manual_df = _active_manual_override_rows(_read_csv(manual_path))

    failures: list[str] = []
    warnings: list[str] = []

    current_rows = len(current_df)
    backup_rows = len(backup_df)
    manual_rows = len(manual_df)

    if config.live_expected and not current_path.exists():
        failures.append(f"{config.prefix} injury file is missing: {current_path.name}")

    if config.live_expected and current_rows < config.min_rows:
        failures.append(
            f"{config.prefix} injury feed only has {current_rows} rows; expected at least {config.min_rows}."
        )
    elif not config.live_expected and current_rows == 0:
        warnings.append(f"{config.prefix} injury feed is still manual-only / empty.")

    latest_updated = _latest_timestamp(current_df)
    age_hours = None
    if latest_updated is not None:
        age_hours = round((pd.Timestamp.now() - latest_updated).total_seconds() / 3600.0, 2)
        if age_hours > config.stale_hours:
            failures.append(
                f"{config.prefix} injury feed is stale at {age_hours}h old (threshold {config.stale_hours:.0f}h)."
            )
    elif config.live_expected and current_rows > 0:
        warnings.append(f"{config.prefix} injury feed has rows but no parseable Updated timestamps.")

    if backup_rows > 0 and current_rows > 0:
        drop_ratio = current_rows / max(backup_rows, 1)
        if backup_rows >= max(config.min_rows, 10):
            if drop_ratio <= config.drop_ratio_fail:
                failures.append(
                    f"{config.prefix} injury feed dropped sharply versus last good file ({current_rows} vs {backup_rows})."
                )
            elif drop_ratio <= config.drop_ratio_warn:
                warnings.append(
                    f"{config.prefix} injury feed is materially lighter than last good file ({current_rows} vs {backup_rows})."
                )
    elif backup_rows > 0 and current_rows == 0 and config.live_expected:
        failures.append(
            f"{config.prefix} injury feed collapsed to zero rows after last good file had {backup_rows}."
        )

    if manual_rows > 0:
        warnings.append(f"{config.prefix} has {manual_rows} manual injury override rows active.")

    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": 1 if len(failures) == 0 else 0,
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "route_count": 0,
        "notes": (
            f"Rows: {current_rows} | LastGood: {backup_rows} | Manual: {manual_rows} | "
            f"AgeHours: {age_hours if age_hours is not None else 'n/a'}"
        ),
        "warnings": warnings,
        "failures": failures,
        "row_count": current_rows,
        "backup_row_count": backup_rows,
        "manual_row_count": manual_rows,
        "age_hours": age_hours,
    }
    if persist:
        append_qc_run_log(config.scope, report)
    return report
