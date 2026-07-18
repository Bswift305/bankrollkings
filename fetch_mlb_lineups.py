"""Fetch confirmed MLB lineups + probable pitchers into data/lineups/MLB_Lineups.csv.

Why this exists: `classify_mlb_lineup_gate()` looks for a lineup status on each
prop row (LineupStatus / ConfirmedLineup / StartingStatus / BattingOrder). The
props feed is an ODDS feed and carries none of those fields, so every batter prop
fell through to "LINEUP PENDING" permanently -- not because lineups were late,
but because nothing could ever confirm them. That downgraded every MLB curated
pick to CONFLICTED/PASS, and since archiving requires a PLAY verdict, MLB built
no track record at all (1 resolved Floor Play vs WNBA's 523).

Source is MLB's own Stats API: free, public, no key. Lineups appear once a club
posts them (typically a few hours before first pitch), so this is worth running
on a timer through the afternoon rather than once in the morning.

Batting order is the array position in lineups.homePlayers / awayPlayers.

Run: python fetch_mlb_lineups.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "lineups", "MLB_Lineups.csv")
API = "https://statsapi.mlb.com/api/v1/schedule"

COLUMNS = [
    "Date", "GamePk", "GameStatus", "Side", "Team", "Opponent",
    "Player", "Position", "BattingOrder", "LineupStatus", "FetchedAt",
]


def _get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "bankrollkings/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def build_rows(date_str: str) -> list[dict]:
    url = f"{API}?sportId=1&date={date_str}&hydrate=probablePitcher,lineups"
    payload = _get(url)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict] = []

    for date_block in payload.get("dates", []) or []:
        for game in date_block.get("games", []) or []:
            game_pk = game.get("gamePk")
            status = ((game.get("status") or {}).get("detailedState") or "").strip()
            teams = game.get("teams") or {}
            names = {
                side: (((teams.get(side) or {}).get("team") or {}).get("name") or "").strip()
                for side in ("home", "away")
            }
            lineups = game.get("lineups") or {}

            for side, key in (("home", "homePlayers"), ("away", "awayPlayers")):
                opponent = names["away" if side == "home" else "home"]
                # Batting order = array position. Only present once posted, which
                # is exactly what makes the CONFIRMED status meaningful.
                for order, player in enumerate(lineups.get(key) or [], start=1):
                    name = (player.get("fullName") or "").strip()
                    if not name:
                        continue
                    rows.append({
                        "Date": date_str,
                        "GamePk": game_pk,
                        "GameStatus": status,
                        "Side": side,
                        "Team": names[side],
                        "Opponent": opponent,
                        "Player": name,
                        "Position": ((player.get("primaryPosition") or {}).get("abbreviation") or "").strip(),
                        "BattingOrder": order,
                        "LineupStatus": "CONFIRMED",
                        "FetchedAt": fetched_at,
                    })

                # Probable starter. Named but not yet in a posted lineup, so it is
                # PROBABLE rather than CONFIRMED -- the gate treats pitcher markets
                # as reviewable pre-lock anyway, and overstating this as CONFIRMED
                # would defeat the point of the badge.
                pitcher = ((teams.get(side) or {}).get("probablePitcher") or {})
                pitcher_name = (pitcher.get("fullName") or "").strip()
                if pitcher_name:
                    rows.append({
                        "Date": date_str,
                        "GamePk": game_pk,
                        "GameStatus": status,
                        "Side": side,
                        "Team": names[side],
                        "Opponent": opponent,
                        "Player": pitcher_name,
                        "Position": "P",
                        "BattingOrder": "",
                        "LineupStatus": "PROBABLE",
                        "FetchedAt": fetched_at,
                    })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch MLB confirmed lineups and probable pitchers.")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        help="Slate date (UTC today by default)")
    parser.add_argument("--output", default=OUT_PATH)
    args = parser.parse_args()

    try:
        rows = build_rows(args.date)
    except Exception as exc:                      # network/API hiccup
        print(f"fetch_mlb_lineups: could not reach MLB Stats API ({exc}) - leaving existing file untouched.")
        return 1

    if not rows:
        print(f"fetch_mlb_lineups: no games/lineups for {args.date} - leaving existing file untouched.")
        return 0

    import pandas as pd
    frame = pd.DataFrame(rows, columns=COLUMNS)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    frame.to_csv(args.output, index=False)

    confirmed = int((frame["LineupStatus"] == "CONFIRMED").sum())
    probable = int((frame["LineupStatus"] == "PROBABLE").sum())
    games = frame["GamePk"].nunique()
    posted = frame.loc[frame["LineupStatus"] == "CONFIRMED", "GamePk"].nunique()
    print(f"Wrote {len(frame):,} rows to {args.output} | {games} games "
          f"({posted} with posted lineups) | {confirmed} confirmed batters, {probable} probable pitchers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
