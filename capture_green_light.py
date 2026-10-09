"""
capture_green_light.py  -- Lens Attribution harness (capture half)

Snapshots every Green Light play each day WITH the lenses that fired on it, so we can grade
later. We're not capturing bets -- we're capturing EVIDENCE, so we can eventually answer the
question invention can't: which lens actually helps when it appears, forward and out-of-sample?
(The 4th doctrine question: "did this lens actually help?")

Writes data/tracking/GreenLight_Archive.csv, idempotent per (SnapshotDate, Player, Stat).
Grade it with grade_lenses.py. Wire into run_daily. See BANKROLL_KINGS_DOCTRINE.md S10.
"""
from __future__ import annotations
import datetime
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
ARCHIVE = BASE / "data" / "tracking" / "GreenLight_Archive.csv"
STATS = BASE / "data" / "tracking" / "_nflverse_stats_2026.parquet"
STAT_KEY = {"Rush Yds": "rushing_yards", "Rec Yds": "receiving_yards",
            "Receptions": "receptions", "Pass Yds": "passing_yards", "Anytime TD": "anytime_td"}


def _as_of_week():
    try:
        s = pd.read_parquet(STATS, columns=["week"])
        return int(pd.to_numeric(s["week"], errors="coerce").max())
    except Exception:
        return None


def main() -> int:
    import app
    w = app.build_green_light(limit=200)
    plays = w.get("plays") or []
    if not plays:
        print("[capture_green_light] no plays on the board -- nothing to capture")
        return 0
    today = datetime.date.today().isoformat()
    aow = _as_of_week()
    rows = []
    for p in plays:
        names = {l["lens"] for l in p["lenses"]}
        rows.append({
            "SnapshotDate": today, "Season": w.get("season"), "AsOfWeek": aow,
            "Player": p["player"], "Team": p["team"], "Stat": p["stat"],
            "StatKey": STAT_KEY.get(p["stat"], ""), "Direction": "OVER",
            "Line": p["line"], "Odds": p.get("odds"), "Game": p.get("game"), "Opp": p.get("opp"),
            "Convergence": p["convergence"], "Tier": p["tier"], "Eligible": int(p["eligible"]),
            "L_Opportunity": int("Opportunity" in names),
            "L_Matchup": int("Matchup" in names),
            "L_GameIdentity": int("Game Identity" in names),
            "L_Coaching": int("Coaching" in names),
            "L_Concentration": int(bool(p.get("td_angle"))),
            "RoleStability": p.get("role_stability") or "",
            "SingleChannel": int(bool(p.get("single_channel"))),
            "Fragile": int(bool(p.get("fragile_note"))),
        })
    new = pd.DataFrame(rows)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        comb = pd.concat([pd.read_csv(ARCHIVE), new], ignore_index=True)
        comb = comb.drop_duplicates(subset=["SnapshotDate", "Player", "Stat"], keep="last")
    else:
        comb = new
    comb.to_csv(ARCHIVE, index=False)
    print(f"[capture_green_light] captured {len(new)} plays ({today}); archive now {len(comb)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
