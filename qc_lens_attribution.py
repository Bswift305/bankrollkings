"""
qc_lens_attribution.py  -- governance regression guards for the Lens Attribution harness

"Attacks that aren't committed are stories." This is the permanent guard for every defect
the adversarial passes found. It exercises capture-side identity resolution and the
grader's resolution states against synthetic fixtures, so a future edit that reintroduces
a governance bug fails here instead of silently corrupting the archive.

Run standalone: `py -3 qc_lens_attribution.py` (exit 0 = all pass, 1 = a guard tripped).
Covers: duplicate names, reversed-order determinism, invalid captured id (no weak
fallback), ambiguous identity, DNP / intended-game mismatch, push, missing stat, NaN
actual, legacy name-only rows, and the win/loss sanity path. See the governance brief and
docs/lens_governance_constitution.md.
"""
from __future__ import annotations
import os
import sys
import tempfile
import numpy as np
import pandas as pd

import grade_lenses as gl
import capture_green_light as cap

_TMP = os.path.join(tempfile.gettempdir(), "qc_lens_attr.parquet")
_STAT_COLS = ("rushing_yards", "receiving_yards", "receptions", "passing_yards",
              "rushing_tds", "receiving_tds")
_FAILS: list[str] = []


def _stats(rows: list[dict]) -> pd.DataFrame:
    """Build a weekly-stats fixture; every stat column present (0 unless overridden)."""
    out = []
    for r in rows:
        base = {c: 0 for c in _STAT_COLS}
        base.update({"player_display_name": r["name"], "player_id": r["id"],
                     "team": r.get("team", ""), "week": r["week"], "position": r.get("pos", "RB")})
        base.update({k: v for k, v in r.items() if k in _STAT_COLS})
        out.append(base)
    return pd.DataFrame(out)


def _grade(rec: dict, stats: pd.DataFrame) -> pd.Series:
    stats.to_parquet(_TMP)
    orig = gl.STATS
    gl.STATS = _TMP
    try:
        return gl._resolve(pd.DataFrame([rec]).copy()).iloc[0]
    finally:
        gl.STATS = orig


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got {got!r}, want {want!r}")
    if not ok:
        _FAILS.append(label)


def rec(**kw) -> dict:
    base = {"Player": "P", "PlayerId": "", "PlayerIdStatus": "", "StatKey": "rushing_yards",
            "Line": 40.5, "AsOfWeek": 4, "Direction": "OVER", "Odds": -110}
    base.update(kw)
    return base


