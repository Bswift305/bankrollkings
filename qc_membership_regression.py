from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import shutil
import uuid

from app import (
    app,
    save_user,
    find_user_by_email,
    DATA_DIR,
    get_stripe_checkout_url,
    get_founder_checkout_url,
    get_stripe_billing_portal_url,
    founder_slots_remaining,
)


USERS_PATH = DATA_DIR / "tracking" / "NBA_Users.csv"


@contextmanager
def isolated_users_file():
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_path = USERS_PATH.with_suffix(".csv.membership_qc_backup")
    if USERS_PATH.exists():
        shutil.copy2(USERS_PATH, backup_path)
    else:
        USERS_PATH.write_text(
            "UserId,DisplayName,Email,PasswordHash,Plan,BillingCycle,PlanStatus,Role,IsAdmin,CreatedAt,PlanSelectedAt\n",
            encoding="utf-8",
        )
    try:
        yield
    finally:
        if backup_path.exists():
            shutil.move(str(backup_path), str(USERS_PATH))
        elif USERS_PATH.exists():
            USERS_PATH.unlink()


def _seed_user(plan_key: str = "free") -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = {
        "UserId": f"member-{uuid.uuid4().hex[:8]}",
        "DisplayName": "Membership QC",
        "Email": f"membership_qc_{uuid.uuid4().hex[:6]}@example.com",
        "PasswordHash": "",
        "Plan": plan_key,
        "BillingCycle": "monthly",
        "PlanStatus": "active" if plan_key != "free" else "selected",
        "Role": "",
        "IsAdmin": "",
        "CreatedAt": now,
        "PlanSelectedAt": now,
    }
    save_user(user)
    return user


def _login(client, user: dict):
    with client.session_transaction() as session:
        session["user_id"] = user["UserId"]
        session["user_email"] = user["Email"].lower()
        session["display_name"] = user["DisplayName"]


def _assert(condition: bool, message: str, failures: list[str]):
    if not condition:
        failures.append(message)


