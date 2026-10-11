"""QC: NFL floor-board cache is deterministic and invalidates on data change.

Regression guard for the floor-board cache fixes (a6d9e4c + the player-log signature
follow-up). Two historical defects this locks down:

  1. Call-order contamination -- build_nfl_floor_board cached on NFL_Props.csv mtime alone,
     ignoring its (limit, min_hit, min_games) params, so whichever caller warmed the single
     slot first served its board to every other caller. The returned board then depended on
     request order.
  2. Stale-on-log-refresh -- the cache did not invalidate when the player-log inputs
     (historical CSVs / tracking parquet / legacy parquet) changed without a props change.

The test calls low-threshold-then-high and high-then-low and asserts each threshold's board is
identical regardless of order, then mutates the player-log signature and asserts the cache
invalidates. Results are compared with the volatile 'updated' timestamp stripped. Exits 0 when
the cache behaves correctly, 1 otherwise (so run_all_scorecards flags a regression).
"""
from __future__ import annotations

import app

# The two real threshold sets in the codebase: _card_pools (Menu/Daily Card) vs the floor page.
LOW = dict(limit=90, min_hit=52, min_games=8)
HIGH = dict(limit=24, min_hit=78, min_games=8)


def _norm(board: dict) -> dict:
    """Strip the per-call 'updated' timestamp so two correct boards compare equal."""
    return {k: v for k, v in (board or {}).items() if k != "updated"}


def _reset_floor_cache() -> None:
    app._NFL_FLOOR_BOARD_CACHE.clear()


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []

    # --- order independence -------------------------------------------------------------
    _reset_floor_cache()
    low_a = _norm(app.build_nfl_floor_board(**LOW))
    high_a = _norm(app.build_nfl_floor_board(**HIGH))

    _reset_floor_cache()
    high_b = _norm(app.build_nfl_floor_board(**HIGH))
    low_b = _norm(app.build_nfl_floor_board(**LOW))

    if low_a != low_b:
        issues.append("low-threshold board differs by call order (low->high vs high->low)")
    if high_a != high_b:
        issues.append("high-threshold board differs by call order (high->low vs low->high)")

    # Sanity: the params must actually take effect. Only assertable with live data; with an
    # empty board both are {} and equal, which is fine (nothing to contaminate).
    if low_a.get("available") and high_a.get("available"):
        if low_a == high_a:
            issues.append("low and high boards identical with live data -- params not applied")
        else:
            notes.append(
                f"params applied: low floor_count={low_a.get('floor_count')} "
                f"vs high floor_count={high_a.get('floor_count')}"
            )
    else:
        notes.append("no live floor data available -- order-independence checked on empty boards")

    # --- player-log signature invalidation ----------------------------------------------
    _reset_floor_cache()
    app.build_nfl_floor_board(**HIGH)
    sig_before = app._NFL_FLOOR_BOARD_CACHE.get("sig")

    original_sig = app._nfl_player_log_signature
    try:
        # Mock a changed player-log signature (as if a gamelog file was refreshed), props
        # file untouched. The floor cache must rebuild under the new composite signature.
        app._nfl_player_log_signature = lambda: (("__qc_mock_log__", 1, 1),)
        app.build_nfl_floor_board(**HIGH)
        sig_after = app._NFL_FLOOR_BOARD_CACHE.get("sig")
    finally:
        app._nfl_player_log_signature = original_sig

    if sig_before is None:
        issues.append("floor cache stored no signature -- cannot verify invalidation")
    elif sig_after == sig_before:
        issues.append("floor cache did NOT invalidate when the player-log signature changed")
    else:
        notes.append("floor cache invalidated on player-log signature change")

    # restore a clean, real cache state (self-heals on next real call anyway)
    _reset_floor_cache()

    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL FLOOR-CACHE QC")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No floor-cache determinism/invalidation issues detected.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
