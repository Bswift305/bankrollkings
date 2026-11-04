"""QC: central NBA/WNBA stale-props enforcement, one fixture per affected route (2026-11 v3, Gap 2).

The 6h executable-price rule (LIVE_LINES_MAX_AGE_HOURS, CLOCK A) lives in the CENTRAL loaders
(app.load_props / load_wnba_props / load_live_props_feed / load_wnba_live_props_feed via
_executable_props_frame), so every surface fails closed without per-template logic. This QC writes
SYNTHETIC props CSVs into a private temp DATA_DIR and drives each surface through the REAL raw readers,
the real central gate and the real caches. For every surface: a STALE feed (freshest LastUpdated 10h ago)
yields no executable row, and a FRESH control (1h) does -- so each absence is the gate biting, not an
empty fixture. Ages are computed between timezone-aware UTC instants (LastUpdated is the fetchers' naive
Eastern wall clock).

Surfaces (route -> builder): /sports/nba/props + /sports/wnba/props (market-only board) · /tools/nba-player
+ /tools/wnba-player (build_market_player_page) · /tools/best-lines · /tools/risk-radar · /tools/slate-pulse ·
/derivatives (_load_derivative_prop_rows) · / + /dashboard + /free (build_cross_sport_dashboard_snapshots,
build_free_sport_prop_rows) · /elite (sharp-money scanner + best-book board) · /sports/wnba + /parlay?sport=wnba
+ WNBA method/matchup pages (build_wnba_prop_board 12h cache) · /sports/nba (gate on) + /parlay + market-edge +
command center (build_live_prop_runtime_context 12h disk cache) · NBA/WNBA/Elite runtime snapshots (72h) ·
Green Light / King's Tickets / Daily Card (+png) / Menu (no NBA/WNBA props input -- static proof).

v4 (owner decisions 5 + 6): qc_skew_contract proves the clock-skew contract (+<=5 min tolerated AND labelled,
beyond fails closed, a single beyond-allowance row dropped); qc_route_matrix renders EVERY route above over
HTTP in four feed states -- stale (10h), fresh (1h), skew_ok (+3 min), skew_fail (+10 min) -- and prints a
route -> fixture -> stale / fresh / skew_ok / skew_fail table. Stale and skew_fail: no price, no fixture row,
no executable/ticket control (data-*/value/onclick/form markup naming the fixture player), and the builder
behind a "builder:" route exposes nothing executable (for /parlay the payout read returns NO PRICE READ).
Fresh and skew_ok: the fixture quote renders (or the builder control proves the executable input); skew_ok is
labelled (props_feed_status flag + data-props-clock-skew on the pages carrying the status partial).

Auth via services.qc_auth (in-memory principals); no user-store writes (heartbeat redirected to temp); no
network; nothing under the real data/ is read or written. Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import inspect
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

os.environ.setdefault("SECRET_KEY", "qc-nba-wnba-props-stale")  # app import needs one; synthetic QC

import app  # noqa: E402
from services.qc_auth import isolated_member_client, isolated_owner_client  # noqa: E402
from services.timeutils import DISPLAY_TZ  # noqa: E402

FAILS: list[str] = []
NOTES: list[str] = []
STALE_H = app.LIVE_LINES_MAX_AGE_HOURS + 4
PLAYER = {"nba": "Qcnba Stalecheck", "wnba": "Qcwnba Stalecheck"}
PRICE = -117          # a distinctive Over price that only the fixture carries
_MTIME = [1_700_000_000]


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def _et(dt):
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def _write_props(sport, age_hours):
    """Synthetic props CSV for `sport` whose freshest LastUpdated is age_hours old. A distinct mtime per write
    (DATAFRAME_CACHE is mtime-keyed)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    p = PLAYER[sport]
    game = "QCA @ QCB"
    rows = []
    for i, (stat, line, book) in enumerate((("PTS", 24.5, "DraftKings"), ("REB", 8.5, "DraftKings"),
                                             ("AST", 6.5, "FanDuel"))):
        rows.append({"Player": p, "Team": "QCA", "Stat": stat, "MarketKey": f"player_{stat.lower()}",
                     "Line": line, "CurrentLine": line, "OpenLine": line - 1.0, "Game": game, "Book": book,
                     "OverOdds": PRICE, "UnderOdds": -103, "OpenOverOdds": PRICE + 15, "OpenUnderOdds": -118,
                     "LastUpdated": _et(now - timedelta(hours=age_hours, minutes=i))})
    path = Path(app.DATA_DIR) / "props" / ("NBA_Props.csv" if sport == "nba" else "WNBA_Props.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    _MTIME[0] += 10
    os.utime(path, (_MTIME[0], _MTIME[0]))
    return path


@contextlib.contextmanager
def sandbox():
    """Private DATA_DIR + redirected module-level paths; caches cleared on entry and exit."""
    names = ("DATA_DIR", "DERIVATIVE_SPORT_PROP_PATHS", "ACTIVE_USER_HEARTBEAT_PATH", "LIVE_SCORES_PATH", "_utc_now")
    saved = {n: getattr(app, n) for n in names}
    saved_env = os.environ.get("BK_NBA_STATS_ENABLED")
    td = tempfile.TemporaryDirectory(prefix="qc_props_stale_")
    root = Path(td.name)
    for sub in ("props", "cache", "odds", "schedules", "gamelogs", "tracking", "injuries", "live_scores"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    try:
        app.DATA_DIR = root
        app.DERIVATIVE_SPORT_PROP_PATHS = {k: root / "props" / v.name for k, v in saved["DERIVATIVE_SPORT_PROP_PATHS"].items()}
        app.ACTIVE_USER_HEARTBEAT_PATH = root / "live_scores" / "active_user_heartbeat.txt"
        app.LIVE_SCORES_PATH = root / "live_scores" / "Live_Scores.csv"
        app.RUNTIME_TTL_CACHE.clear()
        app._ENTITY_MARKET_KEYSET_CACHE.clear()
        os.environ.pop("BK_NBA_STATS_ENABLED", None)
        yield root
    finally:
        for n, v in saved.items():
            setattr(app, n, v)
        if saved_env is None:
            os.environ.pop("BK_NBA_STATS_ENABLED", None)
        else:
            os.environ["BK_NBA_STATS_ENABLED"] = saved_env
        app.RUNTIME_TTL_CACHE.clear()
        app._ENTITY_MARKET_KEYSET_CACHE.clear()
        td.cleanup()


def _both(fn):
    """Run fn(state) for state in (stale, fresh) after writing that state's NBA + WNBA feeds."""
    out = {}
    for state, age in (("stale", STALE_H), ("fresh", 1.0)):
        _write_props("nba", age)
        _write_props("wnba", age)
        app.RUNTIME_TTL_CACHE.clear()
        out[state] = fn(state)
    return out


# ------------------------------------------------------------------------------------------------ routes
def qc_market_only_boards():
    for sport, path in (("nba", "/sports/nba/props"), ("wnba", "/sports/wnba/props")):
        def go(state):
            with isolated_member_client(plan="all_access") as c:
                r = c.get(path)
            return r.status_code, r.get_data(as_text=True), app.props_feed_status(sport)
        res = _both(go)
        (cs, hs, ss), (cf, hf, _) = res["stale"], res["fresh"]
        check(cs == 200 and PLAYER[sport] not in hs and str(PRICE) not in hs and 'data-props-executable="0"' in hs
              and ss["last_updated"] in hs and ss["unavailable_reason"] == "stale",
              f"{path} stale: no quote/price, actual update time {ss['last_updated']} shown ({ss['age_hours']}h)")
        check(cf == 200 and PLAYER[sport] in hf and str(PRICE) in hf, f"{path} fresh control renders the quote")


def qc_market_player_pages():
    for sport, path in (("nba", "/tools/nba-player"), ("wnba", "/tools/wnba-player")):
        def go(state):
            with isolated_member_client(plan="all_access") as c:
                r = c.get(path, query_string={"q": PLAYER[sport]})
            return r.status_code, r.get_data(as_text=True), app.props_feed_status(sport)
        res = _both(go)
        (cs, hs, ss), (cf, hf, sf) = res["stale"], res["fresh"]
        check(cs == 200 and str(PRICE) not in hs and "prices are withheld" in hs and ss["last_updated"] in hs
              and "doesn&rsquo;t resolve" not in hs,
              f"{path} stale: withheld banner + actual update time, no price, no false 'not a player'")
        check(cf == 200 and str(PRICE) in hf and sf["last_updated"] in hf,
              f"{path} fresh control: prices shown, 'data through' = provider update time {sf['last_updated']}")


def qc_quick_tools():
    def go(state):
        with isolated_owner_client() as c:
            bl = c.get("/tools/best-lines").get_data(as_text=True)
            rr = c.get("/tools/risk-radar").get_data(as_text=True)
        pulse = {r["key"]: r for r in app.build_slate_pulse_context().get("rows", [])} \
            if isinstance(app.build_slate_pulse_context(), dict) else {}
        return bl, rr, pulse
    res = _both(go)
    bl_s, rr_s, pulse_s = res["stale"]
    bl_f, rr_f, pulse_f = res["fresh"]
    check(PLAYER["nba"] not in bl_s and PLAYER["wnba"] not in bl_s and PLAYER["nba"] in bl_f,
          "/tools/best-lines: stale NBA/WNBA offers absent (fresh control present)")
    check(PLAYER["nba"] not in rr_s and PLAYER["wnba"] not in rr_s and PLAYER["nba"] in rr_f,
          "/tools/risk-radar: stale NBA/WNBA markets absent (fresh control present)")
    ns, nf = pulse_s.get("nba", {}), pulse_f.get("nba", {})
    check(ns.get("props") == 0 and ns.get("state") == "stale" and nf.get("props", 0) > 0,
          f"/tools/slate-pulse: stale NBA feed reads 'stale' with 0 executable props (fresh {nf.get('props')})")


def qc_derivatives_and_free():
    res = _both(lambda s: (app._load_derivative_prop_rows("NBA"), app._load_derivative_prop_rows("WNBA"),
                           app.build_free_sport_prop_rows("nba"), app.build_free_sport_prop_rows("wnba"),
                           {x["key"]: x for x in app.build_cross_sport_dashboard_snapshots(False)}))
    dn, dw, fn_, fw, snap = res["stale"]
    dn_f, dw_f, fn_f, fw_f, snap_f = res["fresh"]
    check(not dn and not dw and dn_f and dw_f, "/derivatives: no NBA/WNBA derivative row from a stale feed (fresh control rows)")
    check(not fn_ and not fw and fn_f and fw_f, "/free (+/home previews): no NBA/WNBA sample prop row from a stale feed")
    s, f = snap.get("nba", {}), snap_f.get("nba", {})
    check(not s.get("best_prop") and not s.get("best_over") and s.get("props_rows") == 0
          and (f.get("best_prop") or f.get("best_over") or f.get("best_under")),
          "/ + /dashboard cross-sport cards: no NBA best prop/price from a stale feed (fresh control has one)")


def qc_elite():
    cand = [{"sport": "NBA", "player": PLAYER["nba"], "stat": "PTS", "direction": "OVER", "line": 24.5}]
    saved = app.load_mlb_props
    app.load_mlb_props = lambda: pd.DataFrame()
    try:
        res = _both(lambda s: (app.build_elite_sharp_money_scanner([]), app.build_elite_best_book_board(cand)))
    finally:
        app.load_mlb_props = saved
    (scan_s, book_s), (scan_f, book_f) = res["stale"], res["fresh"]
    check(not [x for x in scan_s if x["sport"] in ("NBA", "WNBA")] and [x for x in scan_f if x["sport"] == "NBA"],
          "/elite sharp-money scanner: no NBA/WNBA move rows from a stale feed (fresh control has them)")
    check(not book_s and book_f, "/elite best-book board: no NBA price comparison from a stale feed (fresh control has one)")


def qc_wnba_board_cache():
    """build_wnba_prop_board returns its 12h cache entry BEFORE checking for empty props. Prove the
    executable token in the cache version means a build made while fresh is NOT served once the feed ages."""
    _write_props("wnba", 1.0)
    key = "wnba_prop_board::today::::all::::12"
    token_fresh = app._build_file_token(Path(app.DATA_DIR) / "props" / "WNBA_Props.csv")
    version = app._build_file_token(*[Path(app.DATA_DIR) / p for p in (
        "props/WNBA_Props.csv", "odds/WNBA_Odds.csv", "schedules/WNBA_Schedule.csv", "gamelogs/WNBA_GameLogs.csv",
        "injuries/WNBA_Injuries.csv", "tracking/WNBA_Calibration_Report.csv", "tracking/WNBA_Simulation_Results.csv",
        "tracking/WNBA_Simulation_Results.csv", "tracking/Team_Strength_Priors.csv")])
    sentinel = [{"player": "CACHED-WHILE-FRESH", "over_odds": PRICE}]
    app.RUNTIME_TTL_CACHE[key] = {"created_at": datetime.now(timezone.utc), "version": version, "value": sentinel}
    hit = app.build_wnba_prop_board(app.load_wnba_props(), pd.DataFrame(), pd.DataFrame())
    real_now = app._utc_now
    app._utc_now = lambda: real_now() + timedelta(hours=STALE_H)   # same file, same mtime, 10h later
    try:
        token_later = app._build_file_token(Path(app.DATA_DIR) / "props" / "WNBA_Props.csv")
        later = app.build_wnba_prop_board(app.load_wnba_props(), pd.DataFrame(), pd.DataFrame())
    finally:
        app._utc_now = real_now
    check(hit == sentinel, "control: an unchanged fresh feed serves its cached WNBA board")
    check(token_later != token_fresh and later == [] and "CACHED-WHILE-FRESH" not in repr(later),
          "/sports/wnba, /parlay?sport=wnba, WNBA method + matchup pages: a board cached while fresh is NOT served "
          "after the same, unchanged file ages past 6h (executable token flips the version)")


def qc_nba_runtime_cache():
    """Gate-ON NBA surfaces (/sports/nba/props board, /sports/nba command center, /parlay + saved-ticket payout,
    /sports/nba/market-edge) all read build_live_prop_runtime_context (12h disk cache, mtime version)."""
    os.environ["BK_NBA_STATS_ENABLED"] = "1"
    _write_props("nba", 1.0)
    try:
        fresh = app.build_live_prop_runtime_context(postseason_only=False)
        n_fresh = len(fresh["refresh_meta"].get("books") or [])
        real_now = app._utc_now
        app._utc_now = lambda: real_now() + timedelta(hours=STALE_H)
        try:
            later = app.build_live_prop_runtime_context(postseason_only=False)
        finally:
            app._utc_now = real_now
    finally:
        os.environ.pop("BK_NBA_STATS_ENABLED", None)
    check(fresh["refresh_meta"].get("executable") is True and n_fresh > 0, "control: fresh NBA runtime context is executable")
    check(later is not fresh and getattr(later["props_df"], "empty", False) and later["refresh_meta"].get("is_stale")
          and not later["refresh_meta"].get("executable"),
          "NBA runtime context (props board / command center / parlay payout / market-edge): rebuilt with ZERO "
          "props once the unchanged file ages past 6h; meta is_stale with the real update time")


def qc_snapshots():
    os.environ["BK_NBA_STATS_ENABLED"] = "1"
    try:
        _write_props("nba", 1.0)
        _write_props("wnba", 1.0)
        app.write_runtime_snapshot("nba_props_postseason_today_current", {"rows": [{"over": PRICE}]})
        app.write_runtime_snapshot("wnba_dashboard_today", {"rows": [{"over": PRICE}]})
        app.write_runtime_snapshot("elite_dashboard_v3_all_qc", {"rows": [{"over": PRICE}]})
        keys = ("nba_props_postseason_today_current", "wnba_dashboard_today", "elite_dashboard_v3_all_qc")
        served = [app.load_runtime_snapshot(k, max_age_minutes=720, allow_stale=True, stale_max_age_minutes=4320) for k in keys]
        real_now = app._utc_now
        app._utc_now = lambda: real_now() + timedelta(hours=STALE_H)
        try:
            refused = [app.load_runtime_snapshot(k, max_age_minutes=720, allow_stale=True, stale_max_age_minutes=4320)
                       for k in keys]
        finally:
            app._utc_now = real_now
        # a snapshot rendered BEFORE the feed's current update came from an older feed -> refused
        path = app.get_runtime_snapshot_path("nba_props_postseason_today_current")
        doc = __import__("json").loads(path.read_text(encoding="utf-8"))
        doc["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        path.write_text(__import__("json").dumps(doc), encoding="utf-8")
        older = app.load_runtime_snapshot("nba_props_postseason_today_current", max_age_minutes=720)
        mlb = app._snapshot_props_sports("mlb_dashboard_today")
    finally:
        os.environ.pop("BK_NBA_STATS_ENABLED", None)
    check(all(s is not None for s in served), "control: NBA/WNBA/Elite snapshots serve while the feed is executable")
    check(all(s is None for s in refused),
          "runtime snapshots (72h servable): NBA, WNBA and Elite snapshots refused once the props feed ages past 6h")
    check(older is None, "a snapshot rendered before the feed's current update is refused (older feed)")
    check(mlb == (), "scope: MLB/NFL snapshots are not touched by the NBA/WNBA gate")


def qc_no_props_input_surfaces():
    """Green Light, King's Tickets, Daily Card (+ .png image) and The Menu read no NBA/WNBA props: their view
    functions (and the builders they name) never reference the props loaders. Static proof."""
    loaders = ("load_props(", "load_wnba_props(", "load_live_props_feed", "load_wnba_live_props_feed",
               "NBA_Props.csv", "WNBA_Props.csv", "_load_props_raw", "_load_wnba_props_raw")
    rules = {r.rule: r.endpoint for r in app.app.url_map.iter_rules()}
    checked = []
    for rule in ("/tools/green-light", "/tools/kings-tickets", "/tools/daily-card", "/tools/daily-card.png", "/tools/menu"):
        ep = rules.get(rule)
        if not ep:
            continue
        src = inspect.getsource(app.app.view_functions[ep])
        called = set(__import__("re").findall(r"\b(build_[a-z0-9_]+)\(", src))
        for name in called:
            fn = getattr(app, name, None)
            if callable(fn):
                try:
                    src += inspect.getsource(fn)
                except (OSError, TypeError):
                    pass
        hit = [l for l in loaders if l in src]
        check(not hit, f"{rule}: no NBA/WNBA props input in the view or its builders ({hit or 'none'})")
        checked.append(rule)
    check(len(checked) >= 4, f"no-props-input surfaces located in the url map ({checked})")


def qc_central_contract():
    now = datetime.now(timezone.utc)
    mk = lambda lu: pd.DataFrame([{"Player": "x", "Book": "b", "LastUpdated": lu}, {"Player": "y", "Book": "b", "LastUpdated": lu}])  # noqa: E731
    m_ok = app.props_executable_meta(mk(_et(now - timedelta(hours=5, minutes=59))))
    m_st = app.props_executable_meta(mk(_et(now - timedelta(hours=6, minutes=1))))
    m_loose = app.props_executable_meta(mk(_et(now - timedelta(hours=7))), max_age_hours=24)
    m_utc = app.props_executable_meta(mk((now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    check(m_ok["executable"] and not m_st["executable"] and m_st["unavailable_reason"] == "stale",
          "boundary: 5h59m executable, 6h01m withheld (CLOCK A, 6h)")
    check(not m_loose["executable"] and m_loose["max_age_hours"] == app.LIVE_LINES_MAX_AGE_HOURS,
          "a caller asking for 24h cannot loosen the 6h rule")
    check(m_utc["executable"] and 1.9 < m_utc["age_hours"] < 2.1,
          "an aware UTC stamp and a naive Eastern stamp both age correctly (timezone-aware UTC instants)")
    src = inspect.getsource(app.build_market_only_board)
    check("require_fresh=False" not in src and "props_executable_meta(df)" in src,
          "build_market_only_board no longer calls require_fresh=False and re-verifies the frame it receives")


# ------------------------------------------------------------------------------------------------ v4 matrix
# Four feed states per route (owner decision 5 + 6). Ages in hours; negative = the provider clock is AHEAD.
STATES = {"stale": STALE_H, "fresh": 1.0, "skew_ok": -3.0 / 60.0, "skew_fail": -10.0 / 60.0}
MATRIX: list[dict] = []     # one row per route for the printed table

# (route, fixture name, sports whose fixture the route reads, fresh-control kind, allowed stale name echo)
#   kind "quote": fixture player AND price render over HTTP when executable (fresh / skew_ok)
#   kind "name":  fixture player renders (the page shows no price column at all)
#   kind "builder:<check>": the page shows no fixture row even when fresh in this config (gate off = prod),
#                 so its executable input is proven by the named builder-level check in the same 4 states
ROUTE_MATRIX = [
    ("/", "rt_root_redirect", ("nba", "wnba"), "builder:cross_sport_snapshots", False),
    ("/dashboard", "rt_dashboard", ("nba", "wnba"), "quote", False),
    ("/free", "rt_free", ("nba", "wnba"), "name", False),
    ("/free/nba", "rt_free_nba", ("nba",), "quote", False),
    ("/free/wnba", "rt_free_wnba", ("wnba",), "quote", False),
    ("/home/props", "rt_home_props", ("nba", "wnba"), "quote", False),
    ("/home/elite", "rt_home_elite_redirect", ("nba", "wnba"), "builder:elite_builders", False),
    ("/derivatives", "rt_derivatives", ("nba", "wnba"), "quote", False),
    ("/elite", "rt_elite", ("nba", "wnba"), "name", True),           # alert HISTORY may echo a name; never a price
    ("/sports/nba", "rt_sports_nba", ("nba",), "builder:nba_runtime_context", False),
    ("/sports/wnba", "rt_sports_wnba", ("wnba",), "quote", False),
    ("/sports/nba/props", "rt_nba_props_board", ("nba",), "quote", False),
    ("/sports/wnba/props", "rt_wnba_props_board", ("wnba",), "quote", False),
    ("/parlay", "rt_parlay_nba", ("nba",), "builder:nba_runtime_context+payout", False),
    ("/parlay?sport=wnba", "rt_parlay_wnba", ("wnba",), "quote", False),
    ("/sports/nba/market-edge", "rt_nba_market_edge", ("nba",), "builder:nba_runtime_context", False),
    ("/sports/wnba/market-edge", "rt_wnba_market_edge", ("wnba",), "quote", False),
    ("/sports/wnba/floor", "rt_wnba_floor", ("wnba",), "builder:wnba_prop_board", False),
    ("/sports/wnba/trends", "rt_wnba_trends", ("wnba",), "builder:wnba_prop_board", False),
    ("/sports/wnba/matchup/qca-at-qcb", "rt_wnba_matchup", ("wnba",), "quote", False),
    ("/tools/nba-player?q=Qcnba+Stalecheck", "rt_nba_player", ("nba",), "quote", True),   # echoes the query
    ("/tools/wnba-player?q=Qcwnba+Stalecheck", "rt_wnba_player", ("wnba",), "quote", True),
    ("/tools/best-lines", "rt_best_lines", ("nba", "wnba"), "quote", False),
    ("/tools/risk-radar", "rt_risk_radar", ("nba", "wnba"), "name", False),
    ("/tools/slate-pulse", "rt_slate_pulse", ("nba", "wnba"), "builder:slate_pulse_counts", False),
    # controls that were already strict before v3 (no NBA/WNBA props input): must render in every state
    ("/tools/green-light", "rt_ctrl_green_light", (), "control", False),
    ("/tools/menu", "rt_ctrl_menu", (), "control", False),
]
_SKEW_LABEL_ROUTES = ("/sports/nba/props", "/sports/wnba/props", "/tools/nba-player", "/tools/wnba-player")


def _control_echo(html: str, names) -> list[str]:
    """Any executable/ticket control carrying a fixture player: a data-* / value= / onclick= attribute or a
    form/button whose markup names the player (add-to-ticket, leg, payout inputs)."""
    import re
    hits = []
    for n in names:
        pat = re.escape(n)
        if re.search(r'(data-[a-z0-9_-]+|value|onclick|name)\s*=\s*"[^"]*' + pat, html, re.I) or \
                re.search(r"<(button|form|input)[^>]*" + pat, html, re.I):
            hits.append(n)
    return hits


def _write_wnba_odds(root: Path):
    now = datetime.now(timezone.utc) + timedelta(hours=5)
    et = now.astimezone(DISPLAY_TZ)
    pd.DataFrame([{"GameID": "qcw1", "Date": et.strftime("%Y-%m-%d"), "Time": et.strftime("%H:%M"), "Away": "QCA",
                   "Home": "QCB", "Book": "DraftKings", "AwayML": 120, "HomeML": -140, "Spread": -2.5,
                   "SpreadOdds": -110, "Total": 160.5, "OverOdds": -110, "UnderOdds": -110,
                   "LastUpdated": _et(datetime.now(timezone.utc))}]).to_csv(root / "odds" / "WNBA_Odds.csv", index=False)


def _builder_probe(kind: str):
    """(leaked, fresh_ok) -- see _builder_probe_raw."""
    got = _builder_probe_raw(kind)
    return got if isinstance(got, tuple) else (bool(got), bool(got))


def _builder_probe_raw(kind: str):
    """Executable-input proof for routes that show no fixture row in this config. True when the fixture's
    executable data reached the builder (expected in fresh/skew_ok, never in stale/skew_fail)."""
    if kind == "cross_sport_snapshots":
        snap = {x["key"]: x for x in app.build_cross_sport_dashboard_snapshots(False)}
        n, w = snap.get("nba", {}), snap.get("wnba", {})
        return bool((n.get("best_prop") or n.get("best_over") or n.get("best_under")) and int(n.get("props_rows") or 0) > 0)
    if kind == "elite_builders":
        cand = [{"sport": "NBA", "player": PLAYER["nba"], "stat": "PTS", "direction": "OVER", "line": 24.5}]
        saved = app.load_mlb_props
        app.load_mlb_props = lambda: pd.DataFrame()
        try:
            return bool(app.build_elite_best_book_board(cand))
        finally:
            app.load_mlb_props = saved
    if kind.startswith("nba_runtime_context"):
        os.environ["BK_NBA_STATS_ENABLED"] = "1"
        try:
            ctx = app.build_live_prop_runtime_context(postseason_only=False)
        finally:
            os.environ.pop("BK_NBA_STATS_ENABLED", None)
        has = (not getattr(ctx["props_df"], "empty", True)) and PLAYER["nba"] in set(ctx["props_df"]["Player"].astype(str))
        if kind.endswith("+payout"):
            # The parlay payout read prices a leg from the EXECUTABLE frame only; no price -> it refuses.
            frame = app.load_props()
            leg = frame[frame["Player"].astype(str) == PLAYER["nba"]] if not frame.empty else frame
            price = float(leg["OverOdds"].iloc[0]) if not leg.empty else None
            read = app.calculate_bankroll_iq(true_probability=0.55, decimal_odds=app._american_decimal_odds(price))
            priced = read.get("label") != "NO PRICE READ"
            return (has or priced), (has and priced)   # (anything executable leaked, full fresh control)
        return has
    if kind == "wnba_prop_board":
        board = app.build_wnba_prop_board(app.load_wnba_props(), app.load_wnba_game_market_odds(),
                                          app.load_wnba_schedule(), date_filter="all", featured_top_n=0)
        return any(r.get("player") == PLAYER["wnba"] for r in board)
    if kind == "slate_pulse_counts":
        ctx = app.build_slate_pulse_context()
        rows = {r["key"]: r for r in (ctx.get("rows", []) if isinstance(ctx, dict) else [])}
        return int(rows.get("nba", {}).get("props") or 0) > 0
    raise ValueError(kind)


def qc_route_matrix():
    """Every NBA/WNBA stale-props route x {stale, fresh, skew_ok (+3 min), skew_fail (+10 min)} over HTTP,
    through the real loaders. Stale and skew_fail: no price, no fixture row, no executable/ticket control;
    fresh and skew_ok: the fresh control renders (or the builder control proves the executable input), and
    skew_ok is LABELLED (props_feed_status flag; status partial on the pages that carry it)."""
    _write_wnba_odds(Path(app.DATA_DIR))
    results = {r[0]: {} for r in ROUTE_MATRIX}
    for state, age in STATES.items():
        _write_props("nba", age)
        _write_props("wnba", age)
        app.RUNTIME_TTL_CACHE.clear()
        status = {s: app.props_feed_status(s) for s in ("nba", "wnba")}
        executable = state in ("fresh", "skew_ok")
        # central verdict per state
        for s in ("nba", "wnba"):
            st = status[s]
            want = {"stale": (False, "stale"), "fresh": (True, None), "skew_ok": (True, None),
                    "skew_fail": (False, "future_timestamp")}[state]
            check(st["executable"] is want[0] and st["unavailable_reason"] == want[1]
                  and bool(st.get("clock_skew_tolerated")) is (state == "skew_ok")
                  and (state != "skew_ok" or (st.get("status_reason") == "clock_skew_tolerated"
                                              and 0 < st.get("clock_skew_seconds", 0) <= 300)),
                  f"central gate [{s}/{state}]: executable={st['executable']} reason={st['unavailable_reason']} "
                  f"skew_tolerated={st.get('clock_skew_tolerated')} skew_s={st.get('clock_skew_seconds')}")
        for route, fixture, sports, kind, echo_ok in ROUTE_MATRIX:
            names = [PLAYER[s] for s in sports]
            with isolated_owner_client() as c:
                r = c.get(route)
            html = r.get_data(as_text=True)
            ok_status = r.status_code in (200, 302)
            if kind == "control":
                good = r.status_code == 200
                note = f"HTTP {r.status_code}"
            elif not executable:
                leaked_price = str(PRICE) in html
                leaked_name = [n for n in names if n in html]
                ctrl = _control_echo(html, names)
                good = ok_status and not leaked_price and not ctrl and (echo_ok or not leaked_name)
                if kind.startswith("builder:"):
                    good = good and not _builder_probe(kind.split(":", 1)[1])[0]
                if state == "skew_fail" and route.split("?")[0] in _SKEW_LABEL_ROUTES and r.status_code == 200:
                    good = good and ('data-props-reason="future_timestamp"' in html or "prices are withheld" in html)
                note = (f"HTTP {r.status_code}, price={'LEAK' if leaked_price else 'none'}, "
                        f"controls={ctrl or 'none'}, name={'echo(no price)' if leaked_name else 'none'}")
            else:
                if kind == "quote":
                    good = r.status_code == 200 and all(n in html for n in names) and str(PRICE) in html
                elif kind == "name":
                    good = r.status_code == 200 and all(n in html for n in names)
                else:
                    good = ok_status and _builder_probe(kind.split(":", 1)[1])[1]
                if state == "skew_ok":
                    good = good and all(status[s].get("clock_skew_tolerated") for s in sports)
                    if route.split("?")[0] in _SKEW_LABEL_ROUTES:
                        good = good and 'data-props-clock-skew="1"' in html
                note = f"HTTP {r.status_code}, {kind}"
            results[route][state] = "PASS" if good else "FAIL"
            check(good, f"{route} [{fixture}] {state}: {note}")
    for route, fixture, sports, kind, _ in ROUTE_MATRIX:
        MATRIX.append({"route": route, "fixture": fixture, "kind": kind, **results[route]})
    try:
        (Path(app.DATA_DIR) / "odds" / "WNBA_Odds.csv").unlink()
    except OSError:
        pass


def qc_skew_contract():
    """Clock-skew contract (owner decision 5): +<=5 min tolerated AND labelled; beyond fails closed; a single
    row beyond the allowance is dropped from an otherwise executable feed."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    mk = lambda *lus: pd.DataFrame([{"Player": f"p{i}", "Book": "b", "LastUpdated": lu} for i, lu in enumerate(lus)])  # noqa: E731
    ok3 = app.props_executable_meta(mk(iso(now + timedelta(minutes=3))), now=now)
    edge = app.props_executable_meta(mk(iso(now + timedelta(minutes=5))), now=now)
    bad = app.props_executable_meta(mk(iso(now + timedelta(minutes=5, seconds=1))), now=now)
    plain = app.props_executable_meta(mk(iso(now - timedelta(minutes=30))), now=now)
    check(ok3["executable"] and ok3["clock_skew_tolerated"] and ok3["status_reason"] == "clock_skew_tolerated"
          and ok3["clock_skew_seconds"] == 180, "skew +3 min: executable, clock_skew_tolerated, status_reason, 180 s")
    check(edge["executable"] and edge["clock_skew_tolerated"] and edge["clock_skew_seconds"] == 300,
          "skew exactly +5 min: still tolerated (inclusive boundary)")
    check(not bad["executable"] and bad["unavailable_reason"] == "future_timestamp" and bad["prices_withheld"]
          and not bad["clock_skew_tolerated"], "skew +5 min 1 s: fails closed (future_timestamp, prices withheld)")
    check(plain["executable"] and not plain["clock_skew_tolerated"] and plain["status_reason"] is None,
          "no skew: no skew label")
    frame, meta = app._executable_props_frame("nba", mk(iso(now - timedelta(minutes=20)), iso(now + timedelta(minutes=30))),
                                              now=now)
    check(meta["executable"] and len(frame) == 1 and meta["future_rows_dropped"] == 1
          and list(frame["Player"]) == ["p0"],
          "row level: a row stamped +30 min is dropped from an otherwise executable feed (fail closed per row)")
    with app.app.test_request_context():
        label = app.render_template("_props_feed_status.html", props_status={**ok3, "last_updated": "x"})
        withheld = app.render_template("_props_feed_status.html", props_status={**bad, "last_updated": "y"})
    check('data-props-clock-skew="1"' in label and "clock skew tolerated" in label,
          "the status partial LABELS a tolerated skew")
    check('data-props-executable="0"' in withheld and 'data-props-reason="future_timestamp"' in withheld
          and "beyond the 5-minute clock-skew allowance" in withheld,
          "the status partial explains a beyond-allowance future timestamp and withholds prices")


def print_matrix():
    print("-" * 110)
    print(f"{'route':42} {'fixture':24} {'stale':6} {'fresh':6} {'skew_ok':8} {'skew_fail':9} control")
    for m in MATRIX:
        print(f"{m['route']:42} {m['fixture']:24} {m.get('stale','-'):6} {m.get('fresh','-'):6} "
              f"{m.get('skew_ok','-'):8} {m.get('skew_fail','-'):9} {m['kind']}")
    print("-" * 110)


def main() -> int:
    with sandbox():
        for fn in (qc_central_contract, qc_skew_contract, qc_market_only_boards, qc_market_player_pages,
                   qc_quick_tools, qc_derivatives_and_free, qc_elite, qc_wnba_board_cache, qc_nba_runtime_cache,
                   qc_snapshots, qc_no_props_input_surfaces, qc_route_matrix):
            try:
                fn()
            except Exception as exc:  # a crash is a failure, never a pass
                import traceback
                FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: NBA/WNBA STALE PROPS -- CENTRAL ENFORCEMENT, ONE FIXTURE PER ROUTE")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print_matrix()
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
