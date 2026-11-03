"""
Portable authenticated principal for QCs that render protected routes (incident 2026-10-24).

A QC must not depend on a specific account existing in the local/prod user store -- otherwise it only
tests the protected page on a box that happens to hold that account. This provides a DETERMINISTIC,
ISOLATED owner principal by swapping `app.load_users` for a one-row in-memory owner store for the
duration of a request, reverted afterward. No DB user is required and nothing is written to any store.
This patches only a data boundary (load_users); it changes no application authentication code.

NBA v5 addition (additive; the production helpers are unchanged): `isolated_member_client(plan=...)` -- an
ordinary NON-owner, non-admin member on a given plan with a reserved `.invalid` email and an explicit guard that
it never resolves as an owner, so a QC can prove the plan gate itself.
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


@contextlib.contextmanager
def isolated_user_client(plan: str = "all_access", user_id: str = "qc-portable-member"):
    """Like isolated_owner_client, but a NON-owner member on `plan` (active) -- for QCs that must prove a
    paid (or free) customer's view, not the owner bypass. Same data-boundary swap; nothing persisted."""
    row = {
        "UserId": user_id, "Email": "qc-portable-member@bankrollkings.local", "DisplayName": "QC Portable Member",
        "Plan": plan, "BillingCycle": "monthly", "PlanStatus": "active", "Role": "",
        "IsAdmin": "0", "IsFounder": "0", "Bankroll": 0,
    }
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


# A reserved, non-routable address (RFC 2606 `.invalid`) that can never be an owner email.
QC_MEMBER_EMAIL = "qc-portable-member@example.invalid"


def member_row(plan: str = "free", user_id: str = "qc-portable-member", plan_status: str = "active") -> dict:
    """A non-owner, non-admin member on `plan` (no trial), in the same column layout as owner_row."""
    return {
        "UserId": user_id, "Email": QC_MEMBER_EMAIL, "DisplayName": "QC Portable Member",
        "Plan": plan, "BillingCycle": "monthly", "PlanStatus": plan_status, "Role": "",
        "IsAdmin": "0", "IsFounder": "0", "Bankroll": 0, "TrialExpiresAt": "", "TrialInviteCode": "",
    }


@contextlib.contextmanager
def _isolated_client(row: dict):
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


@contextlib.contextmanager
def isolated_member_client(plan: str = "free", user_id: str = "qc-portable-member", plan_status: str = "active"):
    """Yield a test client authenticated as an isolated in-memory NON-owner member on `plan`
    (no DB user, nothing persisted). load_users is swapped for the one-row store and restored on exit."""
    row = member_row(plan=plan, user_id=user_id, plan_status=plan_status)
    if app.is_owner_user(row):  # guard: a member principal must never silently become an owner bypass
        raise RuntimeError("qc member principal resolved as owner; refusing to run")
    with _isolated_client(row) as client:
        yield client


def unauth_client():
    """A test client with NO session -> get_current_user() returns None -> protected routes 401."""
    return app.app.test_client()
