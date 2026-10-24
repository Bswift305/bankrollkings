"""
QC: fast-smoke command-route markers must be SEASON-ROBUST (incident 2026-10-24 scorecard follow-up).

The CFB Command fast route false-failed the prelaunch smoke in-season because BOTH its markers
("College Football Preseason Intelligence", "Roster Coverage") render only in preseason_mode -- the
page was healthy (200) but showed the live board instead. The football command pages
(templates/nfl_dashboard.html) always render the season-neutral title "{{ sport_title }} Command
Surface", so each football command fast route must include the "Command Surface" token as a marker that
holds in BOTH preseason and in-season. This guards against re-introducing a preseason-only marker set.

Pure/offline (reads ROUTE_CHECKS; app import needs SECRET_KEY, set by the caller).
"""
from __future__ import annotations

from qc_platform_routes import ROUTE_CHECKS

SEASON_NEUTRAL = "Command Surface"


def main() -> int:
    failures = []
    football_command_fast = [
        c for c in ROUTE_CHECKS
        if c.fast and c.group == "football" and c.path.split("?")[0] in ("/sports/nfl", "/sports/ncaaf")
    ]
    if len(football_command_fast) < 2:
        failures.append(f"expected NFL + CFB football command fast routes; found {len(football_command_fast)}")
    for c in football_command_fast:
        if not any(SEASON_NEUTRAL in m for m in c.markers):
            failures.append(f"{c.label} ({c.path}) has no season-neutral '{SEASON_NEUTRAL}' marker; "
                            f"markers={c.markers} would false-fail in-season")

    # NBA board fast routes must accept the restricted-stats CONTAINMENT render (BK_NBA_STATS_ENABLED=0):
    # a marker that holds whether the full board shows OR the "temporarily unavailable" notice does, so
    # the smoke never false-fails the intended containment state.
    nba_props_fast = [c for c in ROUTE_CHECKS if c.fast and c.path.split("?")[0] == "/sports/nba/props"]
    for c in nba_props_fast:
        if not any("temporarily unavailable" in m for m in c.markers):
            failures.append(f"{c.label} ({c.path}) has no containment-aware marker "
                            f"('temporarily unavailable'); markers={c.markers} false-fail while NBA stats gated")

    print("=" * 60)
    print("QC: SMOKE MARKERS SEASON-ROBUST (football command routes)")
    print("=" * 60)
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1
    print("[OK] every football command fast route carries the season-neutral 'Command Surface' marker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
