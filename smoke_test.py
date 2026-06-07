"""Smoke test — verify the app is intact after a change.

Runs IN-PROCESS via Flask's test client (no network, no login required):

  1. GETs every parameter-free GET route and flags any 5xx (server errors /
     template breakage). This is the "is everything still rendering?" check —
     e.g. if csrf_token() weren't wired, every page extending the base would
     500 and show up here immediately.
  2. Verifies CSRF: a POST without a token is rejected (400), the same POST
     with a valid token is accepted, and the Stripe webhook stays exempt.

Exit 0 if all green, 1 otherwise.

Usage:  source venv/bin/activate && python smoke_test.py
"""

from __future__ import annotations

import re
import sys

from app import app

# Status codes that mean "route is alive" (not broken). 5xx = real breakage.
ALIVE = {200, 301, 302, 303, 304, 308, 401, 403}


def _paramless_get_paths():
    seen, paths = set(), []
    for rule in app.url_map.iter_rules():
        if rule.arguments:            # needs URL params -> can't GET blindly
            continue
        if 'GET' not in (rule.methods or set()):
            continue
        path = str(rule.rule)
        if path.startswith('/static') or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return sorted(paths)


def run():
    client = app.test_client()
    server_errors, oddities, checked = [], [], 0

    print("=== 1. GET every parameter-free route ===")
    for path in _paramless_get_paths():
        try:
            code = client.get(path).status_code
        except Exception as exc:
            server_errors.append((path, f"EXCEPTION: {exc}"))
            continue
        checked += 1
        if code >= 500:
            server_errors.append((path, code))
        elif code not in ALIVE:
            oddities.append((path, code))

    print(f"checked {checked} routes")
    if server_errors:
        print(f"!! {len(server_errors)} SERVER ERROR(S):")
        for p, c in server_errors:
            print(f"   {c}  {p}")
    else:
        print("no 5xx server errors")
    if oddities:
        print(f"note: {len(oddities)} non-standard status(es) (not necessarily broken):")
        for p, c in oddities[:40]:
            print(f"   {c}  {p}")

    print("\n=== 2. CSRF protection ===")
    csrf_ok = True

    # token rendered into the base template meta
    page = client.get('/login').get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', page)
    token = m.group(1) if m else ''
    if token:
        print("csrf-token meta present on /login: yes")
    else:
        print("!! csrf-token meta MISSING on /login")
        csrf_ok = False

    # valid token -> must NOT be blocked (same client = same session)
    if token:
        code = client.post('/login', data={'email': 'smoke@example.com',
                                            'password': 'x', 'csrf_token': token}).status_code
        if code == 400:
            print(f"!! valid-token POST /login was rejected ({code})")
            csrf_ok = False
        else:
            print(f"valid-token POST /login accepted (status {code})")

    # missing token (fresh session) -> must be 400
    fresh = app.test_client()
    fresh.get('/login')
    code = fresh.post('/login', data={'email': 'smoke@example.com', 'password': 'x'}).status_code
    if code == 400:
        print("missing-token POST /login blocked (400): yes")
    else:
        print(f"!! missing-token POST /login NOT blocked ({code})")
        csrf_ok = False

    # Stripe webhook must stay exempt (its own 400 is fine; a CSRF 400 is not)
    w = app.test_client()
    rw = w.post('/stripe/webhook', data=b'{}', content_type='application/json')
    if 'csrf' in rw.get_data(as_text=True).lower():
        print("!! /stripe/webhook is NOT exempt (got a CSRF error)")
        csrf_ok = False
    else:
        print(f"/stripe/webhook exempt from CSRF (status {rw.status_code}): yes")

    ok = not server_errors and csrf_ok
    print("\n=== SMOKE: " + ("PASS" if ok else "FAIL") + " ===")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
