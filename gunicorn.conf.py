"""Gunicorn configuration for Bankroll Kings (Linux / AWS).

Run with:  gunicorn -c gunicorn.conf.py wsgi:application

Tunable via environment:
    BK_BIND          bind address          (default 0.0.0.0:8000)
    WEB_CONCURRENCY  number of workers     (default = CPU count, min 2)
    BK_THREADS       threads per worker    (default 4)
    BK_TIMEOUT       worker timeout (sec)  (default 120)
"""
import multiprocessing
import os

bind = os.environ.get('BK_BIND', '0.0.0.0:8000')

# Read-mostly, IO-bound workload (CSV/snapshot reads), so threaded workers give
# good concurrency without N full copies of the interpreter.
worker_class = 'gthread'
workers = int(os.environ.get('WEB_CONCURRENCY', max(2, multiprocessing.cpu_count())))
threads = int(os.environ.get('BK_THREADS', '4'))

# Load the app (and run the boot-time prewarm in wsgi.py) once in the master
# before forking, so every worker inherits the warm DATAFRAME_CACHE via
# copy-on-write instead of each paying the cold parse on its first request.
preload_app = True

timeout = int(os.environ.get('BK_TIMEOUT', '120'))
graceful_timeout = 30
keepalive = 5

accesslog = '-'
errorlog = '-'
