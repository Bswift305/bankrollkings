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
    get_stripe_billing_portal_url,
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

    with isolated_users_file():
        client = app.test_client()
        pricing = client.get("/pricing")
        _assert(pricing.status_code == 200, "Anonymous /pricing should return 200.", failures)
        checks.append("anonymous_pricing")

        anon_checkout = client.get("/checkout/start?plan=pro&billing=monthly", follow_redirects=False)
        _assert(anon_checkout.status_code in {301, 302}, "Anonymous checkout should redirect to login.", failures)
        _assert("/login" in str(anon_checkout.location or ""), "Anonymous checkout should point at login.", failures)
        checks.append("anonymous_checkout_redirect")

        for plan_key in ["pro", "nba_pass", "cbb_pass"]:
            client = app.test_client()
            user = _seed_user("free")
            _login(client, user)

            start = client.get(f"/checkout/start?plan={plan_key}&billing=monthly&next=/pricing", follow_redirects=False)
            expected_checkout_url = get_stripe_checkout_url(plan_key, "monthly")
            _assert(start.status_code in {301, 302}, f"{plan_key} checkout start should redirect.", failures)
            _assert(
                str(start.location or "") == expected_checkout_url,
                f"{plan_key} checkout start should redirect to the configured Stripe URL.",
                failures,
            )

            updated = find_user_by_email(user["Email"])
            _assert(updated is not None, f"{plan_key} user should still exist after checkout start.", failures)
            _assert(str((updated or {}).get("Plan", "")).strip().lower() == plan_key, f"{plan_key} checkout should update plan on the user record.", failures)
            _assert(str((updated or {}).get("PlanStatus", "")).strip().lower() == "pending_checkout", f"{plan_key} checkout should set pending_checkout.", failures)
            checks.append(f"{plan_key}_checkout_start")

            success = client.get(f"/checkout/success?plan={plan_key}&billing=monthly&next=/pricing", follow_redirects=False)
            _assert(success.status_code in {301, 302}, f"{plan_key} checkout success should redirect.", failures)
            _assert("/pricing?checkout=success" in str(success.location or ""), f"{plan_key} success should return to pricing with checkout=success.", failures)
            updated = find_user_by_email(user["Email"])
            _assert(str((updated or {}).get("PlanStatus", "")).strip().lower() == "active", f"{plan_key} success should activate the plan.", failures)
            checks.append(f"{plan_key}_checkout_success")

            billing = client.get("/billing?next=/pricing", follow_redirects=False)
            _assert(billing.status_code in {301, 302}, f"{plan_key} billing should redirect.", failures)
            _assert(
                str(billing.location or "") == get_stripe_billing_portal_url(),
                f"{plan_key} billing should redirect to the live Stripe billing portal.",
                failures,
            )
            checks.append(f"{plan_key}_billing")

            cancel = client.get("/checkout/cancel?next=/pricing", follow_redirects=False)
            _assert(cancel.status_code in {301, 302}, f"{plan_key} cancel should redirect.", failures)
            _assert("/pricing?checkout=cancelled" in str(cancel.location or ""), f"{plan_key} cancel should return to pricing with checkout=cancelled.", failures)
            updated = find_user_by_email(user["Email"])
            _assert(str((updated or {}).get("PlanStatus", "")).strip().lower() == "selected", f"{plan_key} cancel should set plan_status back to selected.", failures)
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
