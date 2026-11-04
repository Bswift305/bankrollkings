"""
QC: an NFL prop quote's update time is the provider's zone-explicit SourceUpdatedAtUTC -- never the zone-less
LastUpdated (production incident 2026-11-04).

On the UTC prod box fetch_player_props writes LastUpdated as its own FETCH time, zone-less, in the process's
zone (the bookmaker-level last_update it prefers is absent from event odds). The ticket gate read that stamp
as Eastern, so every 13:00Z quote looked like 18:00Z: QUOTE_FROM_FUTURE (blocked) for ~5h, then "fresh" up to
~11h after the real update, with a false "updated 13:00 ET" label. This QC freezes the contract:

  - the quote time = SourceUpdatedAtUTC exactly, in any process time zone;
  - a missing, blank or zone-less SourceUpdatedAtUTC -> no quote (fail closed), whatever LastUpdated says;
  - the 6h freshness rule then ages the real provider time (fresh / STALE_QUOTE / never QUOTE_FROM_FUTURE);
  - the newest row is chosen by SourceUpdatedAtUTC, not by LastUpdated;
  - the NFL floor-board disk key moved off 'q1k2' so pre-fix cached quotes are never served.

Offline, synthetic. Run via `py -3 qc_offline.py qc_props_quote_source_time.py`.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "qc-props-quote-source-time")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

passed = 0
failures: list[str] = []


def check(cond, msg):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(msg)


def row(source_utc, last_updated="2026-11-04 13:00", book="DraftKings"):
    return {"Book": book, "LastUpdated": last_updated, "SourceUpdatedAtUTC": source_utc,
            "Game": "Las Vegas Raiders@San Francisco 49ers", "MarketKey": "player_reception_yds",
            "Stat": "Receiving Yards"}


def at(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_in_zone(tz):
    """Run the core assertions with the process clock zone set to `tz` (POSIX; on Windows tzset is absent
    and the parse under test never consults the process zone anyway)."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        # 1. The incident row: LastUpdated is the zone-less fetch time; the provider time is 13:00:38Z.
        q = app._quote_from_row(row("2026-11-04T13:00:38Z"), "Ashton Jeanty", 33.5, -115)
        check(q is not None, f"[{tz}] incident row must yield a quote")
        if q:
            check(q["updated_utc"] == "2026-11-04T13:00:38Z",
                  f"[{tz}] quote time must be SourceUpdatedAtUTC, got {q['updated_utc']}")
            now = at("2026-11-04T13:40:00Z")
            check(app._quote_freshness_failure(q["updated_utc"], now) is None,
                  f"[{tz}] a 40-minute-old quote is fresh, got {app._quote_freshness_failure(q['updated_utc'], now)}")
            check(app._quote_freshness_failure(q["updated_utc"], at("2026-11-04T19:01:00Z")) == "STALE_QUOTE",
                  f"[{tz}] the same quote is STALE past 6h of the REAL provider time")
            for probe in ("2026-11-04T13:00:00Z", "2026-11-04T17:59:00Z", "2026-11-04T23:59:00Z"):
                check(app._quote_freshness_failure(q["updated_utc"], at(probe)) != "QUOTE_FROM_FUTURE",
                      f"[{tz}] never QUOTE_FROM_FUTURE at {probe}")
            # the label shows the real provider time in Eastern (08:00 ET), not the fetch stamp re-read as ET
            check(app._updated_label(q["updated_utc"]).startswith("updated 2026-11-04 08:00"),
                  f"[{tz}] label must be the provider time in ET, got {app._updated_label(q['updated_utc'])}")
        # 2. Offset spellings canonicalize to the same instant.
        q2 = app._quote_from_row(row("2026-11-04T08:00:38-05:00"), "P", 33.5, -115)
        check(q2 is not None and q2["updated_utc"] == "2026-11-04T13:00:38Z",
              f"[{tz}] -05:00 offset must canonicalize to 13:00:38Z")
        # 3. Fail closed: missing / blank / NaN / zone-less source time -> no quote, whatever LastUpdated says.
        for bad in (None, "", "nan", float("nan"), "2026-11-04 13:00:38", "2026-11-04T13:00:38", "garbage"):
            check(app._quote_from_row(row(bad), "P", 33.5, -115) is None,
                  f"[{tz}] SourceUpdatedAtUTC={bad!r} must yield NO quote")
        # LastUpdated alone (even zone-aware) never supplies the time.
        r = row(None, last_updated="2026-11-04T13:00:00Z")
        check(app._quote_from_row(r, "P", 33.5, -115) is None,
              f"[{tz}] LastUpdated must never be used as the quote time")
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        if hasattr(time, "tzset"):
            time.tzset()


