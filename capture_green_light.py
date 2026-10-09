"""
capture_green_light.py  -- Lens Attribution harness (capture half), governance-grade

Snapshots every Green Light recommendation WITH the lenses that fired on it, so we can
grade later. We're not capturing bets -- we're capturing EVIDENCE, to answer the question
invention can't: which lens actually helps when it appears, forward and out-of-sample?
(The 4th doctrine question: "did this lens actually help?")

Governance foundation (per the governance brief -- mandatory, because attribution can only
become governance-grade if the archive is reconstructable and its identities are TRUE):

- DURABLE, DISAMBIGUATED IDENTITY. The board is name-keyed, and display names collide
  (two real "Byron Young"s in the 2026 feed). So we resolve each play's player_id by
  (name, team): exactly one id -> matched; still >1 -> AMBIGUOUS (we do NOT guess); zero
  -> unmatched. PlayerIdStatus records which, so a wrong-identity grade can never happen
  silently -- an unresolved identity surfaces instead of being faked.
- RECOMMENDATION vs SNAPSHOT. A recommendation is graded; a snapshot is one daily
  observation of how it evolved. One snapshot per (SnapshotDate, RecommendationID);
  grade_lenses collapses snapshots to the recommendation before resolving.
- VERSIONING. LensDefinitionVersion / CaptureSchemaVersion / BoardVersion per row; bump
  the constant when the thing it names changes (cleaner than a git hash per row).
- EventKey is a DERIVED slate key (season+week+matchup), NOT a provider event id. It
  exists only to make RecommendationID unique per intended game; resolution itself is
  keyed on (player_id, season, week), which nflverse supplies natively. We do not claim
  provider-grade event identity we don't have.

Writes data/tracking/GreenLight_Archive.csv. Grade with grade_lenses.py; guard with
qc_lens_attribution.py. See BANKROLL_KINGS_DOCTRINE.md S10 and docs/lens_research_queue.md.
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
CAPTURE_SCHEMA_VERSION = "cap-3"      # cap-3: disambiguated identity + EventKey rename
LENS_DEFINITION_VERSION = "lens-1"    # bump when a lens's logic/threshold changes
BOARD_VERSION = "gl-1"                # bump when build_green_light's selection changes

STAT_KEY = {"Rush Yds": "rushing_yards", "Rec Yds": "receiving_yards",
            "Receptions": "receptions", "Pass Yds": "passing_yards", "Anytime TD": "anytime_td"}


def _as_of_week(stats: pd.DataFrame | None):
    try:
        s = stats if stats is not None else pd.read_parquet(STATS, columns=["week"])
        return int(pd.to_numeric(s["week"], errors="coerce").max())
    except Exception:
        return None


def _load_identity_stats():
    try:
        s = pd.read_parquet(STATS, columns=["player_display_name", "player_id", "team",
                                            "position", "week"])
        return s.dropna(subset=["player_display_name"])
    except Exception:
        return None


def resolve_identity(stats: pd.DataFrame | None, name: str, team: str | None):
    """Return (player_id, status, position). status in matched|ambiguous|unmatched.
    Disambiguate by (name, team); if the name+team still maps to >1 id, DO NOT guess."""
    if stats is None or stats.empty:
        return "", "unmatched", ""
    cand = stats[stats["player_display_name"] == name]
    if cand.empty:
        return "", "unmatched", ""
    if team:
        tt = cand[cand["team"].astype(str) == str(team)]
        if not tt.empty:
            cand = tt
    ids = [i for i in cand["player_id"].dropna().astype(str).unique() if i]
    if len(ids) == 1:
        row = cand[cand["player_id"].astype(str) == ids[0]].sort_values("week").iloc[-1]
        return ids[0], "matched", (str(row.get("position")) if pd.notna(row.get("position")) else "")
    if not ids:
        return "", "unmatched", ""
    return "", "ambiguous", ""      # name+team still ambiguous -- refuse to guess


def _event_key(season, aow, game: str) -> str:
    """A DERIVED slate key for the intended game -- not a provider event id."""
    tw = (aow + 1) if aow is not None else "NA"
    g = (game or "").replace(" ", "").replace("@", "_at_")
    return f"{season}W{tw}:{g}"


def _rec_id(season, event_key, player, statkey, line, direction) -> str:
    """Stable across daily snapshots of the SAME recommendation; changes if the line moves."""
    raw = f"{season}|{event_key}|{player}|{statkey}|{line}|{direction}"
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
    idstats = _load_identity_stats()
    aow = _as_of_week(idstats)
    rows = []
    for p in plays:
        names = {l["lens"] for l in p["lenses"]}
        statkey = STAT_KEY.get(p["stat"], "")
        ek = _event_key(season, aow, p.get("game"))
        rid = _rec_id(season, ek, p["player"], statkey, p["line"], "OVER")
        pid, status, pos = resolve_identity(idstats, p["player"], p.get("team"))
        rows.append({
            # --- durable, disambiguated identity (governance) ---
            "RecommendationID": rid, "EventKey": ek,
            "PlayerId": pid, "PlayerIdStatus": status,
            "Player": p["player"], "Team": p["team"], "Opp": p.get("opp"), "Game": p.get("game"),
            "Market": "player_prop", "Stat": p["stat"], "StatKey": statkey,
            "Position": (pos or p.get("pos") or ""),
            "Direction": "OVER", "Line": p["line"], "Odds": p.get("odds"),
            "Timestamp": now.isoformat(timespec="seconds"),
            "SnapshotDate": today, "Season": season, "AsOfWeek": aow,
            # --- versioning (governance) ---
            "LensDefinitionVersion": LENS_DEFINITION_VERSION,
            "CaptureSchemaVersion": CAPTURE_SCHEMA_VERSION,
            "BoardVersion": BOARD_VERSION,
            # --- board verdicts ---
            "Convergence": p["convergence"], "Tier": p["tier"], "Eligible": int(p["eligible"]),
            "Score": p.get("opp_score"),
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
        comb = comb.drop_duplicates(subset=["SnapshotDate", "RecommendationID"], keep="last")
    else:
        comb = new
    comb.to_csv(ARCHIVE, index=False)
    amb = int((new["PlayerIdStatus"] == "ambiguous").sum())
    unm = int((new["PlayerIdStatus"] == "unmatched").sum())
    flag = (f" | identity: {amb} ambiguous, {unm} unmatched (flagged, not guessed)"
            if (amb or unm) else " | identity: all matched")
    print(f"[capture_green_light] captured {len(new)} plays ({today}); "
          f"archive now {len(comb)} rows{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