def main() -> int:
    print("qc_lens_attribution -- governance regression guards\n")

    # --- GRADER: identity gate -------------------------------------------------
    # DEFECT (name-collision): two real players share a display name. A name-join graded
    # whichever row sorted first -- non-deterministic, silently wrong. Guard: resolve by
    # captured id, order-independent, every time.
    print("identity: duplicate name resolves by id (order-independent)")
    r = rec(Player="Byron Young", PlayerId="RB1", PlayerIdStatus="matched", Line=40.5)
    for order in (["RB1", "DB1"], ["DB1", "RB1"]):
        rows = [{"name": "Byron Young", "id": i, "week": 5,
                 "rushing_yards": (10 if i == "RB1" else 99)} for i in order]
        g = _grade(r, _stats(rows))
        check(f"order {order}", (g["State"], g["Hit"]), ("Loss", 0.0))

    # DEFECT (weak fallback): a captured id that fails to match must NOT fall back to a
    # name guess. It's an integrity failure.
    print("identity: invalid captured id -> PlayerIdUnmatched (no name fallback)")
    r = rec(Player="Guy", PlayerId="GHOST", PlayerIdStatus="matched", Line=40.5)
    g = _grade(r, _stats([{"name": "Guy", "id": "REAL", "week": 5, "rushing_yards": 99}]))
    check("captured id absent from feed", g["State"], "PlayerIdUnmatched")

    print("identity: ambiguous capture -> PlayerAmbiguous")
    r = rec(Player="Marcus Harris", PlayerId="", PlayerIdStatus="ambiguous")
    g = _grade(r, _stats([{"name": "Marcus Harris", "id": "A", "week": 5}]))
    check("ambiguous", g["State"], "PlayerAmbiguous")

    print("identity: unmatched capture -> PlayerUnmatched")
    r = rec(Player="Nobody", PlayerId="", PlayerIdStatus="unmatched")
    g = _grade(r, _stats([{"name": "Someone", "id": "A", "week": 5}]))
    check("unmatched", g["State"], "PlayerUnmatched")

    print("identity: legacy name-only row still grades by name")
    r = rec(Player="Legacy Guy", Line=20.5)   # no PlayerId, no PlayerIdStatus
    r.pop("PlayerId"); r.pop("PlayerIdStatus")
    g = _grade(r, _stats([{"name": "Legacy Guy", "id": "L", "week": 5, "rushing_yards": 30}]))
    check("legacy name fallback", (g["State"], g["Hit"]), ("Win", 1.0))

    # --- GRADER: settlement + states -------------------------------------------
    print("settlement: win / loss / push")
    r = rec(Player="W", PlayerId="W", PlayerIdStatus="matched", Line=50.5)
    check("win", _grade(r, _stats([{"name": "W", "id": "W", "week": 5, "rushing_yards": 70}]))["State"], "Win")
    r = rec(Player="L", PlayerId="L", PlayerIdStatus="matched", Line=50.5)
    check("loss", _grade(r, _stats([{"name": "L", "id": "L", "week": 5, "rushing_yards": 10}]))["State"], "Loss")
    r = rec(Player="Pu", PlayerId="Pu", PlayerIdStatus="matched", StatKey="receptions", Line=4)
    check("push (actual==whole line)", _grade(r, _stats([{"name": "Pu", "id": "Pu", "week": 5, "receptions": 4}]))["State"], "Push")

    print("settlement: intended-game discipline (DNP)")
    r = rec(Player="D", PlayerId="D", PlayerIdStatus="matched", Line=30.5)
    g = _grade(r, _stats([{"name": "D", "id": "D", "week": 6, "rushing_yards": 99}]))  # missed wk5, played wk6
    check("inactive intended week -> Void(DNP)", g["State"], "Void(DNP)")

    print("integrity: missing stat / NaN actual / pending")
    r = rec(Player="S", PlayerId="S", PlayerIdStatus="matched", StatKey="return_yards", Line=10.5)
    check("stat not in feed -> SourceMissing", _grade(r, _stats([{"name": "S", "id": "S", "week": 5}]))["State"], "SourceMissing")
    r = rec(Player="N", PlayerId="N", PlayerIdStatus="matched", StatKey="receiving_yards", Line=20.5)
    g = _grade(r, _stats([{"name": "N", "id": "N", "week": 5, "receiving_yards": np.nan}]))
    check("NaN actual -> ManualReview (not a fake loss)", g["State"], "ManualReview")
    r = rec(Player="Z", PlayerId="Z", PlayerIdStatus="matched", Line=20.5, AsOfWeek=9)  # target wk10 > max wk
    check("intended week in the future -> Pending", _grade(r, _stats([{"name": "Z", "id": "Z", "week": 5, "rushing_yards": 99}]))["State"], "Pending")

    # --- CAPTURE: identity disambiguation --------------------------------------
    print("capture: resolve_identity disambiguates by (name, team)")
    coll = _stats([
        {"name": "Byron Young", "id": "LAR-edge", "team": "LAR", "week": 4},
        {"name": "Byron Young", "id": "TEN-lb", "team": "TEN", "week": 4},
    ])
    check("name+team -> matched id", cap.resolve_identity(coll, "Byron Young", "LAR")[:2], ("LAR-edge", "matched"))
    check("name alone (2 ids) -> ambiguous", cap.resolve_identity(coll, "Byron Young", None)[1], "ambiguous")
    check("unknown name -> unmatched", cap.resolve_identity(coll, "Ghost Player", "LAR")[1], "unmatched")
    check("name+unseen team falls to name set -> ambiguous", cap.resolve_identity(coll, "Byron Young", "KC")[1], "ambiguous")
    # team-mismatch integrity metric: board team absent from the feed's rows for this name
    solo = _stats([{"name": "Traded Guy", "id": "TG", "team": "NYJ", "week": 4}])
    check("board team not in feed -> team_mismatch flagged", cap.resolve_identity(solo, "Traded Guy", "CLE")[3], True)
    check("matching team -> no mismatch", cap.resolve_identity(solo, "Traded Guy", "NYJ")[3], False)

    print()
    if _FAILS:
        print(f"RESULT: {len(_FAILS)} guard(s) tripped -> {_FAILS}")
        return 1
    print("RESULT: all governance guards pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
