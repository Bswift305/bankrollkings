"""QC: the portable route-QC principals (services/qc_auth) make these QCs self-contained -- not a waiver.

qc_wnba_visual_trust, qc_wnba_readiness and qc_nba_market_only failed in any data-less environment (401:
they signed in through user-store records that do not exist there; readiness also compared a raw
string against Jinja-escaped HTML). They now use the repo's portable principals in services/qc_auth
(isolated_owner_client, and the additive isolated_user_client for a paid non-owner member) -- a one-row
in-memory load_users swap, real auth code path -- and readiness compares visible text.
This proves the fix did not make them vacuous:
  1. signed out, the gated pages are refused (401); a free member is still gated (no plan bypass);
  2. the principals restore load_users on exit and write nothing to the user store;
  3. readiness still FAILS when the feed warning is absent from the page (mutation);
  4. readiness accepts an HTML-escaped warning that IS displayed (the original false failure).
Exit 0 = all pass.
"""
from __future__ import annotations

import os

os.environ.setdefault('SECRET_KEY', 'qc-route-harness')

import pandas as pd  # noqa: E402

import app  # noqa: E402
from services.qc_auth import isolated_owner_client, isolated_user_client, unauth_client  # noqa: E402

results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))


def main() -> int:
    paths = ('/sports/wnba', '/sports/wnba/floor', '/sports/nba/props')
    anon = unauth_client()
    codes = {p: anon.get(p).status_code for p in paths}
    ok(all(c in (401, 403) or 300 <= c < 400 for c in codes.values()),
       f'1: signed-out requests are refused/redirected ({codes})')

    orig_load = app.load_users
    orig_save = app.save_user
    writes = []
    app.save_user = lambda *a, **k: writes.append(a)
    try:
        with isolated_owner_client() as c:
            got = {p: c.get(p).status_code for p in paths}
        ok(all(v == 200 for v in got.values()), f'1: isolated_owner_client reaches the gated pages ({got})')
        with isolated_user_client('all_access') as c:
            paid = {p: c.get(p).status_code for p in paths[:2]}
        ok(all(v == 200 for v in paid.values()), f'1: paid non-owner member reaches paid pages ({paid})')
        with isolated_user_client('free') as c:
            free = {p: c.get(p).status_code for p in paths[:2]}
        ok(all(v != 200 for v in free.values()), f'1: a free member is still gated (no plan bypass) ({free})')
    finally:
        app.save_user = orig_save
    ok(app.load_users is orig_load, '2: load_users restored after each principal')
    ok(not writes, '2: the principals wrote nothing to the user store')

    import qc_wnba_readiness as rd
    real_feed = rd.load_wnba_live_props_feed
    try:
        rd.load_wnba_live_props_feed = lambda **k: (pd.DataFrame(), {
            'status': 'unavailable', 'warning': 'ZZ-QC-MUTANT warning that no page shows', 'has_live_props': False})
        rep = rd.run_qc()
        ok(any('stale-feed warning missing' in f for f in rep['failures']),
           '3: readiness FAILS when the feed warning is absent from the pages (mutation caught)')
    finally:
        rd.load_wnba_live_props_feed = real_feed
    rep = rd.run_qc()
    ok(not any('stale-feed warning missing' in f for f in rep['failures']),
       "4: readiness accepts the displayed, HTML-escaped warning (aren&#39;t) -- the original false failure")

    print('=' * 60)
    print('BANKROLL KINGS ROUTE-QC HARNESS')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
