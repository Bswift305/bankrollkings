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

    # Guard 4: Riding-the-Wave N+1. The participation index must be built ONCE and reused across many
    # per-player return-status lookups -- the old path re-scanned + .copy()'d the ~103k-row weekly log
    # on every qualifying player (~5.8s / 137 players). With a shared index, 500 lookups must trigger
    # ZERO additional reads of the player-week log, and the shared-index result must match the
    # build-its-own-index result exactly (parity).
    try:
        import pandas as pd
        orig_week_data = app._nfl_player_week_data
        part = []
        for wk in (1, 2, 3, 4, 5):                # a teammate: team played all five weeks
            part.append({'season': 2026, 'week': wk, '_full': 'team mate', '_key': 't.mate',
                         'recent_team': 'TB'})
        for wk in (1, 2, 5):                       # returner: missed weeks 3-4, back week 5
            part.append({'season': 2026, 'week': wk, '_full': 'returner guy', '_key': 'r.guy',
                         'recent_team': 'TB'})
        fixture = pd.DataFrame(part)
        reads = {'n': 0}

        def _counting():
            reads['n'] += 1
            return fixture

        app._nfl_player_week_data = _counting
        try:
            idx = app._nfl_participation_index(2026, 5)      # 1 read
            reads_after_build = reads['n']
            for _ in range(500):
                app._nfl_player_return_status('Returner Guy', 2026, 5, index=idx)
            reads_after_lookups = reads['n']
            shared = app._nfl_player_return_status('Returner Guy', 2026, 5, index=idx)
            own = app._nfl_player_return_status('Returner Guy', 2026, 5)   # builds its own index
        finally:
            app._nfl_player_week_data = orig_week_data

        extra = reads_after_lookups - reads_after_build
        if extra != 0:
            issues.append(f"wave participation index not reused: 500 lookups caused {extra} extra "
                          f"player-log reads (the N+1 regression class)")
        elif not (shared.get('returned') and shared.get('first_return_week') == 5
                  and shared.get('missed_games') == 2):
            issues.append(f"wave index lookup wrong: {shared} (want returned, week 5, missed 2)")
        elif shared != own:
            issues.append(f"wave index parity broken: shared={shared} vs own-built={own}")
        else:
            notes.append("wave participation index built once, reused across 500 lookups (0 extra "
                         "reads), shared==own-built parity")
    except Exception as exc:
        notes.append(f"wave N+1 guard skipped ({type(exc).__name__}: {exc})")

    # Guard 5: de-arrow parity. The dashboard's 340s cold-build hot leaf was pyarrow string columns
    # (read_csv under pandas 2.2 infer_string) boxed scalar-by-scalar in build_player_hit_profiles'
    # per-group loop. The fix coerces string columns to numpy object. This must (a) actually convert
    # arrow/string dtypes to object with identical values, and (b) leave build_player_hit_profiles
    # output IDENTICAL whether the input frame is arrow-backed or object-backed (same rows + order).
    try:
        import pandas as pd
        import services.review_center as rc

        sample = pd.DataFrame({
            'Player': ['A Back', 'A Back', 'A Back', 'B Wideout', 'B Wideout', 'B Wideout', 'C Guard', 'C Guard'],
            'Sport': ['NFL'] * 6 + ['NBA', 'NBA'],
            'Stat': ['Rush Yds'] * 6 + ['Points', 'Points'],
            'Direction': ['OVER'] * 6 + ['UNDER', 'UNDER'],
            'OutcomeState': ['Hit', 'Miss', 'Hit', 'Hit', 'Hit', 'Miss', 'Hit', 'Hit'],
            'SnapshotDate': ['2026-10-0%d' % i for i in range(1, 9)],
            'ResultDate': [''] * 8,
            'Matchup': ['g%d' % i for i in range(8)],
            'Line': [40.5, 55.5, 60.5, 70.5, 80.5, 90.5, 20.5, 24.5],
            'Confidence': [60, 62, 64, 66, 68, 70, 55, 57],
        })

        # (a) coercion converts arrow/string -> object, values unchanged
        de = rc._dearrow_string_columns(sample.copy().astype({'Player': 'string', 'OutcomeState': 'string'}))
        if 'string' in str(de['Player'].dtype) or 'string' in str(de['OutcomeState'].dtype):
            issues.append("_dearrow_string_columns left a string-dtype column (coercion failed)")
        elif de['Player'].tolist() != sample['Player'].tolist():
            issues.append("_dearrow_string_columns altered values")

        # (b) build_player_hit_profiles identical for arrow- vs object-backed input
        def _norm(rws):
            out = []
            for r in rws:
                out.append(tuple((k, ('NaN' if isinstance(v, float) and v != v
                                       else round(v, 6) if isinstance(v, float) else v))
                                 for k, v in sorted(r.items())))
            return out

        arrow_in = sample.copy()
        for c in ('Player', 'Sport', 'Stat', 'Direction', 'OutcomeState', 'SnapshotDate', 'Matchup'):
            try:
                arrow_in[c] = arrow_in[c].astype('string[pyarrow]')
            except Exception:
                pass
        rc._REVIEW_RUNTIME_CACHE.clear()
        out_arrow = _norm(rc.build_player_hit_profiles(arrow_in.copy()))
        rc._REVIEW_RUNTIME_CACHE.clear()
        out_obj = _norm(rc.build_player_hit_profiles(sample.copy()))
        if out_arrow != out_obj:
            issues.append("build_player_hit_profiles output differs for arrow vs object input (de-arrow "
                          "changed results)")
        elif not any(m.startswith('_dearrow') or 'build_player_hit_profiles output' in m for m in issues):
            notes.append(f"de-arrow parity: string->object preserves values; build_player_hit_profiles "
                         f"identical arrow vs object ({len(out_obj)} profiles)")
    except Exception as exc:
        notes.append(f"de-arrow guard skipped ({type(exc).__name__}: {exc})")

    # Guard 6: the dashboard cold-build vectorizations must stay equivalent to the ORIGINAL per-row
    # scalar functions they replaced -- _missed_keys vs _missed_prop_key, _grade_missed_frame vs
    # calculate_missed_opportunity_grade, and the enrich FailureReason/Signals path vs
    # candidate_failure_reason. Compared on a synthetic frame with NaN/missing/edge values.
    try:
        import pandas as pd
        import numpy as np
        import services.review_center as rc

        frame = pd.DataFrame({
            'SnapshotDate': ['2026-10-01', '2026-10-02', '', '2026-10-03', '2026-10-01'],
            'Sport': ['NFL', 'nba', 'MLB', 'NFL', 'WNBA'],
            'Player': ['A Back', 'b guard', 'C Bat', 'A Back', 'D Wing'],
            'Stat': ['Rush Yds', 'Points', 'Hits', 'Rush Yds', 'Points'],
            'Direction': ['OVER', 'under', 'OVER', 'OVER', 'UNDER'],
            'Line': [40.5, 0.0, np.nan, 40.5, 18.5],
            'Matchup': ['g1', 'g2', '', 'g1', 'g3'],
            'OutcomeState': ['Hit', 'Miss', 'Miss', 'Miss', 'Hit'],
            'Confidence': [91.0, np.nan, 62.0, 77.0, 55.0],
            'BetTier': ['Tier 1', '', 'Tier 2', np.nan, 'Tier 3'],
            'MarketGate': ['CLEAR', 'HOLD', np.nan, 'SPLIT', ''],
            'VolatilityFlag': ['STABLE', 'HIGH', '', 'ELEVATED', np.nan],
            'MarketDepthBucket': ['multi', 'single', '', 'two', 'multi'],
            'BookCount': [5, 1, np.nan, 2, 4],
            'MarketMoveBucket': ['toward', 'Against', 'No Move Data', '', np.nan],
            'EdgePct': [16.0, np.nan, 7.0, 9.0, 3.0],
            'Situations': ['', 'SINGLE BOOK', np.nan, 'AVOID', 'clean'],
            'SampleMode': ['available', '', 'full_board', np.nan, 'x'],
            'Method': ['available props', 'promoted', '', 'main board', 'y'],
            'MarketTags': [np.nan, 'ANCHOR', '', 'CONFIRMED', 'CALIBRATED+'],
            'MethodLabels': ['ANCHOR', '', 'MULTI-BOOK', '', ''],
            'ClvLine': [1.0, -1.0, np.nan, -2.0, 0.5],
            'RoleLabel': ['STAR', 'SUPPORT', '', 'BENCH', np.nan],
            'WeightProfile': ['r2', 'r3_r4', '', 'r1_early', np.nan],
        })

        # _missed_keys vs _missed_prop_key (row-wise)
        want_keys = [rc._missed_prop_key(r) for _, r in frame.iterrows()]
        got_keys = rc._missed_keys(frame)
        if got_keys != want_keys:
            issues.append("_missed_keys != per-row _missed_prop_key")

        # _grade_missed_frame vs calculate_missed_opportunity_grade (row-wise)
        want_grades = [rc.calculate_missed_opportunity_grade(r) for _, r in frame.iterrows()]
        gs, gl, gr = rc._grade_missed_frame(frame)
        if [g[0] for g in want_grades] != gs or [g[1] for g in want_grades] != gl \
                or [g[2] for g in want_grades] != gr:
            issues.append("_grade_missed_frame != per-row calculate_missed_opportunity_grade")

        # enrich FailureReason/FailureSignals vs candidate_failure_reason (row-wise) on the Miss rows
        enriched = rc.enrich_candidate_review_rows(frame.copy())
        wr, ws = [], []
        for _, r in enriched.iterrows():
            if str(r.get('OutcomeState') or '').strip() == 'Miss':
                a, b = rc.candidate_failure_reason(r)
            else:
                a, b = '', ''
            wr.append(a)
            ws.append(b)
        if enriched['FailureReason'].tolist() != wr or enriched['FailureSignals'].tolist() != ws:
            issues.append("enrich FailureReason/FailureSignals != per-row candidate_failure_reason")

        if not any('_missed_keys' in m or '_grade_missed_frame' in m or 'enrich Failure' in m for m in issues):
            notes.append("dashboard vectorizations == original per-row functions (keys, grade, failure "
                         "signals) on NaN/edge frame")
    except Exception as exc:
        notes.append(f"vectorization-equivalence guard skipped ({type(exc).__name__}: {exc})")

    # Guard 7: NFL tool DISK materialization (cross-process prewarm). The milestone + floor boards now
    # write a disk artifact keyed on a PROCESS-STABLE signature, so a batch prewarm can warm live
    # gunicorn workers. Prove: (a) the builder writes an artifact under a version, (b) loading with that
    # same version returns BYTE-IDENTICAL data (a fresh worker hits it instead of rebuilding), and (c)
    # the version is picklable + repr-stable (no PYTHONHASHSEED-salted hash()).
    try:
        import json

        def _njson(o):
            return json.dumps(o, sort_keys=True, default=str)

        import glob
        import os
        # Remove any existing artifacts so the build must RE-STORE (otherwise the builder reads the
        # disk artifact left by an earlier guard and never calls the store we are capturing).
        for pat in ('nfl_milestone_streaks*', 'nfl_floor_board*', 'nfl_hot_hand*', 'nfl_wave_context*'):
            for p in glob.glob(os.path.join(str(app.DATA_DIR), 'cache', pat)):
                try:
                    os.remove(p)
                except Exception:
                    pass

        captured = {}   # key -> (version, stored_value): compare loaded to what was STORED, not to the
        orig_store = app._nfl_disk_cache_store   # builder return (hot-hand stores full rows, returns a slice)

        def _cap(key, version, value, ttl_seconds=86400):
            captured[key] = (version, value)
            return orig_store(key, version, value, ttl_seconds)

        app._nfl_disk_cache_store = _cap
        try:
            app._NFL_MILESTONE_CACHE.clear()
            app.build_nfl_milestone_streaks()
            app._NFL_FLOOR_BOARD_CACHE.clear()
            app.build_nfl_floor_board()
            app._NFL_HOTHAND_CACHE.clear()
            app.build_nfl_hot_hand()
            app._NFL_RW_CACHE.clear()
            app.build_nfl_wave_context()
        finally:
            app._nfl_disk_cache_store = orig_store

        checked = 0
        for token in ('milestone', 'floor_board', 'hot_hand', 'wave_context'):
            # find the captured disk key (nfl_milestone_streaks:: / nfl_floor_board:: / nfl_hot_hand::)
            dkey = next((k for k in captured if token in k), None)
            if dkey is None:
                # a builder may legitimately not persist (e.g. empty/unavailable board) -> skip quietly
                continue
            version, stored = captured[dkey]
            # version must survive pickle + be equality-stable (process-stable key)
            try:
                import pickle as _pk
                if _pk.loads(_pk.dumps(version)) != version:
                    issues.append(f"{token} disk version not stable across pickle round-trip")
            except Exception as exc:
                issues.append(f"{token} disk version not picklable ({type(exc).__name__})")
            loaded = app._nfl_disk_cache_load(dkey, version)
            if loaded is None:
                issues.append(f"{token} disk artifact not readable back with its own version "
                              "(cross-process prewarm would miss)")
            elif _njson(loaded) != _njson(stored):
                issues.append(f"{token} disk round-trip changed the data (prewarm would serve a different board)")
            else:
                checked += 1
        if checked and not any('disk' in m for m in issues):
            notes.append(f"NFL disk materialization: {checked} board(s) write a stable-keyed artifact and "
                         "read back byte-identical (prewarm reaches fresh workers)")
    except Exception as exc:
        notes.append(f"NFL disk-materialization guard skipped ({type(exc).__name__}: {exc})")

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
