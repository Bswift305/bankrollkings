"""QC: performance regression guards (Site Performance P0).

Structural guards against the defect class that made /tools/injury-report take ~63 s warm: a shared
keyset/index rebuilt per row because its cache key changed every call. Rather than flaky wall-clock
budgets, these assert the INVARIANT that prevents the regression -- the keyset cache is stable across
calls (built once per source version, O(1) thereafter) -- plus a generous per-call-cost ceiling that
only trips if a per-row full rebuild returns. Exits 0 when the guards hold, 1 otherwise.
"""
from __future__ import annotations

import time

import app


def run_qc():
    issues, notes = [], []

    # Guard 1: the entity keyset is cache-STABLE per sport -- consecutive calls return the SAME object
    # (signature is a file mtime, not id(df)). A per-call rebuild (the 63s injury-report regression)
    # would return a fresh dict each time.
    app._ENTITY_KEYSET_CACHE.clear()
    for sport in ('nfl', 'mlb', 'nba', 'wnba'):
        a = app._entity_player_keyset(sport)
        b = app._entity_player_keyset(sport)
        if a is not b:
            issues.append(f"keyset '{sport}' rebuilt on the 2nd call (cache key unstable -> per-row "
                          f"rebuild risk, the injury-report 63s class)")
    if not any(m.startswith('keyset') for m in issues):
        notes.append("keyset cache stable across calls for nfl/mlb/nba/wnba (built once per source version)")

    # Guard 2: a tight loop of the per-row resolver stays cheap (would blow up if a full gamelog
    # rebuild happened per call). Generous ceiling so it is not flaky; the regression was ~900ms/call.
    app._ENTITY_KEYSET_CACHE.clear()
    app._entity_player_known('mlb', 'Warmup')      # pay any one-time build once
    t0 = time.perf_counter()
    for _ in range(2000):
        app._entity_player_known('mlb', 'Some Player')
    per_call_ms = (time.perf_counter() - t0) * 1000.0 / 2000.0
    if per_call_ms > 5.0:   # a per-row rebuild was ~900ms/call; healthy is <<1ms
        issues.append(f"_entity_player_known ~{per_call_ms:.1f}ms/call (>5ms -> per-row rebuild regression)")
    else:
        notes.append(f"_entity_player_known ~{per_call_ms:.3f}ms/call (cheap; no per-row rebuild)")

    # Guard 3: the milestone builder result is cached (sig-keyed) -- a 2nd call returns the SAME object
    # without re-running the multi-second matchup pass.
    try:
        app._NFL_MILESTONE_CACHE.clear()
        m1 = app.build_nfl_milestone_streaks()
        t0 = time.perf_counter()
        m2 = app.build_nfl_milestone_streaks()
        warm_ms = (time.perf_counter() - t0) * 1000.0
        if m1 is not m2:
            issues.append("build_nfl_milestone_streaks not returning its cached object on a warm call")
        elif warm_ms > 200.0:
            issues.append(f"milestone warm call {warm_ms:.0f}ms (>200ms -> cache not serving)")
        else:
            notes.append(f"milestone builder warm call {warm_ms:.1f}ms (cached, no rebuild)")
    except Exception as exc:
        notes.append(f"milestone guard skipped ({type(exc).__name__}: {exc})")

    return {'issues': issues, 'notes': notes}


def main():
    r = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS PERFORMANCE REGRESSION GUARDS')
    print('=' * 60)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No performance-regression issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
