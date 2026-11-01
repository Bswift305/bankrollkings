"""Adversarial QC for the RC 2D1 props producer correction (fetch_player_props.parse_market_rows).

Proves SourceUpdatedAtUTC is bound to the current MARKET's last_update (not the bookmaker's): bookmaker ts
absent + market ts present works; different markets keep their own timestamp; missing/invalid provider time
stays blank; fetch time is never labeled as source time; rows bind deterministically to the correct book and
market. Synthetic provider dicts only -- no network, no paid request, no file writes."""
from __future__ import annotations

import sys

from fetch_player_props import parse_market_rows

_OK = 0
_FAIL = 0


def ok(cond, label):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print(f"  [ok] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


def mkt(key, last_update, player):
    return {"key": key, "last_update": last_update, "outcomes": [
        {"description": player, "name": "Over", "point": 50.5, "price": -110},  # synthetic-fixture
        {"description": player, "name": "Under", "point": 50.5, "price": -110},  # synthetic-fixture
    ]}


EVENT = {"id": "evt1", "away_team": "SEA", "home_team": "BUF", "commence_time": "2026-11-01T18:00:00Z"}
ALLOWED = ["player_pass_yds", "player_rush_yds", "player_receptions", "player_reception_yds", "player_anytime_td"]

# bookmaker-level last_update is ABSENT (as on the real NFL feed); each market carries its own.
BM = {"key": "draftkings", "title": "DraftKings", "last_update": None, "markets": [
    mkt("player_pass_yds", "2026-10-31T13:00:00Z", "QB One"),          # present, UTC Z
    mkt("player_rush_yds", "2026-10-31T12:30:00Z", "RB Two"),          # different ts
    mkt("player_receptions", None, "WR Three"),                        # absent -> blank
    mkt("player_reception_yds", "2026-10-31 11:00:00", "WR Four"),     # naive (no tz) -> blank
    mkt("player_anytime_td", "2026-10-31T09:00:00-04:00", "WR Five"),  # offset -> canonical UTC
]}

print("=" * 80)
print("QC: NFL props SourceUpdatedAtUTC market-level binding (RC 2D1 producer correction)")
print("=" * 80)

rows = parse_market_rows(EVENT, BM, ALLOWED)
by_player = {r["Player"]: r for r in rows}
ok(set(by_player) == {"QB One", "RB Two", "WR Three", "WR Four", "WR Five"},
   f"one row per (player,line) across 5 markets (got {sorted(by_player)})")

fetched_at = {r["LastUpdated"] for r in rows}  # bookmaker.last_update is None -> LastUpdated == fetched_at
# --- 1. bookmaker ts absent + market ts present works ------------------------------------------------
ok(by_player["QB One"]["SourceUpdatedAtUTC"] == "2026-10-31T13:00:00Z",
   "bookmaker last_update absent + market present -> SourceUpdatedAtUTC = market ts")

# --- 2. different markets retain their OWN timestamp -------------------------------------------------
ok(by_player["RB Two"]["SourceUpdatedAtUTC"] == "2026-10-31T12:30:00Z", "second market keeps its own ts")
ok(by_player["QB One"]["SourceUpdatedAtUTC"] != by_player["RB Two"]["SourceUpdatedAtUTC"],
   "two markets have DISTINCT per-market source times")

# --- 3. missing / invalid provider time stays BLANK (never fabricated) ------------------------------
ok(by_player["WR Three"]["SourceUpdatedAtUTC"] == "", "market with no last_update -> SourceUpdatedAtUTC blank")
ok(by_player["WR Four"]["SourceUpdatedAtUTC"] == "", "naive (tz-unaware) market ts -> SourceUpdatedAtUTC blank")

# --- 4. offset timestamps normalize to canonical zero-offset UTC ------------------------------------
ok(by_player["WR Five"]["SourceUpdatedAtUTC"] == "2026-10-31T13:00:00Z",
   "offset market ts (-04:00) normalized to canonical UTC Z")

# --- 5. fetch time is NEVER labeled as source time --------------------------------------------------
# LastUpdated here is the fetch-time fallback (bookmaker.last_update is None). No SourceUpdatedAtUTC equals it.
ok(all(r["SourceUpdatedAtUTC"] not in fetched_at or r["SourceUpdatedAtUTC"] == "" for r in rows)
   and all(r["SourceUpdatedAtUTC"] == "" or r["SourceUpdatedAtUTC"] != r["LastUpdated"] for r in rows),
   "no SourceUpdatedAtUTC equals the fetch-time LastUpdated")
ok(all(r["SourceUpdatedAtUTC"] == "" or r["SourceUpdatedAtUTC"].endswith("Z") for r in rows),
   "every non-blank SourceUpdatedAtUTC is canonical UTC (ends with Z), never a fetch/display format")

# --- 6. deterministic binding to the correct BOOK and MARKET ----------------------------------------
ok(all(r["Book"] == "DraftKings" for r in rows), "every row bound to the correct book (DraftKings)")
ok(by_player["QB One"]["Stat"] == "Pass Yds" and by_player["RB Two"]["Stat"] == "Rush Yds",
   "each row bound to its own market (Stat matches market key)")
ok(all(r["EventId"] == "evt1" and r["EventCommenceAtUTC"] == "2026-11-01T18:00:00Z" for r in rows),
   "every row carries the event id + UTC kickoff")

# second book proves book binding is not hard-coded
BM2 = {"key": "fanduel", "title": "FanDuel", "last_update": None,
       "markets": [mkt("player_pass_yds", "2026-10-31T14:00:00Z", "QB One")]}
rows2 = parse_market_rows(EVENT, BM2, ALLOWED)
ok(rows2 and rows2[0]["Book"] == "FanDuel" and rows2[0]["SourceUpdatedAtUTC"] == "2026-10-31T14:00:00Z",
   "a different book's rows bind to THAT book + its market ts")

# --- 7. a market whose outcomes carry no player -> no rows (no spurious binding) ---------------------
BM3 = {"key": "draftkings", "title": "DraftKings", "last_update": None,
       "markets": [{"key": "player_pass_yds", "last_update": "2026-10-31T13:00:00Z",
                    "outcomes": [{"description": "", "name": "Over", "point": 50.5, "price": -110}]}]}  # synthetic-fixture
ok(parse_market_rows(EVENT, BM3, ALLOWED) == [], "market with no named player emits no rows")

print("=" * 80)
print(f"Clean: {_FAIL == 0}  (ok={_OK} fail={_FAIL})")
sys.exit(1 if _FAIL else 0)
