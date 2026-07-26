"""
Bankroll Kings - Track NFL injury STATUS CHANGES over time
==========================================================

The live injury feed (NFL_Injuries.csv) is a snapshot of current status only -- it
cannot tell you that a player just moved Questionable -> Out, which is the
actionable, time-sensitive event (it shifts the total/props, and there is a window
before the market fully adjusts). This appends a daily snapshot to a history file
and diffs the two most recent snapshot dates into a changes feed.

Honest scope: this is a TIMING / AWARENESS tool, not a backtested edge. We have no
historical injury-transition + line dataset to quantify it the way wind was
quantified. Its value is surfacing the change fast, especially a move TO "Out"
(the game-week / game-day inactive equivalent).

Writes:
  data/injuries/NFL_Injuries_History.csv   (SnapshotDate, Player, Team, Status)
  data/injuries/NFL_Injury_Changes.csv     (Date, Player, Team, PrevStatus,
                                             NewStatus, ChangeType, Direction)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from services.timeutils import to_eastern_date_str

BASE_DIR = Path(__file__).resolve().parent
INJURIES = BASE_DIR / "data" / "injuries" / "NFL_Injuries.csv"
HISTORY = BASE_DIR / "data" / "injuries" / "NFL_Injuries_History.csv"
CHANGES = BASE_DIR / "data" / "injuries" / "NFL_Injury_Changes.csv"

HISTORY_KEEP_DAYS = 60
SEVERITY = {"OUT": 3, "DOUBTFUL": 2, "QUESTIONABLE": 1, "": 0}


def _today_eastern() -> str:
    return to_eastern_date_str(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _norm_status(value) -> str:
    return str(value or "").strip().upper()


def main() -> int:
    if not INJURIES.exists():
        print("No NFL_Injuries.csv; nothing to track.")
        return 0
    current = pd.read_csv(INJURIES)
    if current.empty or not {"Player", "Team", "Status"}.issubset(current.columns):
        print("NFL_Injuries.csv missing required columns.")
        return 0

    today = _today_eastern()
    snap = current[["Player", "Team", "Status"]].copy()
    snap["Status"] = snap["Status"].map(_norm_status)
    snap.insert(0, "SnapshotDate", today)

    # Append to history: replace any existing rows for today, keep a rolling window.
    if HISTORY.exists():
        try:
            history = pd.read_csv(HISTORY)
        except Exception:
            history = pd.DataFrame(columns=snap.columns)
    else:
        history = pd.DataFrame(columns=snap.columns)
    history = history[history["SnapshotDate"].astype(str) != today]
    prior_dates = sorted(history["SnapshotDate"].astype(str).unique())
    prev_date = prior_dates[-1] if prior_dates else None

    # Diff current vs the most recent PRIOR snapshot date.
    changes = []
    if prev_date:
        prev = history[history["SnapshotDate"].astype(str) == prev_date]
        prev_map = {(str(r["Player"]).strip(), str(r["Team"]).strip()): _norm_status(r["Status"]) for _, r in prev.iterrows()}
        curr_map = {(str(r["Player"]).strip(), str(r["Team"]).strip()): r["Status"] for _, r in snap.iterrows()}
        for key in set(prev_map) | set(curr_map):
            before = prev_map.get(key, "")
            after = curr_map.get(key, "")
            if before == after:
                continue
            if not before:
                change_type, direction = "New injury", "worse"
            elif not after:
                change_type, direction = "Off report", "better"
            else:
                direction = "worse" if SEVERITY.get(after, 0) > SEVERITY.get(before, 0) else "better"
                change_type = "Ruled out" if after == "OUT" else "Downgraded" if direction == "worse" else "Upgraded"
            changes.append({
                "Date": today,
                "Player": key[0],
                "Team": key[1],
                "PrevStatus": before or "(not listed)",
                "NewStatus": after or "(not listed)",
                "ChangeType": change_type,
                "Direction": direction,
            })

    # Persist history (rolling) and the changes feed.
    history = pd.concat([history, snap], ignore_index=True, sort=False)
    keep = sorted(history["SnapshotDate"].astype(str).unique())[-HISTORY_KEEP_DAYS:]
    history = history[history["SnapshotDate"].astype(str).isin(keep)]
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(HISTORY, index=False)

    changes_df = pd.DataFrame(changes, columns=["Date", "Player", "Team", "PrevStatus", "NewStatus", "ChangeType", "Direction"])
    # Rank worse-direction (esp. ruled out) first for display.
    if not changes_df.empty:
        order = {"Ruled out": 0, "Downgraded": 1, "New injury": 2, "Upgraded": 3, "Off report": 4}
        changes_df["_o"] = changes_df["ChangeType"].map(order).fillna(9)
        changes_df = changes_df.sort_values(["_o", "Team", "Player"]).drop(columns="_o")
    changes_df.to_csv(CHANGES, index=False)

    print(f"NFL injury tracker: snapshot {today}, prior {prev_date or 'none'}, "
          f"{len(changes_df)} change(s) written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
