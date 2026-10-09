"""
capture_green_light.py  -- Lens Attribution harness (capture half), governance-grade

Snapshots every Green Light recommendation WITH the lenses that fired on it, so we can
grade later. We're not capturing bets -- we're capturing EVIDENCE, to answer the question
invention can't: which lens actually helps when it appears, forward and out-of-sample?
(The 4th doctrine question: "did this lens actually help?")

Governance foundation (per the governance brief -- these are mandatory, not nice-to-have,
because attribution can only become governance-grade if the archive is reconstructable):

- DURABLE IDENTITY. Every recommendation carries RecommendationID, EventID, PlayerId,
  Market, Direction, Line, Odds, Timestamp. Without stable ids, attribution can never
  judge, promote or retire a lens -- you can't grade what you can't re-find.
- RECOMMENDATION vs SNAPSHOT. A recommendation is the thing that gets graded; a snapshot
  is one daily observation of how it evolved before kickoff. We capture snapshots (one row
  per day) keyed by (SnapshotDate, RecommendationID); grade_lenses collapses them to one
  recommendation (the latest snapshot) before resolving. Two different objects, on purpose.
- VERSIONING. Each row stamps LensDefinitionVersion / CaptureSchemaVersion / BoardVersion
  so a later change to lens logic or capture shape is visible in the data, not silent.
  Cleaner than a git hash on every row -- bump the constant when the thing it names changes.
- RAW lens values captured alongside the binary flags, so we can re-cut later without
  re-capturing. Analysis comes later; the facts must be captured now or they're lost.

Writes data/tracking/GreenLight_Archive.csv. Grade it with grade_lenses.py. See
BANKROLL_KINGS_DOCTRINE.md S10 and docs/lens_research_queue.md.
"""
from __future__ import annotations
import datetime
import hashlib
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
ARCHIVE = BASE / "data" / "tracking" / "GreenLight_Archive.csv"
STATS = BASE / "data" / "tracking" / "_nflverse_stats_2026.parquet"

# --- versioning: bump the constant when the thing it names changes (not a git hash) ---
CAPTURE_SCHEMA_VERSION = "cap-2"      # bump when the ROW SHAPE below changes
LENS_DEFINITION_VERSION = "lens-1"    # bump when a lens's logic/threshold changes
BOARD_VERSION = "gl-1"                # bump when build_green_light's selection changes

STAT_KEY = {"Rush Yds": "rushing_yards", "Rec Yds": "receiving_yards",
            "Receptions": "receptions", "Pass Yds": "passing_yards", "Anytime TD": "anytime_td"}


def _as_of_week():
    try:
        s = pd.read_parquet(STATS, columns=["week"])
        return int(pd.to_numeric(s["week"], errors="coerce").max())
    except Exception:
        return None


def _player_lookup():
    """player_display_name -> (player_id, position), most recent row wins."""
    try:
        s = pd.read_parquet(STATS, columns=["player_display_name", "player_id", "position", "week"])
        s = s.dropna(subset=["player_display_name"]).sort_values("week")
        return {r["player_display_name"]: (r.get("player_id"), r.get("position"))
                for _, r in s.iterrows()}
    except Exception:
        return {}


def _event_id(season, aow, game: str) -> str:
    """The INTENDED game: the slate immediately after the last completed week."""
    tw = (aow + 1) if aow is not None else "NA"
    g = (game or "").replace(" ", "").replace("@", "_at_")
    return f"{season}W{tw}:{g}"


def _rec_id(season, event_id, player, statkey, line, direction) -> str:
    """Stable across daily snapshots of the SAME recommendation; changes if the line moves."""
    raw = f"{season}|{event_id}|{player}|{statkey}|{line}|{direction}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def main() -> int:
    import app
    w = app.build_green_light(limit=200)
    plays = w.get("plays") or []
    if not plays:
        print("[capture_green_light] no plays on the board -- nothing to capture")
        return 0
    now = datetime.datetime.now()
    today = now.date().isoformat()
    season = w.get("season")
    aow = _as_of_week()
    plk = _player_lookup()
    rows = []
    for p in plays:
        names = {l["lens"] for l in p["lenses"]}
        statkey = STAT_KEY.get(p["stat"], "")
        eid = _event_id(season, aow, p.get("game"))
        rid = _rec_id(season, eid, p["player"], statkey, p["line"], "OVER")
        pid, pos = plk.get(p["player"], (None, None))
        rows.append({
            # --- durable identity (governance) ---
            "RecommendationID": rid, "EventID": eid,
            "PlayerId": (pid if pid is not None else ""), "PlayerMatched": int(pid is not None),
            "Player": p["player"], "Team": p["team"], "Opp": p.get("opp"), "Game": p.get("game"),
            "Market": "player_prop", "Stat": p["stat"], "StatKey": statkey,
            "Position": (pos if pos is not None else ""),
            "Direction": "OVER", "Line": p["line"], "Odds": p.get("odds"),
            "Timestamp": now.isoformat(timespec="seconds"),
            "SnapshotDate": today, "Season": season, "AsOfWeek": aow,
            # --- versioning (governance) ---
            "LensDefinitionVersion": LENS_DEFINITION_VERSION,
            "CaptureSchemaVersion": CAPTURE_SCHEMA_VERSION,
            "BoardVersion": BOARD_VERSION,
            # --- board verdicts ---
            "Convergence": p["convergence"], "Tier": p["tier"], "Eligible": int(p["eligible"]),
            "Score": p.get("score"),
            # --- binary lens flags (for grouping) ---
            "L_Opportunity": int("Opportunity" in names),
            "L_Matchup": int("Matchup" in names),
            "L_GameIdentity": int("Game Identity" in names),
            "L_Coaching": int("Coaching" in names),
            "L_Concentration": int(bool(p.get("td_angle"))),
            # --- raw lens values (capture now, analyze later) ---
            "RoleStability": p.get("role_stability") or "",
            "SingleChannel": int(bool(p.get("single_channel"))),
            "ChannelDep": p.get("channel_dep") or "",
            "ScriptConfidence": p.get("script_certainty") or "",
            "Fragile": int(bool(p.get("fragile_note"))),
        })
    new = pd.DataFrame(rows)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        comb = pd.concat([pd.read_csv(ARCHIVE), new], ignore_index=True)
        # one SNAPSHOT per recommendation per day (recommendation vs snapshot model)
        key = ["SnapshotDate", "RecommendationID"]
        comb = comb.drop_duplicates(subset=key, keep="last")
    else:
        comb = new
    comb.to_csv(ARCHIVE, index=False)
    unmatched = int((new["PlayerMatched"] == 0).sum())
    print(f"[capture_green_light] captured {len(new)} plays ({today}); archive now {len(comb)} rows"
          + (f" | WARN {unmatched} player(s) unmatched to nflverse id" if unmatched else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
