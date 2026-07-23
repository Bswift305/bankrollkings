from __future__ import annotations

from datetime import datetime

from app import (
    app,
    build_method_hub_context,
    build_today_hub_context,
    build_matchup_lens_hub_context,
)
from qc_platform_routes import _ensure_qc_user


EXPECTED_SPORT_KEYS = {"nba", "wnba", "mlb", "nfl", "cfb", "ncaamb", "ncaawb"}
HUB_METHODS = ["props", "market-edge", "injuries", "trends", "parlay"]


def run_qc() -> dict:
    failures: list[str] = []
    checks: list[str] = []

    for method_key in HUB_METHODS:
        context = build_method_hub_context(method_key)
        card_keys = {str(card.get("sport_key") or "").strip().lower() for card in context.get("cards", [])}
        if card_keys != EXPECTED_SPORT_KEYS:
            failures.append(
                f"{method_key} hub coverage mismatch. Expected {sorted(EXPECTED_SPORT_KEYS)}, got {sorted(card_keys)}."
            )
        checks.append(f"{method_key}_coverage")

    today_keys = {str(card.get("sport_key") or "").strip().lower() for card in build_today_hub_context().get("cards", [])}
    if today_keys != EXPECTED_SPORT_KEYS:
        failures.append(f"today hub coverage mismatch. Expected {sorted(EXPECTED_SPORT_KEYS)}, got {sorted(today_keys)}.")
    checks.append("today_coverage")

    matchup_keys = {
        str(card.get("sport_key") or "").strip().lower()
        for card in build_matchup_lens_hub_context().get("cards", [])
    }
    if matchup_keys != EXPECTED_SPORT_KEYS:
        failures.append(
            f"matchup-lens hub coverage mismatch. Expected {sorted(EXPECTED_SPORT_KEYS)}, got {sorted(matchup_keys)}."
        )
    checks.append("matchup_coverage")

    client = app.test_client()
    # The /tools/* routes are gated; without an authenticated QC session all nine
    # 401 and report as route failures the routes do not actually have.
    qc_user = _ensure_qc_user("sharp")
    with client.session_transaction() as sess:
        sess["user_id"] = qc_user["user_id"]
        sess["user_email"] = qc_user["email"]
    smoke_paths = [
        "/tools/today",
        "/tools/matchup-lens",
        "/tools/props",
        "/tools/market-edge",
        "/tools/injuries",
        "/tools/trends",
        "/tools/parlay",
        "/tools/props?sport=ncaamb",
        "/tools/matchup-lens?sport=ncaawb",
    ]
    for path in smoke_paths:
        response = client.get(path)
        if response.status_code != 200:
            failures.append(f"{path} returned {response.status_code} instead of 200.")
        checks.append(path)

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
    print("UNIVERSAL TOOL HUBS")
    print("=" * 72)
    print(f"Checked at: {report['checked_at']}")
    print(f"Checks: {report['check_count']}")
    print(f"Failures: {report['failure_count']}")
    print()
    if report["clean"]:
        print("All universal hub checks passed.")
        return 0
    for failure in report["failures"]:
        print(f"[FAIL] {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
