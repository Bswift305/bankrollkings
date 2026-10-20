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

    def _dump(sort_key, heading, restrict=None, keep=None):
        # cumulative = time spent in a frame AND its callees (finds the wrapper); tottime = time spent
        # in the frame ITSELF, excluding callees (finds the actual hot leaf doing the work). restrict
        # filters the printed frames to a substring; None shows ALL modules (incl. services/*.py and
        # pandas), which is how a hot leaf OUTSIDE app.py is revealed.
        print(f'\n--- {heading} ---')
        s = io.StringIO()
        st = pstats.Stats(pr, stream=s)
        if restrict:
            st.sort_stats(sort_key).print_stats(restrict, topn)
        else:
            st.sort_stats(sort_key).print_stats(topn)
        out = s.getvalue()
        for line in out.splitlines():
            if 'function calls' in line:
                print(line.rstrip()[:160])
            elif keep is None or keep in line:
                # a profiled frame line looks like "<ncalls> <tottime> ... path:line(func)"
                if '(' in line and (':' in line) and 'Ordered by' not in line:
                    print(line.rstrip()[:160])

    _dump('tottime', 'SELF-TIME (tottime) — ALL modules — the true hot leaf (incl. services/ + pandas)')
    _dump('tottime', 'SELF-TIME (tottime) — app.py only', restrict='app.py:', keep='app.py:')
    _dump('cumulative', 'CUMULATIVE — app.py calling chain', restrict='app.py:', keep='app.py:')
    return 0


if __name__ == '__main__':
    sys.exit(main())
