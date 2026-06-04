"""Production WSGI entrypoint.

Use this with a real WSGI server instead of Flask's built-in dev server
(`app.run`), which is single-process and stalls under concurrency:

    # Linux / AWS
    gunicorn -c gunicorn.conf.py wsgi:application

    # Windows (local prod-like testing; gunicorn is POSIX-only)
    waitress-serve --listen=0.0.0.0:8000 wsgi:application

On boot the heavy data caches are warmed once so the first real visitor does
not pay the cold CSV-parse cost. Set BK_PREWARM_ON_BOOT=0 to skip it.
"""
from __future__ import annotations

import os

from app import app, prewarm_caches

# WSGI servers look for `application` by default.
application = app


def _truthy(value: str | None) -> bool:
    return str(value or '').strip().lower() not in ('', '0', 'false', 'no', 'off')


if _truthy(os.environ.get('BK_PREWARM_ON_BOOT', '1')):
    _warmed = prewarm_caches()
    print(f"[PREWARM] warmed: {', '.join(_warmed) if _warmed else 'none'}")
