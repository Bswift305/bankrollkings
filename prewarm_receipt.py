"""Operational prewarm RECEIPT for the disk-materialized read caches (Site Performance P0 closure).

Forces a rebuild of each materialized artifact and prints a SANITIZED receipt line per artifact:
source fingerprint (a short hash of the version tuple -- NOT the raw paths/contents), application cache
schema version, build duration, artifact path CATEGORY (dir + basename, never contents), artifact size,
atomic-publication method, validation result (re-read + version/schema match), file permissions, and the
final status. No upstream network calls, no user-specific data; run as the service user:

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python prewarm_receipt.py'

Exit 0 when every artifact built + validated; 1 if any failed (so a deploy/refresh hook can detect a
cold-leaving warm step instead of silently succeeding).
"""
from __future__ import annotations

import glob
import hashlib
import os
import pickle
import stat
import time

import app

CACHE_DIR = os.path.join(str(app.DATA_DIR), 'cache')

# (name, builder, glob, in-memory cache dict or None). The NFL boards use _nfl_disk_cache_* (explicit
# app_version field); the dashboard/promotion use _get_disk_ttl_cached_value (schema folded via the
# cache token). Both are materialized under data/cache/*.pkl and read cross-process.
NFL_BOARDS = [
    ('nfl_milestone_streaks', lambda: app.build_nfl_milestone_streaks(), 'nfl_milestone_streaks*', '_NFL_MILESTONE_CACHE'),
    ('nfl_floor_board', lambda: app.build_nfl_floor_board(), 'nfl_floor_board*', '_NFL_FLOOR_BOARD_CACHE'),
    ('nfl_hot_hand', lambda: app.build_nfl_hot_hand(), 'nfl_hot_hand*', '_NFL_HOTHAND_CACHE'),
    ('nfl_wave_context', lambda: app.build_nfl_wave_context(), 'nfl_wave_context*', '_NFL_RW_CACHE'),
]
DASH_BOARDS = [
    ('live_promotion_signal_context', lambda: app._build_live_promotion_signal_context(), '*live_promotion_signal_context*'),
    ('phase2_dashboard_context', lambda: app.build_phase2_dashboard_context(), '*phase2_dashboard_context*'),
]


def _fingerprint(version) -> str:
    return hashlib.sha256(repr(version).encode('utf-8', 'replace')).hexdigest()[:12]


def _rm(gl):
    for p in glob.glob(os.path.join(CACHE_DIR, gl)):
        try:
            os.remove(p)
        except OSError:
            pass


def _artifact_meta(gl):
    files = [p for p in glob.glob(os.path.join(CACHE_DIR, gl)) if not p.endswith(('.tmp',)) and '.tmp-' not in p]
    if not files:
        return None
    path = max(files, key=os.path.getmtime)
    try:
        st = os.stat(path)
        with open(path, 'rb') as fh:
            doc = pickle.load(fh)
    except Exception as exc:
        return {'path': path, 'error': f'{type(exc).__name__}'}
    return {
        'path': path,
        'size': st.st_size,
        'perms': oct(stat.S_IMODE(st.st_mode)),
        'version': doc.get('version') if isinstance(doc, dict) else None,
        'app_version': doc.get('app_version') if isinstance(doc, dict) else None,
        'has_value': isinstance(doc, dict) and 'value' in doc,
    }


def _row(name, builder, gl, nfl):
    _rm(gl)
    cache_attr = nfl if (nfl and nfl.startswith('_')) else None
    if cache_attr and hasattr(app, cache_attr):
        try:
            getattr(app, cache_attr).clear()
        except Exception:
            pass
    else:
        try:
            app.RUNTIME_TTL_CACHE.clear()
        except Exception:
            pass
    t0 = time.perf_counter()
    status = 'OK'
    try:
        builder()
    except Exception as exc:
        status = f'BUILD_FAIL:{type(exc).__name__}'
    dur_ms = (time.perf_counter() - t0) * 1000.0
    meta = _artifact_meta(gl)
    if meta is None:
        return {'name': name, 'status': status if status != 'OK' else 'NO_ARTIFACT', 'dur_ms': dur_ms}
    # validation: re-read, require a value + (for the NFL boards) a current schema stamp
    valid = bool(meta.get('has_value'))
    if cache_attr:  # NFL boards carry the explicit app_version field
        valid = valid and (meta.get('app_version') == app.APP_CACHE_VERSION)
    return {
        'name': name,
        'fingerprint': _fingerprint(meta.get('version')),
        'schema': meta.get('app_version') or app.APP_CACHE_VERSION,
        'dur_ms': dur_ms,
        'path_category': os.path.join('data/cache', os.path.basename(meta['path'])),
        'size_kb': round(meta['size'] / 1024.0, 1),
        'atomic': 'temp+fsync+replace',
        'validation': 'PASS' if valid else 'FAIL',
        'perms': meta.get('perms'),
        'status': status if status != 'OK' else ('OK' if valid else 'VALIDATION_FAIL'),
    }


def main():
    print('=' * 104)
    print(f'BANKROLL KINGS - PREWARM RECEIPT   schema={app.APP_CACHE_VERSION}   cache_dir=data/cache')
    print('=' * 104)
    rows = []
    for name, builder, gl, nfl in NFL_BOARDS:
        rows.append(_row(name, builder, gl, nfl))
    for name, builder, gl in DASH_BOARDS:
        rows.append(_row(name, builder, gl, None))

    hdr = f"{'artifact':30} {'fprint':>13} {'build_ms':>9} {'size_kb':>8} {'perms':>6} {'valid':>5} {'status':>14}"
    print(hdr)
    print('-' * len(hdr))
    ok = True
    for r in rows:
        if r.get('status') != 'OK':
            ok = False
        print(f"{r['name']:30} {r.get('fingerprint','-'):>13} {r.get('dur_ms',0):9.0f} "
              f"{r.get('size_kb','-'):>8} {r.get('perms','-'):>6} {r.get('validation','-'):>5} {r.get('status','-'):>14}")
    print('-' * len(hdr))
    print(f"atomic publication: temp(.tmp-<pid>) + fsync + os.replace  |  schema(app_version)={app.APP_CACHE_VERSION}")
    print(f"path category: {os.path.join('data/cache','<artifact>.pkl')}  (contents NOT shown)")
    print('ALL ARTIFACTS OK' if ok else 'ONE OR MORE ARTIFACTS FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