def run_qc() -> dict:
    failures: list[str] = []
    checks: list[str] = []

    standard_url = get_stripe_checkout_url("all_access", "monthly")
    founder_url = get_founder_checkout_url()
    live_checkout = bool(standard_url or founder_url)
    portal_url = get_stripe_billing_portal_url()

    with isolated_users_file():
        client = app.test_client()
        pricing = client.get("/pricing")
        _assert(pricing.status_code == 200, "Anonymous /pricing should return 200.", failures)
        _assert(b"$19.99" in pricing.data, "/pricing should show the $19.99 All Access price.", failures)
        checks.append("anonymous_pricing")

        anon_checkout = client.get("/checkout/start?plan=all_access&billing=monthly", follow_redirects=False)
        _assert(anon_checkout.status_code in {301, 302}, "Anonymous checkout should redirect to login.", failures)
        _assert("/login" in str(anon_checkout.location or ""), "Anonymous checkout should point at login.", failures)
        checks.append("anonymous_checkout_redirect")

        # All entry plan keys (new key + legacy links) must land on the single
        # all_access membership.
        for plan_key in ["all_access", "pro", "nba_pass"]:
            client = app.test_client()
            user = _seed_user("free")
            _login(client, user)

            slots_before = founder_slots_remaining()
            start = client.get(f"/checkout/start?plan={plan_key}&billing=monthly&next=/pricing", follow_redirects=False)
            location = str(start.location or "")
            _assert(start.status_code in {301, 302}, f"{plan_key} checkout start should redirect.", failures)
            if live_checkout:
                expect_founder = slots_before > 0 and bool(founder_url)
                expected_base = founder_url if expect_founder else standard_url
                _assert(
                    location.startswith(expected_base),
                    f"{plan_key} checkout start should redirect to the {'founder' if expect_founder else 'standard'} Stripe URL.",
                    failures,
                )
            else:
                _assert(
                    "/checkout/success" in location and "mode=demo" in location,
                    f"{plan_key} checkout start should fall back to the demo checkout when Stripe is not configured.",
                    failures,
                )

            updated = find_user_by_email(user["Email"])
            _assert(updated is not None, f"{plan_key} user should still exist after checkout start.", failures)
            _assert(
                str((updated or {}).get("Plan", "")).strip().lower() == "all_access",
                f"{plan_key} checkout should normalize the user's plan to all_access.",
                failures,
            )
            _assert(
                str((updated or {}).get("PlanStatus", "")).strip().lower() == "pending_checkout",
                f"{plan_key} checkout should set pending_checkout.",
                failures,
            )
            if slots_before > 0:
                _assert(
                    str((updated or {}).get("FounderOffer", "")).strip() == "1",
                    f"{plan_key} checkout should reserve a founder slot while slots remain.",
                    failures,
                )
            checks.append(f"{plan_key}_checkout_start")

            if not live_checkout:
                # Demo path: completing checkout must activate the membership and
                # consume the reserved founder slot into IsFounder.
                success = client.get(location, follow_redirects=False)
                _assert(success.status_code in {301, 302}, f"{plan_key} demo checkout success should redirect.", failures)
                _assert("checkout=success" in str(success.location or ""), f"{plan_key} demo success should signal checkout=success.", failures)
                updated = find_user_by_email(user["Email"])
                _assert(
                    str((updated or {}).get("PlanStatus", "")).strip().lower() == "active",
                    f"{plan_key} demo success should activate the membership.",
                    failures,
                )
                if slots_before > 0:
                    _assert(
                        str((updated or {}).get("IsFounder", "")).strip() == "1",
                        f"{plan_key} activation should convert the founder reservation into IsFounder.",
                        failures,
                    )
                    _assert(
                        str((updated or {}).get("FounderOffer", "")).strip() != "1",
                        f"{plan_key} activation should clear the FounderOffer reservation.",
                        failures,
                    )
                    _assert(
                        founder_slots_remaining() == slots_before - 1,
                        f"{plan_key} activation should consume exactly one founder slot.",
                        failures,
                    )
                checks.append(f"{plan_key}_demo_checkout_success")

                billing = client.get("/billing?next=/pricing", follow_redirects=False)
                _assert(billing.status_code in {301, 302}, f"{plan_key} billing should redirect.", failures)
                if portal_url:
                    _assert(
                        str(billing.location or "") == portal_url,
                        f"{plan_key} billing should redirect to the Stripe billing portal.",
                        failures,
                    )
                else:
                    _assert("billing=demo" in str(billing.location or ""), f"{plan_key} billing should fall back to demo.", failures)
                checks.append(f"{plan_key}_billing")
            else:
                # Live path: cancel releases the founder reservation.
                cancel = client.get("/checkout/cancel?next=/pricing", follow_redirects=False)
                _assert(cancel.status_code in {301, 302}, f"{plan_key} cancel should redirect.", failures)
                _assert("checkout=cancelled" in str(cancel.location or ""), f"{plan_key} cancel should signal checkout=cancelled.", failures)
                updated = find_user_by_email(user["Email"])
                _assert(
                    str((updated or {}).get("PlanStatus", "")).strip().lower() == "selected",
                    f"{plan_key} cancel should set plan_status back to selected.",
                    failures,
                )
                _assert(
                    str((updated or {}).get("FounderOffer", "")).strip() != "1",
                    f"{plan_key} cancel should release the founder reservation.",
                    failures,
                )
                _assert(founder_slots_remaining() == slots_before, f"{plan_key} cancel should restore the founder slot count.", failures)
                checks.append(f"{plan_key}_cancel")

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "check_count": len(checks),
        "failure_count": len(failures),
        "clean": not failures,
        "failures": failures,
    }


def main() -> int:
    report = run_qc()
    print("=" * 72)
    print("MEMBERSHIP REGRESSION")
    print("=" * 72)
    print(f"Checked at: {report['checked_at']}")
    print(f"Checks: {report['check_count']}")
    print(f"Failures: {report['failure_count']}")
    print()
    if report["clean"]:
        print("All membership flow checks passed.")
        return 0
    for failure in report["failures"]:
        print(f"[FAIL] {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
