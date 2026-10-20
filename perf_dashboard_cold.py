"""READ-ONLY cold-build timer for /dashboard (Site Performance P0, Phase B2).

Proves the de-arrow fix on prod by FORCING a true cold recompute, defeating the three caches that would
otherwise hide it (in-memory TTL, disk pkl, and the Player_Profile_Index.csv artifact fast-path). It
writes nothing new -- it only lets the builders regenerate the same caches/artifact they already write
on any cold miss. Run on prod via SSM:

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python perf_dashboard_cold.py'

Reports: build_player_hit_profiles recompute (the former 340s pyarrow-boxing leaf), the full cold
dashboard build, and the warm (cached) read. Expectation after the fix: the recompute and the cold
build drop from the ~200-340s range to a few seconds; the warm read is sub-second.
"""
from __future__ import annotations

import time

import app
import services.review_center as rc


def _clear_mem():
    try:
        rc._REVIEW_RUNTIME_CACHE.clear()
    except Exception:
        pass
    try:
        app.RUNTIME_TTL_CACHE.clear()
    except Exception:
        pass


def main():
    print("=" * 72)
    print("DASHBOARD COLD-BUILD TIMER (forced recompute; read-only)")
    print("=" * 72)

    # 1) The former hot leaf in isolation, with the artifact fast-path DISABLED so it truly recomputes
    #    the de-arrowed per-group pass (not just read Player_Profile_Index.csv).
    orig_fresh = rc._artifact_is_fresh
    rc._artifact_is_fresh = lambda *a, **k: False
    try:
        _clear_mem()
        df = rc.load_all_prop_results_for_review()
        rows = int(len(df)) if df is not None else 0
        t = time.perf_counter()
        profiles = rc.build_player_hit_profiles(df)
        print(f"build_player_hit_profiles RECOMPUTE: {time.perf_counter() - t:7.1f}s  "
              f"({len(profiles)} profiles over {rows} graded rows)")
    except Exception as exc:
        print(f"build_player_hit_profiles err: {type(exc).__name__}: {exc}")
    finally:
        rc._artifact_is_fresh = orig_fresh

    # 2) Full cold dashboard build: empty in-memory caches AND force every disk-TTL read to miss, so the
    #    whole context (promotion + missed + clv + ev-preview + ops) is recomputed end to end.
    orig_read = app._read_disk_ttl_cached_value
    orig_get = app._get_disk_ttl_cached_value
    app._read_disk_ttl_cached_value = lambda *a, **k: (False, None)
    app._get_disk_ttl_cached_value = lambda key, ttl, builder, version=None: builder()
    try:
        _clear_mem()
        t = time.perf_counter()
        app.build_phase2_dashboard_context()
        print(f"build_phase2_dashboard_context COLD:  {time.perf_counter() - t:7.1f}s")
    except Exception as exc:
        print(f"dashboard cold err: {type(exc).__name__}: {exc}")
    finally:
        app._read_disk_ttl_cached_value = orig_read
        app._get_disk_ttl_cached_value = orig_get

    # 3) Warm read -- what a real visitor pays once the batch prewarm has populated the caches. Call
    #    once to populate normally (caches re-enabled), then time the SECOND call (the true warm read).
    try:
        app.build_phase2_dashboard_context()          # populate (writes disk pkl + in-memory TTL)
        t = time.perf_counter()
        app.build_phase2_dashboard_context()          # warm read
        print(f"build_phase2_dashboard_context WARM:  {(time.perf_counter() - t) * 1000:7.1f}ms")
    except Exception as exc:
        print(f"dashboard warm err: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
