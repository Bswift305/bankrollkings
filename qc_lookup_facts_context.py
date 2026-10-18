"""QC for Lookup Phase 3 descriptive Facts + Context distributions."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

import app as web


def _logs():
    return pd.DataFrame([
        {"season": 2026, "week": 1, "rushing_yards": 10, "receiving_yards": 5, "attempts": 0},
        {"season": 2026, "week": 2, "rushing_yards": 20, "receiving_yards": 10, "attempts": 0},
        {"season": 2026, "week": 3, "rushing_yards": 30, "receiving_yards": pd.NA, "attempts": 0},
        {"season": 2025, "week": 18, "rushing_yards": 999, "receiving_yards": 999, "attempts": 0},
    ])


def qc_exact_descriptive_math():
    markets = [{"stat_key": "rushing_yards", "stat": "Rush Yds"}]
    ctx = web._nfl_lookup_facts_context(_logs(), 2026, markets)
    row = ctx["distributions"][0]
    ok = (ctx["availability"] == "verified" and ctx["through_week"] == 3 and
          row["median"] == 20.0 and row["p25"] == 15.0 and row["p75"] == 25.0 and
          row["std_dev"] == 8.2 and row["n"] == 3 and row["unavailable_n"] == 0)
    return ok, str(row)


def qc_combined_never_zero_fills():
    markets = [{"stat_key": "rush_rec_yds", "stat": "Rush + Rec Yds"}]
    row = web._nfl_lookup_facts_context(_logs(), 2026, markets)["distributions"][0]
    # Week 3 has no receiving component and must be absent, not treated as 30 + 0.
    ok = (row["n"] == 2 and row["candidate_n"] == 3 and row["unavailable_n"] == 1 and
          row["availability"] == "partial" and row["median"] == 22.5)
    return ok, str(row)


def _context():
    return {
        "query": "Runner One", "status": "ok",
        "player": {"player": "Runner One", "team": "ARI", "pos": "RB", "player_id": "123"},
        "candidates": [], "matchup": "A @ B", "feed_ts": "2026-10-18 05:00",
        "markets": [], "surfaces": {},
        "lookup_facts_context": web._nfl_lookup_facts_context(
            _logs(), 2026, [{"stat_key": "rushing_yards", "stat": "Rush Yds"}]
        ),
    }


def _render(flag):
    old_testing = web.app.testing
    web.app.testing = True
    try:
        with tempfile.TemporaryDirectory(prefix="lookup_facts_qc_") as td:
            env = {"LOOKUP_CHANGE_ENABLED": flag,
                   "LOOKUP_CHANGE_DB_PATH": str(Path(td) / "changes.db")}
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch.object(web, "evaluate_nfl_player", return_value=_context()), \
                 mock.patch.object(web, "get_current_user", return_value={"user_id": "user-a"}), \
                 mock.patch.object(web, "is_owner_user", return_value=True), \
                 mock.patch.object(web, "_card_prefs_uid", return_value="user-a"):
                with web.app.test_client() as client:
                    return client.get("/tools/player-check?q=Runner+One").get_data(as_text=True)
    finally:
        web.app.testing = old_testing


def qc_dark_and_honest_render():
    dark = _render("0")
    visible = _render("1")
    forbidden = ("Consistency Score", "recommended pick", "Environment Stable")
    ok = ("Facts + Context" not in dark and "Facts + Context" in visible and
          "not projections, rankings, or recommendations" in visible and
          "n=3" in visible and "Environment Stability:</b> unavailable" in visible and
          not any(term in visible for term in forbidden))
    return ok, f"dark={('Facts + Context' in dark)} visible={('Facts + Context' in visible)}"


CHECKS = [
    ("exact descriptive math", qc_exact_descriptive_math),
    ("combined stats never zero-fill", qc_combined_never_zero_fills),
    ("dark flag + honest render", qc_dark_and_honest_render),
]


def main():
    failures = 0
    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += int(not ok)
    print(f"Lookup Facts + Context QC: {len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
