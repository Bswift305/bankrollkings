"""
Portable authenticated principal for QCs that render protected routes (incident 2026-10-24).

A QC must not depend on a specific account existing in the local/prod user store -- otherwise it only
tests the protected page on a box that happens to hold that account. This provides a DETERMINISTIC,
ISOLATED owner principal by swapping `app.load_users` for a one-row in-memory owner store for the
duration of a request, reverted afterward. No DB user is required and nothing is written to any store.
This patches only a data boundary (load_users); it changes no application authentication code.
"""
from __future__ import annotations

import contextlib

import pandas as pd

import app


def owner_row(user_id: str = "qc-portable-owner") -> dict:
    return {
        "UserId": user_id, "Email": next(iter(app.OWNER_EMAILS)), "DisplayName": "QC Portable Owner",
        "Plan": "all_access", "BillingCycle": "monthly", "PlanStatus": "active", "Role": "owner",
        "IsAdmin": "1", "IsFounder": "0", "Bankroll": 0,
    }


@contextlib.contextmanager
def isolated_owner_client(user_id: str = "qc-portable-owner"):
    """Yield a test client authenticated as an isolated in-memory owner (no DB user, nothing persisted).
    load_users is swapped for the one-row store and restored on exit."""
    row = owner_row(user_id)
    orig = app.load_users
    app.load_users = lambda: pd.DataFrame([row])
    try:
        client = app.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = row["UserId"]
            sess["user_email"] = row["Email"]
        yield client
    finally:
        app.load_users = orig


def unauth_client():
    """A test client with NO session -> get_current_user() returns None -> protected routes 401."""
    return app.app.test_client()
