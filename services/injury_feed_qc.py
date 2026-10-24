from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app import BASE_DIR, _load_cached_csv
from services.qc_tracking import append_qc_run_log

try:
    from zoneinfo import ZoneInfo
    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _EASTERN = None


INJURIES_DIR = BASE_DIR / "data" / "injuries"
_SCHED_DIR = BASE_DIR / "data" / "schedules"
_ODDS_DIR = BASE_DIR / "data" / "odds"
_DATE_COLS = ("Date", "CommenceDate", "GameDate", "commence_time", "CommenceTime")


def _events_expected(prefix: str, days_back: int = 1, days_fwd: int = 3):
    """Independent of the injury feed: are there games in the schedule/game-lines manifest within the
    injury-relevant window [today-days_back, today+days_fwd] (Eastern)? Returns (expected, detail).
    SAFE DEFAULT: when no manifest is readable we return expected=True, so a missing schedule never
    masks a real in-season injury-feed failure. Only a readable manifest with ZERO in-window games
    returns expected=False (-> injuries are NO_ACTIVE_EVENTS, not a board failure)."""
    today = (datetime.now(_EASTERN) if _EASTERN else datetime.now()).date()
    lo, hi = today - timedelta(days=days_back), today + timedelta(days=days_fwd)
    for p in (_SCHED_DIR / f"{prefix}_Schedule.csv", _SCHED_DIR / f"{prefix}_Odds.csv",
              _ODDS_DIR / f"{prefix}_Odds.csv"):
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        col = next((c for c in _DATE_COLS if c in df.columns), None)
        if col is None:
            return True, f"schedule {p.name} has no date column -> assume games expected (safe default)"
        dates = pd.to_datetime(df[col], errors="coerce").dropna()
        if dates.empty:
            return True, f"schedule {p.name} dates unparseable -> assume games expected (safe default)"
        in_window = int(((dates.dt.date >= lo) & (dates.dt.date <= hi)).sum())
        return (in_window > 0), f"{in_window} game(s) in [{lo}..{hi}] per {p.name}"
    return True, "no schedule/game-lines manifest readable -> assume games expected (safe default)"


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

    # DATA-RIGHTS GATE (legal register rows 7 NBA / 15 WNBA): while BK_NBA_STATS_ENABLED is OFF, NBA and
    # WNBA injury ingestion is INTENTIONALLY disabled (fetch_injuries.py:401 / fetch_sport_injuries.py
    # skip when gated; the NBA.com header-spoof was removed outright). A stale file is therefore EXPECTED
    # -- not an authorized feed malfunctioning. Classify SKIP_DATA_RIGHTS_GATE: not reported fresh, and
    # NOT a readiness failure. The last artifact is preserved and stays UNEXPOSED (app returns an empty
    # injury lookup when gated; the board shows the containment notice). This never lifts the gate, never
    # bypasses a provider restriction, and never relaxes a freshness threshold.
    if sport_key in ("nba", "wnba"):
        try:
            from services.nba_source_gate import nba_stats_enabled
            gated_off = not nba_stats_enabled()
        except Exception:
            gated_off = (os.environ.get("BK_NBA_STATS_ENABLED", "") or "").strip().lower() not in ("1", "true", "yes", "on")
        if gated_off:
            age_hours = None
            if current_path.exists():
                age_hours = round((datetime.now() - datetime.fromtimestamp(current_path.stat().st_mtime)).total_seconds() / 3600.0, 2)
            report = {
                "outcome": "SKIP_DATA_RIGHTS_GATE",
                "events_expected": False,
                "events_detail": "BK_NBA_STATS_ENABLED off; ingestion intentionally disabled (legal register)",
                "checked_at": checked_at,
                "clean": True,
                "pass_count": 1,
                "warning_count": 1,
                "failure_count": 0,
                "route_count": 0,
                "notes": (f"SKIP - DATA_RIGHTS_GATE: {config.prefix} injury ingestion is gated OFF "
                          f"(BK_NBA_STATS_ENABLED). Last artifact preserved, not exposed. "
                          f"File AgeHours: {age_hours if age_hours is not None else 'n/a'}."),
                "warnings": [f"{config.prefix} injury feed intentionally not ingested while the data-rights "
                             "gate is off (expected; substitute requires a licensed feed -- do not re-enable "
                             "the NBA.com scrape)."],
                "failures": [],
                "row_count": 0,
                "backup_row_count": 0,
                "manual_row_count": 0,
                "age_hours": age_hours,
            }
            if persist:
                append_qc_run_log(config.scope, report)
            return report

    current_df = _read_csv(current_path)
    backup_df = _read_csv(backup_path)
    manual_df = _active_manual_override_rows(_read_csv(manual_path))

    failures: list[str] = []
    warnings: list[str] = []

    current_rows = len(current_df)
    backup_rows = len(backup_df)
    manual_rows = len(manual_df)

    # Are injury updates reasonably expected right now? Decided from the INDEPENDENT schedule/game-lines
    # manifest, not the injury feed itself. When a sport has no games in the window (offseason / between
    # slates / season wound down -- e.g. WNBA in late October), a stale/absent injury feed is
    # NO_ACTIVE_EVENTS, surfaced HONESTLY as a WATCH, never a board failure -- we do not manufacture
    # freshness, and we do not fail the board for data that is not expected. In-season (games present)
    # every existing failure condition is unchanged, so a genuinely broken live feed still fails.
    live = config.live_expected
    events_expected, events_detail = _events_expected(config.prefix) if live else (False, "feed is manual-only")
    reasons: list[str] = []  # structured outcome contributors

    def _flag(msg: str, reason: str) -> None:
        """Route an injury-feed concern to a board FAILURE when games are expected, else to a WATCH."""
        reasons.append(reason)
        (failures if events_expected else warnings).append(
            msg if events_expected else f"{msg} [NO_ACTIVE_EVENTS: {events_detail}; not board-failing]"
        )

    if live and not current_path.exists():
        _flag(f"{config.prefix} injury file is missing: {current_path.name}", "UNAVAILABLE")

    if live and current_rows < config.min_rows:
        _flag(f"{config.prefix} injury feed only has {current_rows} rows; expected at least {config.min_rows}.",
              "TOO_FEW_ROWS")
    elif not live and current_rows == 0:
        warnings.append(f"{config.prefix} injury feed is still manual-only / empty.")

    latest_updated = _latest_timestamp(current_df)
    age_hours = None
    if latest_updated is not None:
        age_hours = round((pd.Timestamp.now() - latest_updated).total_seconds() / 3600.0, 2)
        if age_hours > config.stale_hours:
            file_age_hours = None
            if current_path.exists():
                file_age_hours = round((datetime.now() - datetime.fromtimestamp(current_path.stat().st_mtime)).total_seconds() / 3600.0, 2)
            if file_age_hours is not None and file_age_hours <= 4:
                warnings.append(
                    f"{config.prefix} injury feed source timestamp is stale at {age_hours}h old, but the local fetch ran {file_age_hours}h ago and preserved last-good rows."
                )
            else:
                _flag(f"{config.prefix} injury feed is stale at {age_hours}h old (threshold {config.stale_hours:.0f}h).",
                      "STALE")
    elif live and current_rows > 0:
        warnings.append(f"{config.prefix} injury feed has rows but no parseable Updated timestamps.")

    if backup_rows > 0 and current_rows > 0:
        drop_ratio = current_rows / max(backup_rows, 1)
        if backup_rows >= max(config.min_rows, 10):
            if drop_ratio <= config.drop_ratio_fail:
                _flag(f"{config.prefix} injury feed dropped sharply versus last good file ({current_rows} vs {backup_rows}).",
                      "SHARP_DROP")
            elif drop_ratio <= config.drop_ratio_warn:
                warnings.append(
                    f"{config.prefix} injury feed is materially lighter than last good file ({current_rows} vs {backup_rows})."
                )
    elif backup_rows > 0 and current_rows == 0 and live:
        _flag(f"{config.prefix} injury feed collapsed to zero rows after last good file had {backup_rows}.",
              "COLLAPSED_TO_ZERO")

    if manual_rows > 0:
        warnings.append(f"{config.prefix} has {manual_rows} manual injury override rows active.")

    # Explicit outcome for the structured record / scorecard surface.
    if not live:
        outcome = "SOURCE_NOT_SCHEDULED"
    elif not events_expected:
        outcome = "NO_ACTIVE_EVENTS"
    elif failures:
        outcome = ("UNAVAILABLE" if "UNAVAILABLE" in reasons
                   else "VALIDATION_FAILED" if ("COLLAPSED_TO_ZERO" in reasons or "SHARP_DROP" in reasons
                                                or "TOO_FEW_ROWS" in reasons)
                   else "STALE")
    elif age_hours is not None and age_hours > config.stale_hours:
        outcome = "STALE"
    else:
        outcome = "UPDATED"

    report = {
        "outcome": outcome,
        "events_expected": events_expected,
        "events_detail": events_detail,
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
