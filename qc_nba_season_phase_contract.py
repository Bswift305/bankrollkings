"""QC: NBA season-phase contract (services/nba_season_phase.py) + app.py delegation.

Turns the yearly NBA calendar chore into a loud, dated failure: FAILS when today's Eastern date,
or any date within the look-ahead (default 60 days, --lookahead N / env NBA_PHASE_LOOKAHEAD_DAYS),
resolves to UNKNOWN because its season or a relevant boundary is not configured. Then runs
synthetic adversarial cases (no network, no data files):

  * configured preseason / regular / postseason / offseason dates; first and last postseason day
  * the real 2027 table: postseason end unpublished => UNKNOWN on/after the play-in start, NEVER REGULAR
  * far-future / unconfigured season => UNKNOWN
  * the resolver never returns REGULAR for any date in an unconfigured window
  * fail-closed postseason default (UNKNOWN => postseason unless the date precedes the configured start)
  * app.py delegation is identical to the pre-contract implementation over a date range for every
    configured (complete) window, and the legacy NBA_POSTSEASON_DATES values are mirrored exactly

Prints [ok] / [FAIL] per check; exits 1 on any failure. Run:  py -3 qc_nba_season_phase_contract.py
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

from services import nba_season_phase as P

D = date
results = []


def check(cond, msg):
    results.append((bool(cond), msg))
    print(f"[{'ok' if cond else 'FAIL'}] {msg}")


# --- verbatim pre-contract implementation (app.py @ 63060a9), the regression oracle -----------
OLD_NBA_POSTSEASON_DATES = {2027: {"start": datetime(2027, 4, 13).date(), "end": None}}


def old_resolve_nba_postseason(today, ending_year, config=OLD_NBA_POSTSEASON_DATES):
    entry = config.get(ending_year)
    if not entry:
        return False
    start, end = entry.get("start"), entry.get("end")
    if start is None or end is None:
        return False
    return start <= today <= end


def old_ending_year(d):  # get_current_nba_season() rule applied to d
    return d.year + 1 if d.month >= 10 else d.year


def old_default_postseason(d, config):
    return old_resolve_nba_postseason(d, old_ending_year(d), config)


def daterange(a, b):
    while a <= b:
        yield a
        a += timedelta(days=1)


# Synthetic COMPLETE season (contract shape).
FULL = {2099: {"regular_start": D(2098, 10, 20), "postseason_start": D(2099, 4, 13), "postseason_end": D(2099, 6, 30)}}


def live_config_gate(lookahead):
    today = P.eastern_today()
    r = P.resolve_nba_season_phase(today)
    print(f"[NOTE] Eastern today = {today}; phase = {r.phase} ({r.reason}); look-ahead = {lookahead} days")
    check(r.known, f"today {today} has a configured NBA phase (got {r.phase}: {r.reason})")
    gaps = P.unknown_dates(today, lookahead, None)
    if gaps:
        by_reason = {}
        for g in gaps:
            by_reason.setdefault(g.reason, []).append(g.as_of)
        detail = "; ".join(f"{k}: {min(v)}..{max(v)} ({len(v)} days)" for k, v in by_reason.items())
        check(False, f"every date {today}..{today + timedelta(days=lookahead)} is configured -- UNKNOWN: {detail}. "
                     f"Enter official dates in services/nba_season_phase.py NBA_SEASON_CONFIG")
    else:
        check(True, f"every date {today}..{today + timedelta(days=lookahead)} is configured")
    check(not P.validate_config(), f"NBA_SEASON_CONFIG is structurally valid {P.validate_config() or ''}")


def synthetic_cases():
    R = lambda d, c=FULL: P.resolve_nba_season_phase(d, c)
    check(R(D(2098, 10, 5)).phase == P.PRESEASON, "configured preseason date (Oct 5, before opening night) -> PRESEASON")
    check(R(D(2098, 10, 19)).phase == P.PRESEASON, "day before opening night -> PRESEASON")
    check(R(D(2098, 10, 20)).phase == P.REGULAR, "opening night (inclusive) -> REGULAR")
    check(R(D(2099, 1, 20)).phase == P.REGULAR, "configured mid-season date -> REGULAR")
    check(R(D(2099, 4, 12)).phase == P.REGULAR, "day before postseason start -> REGULAR")
    check(R(D(2099, 4, 13)).phase == P.POSTSEASON, "first postseason day (inclusive) -> POSTSEASON")
    check(R(D(2099, 5, 10)).phase == P.POSTSEASON, "off-day inside postseason window -> POSTSEASON")
    check(R(D(2099, 6, 30)).phase == P.POSTSEASON, "last postseason day (inclusive) -> POSTSEASON")
    check(R(D(2099, 7, 1)).phase == P.OFFSEASON, "day after postseason end -> OFFSEASON")
    check(R(D(2099, 9, 30)).phase == P.OFFSEASON, "Sep 30 after the Finals -> OFFSEASON")
    check(R(D(2099, 10, 1)).phase == P.UNKNOWN and R(D(2099, 10, 1)).reason == "season_not_configured",
          "Oct 1 rolls into the next (unconfigured) season -> UNKNOWN season_not_configured")
    check(R(D(2099, 5, 1)).in_postseason is True and R(D(2099, 1, 1)).in_postseason is False,
          "in_postseason tri-state matches configured window")

    # Real table: 2027 postseason end unpublished.
    real = P.resolve_nba_season_phase
    for d in (D(2027, 4, 13), D(2027, 5, 1), D(2027, 6, 20), D(2027, 8, 15), D(2027, 9, 30)):
        r = real(d)
        check(r.phase == P.UNKNOWN and r.reason == "postseason_end_not_configured" and r.in_postseason is None,
              f"real config {d}: postseason end unknown -> UNKNOWN (not REGULAR), in_postseason=None")
    r = real(D(2027, 4, 12))
    check(r.phase == P.UNKNOWN and r.reason == "regular_start_not_configured" and r.in_postseason is False,
          "real config 2027-04-12: opening night unconfigured -> UNKNOWN, but definitively not postseason")
    check(real(D(2026, 11, 1)).phase == P.UNKNOWN, "real config 2026-11-01: regular_start missing -> UNKNOWN, never guessed REGULAR")

    # Far future / unconfigured seasons.
    for d in (D(2040, 1, 15), D(2027, 10, 15), D(2026, 3, 1), D(1999, 5, 1)):
        r = real(d)
        check(r.phase == P.UNKNOWN and r.reason == "season_not_configured", f"unconfigured season {d} -> UNKNOWN season_not_configured")

    # Never REGULAR inside any unconfigured window (sweep partial configs over whole seasons).
    season = (D(2098, 10, 1), D(2099, 9, 30))
    before_ps, from_ps = (D(2098, 10, 1), D(2099, 4, 12)), (D(2099, 4, 13), D(2099, 9, 30))
    partials = {  # name: (config, the window that config leaves unconfigured)
        "no season": ({}, season),
        "start only": ({2099: {"postseason_start": D(2099, 4, 13)}}, season),
        "end missing": ({2099: {"regular_start": D(2098, 10, 20), "postseason_start": D(2099, 4, 13), "postseason_end": None}}, from_ps),
        "regular missing": ({2099: {"regular_start": None, "postseason_start": D(2099, 4, 13), "postseason_end": D(2099, 6, 30)}}, before_ps),
        "legacy shape": ({2099: {"start": D(2099, 4, 13), "end": D(2099, 6, 30)}}, before_ps),
        "invalid order": ({2099: {"regular_start": D(2099, 5, 1), "postseason_start": D(2099, 4, 13), "postseason_end": D(2099, 3, 1)}}, season),
    }
    for name, (cfg, (a, b)) in partials.items():
        phases = [P.resolve_nba_season_phase(d, cfg) for d in daterange(a, b)]
        bad = [r for r in phases if r.phase in (P.REGULAR, P.PRESEASON)]
        check(not bad and all(r.phase == P.UNKNOWN for r in phases),
              f"partial config '{name}': all of {a}..{b} is UNKNOWN, none REGULAR/PRESEASON (bad={len(bad)})")
    check(P.validate_config(partials["invalid order"][0]), "validate_config flags out-of-order dates")
    check(P.validate_config({2099: {"postseason_start": datetime(2099, 4, 13)}}), "validate_config rejects datetime (must be date)")

    # Fail-closed default mapping.
    F = P.default_postseason_flag
    check(F(real(D(2027, 5, 1))) is True, "fail-closed: UNKNOWN (postseason end missing) -> postseason default True")
    check(F(real(D(2040, 1, 15))) is True, "fail-closed: UNKNOWN (season not configured) -> postseason default True")
    check(F(real(D(2026, 11, 1))) is False, "UNKNOWN before configured postseason start -> default False (decided by config)")
    check(F(R(D(2099, 1, 20))) is False and F(R(D(2099, 7, 1))) is False and F(R(D(2099, 5, 1))) is True,
          "known phases map REGULAR/OFFSEASON->False, POSTSEASON->True")

    # Owner warning.
    w = P.config_warning(D(2027, 2, 20))
    check("postseason_end" in w and "2027-04-13" in w, "config_warning names the missing field and the first UNKNOWN date")
    check(P.config_warning(D(2099, 1, 1), 60, FULL) == "", "config_warning is empty for a fully configured window")


def delegation_cases():
    os.environ.setdefault("SECRET_KEY", "qc-nba-season-phase-dummy")
    import app

    check(app.NBA_POSTSEASON_DATES == OLD_NBA_POSTSEASON_DATES,
          "app.NBA_POSTSEASON_DATES mirrors the pre-contract values exactly")
    check(app.NBA_POSTSEASON_DATES is P.NBA_POSTSEASON_DATES, "app.NBA_POSTSEASON_DATES is the contract's legacy view (one source)")

    legacy_complete = {2099: {"start": D(2099, 4, 13), "end": D(2099, 6, 30)},
                       2100: {"start": D(2100, 4, 14), "end": D(2100, 6, 21)}}
    span = list(daterange(D(2026, 1, 1), D(2028, 1, 1))) + list(daterange(D(2098, 9, 1), D(2100, 10, 31)))
    mism = [(d, y) for d in span for y in (old_ending_year(d), 2027, 2099, 2100)
            for cfg in (legacy_complete, OLD_NBA_POSTSEASON_DATES)
            if app._resolve_nba_postseason(d, y, cfg) != old_resolve_nba_postseason(d, y, cfg)]
    check(not mism, f"_resolve_nba_postseason identical to pre-contract over {len(span)} dates x 4 years x 2 configs (mismatches={len(mism)})")

    # The phase-driven default equals the old default wherever the window is configured.
    contract_complete = {y: {"regular_start": D(y - 1, 10, 20), "postseason_start": e["start"], "postseason_end": e["end"]}
                         for y, e in legacy_complete.items()}
    configured = [d for d in daterange(D(2098, 10, 1), D(2100, 9, 30))]
    diff = [d for d in configured
            if P.default_postseason_flag(P.resolve_nba_season_phase(d, contract_complete)) != old_default_postseason(d, legacy_complete)]
    check(not diff, f"postseason default identical to pre-contract on {len(configured)} configured dates (diffs={len(diff)})")

    real_today = app.sports_today_date
    try:
        for d, expect in ((D(2026, 11, 1), False), (D(2027, 4, 12), False), (D(2027, 4, 13), True),
                          (D(2027, 5, 20), True), (D(2027, 10, 15), True)):
            app.sports_today_date = (lambda dd=d: dd)
            check(app._nba_default_postseason() is expect, f"app._nba_default_postseason() pinned {d} -> {expect}")
            with app.app.test_request_context("/sports/nba"):
                check(app.postseason_only_enabled(sport="nba") is expect, f"NBA page default pinned {d} -> {expect} (bool, no crash)")
            with app.app.test_request_context("/sports/mlb"):
                check(app.postseason_only_enabled() is True, f"non-NBA page default unchanged (True) pinned {d}")
            with app.app.test_request_context("/sports/nba?postseason=0"):
                check(app.postseason_only_enabled(sport="nba") is False, f"explicit ?postseason=0 still wins pinned {d}")
        app.sports_today_date = lambda: D(2027, 5, 1)
        check(bool(app.nba_postseason_config_warning()), "owner warning non-empty while 2027 postseason end is missing")
        check(app.current_nba_season_phase().phase == P.UNKNOWN, "app.current_nba_season_phase() surfaces UNKNOWN")

        def boom():
            raise RuntimeError("clock down")
        app.sports_today_date = boom
        check(app._nba_default_postseason() is True, "clock failure -> fail-closed postseason default True")
        check("UNKNOWN" in app.nba_postseason_config_warning(), "clock failure -> owner warning reports UNKNOWN (not '')")
    finally:
        app.sports_today_date = real_today


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookahead", type=int, default=int(os.environ.get("NBA_PHASE_LOOKAHEAD_DAYS", P.DEFAULT_LOOKAHEAD_DAYS)))
    args = ap.parse_args()
    print("=" * 60)
    print("NBA SEASON PHASE CONTRACT QC")
    print("=" * 60)
    live_config_gate(args.lookahead)
    synthetic_cases()
    delegation_cases()
    fails = [m for ok, m in results if not ok]
    print("-" * 60)
    print(f"{len(results) - len(fails)} ok, {len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
