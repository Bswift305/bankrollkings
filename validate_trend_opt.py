"""One-off equivalence check: optimized build_trend_opportunity_history vs the
legacy implementation, on the real gamelogs. Compares the cached summary AND the
full row set so we can trust the optimization doesn't change /trend-board output.

Run:  source venv/bin/activate && python validate_trend_opt.py
Exit 0 if identical for every case, 1 otherwise.
"""

from __future__ import annotations

import sys
import time

from app import (
    load_gamelogs,
    load_player_snapshot,
    load_current_team_overrides,
    build_current_team_map,
    build_trend_opportunity_history,
    _build_trend_opportunity_history_legacy,
    summarize_trend_opportunities,
)


def _norm(rows):
    out = []
    for r in rows:
        out.append((
            r.get("player"), r.get("team"), r.get("stat"), r.get("threshold"),
            r.get("side"), r.get("streak_len_before"), r.get("line"),
            r.get("history_avg"), r.get("value"), bool(r.get("continued")),
            str(r.get("date")), str(r.get("opp")),
        ))
    out.sort(key=lambda t: tuple("" if x is None else str(x) for x in t))
    return out


def main():
    gamelogs = load_gamelogs()
    ctmap = build_current_team_map(load_gamelogs(), load_player_snapshot(), load_current_team_overrides())
    ok = True
    for sample_mode in ("current", "season", "all"):
        t = time.time()
        new_rows = build_trend_opportunity_history(gamelogs, ctmap, team_filter=None, sample_mode=sample_mode, stat_filter="all")
        t_new = time.time() - t
        t = time.time()
        old_rows = _build_trend_opportunity_history_legacy(gamelogs, ctmap, team_filter=None, sample_mode=sample_mode, stat_filter="all")
        t_old = time.time() - t

        new_sum = summarize_trend_opportunities(new_rows)
        old_sum = summarize_trend_opportunities(old_rows)
        rows_match = _norm(new_rows) == _norm(old_rows)
        sum_match = new_sum == old_sum

        status = "OK" if (rows_match and sum_match) else "MISMATCH"
        if not (rows_match and sum_match):
            ok = False
        print(f"[{status}] sample={sample_mode}: rows new={len(new_rows)} old={len(old_rows)} "
              f"rows_match={rows_match} summary_match={sum_match} | "
              f"new={t_new:.1f}s old={t_old:.1f}s speedup={ (t_old/t_new) if t_new else 0:.0f}x")
        if not sum_match:
            print("   new_summary:", new_sum)
            print("   old_summary:", old_sum)
        if not rows_match:
            ns, os_ = _norm(new_rows), _norm(old_rows)
            only_new = [r for r in ns if r not in set(os_)][:3]
            only_old = [r for r in os_ if r not in set(ns)][:3]
            print("   sample only-in-new:", only_new)
            print("   sample only-in-old:", only_old)

    print("\n=== VALIDATION:", "PASS" if ok else "FAIL", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
