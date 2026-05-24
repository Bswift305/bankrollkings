from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
QC_RUN_LOG_PATH = TRACKING_DIR / "QC_Run_Log.csv"
QC_WARNING_HISTORY_PATH = TRACKING_DIR / "QC_Warning_History.csv"


def _ensure_tracking_dir() -> None:
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)


def append_qc_run_log(scope: str, report: dict) -> None:
    _ensure_tracking_dir()
    row = {
        "CheckedAt": str(report.get("checked_at", "")).strip(),
        "Scope": str(scope or "").strip(),
        "Clean": "1" if bool(report.get("clean", report.get("failure_count", 0) == 0 and report.get("issue_count", 0) == 0)) else "0",
        "PassCount": int(report.get("pass_count", 0) or 0),
        "WarningCount": int(report.get("warning_count", 0) or 0),
        "FailureCount": int(report.get("failure_count", report.get("issue_count", 0)) or 0),
        "RouteCount": int(report.get("route_count", 0) or 0),
        "ScoredPropCount": int(report.get("scored_prop_count", 0) or 0),
        "FeaturedPropCount": int(report.get("featured_prop_count", 0) or 0),
        "LivePropRows": int(report.get("live_prop_rows", 0) or 0),
        "Notes": str(report.get("notes", "") or "").strip(),
    }
    entry = pd.DataFrame([row])
    if QC_RUN_LOG_PATH.exists():
        try:
            existing = pd.read_csv(QC_RUN_LOG_PATH)
        except pd.errors.EmptyDataError:
            existing = pd.DataFrame()
        entry = pd.concat([existing, entry], ignore_index=True)
    entry.to_csv(QC_RUN_LOG_PATH, index=False)


def load_warning_history(scope: str) -> pd.DataFrame:
    if not QC_WARNING_HISTORY_PATH.exists():
        return pd.DataFrame(
            columns=[
                "Scope",
                "Rule",
                "Player",
                "Stat",
                "Featured",
                "ConsecutiveRuns",
                "LastStatus",
                "LastSeenAt",
                "Message",
            ]
        )
    try:
        df = pd.read_csv(QC_WARNING_HISTORY_PATH)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()
    if df.empty or "Scope" not in df.columns:
        return pd.DataFrame(columns=["Scope", "Rule", "Player", "Stat", "Featured", "ConsecutiveRuns", "LastStatus", "LastSeenAt", "Message"])
    scoped = df[df["Scope"].astype(str) == str(scope or "")].copy()
    if "ConsecutiveRuns" in scoped.columns:
        scoped["ConsecutiveRuns"] = pd.to_numeric(scoped["ConsecutiveRuns"], errors="coerce").fillna(0).astype(int)
    return scoped


def build_warning_history_map(scope: str) -> dict[tuple[str, str, str, bool], int]:
    history = load_warning_history(scope)
    history_map: dict[tuple[str, str, str, bool], int] = {}
    for _, row in history.iterrows():
        key = (
            str(row.get("Rule", "")).strip(),
            str(row.get("Player", "")).strip(),
            str(row.get("Stat", "")).strip(),
            str(row.get("Featured", "0")).strip() == "1",
        )
        history_map[key] = int(row.get("ConsecutiveRuns", 0) or 0)
    return history_map


def update_warning_history(scope: str, warnings: list, failures: list, checked_at: str) -> pd.DataFrame:
    _ensure_tracking_dir()
    if QC_WARNING_HISTORY_PATH.exists():
        try:
            existing = pd.read_csv(QC_WARNING_HISTORY_PATH)
        except pd.errors.EmptyDataError:
            existing = pd.DataFrame()
    else:
        existing = pd.DataFrame(
            columns=["Scope", "Rule", "Player", "Stat", "Featured", "ConsecutiveRuns", "LastStatus", "LastSeenAt", "Message"]
        )
    if existing.empty:
        existing = pd.DataFrame(columns=["Scope", "Rule", "Player", "Stat", "Featured", "ConsecutiveRuns", "LastStatus", "LastSeenAt", "Message"])

    active_items = []
    for item, status in ([(w, "WARN") for w in warnings] + [(f, "FAIL") for f in failures]):
        active_items.append({
            "Scope": str(scope or "").strip(),
            "Rule": str(getattr(item, "rule", "")).strip(),
            "Player": str(getattr(item, "player", "")).strip(),
            "Stat": str(getattr(item, "stat", "")).strip(),
            "Featured": "1" if bool(getattr(item, "featured", False)) else "0",
            "LastStatus": status,
            "LastSeenAt": str(checked_at or "").strip(),
            "Message": str(getattr(item, "message", "")).strip(),
        })

    scope_mask = existing["Scope"].astype(str) == str(scope or "").strip()
    scoped = existing[scope_mask].copy()
    other = existing[~scope_mask].copy()
    next_rows = []
    active_keys = set()
    for item in active_items:
        key = (item["Rule"], item["Player"], item["Stat"], item["Featured"])
        active_keys.add(key)
        prior = scoped[
            (scoped["Rule"].astype(str) == item["Rule"]) &
            (scoped["Player"].astype(str) == item["Player"]) &
            (scoped["Stat"].astype(str) == item["Stat"]) &
            (scoped["Featured"].astype(str) == item["Featured"])
        ]
        consecutive = int(pd.to_numeric(prior["ConsecutiveRuns"], errors="coerce").fillna(0).max()) if not prior.empty else 0
        item["ConsecutiveRuns"] = consecutive + 1
        next_rows.append(item)

    scoped["Key"] = list(zip(
        scoped["Rule"].astype(str),
        scoped["Player"].astype(str),
        scoped["Stat"].astype(str),
        scoped["Featured"].astype(str),
    ))
    scoped = scoped[scoped["Key"].isin(active_keys)].drop(columns=["Key"], errors="ignore")
    updated = pd.concat([other, pd.DataFrame(next_rows)], ignore_index=True)
    updated.to_csv(QC_WARNING_HISTORY_PATH, index=False)
    return pd.DataFrame(next_rows)