def skew_and_age(tz):
    """5-minute provider clock-skew contract + the real 6h age boundary (process zone `tz`)."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        now = at("2026-11-04T13:00:00Z")
        st = app._quote_clock_status("2026-11-04T13:00:00Z", now)
        check(st["failure"] is None and st["notes"] == [] and st["age_seconds"] == 0,
              f"[{tz}] same-instant quote fresh, no skew note ({st})")
        for ahead in ("2026-11-04T13:00:01Z", "2026-11-04T13:03:00Z", "2026-11-04T13:05:00Z"):
            st = app._quote_clock_status(ahead, now)
            check(st["failure"] is None and st["notes"] == ["CLOCK_SKEW_TOLERATED"] and st["age_seconds"] == 0,
                  f"[{tz}] {ahead} (<=5 min ahead) accepted fresh, CLOCK_SKEW_TOLERATED, age clamped 0 ({st})")
        for ahead in ("2026-11-04T13:05:01Z", "2026-11-04T13:15:00Z", "2026-11-04T18:00:00Z"):
            check(app._quote_freshness_failure(ahead, now) == "QUOTE_FROM_FUTURE",
                  f"[{tz}] {ahead} (>5 min ahead) fails closed QUOTE_FROM_FUTURE")
        # the tolerated skew is clamped to zero, so it never extends the 6h window
        check(app._quote_freshness_failure("2026-11-04T13:05:00Z", at("2026-11-04T19:05:00Z")) is None,
              f"[{tz}] exactly 6h after a tolerated-skew time is still fresh")
        check(app._quote_freshness_failure("2026-11-04T13:00:00Z", at("2026-11-04T19:00:00Z")) is None,
              f"[{tz}] exactly 6h old is still fresh")
        check(app._quote_freshness_failure("2026-11-04T13:00:00Z", at("2026-11-04T19:00:01Z")) == "STALE_QUOTE",
              f"[{tz}] 6h + 1s old is STALE_QUOTE")
        # zone-less / blank / missing source times are never read in an assumed zone
        for bad in (None, "", "2026-11-04 13:00", "2026-11-04T13:00:00", "13:00"):
            check(app._quote_freshness_failure(bad, now) == "MISSING_UPDATE_TIME",
                  f"[{tz}] source time {bad!r} -> MISSING_UPDATE_TIME")
        # DST: explicit America/New_York, not the process zone
        check(app._updated_label("2026-07-04T12:00:00Z") == "updated 2026-07-04 08:00 ET",
              f"[{tz}] July (EDT, UTC-4) label, got {app._updated_label('2026-07-04T12:00:00Z')}")
        check(app._updated_label("2026-12-04T13:00:00Z") == "updated 2026-12-04 08:00 ET",
              f"[{tz}] December (EST, UTC-5) label, got {app._updated_label('2026-12-04T13:00:00Z')}")
        check(app._updated_label("2026-11-01T05:30:00Z") == "updated 2026-11-01 01:30 ET"
              and app._updated_label("2026-11-01T06:30:00Z") == "updated 2026-11-01 01:30 ET",
              f"[{tz}] fall-back hour labels both 01:30 ET")
        check(app._updated_label("2026-11-04 13:00") == "update time not recorded",
              f"[{tz}] a zone-less stamp is never labelled as a time")
        # SGP Workbench prop legs: authority is source_updated_utc, never the display timestamp
        lg = {"book": "DraftKings", "price": -115, "line": 33.5, "timestamp": "2026-11-04 13:00",
              "source_updated_utc": "2026-11-04T13:00:38Z"}
        check(app._sgp_leg_quote_failures(lg, at("2026-11-04T13:40:00Z")) == [],
              f"[{tz}] SGP leg with a fresh source time is executable ({app._sgp_leg_quote_failures(lg, at('2026-11-04T13:40:00Z'))})")
        lg2 = dict(lg, source_updated_utc=None)
        check("MISSING_UPDATE_TIME" in app._sgp_leg_quote_failures(lg2, at("2026-11-04T13:40:00Z")),
              f"[{tz}] SGP leg without a source time is not executable, whatever its display timestamp")
        check("STALE_QUOTE" in app._sgp_leg_quote_failures(lg, at("2026-11-04T19:01:00Z")),
              f"[{tz}] SGP leg is stale at the real 6h age")
        cur = app._sgp_current_terms(dict(lg, id="x", label="L"))
        check(cur["updated_utc"] == "2026-11-04T13:00:38Z" and cur["updated_label"] == "updated 2026-11-04 08:00 ET",
              f"[{tz}] SGP current terms carry the provider time ({cur})")
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        if hasattr(time, "tzset"):
            time.tzset()


for zone in ("UTC", "America/New_York", "America/Los_Angeles"):
    run_in_zone(zone)
    skew_and_age(zone)

# 4. Static guards on the source: _quote_from_row and the newest-row sort never read LastUpdated.
src = (ROOT / "app.py").read_text(encoding="utf-8")
m = re.search(r"def _quote_from_row\(.*?\n(?=def )", src, re.S)
body = m.group(0) if m else ""
code_only = "\n".join(l for l in body.splitlines() if not l.strip().startswith(("#",)))
doc_end = code_only.find('"""', code_only.find('"""') + 3)
check(m is not None, "_quote_from_row must exist")
check("row.get('LastUpdated')" not in code_only[doc_end:],
      "_quote_from_row must not read LastUpdated")
check("_canonical_kickoff_utc(row.get('SourceUpdatedAtUTC'))" in code_only[doc_end:],
      "_quote_from_row must parse SourceUpdatedAtUTC zone-explicitly")
check("_m['LastUpdated'].map(_feed_stamp_to_utc)" not in src,
      "the newest-quote row must not be chosen by LastUpdated")
check("_m['SourceUpdatedAtUTC'].map(_canonical_kickoff_utc)" in src,
      "the newest-quote row must be chosen by SourceUpdatedAtUTC")

# 4b. Every executable NFL-prop quote has ONE origin: the floor board's _quote_from_row (Daily Card, King's
# Tickets, Green Light, Menu, image POST and Featured Parlay all read board['floors'/'swings'][*]['quote']);
# the SGP Workbench prop legs carry source_updated_utc. No authority function reads LastUpdated.
check(len(re.findall(r"_quote_from_row\(", src)) == 2, "exactly one _quote_from_row call site (+ its def)")
check(len(re.findall(r"'quote': quote,", src)) == 1, "only the floor board assigns a fresh 'quote' to a row")


def fn_body(name):
    mm = re.search(rf"def {name}\(.*?\n(?=def |\S)", src, re.S)
    return mm.group(0) if mm else ""


for fn in ("_quote_clock_status", "_quote_freshness_failure", "_leg_quote_failures", "_sgp_leg_quote_failures",
           "_sgp_current_terms", "_updated_label"):
    b = fn_body(fn)
    check(bool(b), f"{fn} must exist")
    check("LastUpdated" not in b.split('"""')[-1] and "_feed_stamp_to_utc" not in b,
          f"{fn} must not read LastUpdated or the zone-assuming parser")
