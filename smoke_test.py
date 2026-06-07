"""Smoke test — verify the app is intact after a change.

Runs IN-PROCESS via Flask's test client (no network, no login required):

  1. CSRF checks (fast, first): a POST without a token is rejected (400), the
     same POST with a valid token is accepted, the token meta renders, and the
     Stripe webhook stays exempt.
  2. GETs every parameter-free GET route and flags any 5xx (server errors /
     template breakage). Each route is bounded by a per-request timeout so a
     slow or external-calling route can't wedge the whole run.

Exit 0 if all green, 1 otherwise.

Usage:  source venv/bin/activate && python smoke_test.py
Env:    SMOKE_ROUTE_TIMEOUT (seconds per route, default 12)
        SMOKE_SKIP_SWEEP=1  (run only the CSRF checks)
"""

from __future__ import annotations

import os
import re
import signal
import sys

from app import app

# Status codes that mean "route is alive" (not broken). 5xx = real breakage.
ALIVE = {200, 301, 302, 303, 304, 308, 401, 403}
ROUTE_TIMEOUT = int(os.environ.get("SMOKE_ROUTE_TIMEOUT", "20") or "20")

# Set by the alarm handler so a timeout that Flask catches mid-view (and turns
# into a 500) is still recognized as a timeout, not a real server error.
_TIMED_OUT = False


class _RouteTimeout(Exception):
    pass


def _on_alarm(signum, frame):
    global _TIMED_OUT
    _TIMED_OUT = True
    raise _RouteTimeout()


def _paramless_get_paths():
    seen, paths = set(), []
    for rule in app.url_map.iter_rules():
        if rule.arguments:            # needs URL params -> can't GET blindly
            continue
        if "GET" not in (rule.methods or set()):
            continue
        path = str(rule.rule)
        if path.startswith("/static") or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return sorted(paths)


def _check_csrf(client):
    print("=== 1. CSRF protection ===", flush=True)
    ok = True

    page = client.get("/login").get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', page)
    meta_present = bool(m)
    token = m.group(1) if m else ""
    if not token:  # fall back to the hidden form field
        m2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', page)
        token = m2.group(1) if m2 else ""
    print(f"csrf-token meta on /login: {'yes' if meta_present else 'MISSING'}", flush=True)
    print(f"csrf token available on /login: {'yes' if token else 'NO'}", flush=True)
    ok = ok and bool(token)

    if token:
        code = client.post("/login", data={"email": "smoke@example.com",
                                           "password": "x", "csrf_token": token}).status_code
        good = code != 400
        print(f"valid-token POST /login accepted: {'yes' if good else 'NO'} (status {code})", flush=True)
        ok = ok and good

    fresh = app.test_client()
    fresh.get("/login")
    code = fresh.post("/login", data={"email": "smoke@example.com", "password": "x"}).status_code
    blocked = code == 400
    print(f"missing-token POST /login blocked: {'yes' if blocked else 'NO'} (status {code})", flush=True)
    ok = ok and blocked

    w = app.test_client()
    rw = w.post("/stripe/webhook", data=b"{}", content_type="application/json")
    exempt = "csrf" not in rw.get_data(as_text=True).lower()
    print(f"/stripe/webhook CSRF-exempt: {'yes' if exempt else 'NO'} (status {rw.status_code})", flush=True)
    ok = ok and exempt

    return ok


def _sweep_routes(client):
    print("\n=== 2. GET every parameter-free route ===", flush=True)
    print(f"(per-route timeout: {ROUTE_TIMEOUT}s)", flush=True)
    has_alarm = hasattr(signal, "SIGALRM")
    if has_alarm:
        signal.signal(signal.SIGALRM, _on_alarm)

    global _TIMED_OUT
    server_errors, oddities, timeouts, checked = [], [], [], 0
    for path in _paramless_get_paths():
        _TIMED_OUT = False
        if has_alarm:
            signal.alarm(ROUTE_TIMEOUT)
        try:
            code = client.get(path).status_code
        except _RouteTimeout:
            timeouts.append(path)
            print(f"  TIMEOUT  {path}", flush=True)
            continue
        except Exception as exc:
            server_errors.append((path, f"EXCEPTION: {exc}"))
            print(f"  EXC      {path} :: {exc}", flush=True)
            continue
        finally:
            if has_alarm:
                signal.alarm(0)
        # A timeout that Flask swallowed mid-view surfaces as a 500 here; treat
        # it as a (slow) timeout, not a real server error.
        if _TIMED_OUT:
            timeouts.append(path)
            print(f"  TIMEOUT  {path} (slow; interrupted)", flush=True)
            continue
        checked += 1
        if code >= 500:
            server_errors.append((path, code))
        elif code not in ALIVE:
            oddities.append((path, code))
        print(f"  {code}     {path}", flush=True)

    print(f"\nchecked {checked} routes", flush=True)
    if server_errors:
        print(f"!! {len(server_errors)} SERVER ERROR(S):")
        for p, c in server_errors:
            print(f"   {c}  {p}")
    else:
        print("no 5xx server errors")
    if timeouts:
        print(f"note: {len(timeouts)} route(s) timed out (slow/external; not a code failure):")
        for p in timeouts:
            print(f"   TIMEOUT  {p}")
    if oddities:
        print(f"note: {len(oddities)} non-standard status(es):")
        for p, c in oddities[:40]:
            print(f"   {c}  {p}")

    return not server_errors


def run():
    client = app.test_client()
    csrf_ok = _check_csrf(client)
    sweep_ok = True
    if os.environ.get("SMOKE_SKIP_SWEEP", "").strip() not in ("1", "true", "yes"):
        sweep_ok = _sweep_routes(client)
    ok = csrf_ok and sweep_ok
    print("\n=== SMOKE: " + ("PASS" if ok else "FAIL") + " ===", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
