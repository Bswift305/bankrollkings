"""Acceptance tests for NFL Player Check (Player Check stage 6).

Two layers, per the frozen spec (docs/nfl_player_check_spec.md §9):
  A-C. CONTROLLED FIXTURES -- data-independent assertions on the shared reason-producing
       predicates, the per-market floor evaluator, and the name resolver. These are the
       durable regression guards (lines/tiers/prices drift; these do not).
  D.   NAMED LIVE ACCEPTANCE -- Bijan Robinson + Drake London. Structural assertions only
       (resolves, per-market codes present, no player-level collapse); tolerant if a player
       is off this week's slate (bye/off-season) so the suite never hard-fails on live drift.

Exit 0 when the controlled fixtures pass; the live section is advisory (notes, never a fail).
"""
from __future__ import annotations

import app
from services import nfl_inclusion as ni
from services.nfl_inclusion import Reason as R


def _fixtures():
    issues, notes = [], []

    def expect(cond, msg):
        if not cond:
            issues.append(msg)

    # --- A. shared predicates --------------------------------------------------------------
    # price-not-a-gate on the floor; the Menu requires a usable price
    expect(ni.menu_candidate_tier(85, None) == (None, R.INVALID_PRICE),
           "menu_candidate_tier(85, no price) should be INVALID_PRICE")
    expect(ni.menu_candidate_tier(85, -120) == ("floor", R.INCLUDED),
           "menu_candidate_tier(85, -120) should be an INCLUDED floor")
    expect(ni.menu_candidate_tier(60, 130) == ("swing", R.INCLUDED),
           "menu_candidate_tier(60, +130) should be an INCLUDED swing")
    expect(ni.menu_candidate_tier(60, -110) == (None, R.NOT_FLOOR_OR_SWING),
           "menu_candidate_tier(60, -110) should be NOT_FLOOR_OR_SWING")
    expect(ni.floor_market_verdict(90, 3, min_hit=78, min_games=8) == (False, R.INSUFFICIENT_SAMPLE),
           "floor_market_verdict with n<min_games should be INSUFFICIENT_SAMPLE")
    expect(ni.floor_market_verdict(70, 10, min_hit=78, min_games=8) == (False, R.BELOW_HIT_THRESHOLD),
           "floor_market_verdict below min_hit should be BELOW_HIT_THRESHOLD")
    expect(ni.floor_market_verdict(80, 10, min_hit=78, min_games=8) == (True, R.INCLUDED),
           "floor_market_verdict at/above min_hit should be INCLUDED")
    # a floor ignores price entirely (price-not-a-gate): verdict has no price parameter
    import inspect
    expect("price" not in inspect.signature(ni.floor_market_verdict).parameters,
           "floor_market_verdict must not take price -- price is not a floor gate")

    # --- B. reason classes (VIEW vs ELIGIBILITY vs INCLUDED) -------------------------------
    expect(ni.reason_class(R.INCLUDED) == "INCLUDED", "INCLUDED should class as INCLUDED")
    expect(ni.reason_class(R.BELOW_HIT_THRESHOLD) == "ELIGIBILITY",
           "BELOW_HIT_THRESHOLD should class as ELIGIBILITY")
    expect(ni.reason_class(R.BELOW_DISPLAY_CUTOFF) == "VIEW",
           "BELOW_DISPLAY_CUTOFF must be VIEW, not an eligibility failure")
    expect(ni.reason_class(R.POSITION_FILTERED) == "VIEW", "POSITION_FILTERED should class as VIEW")

    # --- C. per-market floor evaluator codes (no data needed for these paths) --------------
    meta = app._NFL_FLOOR_STATS.get("rushing_yards")
    expect(app._nfl_floor_market_eval(None, None, 50.0, 2026, min_hit=78, min_games=8)["code"] == R.STAT_NOT_SUPPORTED,
           "meta=None should yield STAT_NOT_SUPPORTED")
    expect(app._nfl_floor_market_eval(None, meta, 50.0, 2026, min_hit=78, min_games=8)["code"] == R.NO_GAMELOG,
           "sub=None (with meta) should yield NO_GAMELOG")

    # --- D(resolver). name resolution fixtures (controlled universe) -----------------------
    names = {"Bijan Robinson", "Brian Robinson", "Patrick Mahomes II", "Ja'Marr Chase"}
    expect(app._player_check_resolve("Bijan Robinson", names) == ("resolved", "Bijan Robinson"),
           "exact name should resolve")
    st, cands = app._player_check_resolve("B. Robinson", names)
    expect(st == "ambiguous" and set(cands) == {"Bijan Robinson", "Brian Robinson"},
           "B. Robinson should be ambiguous (Bijan vs Brian), never a silent pick")
    expect(app._player_check_resolve("Patrick Mahomes", names)[0] == "resolved",
           "suffix-insensitive: 'Patrick Mahomes' should resolve to 'Patrick Mahomes II'")
    expect(app._player_check_resolve("patrick mahomes ii", names)[0] == "resolved",
           "case/suffix normalization should resolve")
    expect(app._player_check_resolve("jamarr chase", names)[0] == "resolved",
           "apostrophe/punctuation normalization should resolve Ja'Marr Chase")
    expect(app._player_check_resolve("Nobody Here", names) == ("not_found", []),
           "unknown name should be not_found")

    return issues, notes


def _live_named_acceptance():
    """Advisory: Bijan Robinson + Drake London structural checks against live data."""
    notes = []
    for name in ("Bijan Robinson", "Drake London"):
        r = app.evaluate_nfl_player(name)
        if r.get("status") != "ok":
            notes.append(f"{name}: not resolvable on the current slate (status={r.get('status')}) -- live section skipped")
            continue
        s = r.get("surfaces", {})
        # structural: every evaluated market carries BOTH a floor and menu code (per-market,
        # never collapsed to one player verdict)
        bad = [m["stat"] for m in r.get("markets", [])
               if "code" not in m.get("surfaces", {}).get("floor", {})
               or "code" not in m.get("surfaces", {}).get("menu", {})]
        shape = "ok" if not bad else f"markets missing per-surface codes: {bad}"
        notes.append(f"{name}: status=ok, featured={s.get('featured', {}).get('code')}, "
                     f"green_light={s.get('green_light', {}).get('code')}, "
                     f"markets={len(r.get('markets', []))}, per-market-codes={shape}")
    return notes


def main() -> int:
    issues, notes = _fixtures()
    live = _live_named_acceptance()
    print("=" * 60)
    print("NFL PLAYER CHECK -- ACCEPTANCE")
    print("=" * 60)
    for n in notes + live:
        print(f"[NOTE] {n}")
    if notes or live:
        print()
    if not issues:
        print("Controlled fixtures passed.")
        return 0
    for msg in issues:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
