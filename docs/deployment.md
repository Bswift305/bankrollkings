# Deployment & Serving

The Flask dev server (`python app.py` → `app.run`) is single-process and stalls
under concurrency. Never use it for anything public. Serve through `wsgi.py`
instead.

## Linux / AWS (production)

```bash
gunicorn -c gunicorn.conf.py wsgi:application
```

`gunicorn.conf.py` sets `preload_app = True`, so the app loads and the
boot-time cache prewarm (in `wsgi.py`) runs **once in the master process before
workers fork**. Every worker then inherits the warm `DATAFRAME_CACHE` through
copy-on-write — no worker pays the cold CSV-parse cost on its first request.

Tunables (env vars): `BK_BIND`, `WEB_CONCURRENCY`, `BK_THREADS`, `BK_TIMEOUT`,
`BK_PREWARM_ON_BOOT` (set `0` to skip prewarm).

## Windows (local prod-like testing)

gunicorn is POSIX-only. Use waitress, which `wsgi.py` also supports:

```powershell
waitress-serve --listen=0.0.0.0:8000 wsgi:application
```

## Cache invalidation after a refresh

`DATAFRAME_CACHE` is per-process and keyed by file mtime, so when a refresh job
rewrites a CSV the running workers detect the change and re-parse it **lazily on
the next request** — meaning the first visitor after each refresh eats the cold
cost again, once per worker.

To avoid that, send gunicorn a graceful reload after the refresh chain finishes,
which re-runs the master prewarm and rolls workers without dropping requests:

```bash
kill -HUP "$(cat /run/bankrollkings.pid)"   # or: systemctl reload bankrollkings
```

On AWS this is the post-refresh hook the EventBridge/ECS refresh task should call
against the web tier (HUP signal, ECS rolling restart, or an authenticated
`/internal/prewarm` request — pick one when the infra is chosen).

## Why this matters for multi-daily refreshes

Props and other market data are scheduled to refresh several times a day. Each
refresh invalidates the cache, so without a post-refresh reload the cold-parse
penalty recurs all day. preload + prewarm + a reload hook keep every refresh
cycle warm.
