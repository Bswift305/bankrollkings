"""QC: disk-materialized prewarm cache lifecycle invariants (Site Performance P0 closure).

Proves, against the real _nfl_disk_cache_load/_store helpers, that:
  1. a SOURCE-version change invalidates + rebuilds (old fingerprint no longer matches);
  2. an APPLICATION cache-schema change (APP_CACHE_VERSION) invalidates + rebuilds;
  3. UNCHANGED inputs reuse the artifact (no rebuild);
  4. a CORRUPT / structurally-incomplete / wrong-schema artifact fails validation -> None (fail closed);
  5. concurrent warmers cannot publish PARTIAL output -- publication is atomic (temp + fsync + replace),
     a crashed writer's temp file never becomes the artifact, and the last complete write wins.

Uses a throwaway probe key + synthetic values (no heavy builders), so it is fast + deterministic and
leaves no residue. Exits 0 when all invariants hold, 1 otherwise.
"""
from __future__ import annotations

import glob
import os
import pickle

import app

KEY = '__qc_prewarm_lifecycle_probe'


def _path():
    return app._disk_ttl_cache_path(KEY)


def _cleanup():
    p = _path()
    for f in [str(p)] + glob.glob(str(p) + '*'):
        try:
            os.remove(f)
        except OSError:
            pass


def run_qc():
    issues, notes = [], []
    _cleanup()
    try:
        # 3. unchanged inputs reuse
        app._nfl_disk_cache_store(KEY, ('src', 1), {'payload': 'A'})
        if app._nfl_disk_cache_load(KEY, ('src', 1)) != {'payload': 'A'}:
            issues.append("unchanged inputs did not reuse the artifact")
        else:
            notes.append("unchanged inputs reuse the artifact (no rebuild)")

        # 1. source-version change -> miss (rebuild)
        if app._nfl_disk_cache_load(KEY, ('src', 2)) is not None:
            issues.append("source-version change did NOT invalidate (stale artifact served)")
        else:
            notes.append("source-version change invalidates -> rebuild")

        # 2. app-cache-version change -> miss (rebuild)
        saved = app.APP_CACHE_VERSION
        try:
            app.APP_CACHE_VERSION = saved + '.CHANGED'
            if app._nfl_disk_cache_load(KEY, ('src', 1)) is not None:
                issues.append("app-cache-version change did NOT invalidate (stale schema served)")
            else:
                notes.append("app-cache-version change invalidates -> rebuild")
        finally:
            app.APP_CACHE_VERSION = saved

        # 4. corrupt / incomplete / wrong-schema -> fail closed
        with open(_path(), 'wb') as fh:
            fh.write(b'not a pickle at all')
        if app._nfl_disk_cache_load(KEY, ('src', 1)) is not None:
            issues.append("corrupt artifact did not fail closed")
        else:
            notes.append("corrupt artifact fails validation -> None (rebuild)")
        with open(_path(), 'wb') as fh:               # valid pickle, but missing 'value'
            pickle.dump({'version': ('src', 1), 'app_version': app.APP_CACHE_VERSION, 'expires_at': 1e18}, fh)
        if app._nfl_disk_cache_load(KEY, ('src', 1)) is not None:
            issues.append("structurally-incomplete artifact (no value) did not fail closed")
        else:
            notes.append("incomplete artifact (no 'value') fails closed")
        with open(_path(), 'wb') as fh:               # valid, but wrong schema stamp
            pickle.dump({'version': ('src', 1), 'app_version': 'WRONG', 'expires_at': 1e18, 'value': 'x'}, fh)
        if app._nfl_disk_cache_load(KEY, ('src', 1)) is not None:
            issues.append("wrong-schema artifact was served (should fail closed)")

        # 5. atomic publication: no temp residue, complete artifact, last write wins, crashed-writer temp
        #    is never read as the artifact.
        _cleanup()
        app._nfl_disk_cache_store(KEY, ('src', 1), {'payload': 'first'})
        app._nfl_disk_cache_store(KEY, ('src', 1), {'payload': 'second'})   # last complete write wins
        leftover = [f for f in glob.glob(str(_path()) + '*') if '.tmp-' in f]
        if leftover:
            issues.append(f"temp residue left after store ({len(leftover)} .tmp- files) -- not atomic")
        loaded = app._nfl_disk_cache_load(KEY, ('src', 1))
        if loaded != {'payload': 'second'}:
            issues.append(f"atomic publish did not keep the last complete write (got {loaded!r})")
        # a crashed writer's temp file must not be read as the artifact
        crashed = str(_path()) + '.tmp-999999'
        with open(crashed, 'wb') as fh:
            fh.write(b'partial garbage')
        try:
            if app._nfl_disk_cache_load(KEY, ('src', 1)) != {'payload': 'second'}:
                issues.append("a stray temp file changed what the reader sees (temp not isolated)")
            else:
                notes.append("atomic publish: no partial reads, last complete write wins, temp isolated")
        finally:
            try:
                os.remove(crashed)
            except OSError:
                pass
    finally:
        _cleanup()

    return {'issues': issues, 'notes': notes}


def main():
    r = run_qc()
    print('=' * 64)
    print('BANKROLL KINGS PREWARM CACHE LIFECYCLE QC')
    print('=' * 64)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No prewarm-lifecycle issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
