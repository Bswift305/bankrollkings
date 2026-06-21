from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import shutil
import uuid

from app import app, save_user, DATA_DIR


USERS_PATH = DATA_DIR / "tracking" / "NBA_Users.csv"

ALL_SPORT_PATHS = {
    "/sports/nba",
    "/sports/wnba",
    "/sports/mlb",
    "/sports/nfl",
    "/sports/ncaaf",
    "/sports/ncaamb",
    "/sports/ncaawb",
}

# Single-plan era: free denies everything, all_access allows everything, and
# legacy multi-tier keys still on user rows must resolve to full access.
PLAN_MATRIX = {
    "free": {
        "allow": set(),
        "deny": set(ALL_SPORT_PATHS),
    },
    "all_access": {
        "allow": set(ALL_SPORT_PATHS),
        "deny": set(),
    },
    "nba_pass": {
        "allow": set(ALL_SPORT_PATHS),
        "deny": set(),
    },
    "pro": {
        "allow": set(ALL_SPORT_PATHS),
        "deny": set(),
    },
    "sharp": {
        "allow": set(ALL_SPORT_PATHS),
        "deny": set(),
    },
    "elite": {
        "allow": set(ALL_SPORT_PATHS),
        "deny": set(),
    },
}


def _is_allowed(status_code: int, location: str = "") -> bool:
    return status_code == 200 and "/login" not in str(location or "")


@contextmanager
def isolated_users_file():
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_path = USERS_PATH.with_suffix(".csv.pass_qc_backup")
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


def _seed_user(plan_key: str) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = {
        "UserId": f"qc-{plan_key}-{uuid.uuid4().hex[:8]}",
        "DisplayName": f"QC {plan_key}",
        "Email": f"qc_{plan_key}_{uuid.uuid4().hex[:6]}@example.com",
        "PasswordHash": "",
        "Plan": plan_key,
        "BillingCycle": "monthly",
        "PlanStatus": "active",
        "Role": "",
        "IsAdmin": "",
        "CreatedAt": now,
        "PlanSelectedAt": now,
    }
    save_user(user)
    return user


def run_qc() -> dict:
    results: list[dict] = []
    failures: list[str] = []

    with isolated_users_file():
        for plan_key, expectations in PLAN_MATRIX.items():
            client = app.test_client()
            if plan_key != "free":
                user = _seed_user(plan_key)
                with client.session_transaction() as session:
                    session["user_id"] = user["UserId"]
                    session["user_email"] = user["Email"].lower()
                    session["display_name"] = user["DisplayName"]

            for path in sorted(expectations["allow"] | expectations["deny"]):
                response = client.get(path)
                allowed = _is_allowed(response.status_code, getattr(response, "location", ""))
                expected_allowed = path in expectations["allow"]
                ok = allowed == expected_allowed
                results.append(
                    {
                        "plan": plan_key,
                        "path": path,
                        "status_code": response.status_code,
                        "allowed": allowed,
                        "expected_allowed": expected_allowed,
                        "ok": ok,
                    }
                )
                if not ok:
                    failures.append(
                        f"{plan_key} -> {path} expected {'ALLOW' if expected_allowed else 'DENY'} "
                        f"but got status {response.status_code}"
                    )

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_checks": len(results),
        "failure_count": len(failures),
        "clean": not failures,
        "results": results,
        "failures": failures,
    }


def main() -> int:
    report = run_qc()
    print("=" * 72)
    print("PLAN ACCESS MATRIX")
    print("=" * 72)
    print(f"Checked at: {report['checked_at']}")
    print(f"Total checks: {report['total_checks']}")
    print(f"Failures: {report['failure_count']}")
    print()
    for item in report["results"]:
        if not item["ok"]:
            print(
                f"[FAIL] {item['plan']} | {item['path']} | "
                f"expected={'ALLOW' if item['expected_allowed'] else 'DENY'} | "
                f"status={item['status_code']}"
            )
    if report["clean"]:
        print("All plan-access checks passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
