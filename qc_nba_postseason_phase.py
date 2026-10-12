"""QC: NBA postseason phase rule (the approved thirteen phase tests + scoping).

Regression guard for the NBA P0 season-state correction. The window is a CONFIGURED official
[start, end] per season ending year (not derived from completed results), so day-1 and off-days
between games stay postseason; an incomplete entry (end unpublished) defaults safely to regular
season; explicit ?postseason= always overrides; props/feed availability and stale prior-season
results cannot flip it; other sports are unchanged.

Boundary/end tests use a SYNTHETIC complete window (the real 2027 end is intentionally None).
Exits 0 when all checks pass, 1 otherwise.
"""
from __future__ import annotations

from datetime import datetime

import app

D = lambda y, m, d: datetime(y, m, d).date()

# Synthetic COMPLETE window (the real NBA_POSTSEASON_DATES[2027] has end=None by design).
COMPLETE = {2099: {"start": D(2099, 4, 13), "end": D(2099, 6, 30)}}


def run():
    issues, notes = [], []

    def expect(cond, msg):
        if not cond:
            issues.append(msg)

    R = app._resolve_nba_postseason  # pure: (today, ending_year, config) -> bool

    # 1. Preseason, no props (Oct, before the window) -> regular season
    expect(R(D(2099, 10, 15), 2099, COMPLETE) is False, "1 preseason(no props) should be regular")
    # 2. Preseason WITH props -> still regular (the resolver takes no props input, so props cannot flip it)
    expect(R(D(2099, 10, 15), 2099, COMPLETE) is False, "2 preseason(with props) must not flip to postseason")
    # 3. Regular season (before start) -> regular
    expect(R(D(2099, 1, 20), 2099, COMPLETE) is False, "3 regular season should be regular")
    # 4. Current-season postseason (inside window) -> postseason
    expect(R(D(2099, 5, 1), 2099, COMPLETE) is True, "4 inside window should be postseason")
    # 5. Stale prior-season results present -> ignored (resolver reads no results); a regular-season date stays regular
    expect(R(D(2099, 10, 15), 2099, COMPLETE) is False, "5 stale prior-season results must not flip phase")
    # 7. First playoff day, before any result recorded -> postseason (no results needed)
    expect(R(D(2099, 4, 13), 2099, COMPLETE) is True, "7 first playoff day (no result yet) should be postseason")
    # 8. Off-day between games (inside window, latest result days old) -> postseason (window governs)
    expect(R(D(2099, 5, 10), 2099, COMPLETE) is True, "8 off-day between games should be postseason")
    # 9. Day before configured start -> regular
    expect(R(D(2099, 4, 12), 2099, COMPLETE) is False, "9 day before start should be regular")
    # 10. Exactly the configured start -> postseason (inclusive)
    expect(R(D(2099, 4, 13), 2099, COMPLETE) is True, "10 start is inclusive -> postseason")
    # 11. Exactly the configured end -> postseason (inclusive)
    expect(R(D(2099, 6, 30), 2099, COMPLETE) is True, "11 end is inclusive -> postseason")
    # 12. Day after configured end -> regular
    expect(R(D(2099, 7, 1), 2099, COMPLETE) is False, "12 day after end should be regular")
    # 13. Incomplete config (real 2027 end is None) -> regular, and the owner warning fires
    expect(R(D(2027, 5, 1), 2027, app.NBA_POSTSEASON_DATES) is False, "13 incomplete (end None) must be regular")
    expect(app._nba_postseason_config_complete(2027) is False, "13 2027 config must read incomplete")
    expect(bool(app.nba_postseason_config_warning()), "13 incomplete 2027 must raise an owner warning")

    # missing entry -> regular
    expect(R(D(2099, 5, 1), 1900, COMPLETE) is False, "missing entry should be regular")

    # --- Route-level integration (6 + the /dashboard correction) -------------------------
    # The real 2027 window is incomplete (end=None), so every NBA-owned surface must default to
    # REGULAR season. /dashboard is NBA-owned (the NBA Command Center) and must NOT stay postseason.
    NBA_OWNED = [
        "/dashboard", "/sports/nba", "/sports/nba/props", "/sports/nba/market-edge",
        "/sports/nba/matchup-lens", "/sports/nba/trends", "/sports/nba/injuries",
        "/props", "/market-edge", "/matchup-lens", "/trends", "/injuries",
    ]
    for p in NBA_OWNED:
        with app.app.test_request_context(p):
            expect(app.postseason_only_enabled() is False, f"NBA-owned {p} must default to regular season")

    # 6. Explicit query overrides always win, on any NBA surface.
    with app.app.test_request_context("/dashboard?postseason=1"):
        expect(app.postseason_only_enabled() is True, "override ?postseason=1 on /dashboard -> postseason")
    with app.app.test_request_context("/sports/nba?postseason=0"):
        expect(app.postseason_only_enabled() is False, "override ?postseason=0 on /sports/nba -> regular")
    with app.app.test_request_context("/sports/nba/props?postseason=1"):
        expect(app.postseason_only_enabled() is True, "override ?postseason=1 on NBA props -> postseason")

    # 7. Non-NBA routes keep the prior default (True) -- unchanged.
    NON_NBA = ["/sports/mlb", "/sports/wnba", "/sports/nfl", "/sports/ncaaf", "/"]
    for p in NON_NBA:
        with app.app.test_request_context(p):
            expect(app.postseason_only_enabled() is True, f"non-NBA {p} must keep the prior default True")
    # a shared tool carrying an explicit non-NBA sport param is not NBA-owned
    with app.app.test_request_context("/props?sport=mlb"):
        expect(app.postseason_only_enabled() is True, "/props?sport=mlb must not be treated as NBA")
    # explicit sport='nba' forces the NBA default regardless of path
    with app.app.test_request_context("/"):
        expect(app.postseason_only_enabled(sport="nba") is False, "explicit sport=nba forces the NBA default")

    notes.append("13 phase tests + overrides + route-level NBA-owned (incl /dashboard) + "
                 "non-NBA-unchanged + explicit-sport checks executed")
    return issues, notes


def main() -> int:
    issues, notes = run()
    print("=" * 60)
    print("NBA POSTSEASON PHASE QC")
    print("=" * 60)
    for n in notes:
        print(f"[NOTE] {n}")
    if not issues:
        print("All phase/override/scoping checks passed.")
        return 0
    for m in issues:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
