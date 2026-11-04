"""
QC: game-line truthful time + spread-side truth (correction L1, 2026-11-04).

Contract frozen here (docs/game_lines_correction_proposal_20261104.md, G1 + G4):

  WRITER (fetch_game_lines.py) -- every row carries zone-explicit SourceUpdatedAtUTC (book last_update) and
  FetchedAtUTC (when BK observed it), EventId + EventCommenceAtUTC (provider commence_time), book, and each
  spread SIDE as its own selection (HomeSpread/HomeSpreadOdds/AwaySpread/AwaySpreadOdds) matched by outcome
  NAME, never provider order. Legacy SpreadOdds = the HOME side's own price or empty, never the other side's.

  READER -- FetchedAtUTC within 6h => current, however old SourceUpdatedAtUTC is; missing / invalid fetched
  time => unavailable (fail closed); <=5 min future skew tolerated (age 0), beyond => unavailable. LEGACY files
  (no FetchedAtUTC) read LastUpdated as America/New_York (DST-aware) => DERIVED_LEGACY_SOURCE_TIME. `now` is
  injected aware UTC; the process zone is never consulted. Display: 'Observed by BK' vs 'Book updated'.

Path exercised end to end, offline: provider JSON fixtures -> the REAL parse_event_markets / fetch_odds_rows /
build_dataframe (network functions patched to FAIL if called) -> CSV on a temp DATA_DIR -> the REAL loaders
(load_ncaaf_context_slate, get_lines_refresh_meta, build_football_live_games, the CFB context builders, the
real template markup). Repeated under process TZ=UTC, America/New_York, America/Los_Angeles (tzset where the
platform has it; a static guard proves no naive-now / local-zone conversion in the governed functions).
Mutation proofs: a LastUpdated-naive parse and a first-outcome SpreadOdds writer must each FAIL these checks.

Run: py -3 qc_offline.py qc_game_lines_truthful_time.py
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "qc-game-lines-truthful-time")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import fetch_game_lines as fgl  # noqa: E402
import app  # noqa: E402

passed = 0
failures: list[str] = []


def check(cond, msg):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(msg)


def at(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- network is never touched: any call fails loudly ---------------------------------------------------
def _net_forbidden(*a, **k):
    raise AssertionError("QC called a network function")


fgl.get_json = _net_forbidden
fgl.urlopen = _net_forbidden

HOME, AWAY = "Alabama Crimson Tide", "Georgia Bulldogs"


def ev(eid, away, home, commence, bookmakers):
    return {"id": eid, "sport_key": "americanfootball_ncaaf", "commence_time": commence,
            "home_team": home, "away_team": away, "bookmakers": bookmakers}


def bk(key, title, last_update, spreads=None, h2h=None, totals=None):
    markets = []
    if h2h is not None:
        markets.append({"key": "h2h", "last_update": last_update, "outcomes": h2h})
    if spreads is not None:
        markets.append({"key": "spreads", "last_update": last_update, "outcomes": spreads})
    if totals is not None:
        markets.append({"key": "totals", "last_update": last_update, "outcomes": totals})
    return {"key": key, "title": title, "last_update": last_update, "markets": markets}


def std_book(last_update, away_first=True):
    sp = [{"name": AWAY, "price": 105, "point": 3.5}, {"name": HOME, "price": -125, "point": -3.5}]
    if not away_first:
        sp = list(reversed(sp))
    return bk("draftkings", "DraftKings", last_update, spreads=sp,
              h2h=[{"name": AWAY, "price": 140}, {"name": HOME, "price": -165}],
              totals=[{"name": "Over", "price": -112, "point": 51.5}, {"name": "Under", "price": -108, "point": 51.5}])


# =========================================================================================================
# 1. Spread side (G4) -- each outcome its own selection, by NAME
# =========================================================================================================
def eq(a, b):
    """NA-safe numeric equality (a missing value never equals a number)."""
    try:
        v = pd.to_numeric(a, errors="coerce")
        return (not pd.isna(v)) and float(v) == float(b)
    except (TypeError, ValueError):
        return False


def spread_checks(mod, tag=""):
    """Returns failures (list). Used for the real writer and for the mutation proof."""
    out = []
    lu, fetched = "2026-11-04T12:58:00Z", "2026-11-04T13:00:00Z"
    commence = "2026-11-07T20:30:00Z"
    for away_first in (True, False):
        r = mod.parse_event_markets(ev("e1", AWAY, HOME, commence, []), std_book(lu, away_first), fetched_at_utc=fetched) \
            if "fetched_at_utc" in mod.parse_event_markets.__code__.co_varnames else \
            mod.parse_event_markets(ev("e1", AWAY, HOME, commence, []), std_book(lu, away_first))
        order = "away-first" if away_first else "home-first"
        if not (eq(r.get("HomeSpread"), -3.5) and eq(r.get("HomeSpreadOdds"), -125)):
            out.append(f"{tag}[{order}] home side must be its own line/price (-3.5/-125), got "
                       f"{r.get('HomeSpread')}/{r.get('HomeSpreadOdds')}")
        if not (eq(r.get("AwaySpread"), 3.5) and eq(r.get("AwaySpreadOdds"), 105)):
            out.append(f"{tag}[{order}] away side must be its own line/price (+3.5/+105)")
        if not (eq(r.get("Spread"), -3.5) and eq(r.get("SpreadOdds"), -125)):
            out.append(f"{tag}[{order}] legacy Spread/SpreadOdds must be the HOME line and HOME price "
                       f"(-3.5/-125), got {r.get('Spread')}/{r.get('SpreadOdds')}")
    # home side missing: home line mirrors the away point, but the home PRICE was never captured
    only_away = bk("fanduel", "FanDuel", lu, spreads=[{"name": AWAY, "price": 110, "point": 7.0}])
    r = mod.parse_event_markets(ev("e2", AWAY, HOME, commence, []), only_away)
    if not (pd.isna(r.get("SpreadOdds")) and eq(r.get("Spread"), -7.0)):
        out.append(f"{tag}[home missing] SpreadOdds must be unavailable (never the away +110), got {r.get('SpreadOdds')}")
    if not (eq(r.get("AwaySpreadOdds"), 110) and pd.isna(r.get("HomeSpreadOdds", float("nan")))):
        out.append(f"{tag}[home missing] away selection kept with its own price; home price empty")
    # away side missing
    only_home = bk("betmgm", "BetMGM", lu, spreads=[{"name": HOME, "price": -118, "point": -6.5}])
    r = mod.parse_event_markets(ev("e3", AWAY, HOME, commence, []), only_home)
    if not (eq(r.get("SpreadOdds"), -118) and eq(r.get("Spread"), -6.5) and pd.isna(r.get("AwaySpreadOdds", float("nan")))):
        out.append(f"{tag}[away missing] home price/line kept, away price unavailable")
    # mismatched names: neither outcome is either team -> no spread, no price
    mism = bk("caesars", "Caesars", lu, spreads=[{"name": "Georgia", "price": -110, "point": 3.5},
                                                 {"name": "Alabama", "price": -110, "point": -3.5}])
    r = mod.parse_event_markets(ev("e4", AWAY, HOME, commence, []), mism)
    if not (pd.isna(r.get("Spread")) and pd.isna(r.get("SpreadOdds"))):
        out.append(f"{tag}[mismatched names] no spread/price may be attributed, got {r.get('Spread')}/{r.get('SpreadOdds')}")
    # conflicting duplicate of one side -> that side dropped, never guessed
    dup = bk("draftkings", "DraftKings", lu, spreads=[{"name": HOME, "price": -110, "point": -3.5},
                                                      {"name": HOME, "price": -130, "point": -4.5},
                                                      {"name": AWAY, "price": -110, "point": 3.5}])
    r = mod.parse_event_markets(ev("e5", AWAY, HOME, commence, []), dup)
    if not pd.isna(r.get("SpreadOdds")):
        out.append(f"{tag}[conflicting home quotes] home price must be unavailable, got {r.get('SpreadOdds')}")
    return out


_sf = spread_checks(fgl)
check(not _sf, "real writer spread-side checks: " + "; ".join(_sf))

# =========================================================================================================
# 2. Writer schema + zone-explicit times through the REAL fetch_odds_rows/build_dataframe
# =========================================================================================================
T0 = at("2026-11-04T13:00:00Z")              # BK observation (fetch) instant
SRC_OLD = z(T0 - timedelta(hours=10))         # book last changed the market 10h before we observed it
_today_et = app.sports_today_ts()
# kickoff 23:30 ET today -> Date today (ET) so 'week' views include it, whatever the real clock
_kick_et = pd.Timestamp(_today_et.strftime("%Y-%m-%d") + " 23:30").tz_localize("America/New_York")
KICK = z(_kick_et.to_pydatetime())


def provider_payload(src=SRC_OLD, away_first=True):
    return [ev("evt-uga-bama", AWAY, HOME, KICK, [std_book(src, away_first)]),
            ev("evt-troy-army", "Troy Trojans", "Army Black Knights", KICK,
               [bk("fanduel", "FanDuel", src, spreads=[{"name": "Troy Trojans", "price": 102, "point": 4.0}],
                   totals=[{"name": "Over", "price": -110, "point": 44.5}, {"name": "Under", "price": -110, "point": 44.5}])])]


def writer_frame(fetched=T0, src=SRC_OLD, away_first=True):
    saved = (fgl.get_json, fgl.observed_at_utc)
    fgl.get_json = lambda url: provider_payload(src, away_first)     # fixture; no socket
    fgl.observed_at_utc = lambda: z(fetched)
    try:
        rows = fgl.fetch_odds_rows("k", "americanfootball_ncaaf", "draftkings,fanduel", ["h2h", "spreads", "totals"], "us", 7)
    finally:
        fgl.get_json, fgl.observed_at_utc = saved
    return fgl.build_dataframe(rows)


df0 = writer_frame()
NEW_COLS = ["HomeSpread", "HomeSpreadOdds", "AwaySpread", "AwaySpreadOdds", "EventId", "EventCommenceAtUTC",
            "SourceUpdatedAtUTC", "FetchedAtUTC"]
LEGACY_COLS = ["Date", "Time", "Away", "Home", "AwayFull", "HomeFull", "AwayML", "HomeML", "Spread", "SpreadOdds",
               "Total", "OverOdds", "UnderOdds", "Book", "GameID", "LastUpdated"]
check(list(df0.columns) == LEGACY_COLS + NEW_COLS, f"writer columns = legacy + additive ({list(df0.columns)})")
check(set(fgl.build_dataframe([]).columns) == set(LEGACY_COLS + NEW_COLS), "empty writer frame has the full schema")
uga = df0[df0["EventId"] == "evt-uga-bama"].iloc[0]
check(uga["FetchedAtUTC"] == "2026-11-04T13:00:00Z", f"FetchedAtUTC = BK observation ISO-Z ({uga['FetchedAtUTC']})")
check(uga["SourceUpdatedAtUTC"] == SRC_OLD, f"SourceUpdatedAtUTC = book last_update ISO-Z ({uga['SourceUpdatedAtUTC']})")
check(uga["EventCommenceAtUTC"] == KICK and uga["GameID"] == "evt-uga-bama", "EventId + EventCommenceAtUTC from the provider")
check(uga["LastUpdated"] == "2026-11-03 22:00", f"legacy LastUpdated kept (Eastern display) ({uga['LastUpdated']})")
check(float(uga["HomeSpreadOdds"]) == -125 and float(uga["SpreadOdds"]) == -125 and float(uga["AwaySpreadOdds"]) == 105,
      "written frame: home/away spread prices on their own sides")
troy = df0[df0["EventId"] == "evt-troy-army"].iloc[0]
check(pd.isna(troy["SpreadOdds"]) and float(troy["AwaySpreadOdds"]) == 102,
      "written frame: home-missing spread -> SpreadOdds empty, away price on the away selection")
check(fgl.utc_iso_z("2026-11-04T08:00:00-05:00") == "2026-11-04T13:00:00Z", "offset spelling canonicalizes to Z")
for bad in ("2026-11-04 13:00", "2026-11-04T13:00:00", "", None, "garbage"):
    check(fgl.utc_iso_z(bad) == "", f"zone-less / invalid provider time {bad!r} is never assumed into a zone")
check(fgl.parse_event_markets(provider_payload()[0], std_book(SRC_OLD))["FetchedAtUTC"] == "",
      "a row parsed without an observation time (historical backfill) never claims one")
_obs = fgl.observed_at_utc()
check(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", _obs) is not None and
      abs((at(_obs) - datetime.now(timezone.utc)).total_seconds()) < 120, "observed_at_utc is aware UTC ISO-Z")
from services.feed_validation import GAME_LINES_SPEC, validate_feed  # noqa: E402
_ok, _errs = validate_feed(df0, GAME_LINES_SPEC, prior_df=None, path=Path("data/odds/NCAAF_Odds.csv"),
                           sport_tokens=("NCAAF",), allow_collapse=True)
check(_ok, f"writer frame passes the publish validator unchanged ({_errs})")


# =========================================================================================================
# 3. Real loaders on a temp DATA_DIR
# =========================================================================================================
R = Path(tempfile.mkdtemp(prefix="qc_gl_l1_"))
for d in ("odds", "schedules"):
    (R / d).mkdir(parents=True)
_saved_dir, _saved_now = app.DATA_DIR, app._now_utc


def publish(df, cfbd=False):
    for p in ("odds/NCAAF_Odds.csv", "schedules/NCAAF_Odds.csv"):
        df.to_csv(R / p, index=False)
    fgl.build_schedule_alias(df).to_csv(R / "schedules/NCAAF_Schedule.csv", index=False)
    cf = R / "schedules/NCAAF_CFBD_Schedule.csv"
    if cfbd:
        d = df["Date"].iloc[0]
        pd.DataFrame([{"Date": d, "Time": "23:30", "Away": "Georgia", "Home": "Alabama", "CfbdGameId": 1, "Source": "CFBD"},
                      {"Date": d, "Time": "23:30", "Away": "Troy", "Home": "Army", "CfbdGameId": 2, "Source": "CFBD"}]
                     ).to_csv(cf, index=False)
    elif cf.exists():
        cf.unlink()
    app.DATAFRAME_CACHE.clear()


def raw_w1():
    app.DATAFRAME_CACHE.clear()
    return app._load_cached_csv(R / "odds/NCAAF_Odds.csv", transform=app._ncaaf_market_raw, default=pd.DataFrame())


def slate_games(now, cfbd):
    o, s = app.load_ncaaf_context_slate(now=now)
    games = app.build_football_live_games(o, s, date_filter="all")
    return o, [g for g in games if "troy" not in str(g.get("away") or "").lower()]


def legacy_of(df):
    return df.drop(columns=NEW_COLS)


G3_LEAK_OBSERVED: set = set()


def clock_checks(tz):
    out = []

    def ok(c, m):
        if not c:
            out.append(f"[{tz}] {m}")

    app.DATA_DIR = R
    try:
        # 3a. new writer format: fetched T0, book source 10h older
        for cfbd in (False, True):
            publish(writer_frame(), cfbd=cfbd)
            for age, want_current in ((0.5, True), (5.5, True), (6.5, False)):
                now = T0 + timedelta(hours=age)
                meta = app.get_lines_refresh_meta(raw_w1(), now=now)
                ok(meta["time_basis"] == app.GAME_LINE_TIME_FETCHED, f"basis FETCHED_AT_UTC ({meta['time_basis']})")
                ok(meta["age_hours"] == age, f"cfbd={cfbd} true fetched age {age}h, got {meta['age_hours']}")
                ok(meta["is_stale"] is (not want_current) and meta["is_current"] is want_current,
                   f"cfbd={cfbd} age {age}h -> current={want_current} (source 10h old must not make it stale): {meta}")
                ok(meta["observed_label"] == "Observed by BK 2026-11-04 08:00 ET",
                   f"observed label = FetchedAtUTC in ET ({meta['observed_label']})")
                ok(meta["book_updated_label"] == "Book updated 2026-11-03 22:00 ET",
                   f"book-updated label = SourceUpdatedAtUTC in ET ({meta['book_updated_label']})")
                o, g = slate_games(now, cfbd)
                booked = o[o.get("Source", pd.Series(dtype=str)).astype(str) == "odds_api"] if "Source" in o.columns else o
                ok((len(booked) > 0) is want_current, f"cfbd={cfbd} age {age}h: Odds-API book rows kept={want_current}")
                if want_current:
                    ok(len(g) == 1 and g[0]["line_time_label"] == ("Observed by BK 2026-11-04 08:00 ET · "
                                                                   "Book updated 2026-11-03 22:00 ET"),
                       f"cfbd={cfbd} game carries the two distinct labels ({[x.get('line_time_label') for x in g]})")
                    ok(len(g) == 1 and pd.to_numeric(g[0]["spread"], errors="coerce") == -3.5, "book spread shown (home -3.5)")
                    sp = booked.iloc[0].get("SpreadOdds") if len(booked) else None
                    ok(len(booked) and float(pd.to_numeric(booked["SpreadOdds"], errors="coerce").dropna().iloc[0]) == -125,
                       f"cfbd={cfbd}: composed SpreadOdds is the HOME price (-125), got {sp}")
                elif cfbd:
                    ok(all(pd.isna(pd.to_numeric(x.get("spread"), errors="coerce")) for x in g),
                       f"cfbd={cfbd} 6.5h: no book line shown as current ({g})")
                else:
                    # No CFBD universe: the composer's own odds are empty (asserted above), but the game
                    # list still comes from load_ncaaf_schedule(), whose data/schedules mirror carries
                    # lines -- the G3 schedule-mirror bypass, deliberately left for L2. Recorded, not hidden.
                    G3_LEAK_OBSERVED.add(bool(g) and not pd.isna(pd.to_numeric(g[0].get("spread"), errors="coerce")))
        # 3b. provider order reversed (home first) -> identical result
        publish(writer_frame(away_first=False), cfbd=True)
        o, g = slate_games(T0 + timedelta(hours=1), True)
        ok(float(pd.to_numeric(o[o["Source"] == "odds_api"]["SpreadOdds"]).dropna().iloc[0]) == -125,
           "home-first provider order: same home price")
        # 3c. missing / invalid / zone-less fetched time -> unavailable, fail closed
        for bad in ("", "garbage", "2026-11-04 13:00", "2026-11-04T13:00:00"):
            publish(writer_frame().assign(FetchedAtUTC=bad), cfbd=True)
            meta = app.get_lines_refresh_meta(raw_w1(), now=T0 + timedelta(hours=0.5))
            ok(meta["status"] == "unavailable" and meta["is_stale"] and not meta["is_current"]
               and meta["reason"] == "MISSING_TIME", f"FetchedAtUTC={bad!r} -> unavailable/fail closed ({meta})")
            o, g = slate_games(T0 + timedelta(hours=0.5), True)
            ok("Source" in o.columns and not (o["Source"] == "odds_api").any(),
               f"FetchedAtUTC={bad!r}: no Odds-API line reaches the CFB slate")
        # 3d. future / skew (fetched relative to now)
        publish(writer_frame(), cfbd=True)
        for ahead_s, want in ((0, "CURRENT"), (180, "CURRENT"), (300, "CURRENT"), (301, "FROM_FUTURE"), (3600, "FROM_FUTURE")):
            now = T0 - timedelta(seconds=ahead_s)
            meta = app.get_lines_refresh_meta(raw_w1(), now=now)
            if want == "CURRENT":
                ok(meta["is_current"] and meta["age_hours"] == 0.0, f"fetched {ahead_s}s ahead -> current, age 0 ({meta})")
            else:
                ok(meta["status"] == "unavailable" and meta["is_stale"] and meta["reason"] == "FROM_FUTURE",
                   f"fetched {ahead_s}s ahead -> unavailable FROM_FUTURE ({meta})")
        clk = app._game_line_row_clock({"FetchedAtUTC": z(T0), "SourceUpdatedAtUTC": z(T0 + timedelta(hours=2))},
                                       T0 + timedelta(hours=1))
        ok(clk["state"] == "CURRENT" and clk["source_utc"] is None and "SOURCE_AFTER_OBSERVATION" in clk["notes"],
           f"a book time after the observation is not displayed ({clk})")
        ok(app._game_line_time_label(clk) == "Observed by BK 2026-11-04 08:00 ET · Book updated: not recorded",
           f"label when the book time is not usable ({app._game_line_time_label(clk)})")
        # 3e. LEGACY file (no FetchedAtUTC / SourceUpdatedAtUTC): LastUpdated read as America/New_York
        src_t = T0
        publish(legacy_of(writer_frame(src=z(src_t))), cfbd=True)
        for age, want_current in ((0.5, True), (5.5, True), (6.5, False)):
            meta = app.get_lines_refresh_meta(raw_w1(), now=src_t + timedelta(hours=age))
            ok(meta["time_basis"] == app.GAME_LINE_TIME_LEGACY, f"legacy basis DERIVED_LEGACY_SOURCE_TIME ({meta['time_basis']})")
            ok(meta["age_hours"] == age and meta["is_current"] is want_current,
               f"legacy age {age}h exact via America/New_York (got {meta['age_hours']}, {meta['status']})")
            ok(meta["observed_label"] == "" and "derived from legacy" in meta["book_updated_label"],
               f"legacy display never claims a BK observation ({meta['book_updated_label']})")
        o, g = slate_games(src_t + timedelta(hours=1), True)
        oa = o[o["Source"] == "odds_api"]
        ok(len(oa) >= 1 and oa["SpreadOdds"].isna().all(),
           "legacy file: SpreadOdds side unknown -> price unavailable (never possibly the away price)")
        ok(len(g) == 1 and "derived from legacy" in g[0]["line_time_label"], "legacy game labelled as derived")
        # 3f. DST boundaries, legacy derivation (America/New_York, explicit)
        for stamp, want_utc in (("2026-11-01 00:30", "2026-11-01T04:30:00Z"),   # EDT (UTC-4)
                                ("2026-11-01 03:00", "2026-11-01T08:00:00Z"),   # EST (UTC-5)
                                ("2026-03-08 01:30", "2026-03-08T06:30:00Z"),   # EST
                                ("2026-03-08 03:30", "2026-03-08T07:30:00Z"),   # EDT
                                ("2026-07-04 09:00", "2026-07-04T13:00:00Z")):  # summer EDT
            c = app._game_line_row_clock({"LastUpdated": stamp}, at(want_utc) + timedelta(hours=1))
            ok(c["state"] == "CURRENT" and c["clock_utc"] == at(want_utc) and abs(c["age_seconds"] - 3600) < 1e-6,
               f"legacy {stamp} ET -> {want_utc} exactly ({c})")
        for stamp in ("2026-11-01 01:30", "2026-03-08 02:30"):   # ambiguous fall-back / nonexistent spring-forward
            c = app._game_line_row_clock({"LastUpdated": stamp}, at("2026-11-02T12:00:00Z"))
            ok(c["state"] == "MISSING_TIME", f"legacy {stamp} (DST gap/overlap) is dropped, never guessed ({c['state']})")
        meta = app.get_lines_refresh_meta(pd.DataFrame([{"Away": "a", "Home": "h", "LastUpdated": "2026-11-01 01:30"}]),
                                          now=at("2026-11-01T07:00:00Z"))
        ok(meta["status"] == "unavailable" and meta["is_stale"], "all-ambiguous legacy stamps -> unavailable (fail closed)")
        # fetched basis across DST: aging is pure UTC; labels in ET
        for f_utc, lab in (("2026-11-01T05:30:00Z", "2026-11-01 01:30 ET"), ("2026-11-01T06:30:00Z", "2026-11-01 01:30 ET"),
                           ("2026-03-08T06:30:00Z", "2026-03-08 01:30 ET"), ("2026-03-08T07:30:00Z", "2026-03-08 03:30 ET")):
            c = app._game_line_row_clock({"FetchedAtUTC": f_utc, "SourceUpdatedAtUTC": f_utc}, at(f_utc) + timedelta(hours=5.5))
            ok(c["state"] == "CURRENT" and abs(c["age_seconds"] - 5.5 * 3600) < 1e-6
               and app._game_line_time_labels(c)[0] == f"Observed by BK {lab}",
               f"fetched {f_utc} across DST: age 5.5h, label {lab} ({app._game_line_time_labels(c)})")
        # 3g. formatted loader output (no time columns) is unchanged pre-L1 behaviour (L2 decides)
        nocol = app.get_lines_refresh_meta(pd.DataFrame([{"Away": "x", "Home": "y"}]), now=T0)
        ok(nocol["time_basis"] == app.GAME_LINE_TIME_NONE and not nocol["is_stale"] and nocol["status"] == "live",
           "no time column -> unchanged (not suppressed; L2)")
        ok(app.get_lines_refresh_meta(pd.DataFrame(), now=T0)["status"] == "unavailable", "empty frame unavailable")
    except Exception as exc:  # noqa: BLE001 -- an exception is a failure (and keeps earlier findings)
        out.append(f"[{tz}] EXCEPTION {type(exc).__name__}: {exc}")
    finally:
        app.DATA_DIR = _saved_dir
        app.DATAFRAME_CACHE.clear()
    return out


def in_zone(tz, fn, *a):
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        return fn(*a)
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        if hasattr(time, "tzset"):
            time.tzset()


ZONES = ("UTC", "America/New_York", "America/Los_Angeles")
try:
    for tz in ZONES:
        cf = in_zone(tz, clock_checks, tz)
        check(not cf, "clock checks:\n  " + "\n  ".join(cf))
        sf = in_zone(tz, spread_checks, fgl, f"[{tz}] ")
        check(not sf, "spread checks: " + "; ".join(sf))

    # =====================================================================================================
    # 4. The five CFB context surfaces: builders + real template markup show the two labels
    # =====================================================================================================
    app.DATA_DIR = R
    publish(writer_frame(), cfbd=True)
    app._now_utc = lambda: T0 + timedelta(hours=1)
    LBL = "Observed by BK 2026-11-04 08:00 ET · Book updated 2026-11-03 22:00 ET"
    mu = app.build_cfb_matchup_context().get("mu_week", [])
    mg = [g for g in mu if g.get("away") == "Georgia"]
    check(len(mg) == 1 and mg[0].get("line_time_label") == LBL and not mg[0].get("line_label"),
          f"/tools/cfb-matchup week list carries both labels ({[g.get('line_time_label') for g in mg]})")
    to = app.build_cfb_totals_context().get("to_week", [])
    check(all(r.get("line_time_label") in ("", LBL) for r in to), "/tools/cfb-totals rows carry line_time_label")
    # Big Favorites (Best Spots + Weekend) and Best Spots cards: thresholds are 20/30/40 and cards need
    # analysis bullets, so feed the builders one labelled game (the slate -> game label path is proven above).
    _real_bflg, _real_an = app.build_football_live_games, app._cfb_analyze_game
    _big = {"away": "Georgia", "home": "Alabama", "spread": -24.5, "total": 51.5, "date": "2026-11-04",
            "time": "23:30", "line_label": "", "line_time_label": LBL}
    app.build_football_live_games = lambda *a, **k: [dict(_big)]
    app._cfb_analyze_game = lambda *a, **k: ("h", ["b"], 1)
    try:
        bfr = app.build_cfb_big_favorites_context("week", 20).get("bf_rows", [])
        bsl = app.build_cfb_best_spots_context("week").get("bs_live", [])
        wk = app.build_weekend_context()
        hub = app.build_cfb_hub_context()
    finally:
        app.build_football_live_games, app._cfb_analyze_game = _real_bflg, _real_an
    check(len(bfr) == 1 and bfr[0].get("line_time_label") == LBL, f"big favorites row labelled ({bfr})")
    check(len(bsl) == 1 and bsl[0].get("line_time_label") == LBL, f"best spots card labelled ({bsl})")
    check(any(c.get("line_time_label") == LBL for c in wk.get("cfb_spots", [])) or
          any(r.get("line_time_label") == LBL for r in wk.get("cfb_fades", []) + wk.get("cfb_covers", [])) or
          not (wk.get("cfb_spots") or wk.get("cfb_fades") or wk.get("cfb_covers")),
          "/tools/weekend CFB rows carry the label when shown")
    check(all(c.get("line_time_label") == LBL for c in hub.get("h_best", [])) and hub.get("h_best"),
          f"/tools/cfb-hub best cards carry the label ({hub.get('h_best')})")
    # stale (6.5h after observation): the same surfaces show no book line and no observed label
    app._now_utc = lambda: T0 + timedelta(hours=6.5)
    mu_s = [g for g in app.build_cfb_matchup_context().get("mu_week", []) if g.get("away") == "Georgia"]
    check(all(not g.get("line_time_label") and "3.5" not in str(g.get("spread") or "") for g in mu_s),
          f"6.5h after observation the CFB matchup shows no book line ({mu_s})")

    def block(tpl, start, stop, suffix="", **ctx):
        text = (ROOT / "templates" / tpl).read_text(encoding="utf-8")
        i = text.index(start)
        j = text.index(stop, i)
        return app.app.jinja_env.from_string(text[i:j] + suffix).render(**ctx)

    html = block("cfb_matchup.html", "{% if mu_week %}", "<div class=\"card mb-24\">\n  <div class=\"p-16\" style=\"border-bottom",
                 mu_week=mg)
    check("Observed by BK 2026-11-04 08:00 ET" in html and "Book updated 2026-11-03 22:00 ET" in html,
          "cfb_matchup.html renders 'Observed by BK' and 'Book updated'")
    card = {"matchup": "Georgia @ Alabama", "spread": "-3.5", "total": 51.5, "date": "d", "time": "t",
            "headline": "h", "bullets": ["b"], "strength": 1, "line_label": "", "line_time_label": LBL}
    check(LBL in block("cfb_best_spots.html", "{% for c in bs_live %}", "  {% else %}", bs_live=[card]),
          "cfb_best_spots.html card renders the labels")
    check(LBL in block("cfb_totals.html", "{% if to_week %}", "    </tbody>", suffix="{% endif %}",
                       to_week=[{"away": "Georgia", "home": "Alabama", "time": "t", "pace": 70, "proj": 50,
                                 "posted": 51.5, "gap": -1.5, "read": "", "line_label": "", "line_time_label": LBL}]),
          "cfb_totals.html renders the labels")
    for tpl in ("weekend.html", "cfb_hub.html", "cfb_best_spots.html"):
        t = (ROOT / "templates" / tpl).read_text(encoding="utf-8")
        check(".line_time_label }}" in t, f"{tpl} renders line_time_label")
finally:
    app.DATA_DIR = _saved_dir
    app._now_utc = _saved_now
    app.DATAFRAME_CACHE.clear()

# =========================================================================================================
# 5. SpreadOdds consumers: truthful side or unavailable
# =========================================================================================================
legacy_df = pd.DataFrame([{"Date": "2026-11-07", "Away": "A", "Home": "H", "Spread": -3.5, "SpreadOdds": 105}])
new_df = legacy_df.assign(HomeSpreadOdds=-125, AwaySpreadOdds=105)
check(pd.isna(app._format_game_market_odds(legacy_df)["SpreadOdds"].iloc[0]), "formatted loaders: legacy SpreadOdds -> unavailable")
check(app._format_game_market_odds(new_df)["SpreadOdds"].iloc[0] == -125, "formatted loaders: SpreadOdds = home price")
check(list(app._format_game_market_odds(new_df).columns) == list(app._format_game_market_odds(legacy_df).columns),
      "formatted loader column list unchanged")
check(pd.isna(app._format_schedule(legacy_df)["SpreadOdds"].iloc[0]) and
      app._format_schedule(new_df)["SpreadOdds"].iloc[0] == -125, "schedule mirrors: same rule")
check(pd.isna(app._ncaaf_market_raw(legacy_df)["SpreadOdds"].iloc[0]), "CFB context raw frame: same rule")
check(app._row_home_spread_odds(pd.Series({"SpreadOdds": 105})) is None and
      app._row_home_spread_odds(pd.Series({"SpreadOdds": 105, "HomeSpreadOdds": -125})) == -125,
      "raw-row readers (SGP): home price or unavailable")
_src = (ROOT / "app.py").read_text(encoding="utf-8")
check("'price': _sgp_price(_row_home_spread_odds(r))" in _src and "_sgp_price(r.get('SpreadOdds'))" not in _src,
      "SGP home spread leg prices from the home side only")

# =========================================================================================================
# 6. Static guards: no naive now / process-local conversion in the governed functions
# =========================================================================================================
def fn_body(src, name):
    m = re.search(rf"^def {name}\(.*?(?=^\S)", src, re.S | re.M)
    if not m:
        return ""
    return "\n".join(l.split("#", 1)[0] for l in m.group(0).splitlines())


FORBIDDEN = [r"datetime\.now\(\s*\)", r"pd\.Timestamp\.now\(\s*\)", r"Timestamp\.now\(\s*\)", r"\.astimezone\(\s*\)",
             r"datetime\.utcnow", r"time\.localtime", r"tz_localize\(\s*None", r"tz=None"]
for name in ("get_lines_refresh_meta", "_game_line_row_clock", "_game_line_time_labels", "_game_line_time_label",
             "_game_line_time_basis", "load_ncaaf_context_slate", "_ncaaf_cfbd_fresh", "_truthful_spread_odds",
             "_feed_stamp_to_utc", "_canonical_kickoff_utc", "_source_time_label"):
    b = fn_body(_src, name)
    check(bool(b), f"app.{name} exists")
    for pat in FORBIDDEN:
        check(re.search(pat, b) is None, f"app.{name} must not use {pat}")
fsrc = (ROOT / "fetch_game_lines.py").read_text(encoding="utf-8")
for name in ("utc_iso_z", "observed_at_utc", "blank_row", "parse_event_markets", "fetch_odds_rows", "build_dataframe"):
    b = fn_body(fsrc, name)
    check(bool(b), f"fetch_game_lines.{name} exists")
    for pat in FORBIDDEN:
        check(re.search(pat, b) is None, f"fetch_game_lines.{name} must not use {pat}")
glm = fn_body(_src, "get_lines_refresh_meta") + fn_body(_src, "_game_line_row_clock")
check("pd.to_datetime(odds_df['LastUpdated']" not in glm and "_feed_stamp_to_utc(get('LastUpdated'))" in glm,
      "LastUpdated only ever read through the explicit America/New_York parser")
check("tz_localize('America/New_York', ambiguous='NaT', nonexistent='NaT')" in fn_body(_src, "_feed_stamp_to_utc"),
      "legacy parser localizes explicitly to America/New_York, DST gaps/overlaps -> NaT")

# =========================================================================================================
# 7. Mutation proofs -- each mutant must FAIL the checks above
# =========================================================================================================
# 7a. LastUpdated-naive parse: legacy stamps read in the PROCESS zone / as UTC (the G1 bug)
_real_fs = app._feed_stamp_to_utc


def _naive_parse(value):
    ts = pd.to_datetime(str(value), errors="coerce")
    if ts is None or pd.isna(ts):
        return None
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")).to_pydatetime()


app._feed_stamp_to_utc = _naive_parse
try:
    mf = in_zone("UTC", clock_checks, "MUTANT-naive")
finally:
    app._feed_stamp_to_utc = _real_fs
check(any("legacy" in m for m in mf), f"mutant (naive LastUpdated parse) is DETECTED ({len(mf)} failures)")

# 7b. freshness keyed on the book source time instead of the BK observation time
_real_clock = app._game_line_row_clock


def _source_clock(row, now, max_age_hours=None, basis=None):
    r = dict(row)
    if "FetchedAtUTC" in r:
        r["FetchedAtUTC"] = r.get("SourceUpdatedAtUTC")
    return _real_clock(r, now, max_age_hours, basis)


app._game_line_row_clock = _source_clock
try:
    mf2 = in_zone("UTC", clock_checks, "MUTANT-source-clock")
finally:
    app._game_line_row_clock = _real_clock
check(any("must not make it stale" in m for m in mf2), f"mutant (source time as freshness) is DETECTED ({len(mf2)})")

# 7c. first-outcome SpreadOdds writer re-introduced (the G4 bug)
OLD_SPREADS = '''
        elif key == "spreads":
            for outcome in outcomes:
                name = str(outcome.get("name", "")).strip()
                point = outcome.get("point")
                price = outcome.get("price")
                if name == home:
                    row["Spread"] = point
                    row["SpreadOdds"] = price
                    break
                if name == away and point not in [None, ""]:
                    row["Spread"] = -float(point)
                    row["SpreadOdds"] = price
                    break
'''
m = re.search(r'\n        elif key == "spreads":\n.*?(?=\n        elif key == "totals":)', fsrc, re.S)
check(m is not None, "located the writer spreads block for the mutation")
if m:
    mut_src = fsrc[:m.start()] + OLD_SPREADS.rstrip("\n") + fsrc[m.end():]
    mod = types.ModuleType("fetch_game_lines_mutant")
    mod.__file__ = str(ROOT / "fetch_game_lines.py")
    exec(compile(mut_src, str(ROOT / "fetch_game_lines.py"), "exec"), mod.__dict__)  # noqa: S102 -- test mutant
    mod.get_json = _net_forbidden
    mod.urlopen = _net_forbidden
    msf = spread_checks(mod, "MUTANT ")
    check(any("away-first" in x for x in msf) and any("home missing" in x for x in msf),
          f"mutant (first-outcome SpreadOdds) is DETECTED ({msf})")

# 7d. reader mutant: SpreadOdds passed through untouched for legacy files
_real_ts = app._truthful_spread_odds
app._truthful_spread_odds = lambda df: df
try:
    check(not pd.isna(app._format_game_market_odds(legacy_df)["SpreadOdds"].iloc[0]),
          "mutant (legacy SpreadOdds trusted) is DETECTED by the formatted-loader check")
finally:
    app._truthful_spread_odds = _real_ts

shutil.rmtree(R, ignore_errors=True)
print(f"[NOTE] G3 schedule-mirror bypass (no-CFBD-universe path, stale feed) observed={sorted(G3_LEAK_OBSERVED)} "
      "-- deliberately NOT closed in L1 (owner contract: L2). The CFBD-universe path (production) shows no stale line.")
total = passed + len(failures)
for f in failures:
    print(f"[FAIL] {f}")
print(f"{passed}/{total} passed")
sys.exit(1 if failures else 0)
