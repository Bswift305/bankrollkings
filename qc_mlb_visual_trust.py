"""QC: key MLB surfaces expose visual-trust markers (live board state, method guidance, context).

Self-contained: authenticates with the portable in-memory owner principal
`services.qc_auth.isolated_owner_client` (one-row load_users swap, real auth code path, nothing
persisted) instead of looking up one personal account in the local user store -- which 401'd every
route on any box without that account. Routes and markers are unchanged.

Synthetic data: the "MLB Slate Intelligence" card renders only when there is a game-market slate
(`{% if mlb_slate_intelligence %}`), so on a data-less box (or in the MLB offseason) the marker check
could never pass. The QC feeds the REAL builder (`build_mlb_slate_intelligence`, route, template)
a one-game synthetic odds fixture by swapping the data boundary `app.load_mlb_game_market_odds`
for the run (restored after) -- the same data-boundary pattern as services/qc_auth.

Mutation proof (run every time, part of the verdict):
  * a page whose required marker is stripped -- through the real Flask request path -- is reported;
  * a signed-out request is still reported as a non-200 failure (auth is not bypassed).
"""
from __future__ import annotations

import contextlib
from datetime import datetime

import pandas as pd

import app as app_module
from app import app
from services.qc_auth import isolated_owner_client, unauth_client
from services.qc_tracking import append_qc_run_log


ROUTES = (
    ("/sports/mlb", ("MLB Slate Intelligence", "MLB Prop Board")),
    ("/sports/mlb/market-edge?date=all", ("MLB Method Board", "How To Use", "Context")),
    ("/sports/mlb/floor?date=all", ("MLB Method Board", "How To Use", "Context")),
    ("/sports/mlb/trends?date=all", ("MLB Method Board", "How To Use", "Context")),
)


# Synthetic, clearly non-real fixture: one game, two books, totals + run line.
SYNTHETIC_MLB_ODDS = pd.DataFrame([
    {"Date": "2026-11-04", "Time": "7:05 PM", "Away": "QC Away Nine", "Home": "QC Home Nine",
     "AwayFull": "QC Away Nine", "HomeFull": "QC Home Nine", "Total": 8.5, "Spread": -1.5, "Book": "QC Book A"},
    {"Date": "2026-11-04", "Time": "7:05 PM", "Away": "QC Away Nine", "Home": "QC Home Nine",
     "AwayFull": "QC Away Nine", "HomeFull": "QC Home Nine", "Total": 9.0, "Spread": -1.5, "Book": "QC Book B"},
])


@contextlib.contextmanager
def synthetic_mlb_slate():
    """Swap the MLB game-odds data boundary for the synthetic fixture; restored on exit."""
    original = app_module.load_mlb_game_market_odds
    app_module.load_mlb_game_market_odds = lambda: SYNTHETIC_MLB_ODDS.copy()
    try:
        yield
    finally:
        app_module.load_mlb_game_market_odds = original


def _check_route(client, path: str, markers) -> list[str]:
    response = client.get(path)
    text = response.get_data(as_text=True)
    if response.status_code != 200:
        return [f"{path}: returned {response.status_code}."]
    missing = [marker for marker in markers if marker not in text]
    if missing:
        return [f"{path}: missing visual trust markers: {', '.join(missing)}."]
    return []


def _mutation_proof() -> list[str]:
    """Each injected violation must be caught by _check_route; returns failures if one is not."""
    failures: list[str] = []
    path, markers = ROUTES[0]
    endpoint = app.url_map.bind("localhost").match(path.split("?", 1)[0])[0]
    real_view = app.view_functions[endpoint]

    def stripped_view(*args, **kwargs):
        response = app.make_response(real_view(*args, **kwargs))
        response.set_data(response.get_data(as_text=True).replace(markers[0], "MLB QC-MUTANT"))
        return response

    app.view_functions[endpoint] = stripped_view
    try:
        with synthetic_mlb_slate(), isolated_owner_client() as client:
            caught = _check_route(client, path, markers)
    finally:
        app.view_functions[endpoint] = real_view
    if not any("missing visual trust markers" in item and markers[0] in item for item in caught):
        failures.append(f"mutation not caught: '{markers[0]}' stripped from {path} -> {caught}")

    anon = _check_route(unauth_client(), path, markers)
    if not any("returned" in item for item in anon):
        failures.append(f"mutation not caught: signed-out request to {path} passed -> {anon}")
    return failures


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failures: list[str] = []
    warnings: list[str] = []
    route_count = 0

    # Portable owner principal (services/qc_auth): no dependency on a real account in the user store.
    with synthetic_mlb_slate(), isolated_owner_client() as client:
        for path, markers in ROUTES:
            route_count += 1
            failures.extend(_check_route(client, path, markers))

    failures.extend(_mutation_proof())

    report = {
        "checked_at": checked_at,
        "clean": len(failures) == 0,
        "pass_count": max(route_count - len(failures), 0),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "route_count": route_count,
        "notes": "Verified key MLB surfaces expose trust markers for live board state, method guidance, and context language (mutation proof included).",
        "warnings": warnings,
        "failures": failures,
    }
    append_qc_run_log("mlb_visual_trust", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("MLB VISUAL TRUST QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Routes checked: {report['route_count']}")
    print(f"Warnings: {report['warning_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print(report["notes"])
    for item in report["warnings"]:
        print(f"[WARN] {item}")
    for item in report["failures"]:
        print(f"[FAIL] {item}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
