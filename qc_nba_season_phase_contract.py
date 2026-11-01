"""QC: NBA season-phase contract (services/nba_season_phase.py) + app.py delegation.

Turns the yearly NBA calendar chore into a loud, dated failure: FAILS when today's Eastern date
is UNKNOWN, and FAILS the look-ahead check once any date within the look-ahead (default 60 days,
--lookahead N / env NBA_PHASE_LOOKAHEAD_DAYS) resolves UNKNOWN -- i.e. from (first UNKNOWN date -
look-ahead) onward. Before that it passes but prints a [WARN] with the first UNKNOWN date and the
exact date the look-ahead will start failing. --as-of YYYY-MM-DD rehearses a future run. Then runs
adversarial cases (no network, no data files):

  * the real 2026-27 table (official dates, retrieved 2026-11-01): 10-19 PRESEASON, 10-20 REGULAR,
    04-11 REGULAR, 04-12 PRE_POSTSEASON_BREAK, 04-13 / 04-17 POSTSEASON, 04-18+ UNKNOWN (Finals end
    unpublished -- never invented); the look-ahead fire date; provenance on every configured season
  * configured preseason / regular / postseason / offseason dates; first and last postseason day
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


def live_config_gate(lookahead, as_of=None):
    """Today must be KNOWN (hard fail). The look-ahead fails from (first UNKNOWN date - lookahead)
    onward; before that it passes but prints a loud, dated [WARN] naming the gap and the fire date."""
    today = as_of or P.eastern_today()
    r = P.resolve_nba_season_phase(today)
    print(f"[NOTE] as-of (Eastern) = {today}{' (pinned via --as-of)' if as_of else ''}; "
          f"phase = {r.phase} ({r.reason}); look-ahead = {lookahead} days")
    check(r.known, f"today {today} has a configured NBA phase (got {r.phase}: {r.reason})")
    first = P.first_unknown_date(today)
    fire = P.lookahead_fire_date(today, lookahead)
    if first is not None:
        print(f"[WARN] !!! NBA phase becomes UNKNOWN on {first.as_of} ({first.reason}; missing "
              f"{', '.join(first.missing)}). The {lookahead}-day look-ahead check FAILS from {fire} onward. "
              f"Enter the official date(s) in services/nba_season_phase.py NBA_SEASON_CONFIG before then. !!!")
    else:
        print(f"[NOTE] no UNKNOWN date within {P.DEFAULT_UNKNOWN_HORIZON_DAYS} days of {today}")
    gaps = P.unknown_dates(today, lookahead, None)
    if gaps:
        by_reason = {}
        for g in gaps:
            by_reason.setdefault(g.reason, []).append(g.as_of)
        detail = "; ".join(f"{k}: {min(v)}..{max(v)} ({len(v)} days)" for k, v in by_reason.items())
        check(False, f"every date {today}..{today + timedelta(days=lookahead)} is configured -- UNKNOWN: {detail}. "
                     f"Enter official dates in services/nba_season_phase.py NBA_SEASON_CONFIG")
    else:
        check(True, f"every date {today}..{today + timedelta(days=lookahead)} is configured"
                    + (f" (look-ahead fires {fire}; first UNKNOWN {first.as_of})" if first else ""))
    check(not P.validate_config(), f"NBA_SEASON_CONFIG is structurally valid {P.validate_config() or ''}")
    check(not P.validate_provenance(), f"every configured season has complete provenance {P.validate_provenance() or ''}")


def real_table_cases():
    """The configured 2026-27 table (official dates retrieved 2026-11-01)."""
    real = P.resolve_nba_season_phase
    expect = [
        (D(2026, 10, 1), P.PRESEASON, False), (D(2026, 10, 19), P.PRESEASON, False),
        (D(2026, 10, 20), P.REGULAR, False), (D(2026, 11, 1), P.REGULAR, False),
        (D(2027, 4, 11), P.REGULAR, False), (D(2027, 4, 12), P.PRE_POSTSEASON_BREAK, False),
        (D(2027, 4, 13), P.POSTSEASON, True), (D(2027, 4, 16), P.POSTSEASON, True),
        (D(2027, 4, 17), P.POSTSEASON, True), (D(2027, 4, 18), P.UNKNOWN, None),
        (D(2027, 6, 20), P.UNKNOWN, None), (D(2027, 9, 30), P.UNKNOWN, None),
        (D(2027, 10, 15), P.UNKNOWN, None), (D(2040, 1, 15), P.UNKNOWN, None),
    ]
    for d, phase, in_post in expect:
        r = real(d)
        check(r.phase == phase and r.in_postseason is in_post,
              f"real 2026-27 {d} -> {phase} in_postseason={in_post} (got {r.phase}/{r.in_postseason}: {r.reason})")
    check(real(D(2027, 4, 13)).reason == "inside_published_play_in_end_unpublished", "2027-04-13 is the Play-In (reason)")
    check(real(D(2027, 4, 17)).reason == "on_published_postseason_date_end_unpublished", "2027-04-17 is playoffs start (reason)")
    check(real(D(2027, 4, 18)).reason == "postseason_end_not_configured", "2027-04-18 UNKNOWN: Finals end unpublished, not guessed")
    check(real(D(2027, 10, 15)).reason == "season_not_configured", "2027-10-15 (2027-28) UNKNOWN season_not_configured")
    sweep = [real(d) for d in daterange(D(2026, 10, 1), D(2027, 9, 30))]
    check(not [x for x in sweep if x.as_of > D(2027, 4, 11) and x.phase == P.REGULAR],
          "no date after the official regular-season end (2027-04-11) is REGULAR")
    check(not [x for x in sweep if x.as_of > D(2027, 4, 17) and x.phase != P.UNKNOWN],
          "every date after the last published postseason date (2027-04-17) is UNKNOWN (no Finals date invented)")
    cfg = P.NBA_SEASON_CONFIG[2027]
    check(cfg["postseason_end"] is None and cfg["provenance"]["unpublished"] == ("postseason_end",),
          "2027 postseason_end stays None and is declared unpublished")
    check(P.config_warning(D(2026, 11, 1)) and "postseason_end" in P.config_warning(D(2026, 11, 1)),
          "owner warning still names the unpublished postseason_end today")

    # Look-ahead fire date: first UNKNOWN 2027-04-18 minus N days.
    first = P.first_unknown_date(D(2026, 11, 1))
    check(first is not None and first.as_of == D(2027, 4, 18), f"first UNKNOWN date from 2026-11-01 is 2027-04-18 (got {first and first.as_of})")
    check(P.lookahead_fire_date(D(2026, 11, 1), 60) == D(2027, 2, 17), "60-day look-ahead fires on 2027-02-17")
    check(P.lookahead_fire_date(D(2026, 11, 1), 90) == D(2027, 1, 18), "90-day look-ahead fires on 2027-01-18")
    check(not P.unknown_dates(D(2027, 2, 16), 60) and P.unknown_dates(D(2027, 2, 17), 60),
          "look-ahead clean on 2027-02-16, non-empty on 2027-02-17 (fire date is exact)")
    check(P.lookahead_fire_date(D(2027, 5, 1), 60) == D(2027, 5, 1), "fire date clamps to as-of when already UNKNOWN")
    check(P.lookahead_fire_date(D(2099, 1, 1), 60, {}) == D(2099, 1, 1), "empty config fires immediately")


def provenance_cases():
    good = P.NBA_SEASON_CONFIG
    check(not P.validate_provenance(good), "real config provenance validates")
    for year, entry in good.items():
        prov = entry.get("provenance") or {}
        srcs = prov.get("sources") or ()
        check(isinstance(prov.get("retrieved"), date) and srcs and all(
            s.get("url", "").startswith("https://") and s.get("quotes") and isinstance(s.get("retrieved"), date)
            for s in srcs) and "unpublished" in prov,
            f"{year}: provenance has retrieved date, sources(url+quotes+retrieved) and unpublished field")
    urls = {s["url"] for s in good[2027]["provenance"]["sources"]}
    check(urls == {"https://pr.nba.com/2026-27-nba-regular-season-schedule", "https://www.nba.com/news/key-dates"},
          "2027 sources are the two official NBA pages")
    check(any("Playoffs 2026" in s.get("notes", "") for s in good[2027]["provenance"]["sources"]),
          "key-dates labeling discrepancy ('NBA Playoffs 2026') is recorded")
    base = {"regular_start": D(2098, 10, 20), "postseason_start": D(2099, 4, 13), "postseason_end": None}
    src = {"url": "https://example.invalid/x", "retrieved": D(2098, 9, 1), "quotes": ("q",),
           "supports": ("regular_start", "postseason_start")}
    ok_prov = {"retrieved": D(2098, 9, 1), "sources": (src,),
               "unpublished": ("regular_end", "playoffs_start", "postseason_end")}
    check(not P.validate_provenance({2099: {**base, "provenance": ok_prov}}), "synthetic complete provenance validates")
    bad = {
        "no provenance": {2099: dict(base)},
        "None not declared unpublished": {2099: {**base, "provenance": {**ok_prov, "unpublished": ("postseason_end",)}}},
        "set field declared unpublished": {2099: {**base, "provenance": {**ok_prov, "unpublished": ok_prov["unpublished"] + ("regular_start",)}}},
        "set field unsupported": {2099: {**base, "postseason_end": D(2099, 6, 20), "provenance": {**ok_prov, "unpublished": ("regular_end", "playoffs_start")}}},
        "empty quotes": {2099: {**base, "provenance": {**ok_prov, "sources": ({**src, "quotes": ("",)},)}}},
        "http url": {2099: {**base, "provenance": {**ok_prov, "sources": ({**src, "url": "http://x"},)}}},
        "no sources": {2099: {**base, "provenance": {**ok_prov, "sources": ()}}},
    }
    for name, cfg in bad.items():
        check(P.validate_provenance(cfg), f"validate_provenance rejects: {name}")


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

    # regular_end + playoffs_start semantics (synthetic complete season).
    FULL2 = {2099: {**FULL[2099], "regular_end": D(2099, 4, 11), "playoffs_start": D(2099, 4, 17)}}
    R2 = lambda d: P.resolve_nba_season_phase(d, FULL2)
    check(R2(D(2099, 4, 11)).phase == P.REGULAR, "regular_end (inclusive) -> REGULAR")
    check(R2(D(2099, 4, 12)).phase == P.PRE_POSTSEASON_BREAK and R2(D(2099, 4, 12)).in_postseason is False,
          "after regular_end, before Play-In -> PRE_POSTSEASON_BREAK (not REGULAR), in_postseason=False")
    check(R2(D(2099, 4, 13)).reason == "inside_configured_play_in" and R2(D(2099, 4, 17)).phase == P.POSTSEASON,
          "Play-In days are POSTSEASON (play-in reason); playoffs start POSTSEASON")
    check(R2(D(2099, 6, 30)).phase == P.POSTSEASON and R2(D(2099, 7, 1)).phase == P.OFFSEASON,
          "complete window with playoffs_start still ends at postseason_end")
    check(P.default_postseason_flag(R2(D(2099, 4, 12))) is False, "PRE_POSTSEASON_BREAK -> postseason default False")
    # Finals end unpublished: published span only.
    NOEND = {2099: {**FULL2[2099], "postseason_end": None}}
    check(P.resolve_nba_season_phase(D(2099, 4, 17), NOEND).phase == P.POSTSEASON
          and P.resolve_nba_season_phase(D(2099, 4, 18), NOEND).phase == P.UNKNOWN,
          "end unpublished: POSTSEASON through playoffs_start, UNKNOWN the day after")
    NOPO = {2099: {**NOEND[2099], "playoffs_start": None}}
    check(P.resolve_nba_season_phase(D(2099, 4, 13), NOPO).phase == P.POSTSEASON
          and P.resolve_nba_season_phase(D(2099, 4, 14), NOPO).phase == P.UNKNOWN,
          "end + playoffs_start unpublished: only the Play-In start day is POSTSEASON, then UNKNOWN")
    pre_ps, from_ps2 = (D(2098, 10, 1), D(2099, 4, 12)), (D(2099, 4, 13), D(2099, 9, 30))
    for name, bad, (a, b) in (("regular_end == postseason_start", {"regular_end": D(2099, 4, 13)}, pre_ps),
                              ("regular_end before regular_start", {"regular_end": D(2098, 10, 1)}, pre_ps),
                              ("playoffs_start before Play-In", {"playoffs_start": D(2099, 4, 10)}, from_ps2),
                              ("postseason_end before playoffs_start", {"postseason_end": D(2099, 4, 15)}, from_ps2)):
        cfg = {2099: {**FULL2[2099], **bad}}
        check(P.validate_config(cfg), f"validate_config rejects {name}")
        sweep = [P.resolve_nba_season_phase(d, cfg) for d in daterange(a, b)]
        check(all(x.phase == P.UNKNOWN and x.reason.startswith("config_invalid") for x in sweep),
              f"invalid '{name}': every date in {a}..{b} is UNKNOWN config_invalid_* (never a guessed phase)")
    check(not P.validate_config(FULL2), "valid FULL2 config passes validate_config")

    real = P.resolve_nba_season_phase

    # Far future / unconfigured seasons.
    for d in (D(2040, 1, 15), D(2027, 10, 15), D(2026, 3, 1), D(1999, 5, 1)):
        r = real(d)
        check(r.phase == P.UNKNOWN and r.reason == "season_not_configured", f"unconfigured season {d} -> UNKNOWN season_not_configured")

    # Never REGULAR inside any unconfigured window (sweep partial configs over whole seasons).
    season = (D(2098, 10, 1), D(2099, 9, 30))
    # The Play-In start day itself is a published postseason date, so with the Finals end missing the
    # unconfigured window begins the day AFTER it (2099-04-14).
    before_ps, after_ps = (D(2098, 10, 1), D(2099, 4, 12)), (D(2099, 4, 14), D(2099, 9, 30))
    partials = {  # name: (config, the window(s) that config leaves unconfigured)
        "no season": ({}, [season]),
        "start only": ({2099: {"postseason_start": D(2099, 4, 13)}}, [before_ps, after_ps]),
        "end missing": ({2099: {"regular_start": D(2098, 10, 20), "postseason_start": D(2099, 4, 13), "postseason_end": None}}, [after_ps]),
        "regular missing": ({2099: {"regular_start": None, "postseason_start": D(2099, 4, 13), "postseason_end": D(2099, 6, 30)}}, [before_ps]),
        "legacy shape": ({2099: {"start": D(2099, 4, 13), "end": D(2099, 6, 30)}}, [before_ps]),
        "invalid order": ({2099: {"regular_start": D(2099, 5, 1), "postseason_start": D(2099, 4, 13), "postseason_end": D(2099, 3, 1)}}, [season]),
    }
    for name, (cfg, windows) in partials.items():
        whole = [P.resolve_nba_season_phase(d, cfg) for d in daterange(*season)]
        for a, b in windows:
            phases = [r for r in whole if a <= r.as_of <= b]
            bad = [r for r in phases if r.phase != P.UNKNOWN]
            check(not bad, f"partial config '{name}': all of {a}..{b} is UNKNOWN (bad={len(bad)})")
        if name != "end missing":  # 'end missing' configures regular_start, so its pre-Play-In dates are known
            check(not [r for r in whole if r.phase in (P.REGULAR, P.PRESEASON, P.PRE_POSTSEASON_BREAK)],
                  f"partial config '{name}': no REGULAR/PRESEASON/BREAK anywhere in the season")
    check(P.validate_config(partials["invalid order"][0]), "validate_config flags out-of-order dates")
    check(P.validate_config({2099: {"postseason_start": datetime(2099, 4, 13)}}), "validate_config rejects datetime (must be date)")

    # Fail-closed default mapping.
    F = P.default_postseason_flag
    check(F(real(D(2027, 5, 1))) is True, "fail-closed: UNKNOWN (postseason end missing) -> postseason default True")
    check(F(real(D(2040, 1, 15))) is True, "fail-closed: UNKNOWN (season not configured) -> postseason default True")
    check(F(P.resolve_nba_season_phase(D(2099, 1, 1), partials["regular missing"][0])) is False,
          "UNKNOWN before configured postseason start -> default False (decided by config)")
    check(F(real(D(2026, 11, 1))) is False and F(real(D(2027, 4, 13))) is True and F(real(D(2027, 4, 18))) is True,
          "real table defaults: REGULAR->False, Play-In->True, UNKNOWN after published span->True (fail-closed)")
    check(F(R(D(2099, 1, 20))) is False and F(R(D(2099, 7, 1))) is False and F(R(D(2099, 5, 1))) is True,
          "known phases map REGULAR/OFFSEASON->False, POSTSEASON->True")

    # Owner warning.
    w = P.config_warning(D(2027, 2, 20))
    check("postseason_end" in w and "2027-04-18" in w, "config_warning names the missing field and the first UNKNOWN date (2027-04-18)")
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
        for d, expect in ((D(2026, 10, 19), False), (D(2026, 11, 1), False), (D(2027, 4, 11), False),
                          (D(2027, 4, 12), False), (D(2027, 4, 13), True), (D(2027, 4, 17), True),
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
    ap.add_argument("--as-of", type=date.fromisoformat, default=None,
                    help="pin the live gate's 'today' (YYYY-MM-DD) to rehearse a future run; default = Eastern today")
    args = ap.parse_args()
    print("=" * 60)
    print("NBA SEASON PHASE CONTRACT QC")
    print("=" * 60)
    live_config_gate(args.lookahead, args.as_of)
    real_table_cases()
    provenance_cases()
    synthetic_cases()
    delegation_cases()
    fails = [m for ok, m in results if not ok]
    print("-" * 60)
    print(f"{len(results) - len(fails)} ok, {len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
