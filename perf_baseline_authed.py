"""READ-ONLY authenticated server-render baseline for the Site Performance P0 (Phase A).

Boots the Flask app in-process, bypasses the plan/access gate as a logged-in owner, and times each
representative member route's FULL server render (the server-side component of TTFB that backend work
drives), with response size and a crude rendered-row proxy. GET-only; no writes, no external calls it
wouldn't already make, no user data printed. Run on prod via SSM with the venv python:

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python perf_baseline_authed.py'

Reports, per route and per run: status, server-render ms, KB, row-proxy. Run 1 is the cold-process
first hit (caches empty); runs 2-3 are warm. Shows median + worst. This is the backend baseline; Core
Web Vitals (LCP/INP/CLS) still need a real browser (devtools/Lighthouse on a logged-in session).
"""
from __future__ import annotations

import time
import statistics
import re
import sys

import app

# Representative routes. Args chosen to exercise real data where a path/query entity is needed.
ROUTES = [
    ("landing", "/"),
    ("login", "/login"),
    ("dashboard", "/dashboard"),
    ("nfl-hub", "/nfl"),
    ("nfl-matchup", "/tools/nfl-matchup"),
    ("nfl-matchup-edge", "/tools/nfl-matchup-edge"),
    ("nfl-totals(wind)", "/tools/nfl-totals-today"),
    ("nfl-spots", "/tools/nfl-spots"),
    ("nfl-props-floor", "/tools/nfl-floor"),
    ("riding-the-wave", "/tools/riding-the-wave"),
    ("heat-map", "/tools/nfl-heatmap"),
    ("milestones", "/tools/nfl-milestones"),
    ("player-check(NFL)", "/tools/player-check?q=Nico+Collins"),
    ("nfl-team(JAX)", "/tools/nfl-team?team=JAX"),
    ("injury-report", "/tools/injury-report"),
    ("sgp-workbench", "/tools/sgp-workbench"),
    ("green-light", "/tools/green-light"),
    ("daily-card", "/tools/daily-card"),
    ("the-menu", "/tools/menu"),
]

ROW_RE = re.compile(r'<tr[\s>]|class="[^"]*\b(?:rw-row|ms-row|bk-row|bkn-row|hm-row|inj-row|dc-leg|card-row)\b')


def main():
    # Owner bypass so enforce_access_gate lets member routes render (read-only).
    app.get_current_user = lambda: {"user_id": "perf", "email": "perf@bankrollkings.test", "plan": "all_access"}
    app.is_owner_user = lambda u=None: True
    client = app.app.test_client()

    print("=" * 96)
    print("NFL / member ROUTE RENDER BASELINE (authenticated owner, in-process, read-only)")
    print("=" * 96)
    print(f"{'route':22} {'code':>4} {'run1_ms':>8} {'med_ms':>8} {'worst_ms':>9} {'KB':>7} {'rows':>6}")
    rows_out = []
    for label, path in ROUTES:
        times, code, size, rown = [], None, 0, 0
        for i in range(3):
            t0 = time.perf_counter()
            try:
                resp = client.get(path)
                dt = (time.perf_counter() - t0) * 1000.0
                code = resp.status_code
                body = resp.get_data(as_text=True)
                size = len(body)
                rown = len(ROW_RE.findall(body))
            except Exception as exc:
                dt = (time.perf_counter() - t0) * 1000.0
                code = f"ERR:{type(exc).__name__}"
                body = ""
            times.append(dt)
        med = statistics.median(times)
        worst = max(times)
        kb = size / 1024.0
        print(f"{label:22} {str(code):>4} {times[0]:8.0f} {med:8.0f} {worst:9.0f} {kb:7.1f} {rown:6d}")
        rows_out.append((label, code, times[0], med, worst, kb, rown))

    # Quick worst-offender ranking by warm median render time + by payload.
    graded = [r for r in rows_out if isinstance(r[1], int) and r[1] == 200]
    print("\nTOP 5 by warm MEDIAN render ms:")
    for r in sorted(graded, key=lambda x: -x[3])[:5]:
        print(f"  {r[0]:22} median {r[3]:.0f} ms  worst {r[4]:.0f} ms  ({r[6]} rows, {r[5]:.1f} KB)")
    print("TOP 5 by PAYLOAD KB:")
    for r in sorted(graded, key=lambda x: -x[5])[:5]:
        print(f"  {r[0]:22} {r[5]:.1f} KB  ({r[6]} rows, median {r[3]:.0f} ms)")
    print("\nNOTE: run1 = cold process (caches empty); runs 2-3 warm. Server render only; CWV needs a browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
