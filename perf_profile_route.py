"""READ-ONLY cold-route profiler (Site Performance P0, Phase B2).

cProfiles a single COLD request (fresh process, caches empty) to localize where a route's cold-build
time goes, filtered to this app's own frames. Owner-bypass, GET-only, no writes, no user data printed.
Run on prod via SSM (local data is too small to reproduce prod cold costs):

    sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python perf_profile_route.py /dashboard'

Optional 2nd arg = how many app.py frames to show (default 20). Prints total seconds + the top app.py
frames by cumulative time -- the builder eating the cold build is at/near the top.
"""
from __future__ import annotations

import cProfile
import io
import pstats
import sys

import app


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/dashboard'
    topn = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    app.get_current_user = lambda: {'user_id': 'perf', 'email': 'perf@bankrollkings.test', 'plan': 'all_access'}
    app.is_owner_user = lambda u=None: True
    client = app.app.test_client()

    pr = cProfile.Profile()
    pr.enable()
    resp = client.get(path)          # first hit in this process = cold
    pr.disable()

    body = resp.get_data()
    print('=' * 92)
    print(f'COLD PROFILE  {path}  -> status {resp.status_code}  {len(body)/1024:.1f} KB')
    print('=' * 92)

    def _dump(sort_key, heading):
        # cumulative = time spent in a frame AND its callees (finds the wrapper); tottime = time spent
        # in the frame ITSELF, excluding callees (finds the actual hot leaf doing the work). The 77s
        # culprit inside a builder shows up at the TOP of the tottime list, not the cumulative one.
        print(f'\n--- {heading} ---')
        s = io.StringIO()
        st = pstats.Stats(pr, stream=s)
        st.sort_stats(sort_key).print_stats('app.py:', topn)
        out = s.getvalue()
        for line in out.splitlines():
            if 'function calls' in line or ('app.py:' in line and 'Lib' not in line):
                print(line.rstrip()[:150])

    _dump('tottime', 'SELF-TIME (tottime) — the actual hot function')
    _dump('cumulative', 'CUMULATIVE — the calling wrapper chain')
    return 0


if __name__ == '__main__':
    sys.exit(main())