sgp_props = src[src.find("# ---- player props: each book row"):src.find("# D4: NFL_Odds / NFL_FirstHalf")]
check("r.get('SourceUpdatedAtUTC')" in sgp_props and "r.get('LastUpdated')" not in sgp_props,
      "SGP player-prop legs take their time from SourceUpdatedAtUTC, never LastUpdated")

# 4c. Customer-facing NFL-prop times (Player Check, Best Lines, props-feed "last updated"): the provider's
# SourceUpdatedAtUTC in explicit ET, or 'Update time not recorded'. A naive LastUpdated is never shown.
import pandas as pd  # noqa: E402
from datetime import timedelta  # noqa: E402

check(app._source_time_label("2026-11-04T13:00:38Z") == "2026-11-04 08:00 ET", "source label 13:00:38Z -> 08:00 ET")
for bad in (None, "", "2026-11-04 13:00", float("nan")):
    check(app._source_time_label(bad) == "Update time not recorded", f"source label {bad!r} -> not recorded")

_now = datetime.now(timezone.utc).replace(microsecond=0)
_src = (_now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
_naive_fetch = (_now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")   # the zone-less fetch stamp
_df = pd.DataFrame([{"Player": "P", "Stat": "Receiving Yards", "Line": 40.5, "Game": "A@B", "Book": "DraftKings",
                     "OverOdds": -115, "UnderOdds": -105, "LastUpdated": _naive_fetch, "SourceUpdatedAtUTC": _src}])
meta = app.get_props_refresh_meta(_df, max_age_hours=6)
check(meta["last_updated"] == app._source_time_label(_src) and meta["last_updated"].endswith(" ET"),
      f"refresh meta label is the source time in ET ({meta['last_updated']})")
check(meta["age_hours"] is not None and 0.4 <= meta["age_hours"] <= 0.6 and not meta["is_stale"],
      f"refresh meta age is the real source age (~0.5h), not stale ({meta['age_hours']})")
_df_blank = _df.assign(SourceUpdatedAtUTC="")
check(app.get_props_refresh_meta(_df_blank, max_age_hours=6)["last_updated"] == "Update time not recorded",
      "refresh meta with no source time says 'Update time not recorded' (never the naive LastUpdated)")
_old = (_now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
check(app.get_props_refresh_meta(_df.assign(SourceUpdatedAtUTC=_old), max_age_hours=6)["is_stale"],
      "refresh meta is stale at the real source age (7h)")

_saved_specs = app._BEST_LINE_SPECS
try:
    _bl = pd.concat([_df, _df.assign(Book="FanDuel", SourceUpdatedAtUTC="", OverOdds=-120)], ignore_index=True)
    _bl_none = _df.assign(SourceUpdatedAtUTC="")
    app._BEST_LINE_SPECS = [("nfl", "NFL", lambda: _bl), ("ncaaf", "NCAAF", lambda: _bl_none)]
    rows, feeds = app._build_best_lines_snapshot()
    nfl_rows = [r for r in rows if r["league"] == "nfl"]
    ncaaf_rows = [r for r in rows if r["league"] == "ncaaf"]
    check(nfl_rows and all(r["updated"] == app._source_time_label(_src) for r in nfl_rows),
          f"Best Lines offer time = newest source time in ET ({[r['updated'] for r in nfl_rows]})")
    check(ncaaf_rows and all(r["updated"] == "Update time not recorded" for r in ncaaf_rows),
          f"Best Lines with no source time says not recorded ({[r['updated'] for r in ncaaf_rows]})")
    check(all(_naive_fetch not in str(r["updated"]) for r in rows) and all(_naive_fetch not in str(f["updated"]) for f in feeds),
          "Best Lines never shows the naive LastUpdated stamp")
finally:
    app._BEST_LINE_SPECS = _saved_specs

pc_body = fn_body("evaluate_nfl_player")
pc_code = "\n".join(l.split("#", 1)[0] for l in pc_body.splitlines())   # code only, comments stripped
check("LastUpdated" not in pc_code and "_source_time_label(r.get('SourceUpdatedAtUTC'))" in pc_code,
      "Player Check per-book and feed times come from SourceUpdatedAtUTC, never LastUpdated")
bl_body = fn_body("_build_best_lines_snapshot")
check("props['LastUpdated']" not in bl_body, "Best Lines never reads LastUpdated for an offer time")
tpl = (ROOT / "templates" / "player_check.html").read_text(encoding="utf-8")
check("feed updated {{ feed_ts }}" not in tpl and "latest quote updated {{ feed_ts }}" in tpl,
      "Player Check template labels the quote time (and shows 'Update time not recorded' as-is)")
check("+ ('srcutc1',)" in fn_body("build_nfl_dashboard_runtime_bundle"),
      "NFL dashboard disk bundle version moved so pre-fix refresh labels are never served")

# 5. Cache isolation: pre-fix floor-board disk entries (key 'nfl_floor_board::q1k2::...') are never read.
check("f'nfl_floor_board::q1k2::" not in src, "the pre-fix floor-board disk key 'q1k2::' must not be used")
check("f'nfl_floor_board::q1k2s3::" in src, "the floor-board disk key must carry the 's3' source-time version")

total = passed + len(failures)
for f in failures:
    print(f"[FAIL] {f}")
print(f"{passed}/{total} passed")
sys.exit(1 if failures else 0)
