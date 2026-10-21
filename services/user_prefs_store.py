"""Atomic, multi-worker-safe per-user preference JSON store.

One JSON file per account at ``{prefs_dir}/{uid}.json`` holding independent top-level keys (``card``,
``home``, ``seen_start``, ``greenlight``, …). Shared by every preference writer so they cannot corrupt each
other. Guarantees:

- **Atomic writes** — a temp file in the same directory + ``fsync`` + ``os.replace``; a reader ever only sees
  the complete old or complete new file (no torn/truncated JSON), and a crash mid-write cannot leave a
  partial file at the real path.
- **Multi-worker safety** — an exclusive file lock (``fcntl`` on POSIX / prod gunicorn workers) plus an
  in-process thread lock serialize read-merge-write, so a concurrent writer of a *different* key is never
  clobbered (no lost update).
- **Key-scoped mutation** — ``mutate(d)`` edits only its own top-level key; everything else is preserved.
- **Fail-safe reads** — a missing or corrupt file is treated as ``{}`` (never raises to the caller).

Pure/stdlib only, no app import, so it is unit-testable without the Flask app (``qc_user_prefs_store.py``).
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading

_TLOCK = threading.Lock()  # in-process guard; the file lock covers cross-process (prod worker) races


@contextlib.contextmanager
def file_lock(path):
    """Best-effort exclusive lock around a prefs file, via a sidecar ``.lock`` (never replaced). fcntl on
    POSIX; a safe degrade elsewhere (in-process threads are still serialized by the caller's thread lock)."""
    fh = None
    try:
        fh = open(path + '.lock', 'a+')
        if os.name == 'posix':
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except (OSError, ImportError):
                pass
        yield
    finally:
        if fh is not None:
            try:
                if os.name == 'posix':
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except (OSError, ImportError):
                pass
            fh.close()


def atomic_write_json(path, data):
    """Serialize ``data`` to ``path`` atomically (temp in the same dir + fsync + replace)."""
    d = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.prefs-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_prefs(prefs_dir, uid):
    """The raw prefs dict for ``uid`` (``{}`` if absent, empty-uid, or corrupt). Never raises."""
    if not uid:
        return {}
    try:
        with open(os.path.join(prefs_dir, f'{uid}.json'), encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def update_prefs(prefs_dir, uid, mutate):
    """Atomic, locked read-merge-write of ``{prefs_dir}/{uid}.json``. ``mutate(d)`` edits only its own
    top-level key. Anon/empty uid is a no-op (returns False and writes nothing); returns True on write."""
    if not uid:
        return False
    os.makedirs(prefs_dir, exist_ok=True)
    path = os.path.join(prefs_dir, f'{uid}.json')
    with _TLOCK, file_lock(path):
        try:
            with open(path, encoding='utf-8') as fh:
                d = json.load(fh)
            if not isinstance(d, dict):
                d = {}
        except (OSError, ValueError):
            d = {}
        mutate(d)
        atomic_write_json(path, d)
    return True
