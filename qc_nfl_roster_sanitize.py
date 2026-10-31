"""Adversarial QC for the RC 2D1 roster producer correction (fetch_nfl_player_week.sanitize_player_identities).

Proves: all-null aggregate rows are removed; valid player rows are field-equivalent; partial-null identities
fail closed; no real player is silently dropped; the result contains no null governed identity. Synthetic
data only -- no network, no file writes, no provider calls."""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from fetch_nfl_player_week import sanitize_player_identities, IDENTITY_COLS, GOVERNED_IDENTITY_COLS

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


def _row(pid, disp, name, week, team, pos="WR"):
    return {"player_id": pid, "player_display_name": disp, "player_name": name,
            "week": week, "team": team, "position": pos, "receiving_yards": "50"}


def _agg(week, team):
    # upstream team-attributed aggregate: EVERY identity column null, no position
    return {"player_id": np.nan, "player_display_name": np.nan, "player_name": np.nan,
            "week": week, "team": team, "position": np.nan, "receiving_yards": "7"}


print("=" * 80)
print("QC: NFL roster identity sanitation (RC 2D1 producer correction)")
print("=" * 80)

# --- 1. all-null aggregate rows removed; valid preserved; counts exact -------------------------------
valid = [_row("00-1", "Alice Alpha", "A.Alpha", 1, "SEA"),
         _row("00-2", "Bob Beta", "B.Beta", 1, "BUF"),
         _row("00-1", "Alice Alpha", "A.Alpha", 2, "SEA")]
df = pd.DataFrame(valid + [_agg(1, "DAL"), _agg(2, "ATL"), _agg(3, "CAR")])
clean, removed = sanitize_player_identities(df)
ok(removed == 3, f"removed count == 3 all-null aggregate rows (got {removed})")
ok(len(clean) == 3, f"3 valid player rows retained (got {len(clean)})")
ok(not bool(clean["player_id"].isna().any() or clean["player_display_name"].isna().any()),
   "result has NO null governed identity")

# --- 2. valid player rows are field-equivalent (values unchanged) ------------------------------------
exp = pd.DataFrame(valid).reset_index(drop=True)
got = clean.reset_index(drop=True)[exp.columns]
ok(got.equals(exp), "retained rows are field-equivalent to the input valid rows (no mutation)")

# --- 3. no real player silently dropped --------------------------------------------------------------
ok(set(zip(clean["player_id"], clean["week"])) == {("00-1", 1), ("00-2", 1), ("00-1", 2)},
   "every real (player_id, week) survived; none dropped")
ok(removed == 3 and len(df) - len(clean) == removed, "rows removed == aggregate count exactly")

# --- 4. partial-null identities FAIL CLOSED (never inferred) -----------------------------------------
def _raises(rows, why):
    try:
        sanitize_player_identities(pd.DataFrame(rows))
        return False
    except ValueError:
        return True

ok(_raises(valid + [_row(np.nan, "Carl Gamma", "C.Gamma", 1, "NE")], "id null"),
   "player-like row with null player_id (display present) -> fail closed")
ok(_raises(valid + [_row("00-9", np.nan, "D.Delta", 1, "CLE")], "display null"),
   "player-like row with null player_display_name (id present) -> fail closed")
ok(_raises(valid + [_row(np.nan, np.nan, "E.Echo", 1, "GB")], "only name"),
   "player-like row with only player_name (governed null) -> fail closed")
ok(_raises(valid + [_row("00-9", "   ", "F.Foxtrot", 1, "MIA")], "blank display"),
   "player-like row with BLANK display -> fail closed (blank counts as null)")

# --- 5. a fully-valid frame is unchanged; zero removed ----------------------------------------------
clean2, removed2 = sanitize_player_identities(pd.DataFrame(valid))
ok(removed2 == 0 and len(clean2) == 3, "all-valid frame: 0 removed, all retained")

# --- 6. missing governed column fails closed ---------------------------------------------------------
ok(_raises([{"player_id": "00-1", "player_name": "x", "week": 1}], "no display col"),
   "missing player_display_name column -> fail closed")

# --- 7. aggregate detection works when player_name column is ABSENT ----------------------------------
no_name = pd.DataFrame([
    {"player_id": "00-1", "player_display_name": "Alice Alpha", "week": 1, "team": "SEA"},
    {"player_id": np.nan, "player_display_name": np.nan, "week": 1, "team": "DAL"},
])
c3, r3 = sanitize_player_identities(no_name)
ok(r3 == 1 and len(c3) == 1, "all-null aggregate removed even without a player_name column")

# --- 8. post-condition guarantee: survivors never carry a null governed identity ---------------------
ok(not bool(clean["player_id"].astype(str).str.strip().eq("").any()), "no blank player_id survives")
ok(not bool(clean["player_display_name"].astype(str).str.strip().eq("").any()), "no blank display survives")

print("=" * 80)
print(f"Clean: {_FAIL == 0}  (ok={_OK} fail={_FAIL})")
sys.exit(1 if _FAIL else 0)
