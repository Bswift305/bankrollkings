"""QC: LastUpdated survives the REAL game-line load path, so the 6h stale-lines cutoff fires on real data.

Defect (fixed): `_format_game_market_odds` projected loaded odds onto a fixed column list that omitted
`LastUpdated`. Every sport's game-line loader goes through it, so `get_lines_refresh_meta` never saw a
timestamp and the stale-lines cutoff (CLOCK A, 6h -- services/freshness_contract.py) could never fire on
real data. qc_game_lines_freshness.py did not catch it: its fixture is a pre-shaped frame that bypasses
the formatter.

This QC writes CSVs to disk in the fetch_game_lines.py schema, points app.DATA_DIR at a temp dir and
loads through the REAL loaders (`load_*_game_market_odds` -> `_load_cached_csv` ->
`_format_game_market_odds`). Then:
  1. every sport loader (NBA/WNBA/MLB/NFL/NCAAF) keeps LastUpdated, raw values unchanged;
  2. a 10h-old file (naive-Eastern stamp, the fetch_game_lines.py convention) -> stale; the market
     lookup is empty and build_football_live_games hands the board an EMPTY odds frame (suppressed);
  3. a 1h-old file -> live; lookup populated (payload last_updated = raw stamp); odds passed through;
  4. offset-bearing UTC stamps (fetch_ncaaf_slate_cfbd.py '...Z') age correctly both ways;
  5. a file with NO LastUpdated column -> the EXISTING contract: age unknown -> NOT stale, NOT
     suppressed (status 'live', last_updated 'Unknown'). Pinned here so a change to it is deliberate;
  6. the tz convention (services.timeutils.parse_feed_timestamp_utc) on fixed stamps, incl. DST;
  7. MUTATION: re-dropping LastUpdated in the formatter makes the stale-file check FAIL (QC is live).

Temp files only; no network. Exit 0 on pass, 1 on any [FAIL].
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import app
from services.timeutils import parse_feed_timestamp_utc, to_eastern_datetime_str

COLUMNS = ["Date", "Time", "Away", "Home", "AwayFull", "HomeFull", "AwayML", "HomeML", "Spread",
           "SpreadOdds", "Total", "OverOdds", "UnderOdds", "Book", "GameID", "LastUpdated"]
SPORT_LOADERS = {
    "NBA": "load_game_market_odds",
    "WNBA": "load_wnba_game_market_odds",
    "MLB": "load_mlb_game_market_odds",
    "NFL": "load_nfl_game_market_odds",
    "NCAAF": "load_ncaaf_game_market_odds",
}
TOL_H = 0.1

_results = {"ok": 0, "fail": 0}
_tmp_dirs = []


def ok(msg):
    _results["ok"] += 1
    print(f"[ok] {msg}")


def fail(msg):
    _results["fail"] += 1
    print(f"[FAIL] {msg}")


def check(cond, good, bad):
    (ok if cond else fail)(good if cond else bad)
    return bool(cond)


def _utc_iso(age_hours):
    return (datetime.now(timezone.utc) - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def eastern_stamp(age_hours):
    """Exactly what fetch_game_lines.py writes: provider UTC last_update -> naive Eastern 'YYYY-MM-DD HH:MM'."""
    return to_eastern_datetime_str(_utc_iso(age_hours))


def _rows(stamp):
    base = {"Date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"), "Time": "13:00",
            "AwayML": 260, "HomeML": -325, "Spread": -7.0, "SpreadOdds": -110, "Total": 54.5,  # synthetic-fixture
            "OverOdds": -110, "UnderOdds": -110, "Book": "BetMGM"}  # synthetic-fixture
    games = [("Arizona Cardinals", "Dallas Cowboys", "g1"), ("Buffalo Bills", "Miami Dolphins", "g2")]
    out = []
    for away, home, gid in games:
        out.append({**base, "Away": away, "Home": home, "AwayFull": away, "HomeFull": home,
                    "GameID": gid, "LastUpdated": stamp})
    return out


def write_odds_dir(stamp, sports=("NFL",), drop_lastupdated=False):
    """Create a temp DATA_DIR with data/odds/<SPORT>_Odds.csv on disk; returns the dir."""
    d = Path(tempfile.mkdtemp(prefix="qc_lu_pipeline_"))
    _tmp_dirs.append(d)
    (d / "odds").mkdir(parents=True)
    df = pd.DataFrame(_rows(stamp), columns=COLUMNS)
    if drop_lastupdated:
        df = df.drop(columns=["LastUpdated"])
    for sport in sports:
        df.to_csv(d / "odds" / f"{sport}_Odds.csv", index=False)
    return d


def load_real(data_dir, sport="NFL"):
    """Load through the REAL loader -> _load_cached_csv -> _format_game_market_odds."""
    orig = app.DATA_DIR
    app.DATA_DIR = data_dir
    try:
        return getattr(app, SPORT_LOADERS[sport])()
    finally:
        app.DATA_DIR = orig


def football_board_odds_len(odds_df):
    """Length of the odds frame build_football_live_games actually hands to the board lookup."""
    seen = []
    orig = app.build_live_game_lookup

    def spy(o, s, *a, **k):
        seen.append(0 if o is None else int(len(o)))
        return orig(o, s, *a, **k)

    app.build_live_game_lookup = spy
    try:
        try:
            app.build_football_live_games(odds_df, pd.DataFrame(), date_filter="all")
        except Exception:
            pass   # only the odds hand-off matters here
    finally:
        app.build_live_game_lookup = orig
    return seen[0] if seen else None


def stale_file_suppressed(label):
    """The core adversarial check, reused by the mutation test. Returns the list of failures."""
    problems = []
    loaded = load_real(write_odds_dir(eastern_stamp(10)))
    meta = app.get_lines_refresh_meta(loaded)
    if not meta.get("is_stale"):
        problems.append(f"{label}: 10h-old file NOT flagged stale (meta={meta})")
    if app.build_game_market_lookup(loaded):
        problems.append(f"{label}: 10h-old file still annotated current lines (lookup not empty)")
    n = football_board_odds_len(loaded)
    if n is None or n != 0:
        problems.append(f"{label}: 10h-old file -> football board got {n} odds rows (expected 0)")
    return problems, meta


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS GAME-LINES LastUpdated PIPELINE QC")
    print("=" * 60)
    real_formatter = app._format_game_market_odds
    try:
        # (1) every sport loader keeps LastUpdated, raw
        stamp = eastern_stamp(1)
        d = write_odds_dir(stamp, sports=tuple(SPORT_LOADERS))
        for sport in SPORT_LOADERS:
            df = load_real(d, sport)
            has = "LastUpdated" in df.columns
            check(has and not df.empty and df["LastUpdated"].astype(str).eq(stamp).all(),
                  f"{sport}: real loader keeps LastUpdated, raw value unchanged ('{stamp}')",
                  f"{sport}: real loader lost/altered LastUpdated (cols={list(df.columns)})")

        # (2) 10h-old naive-Eastern file -> stale + suppressed
        problems, meta = stale_file_suppressed("real formatter")
        if problems:
            for p in problems:
                fail(p)
        else:
            ok(f"10h-old file -> is_stale (age {meta.get('age_hours')}h), lookup empty, football board odds empty")
        age = meta.get("age_hours")
        check(age is not None and abs(age - 10) <= TOL_H,
              f"10h-old naive-Eastern stamp ages as {age}h (Eastern-anchored, not process-local)",
              f"10h-old naive-Eastern stamp aged as {age}h (expected 10 +/- {TOL_H}) -- tz misread")

        # (3) 1h-old file -> live, shown
        fresh_stamp = eastern_stamp(1)
        fresh = load_real(write_odds_dir(fresh_stamp))
        fmeta = app.get_lines_refresh_meta(fresh)
        fage = fmeta.get("age_hours")
        check(not fmeta.get("is_stale") and fmeta.get("status") == "live",
              f"1h-old file -> live (age {fage}h)", f"1h-old file wrongly stale: {fmeta}")
        check(fage is not None and abs(fage - 1) <= TOL_H,
              f"1h-old naive-Eastern stamp ages as {fage}h", f"1h-old stamp aged as {fage}h (tz misread)")
        lk = app.build_game_market_lookup(fresh)
        payload = next(iter(lk.values()), {}) if lk else {}
        check(bool(lk) and payload.get("last_updated") == fresh_stamp,
              "1h-old file -> lookup populated; payload last_updated is the raw stamp",
              f"1h-old file -> lookup empty or last_updated wrong ({payload.get('last_updated')!r})")
        n = football_board_odds_len(fresh)
        check(n == len(fresh) and n > 0, f"1h-old file -> football board receives all {n} odds rows",
              f"1h-old file -> football board got {n} rows (expected {len(fresh)})")

        # (4) offset-bearing UTC stamps (CFBD writer format)
        zs = app.get_lines_refresh_meta(load_real(write_odds_dir(_utc_iso(10))))
        zf = app.get_lines_refresh_meta(load_real(write_odds_dir(_utc_iso(1))))
        check(zs.get("is_stale") and abs((zs.get("age_hours") or 0) - 10) <= TOL_H,
              f"10h-old '...Z' stamp -> stale (age {zs.get('age_hours')}h)", f"10h-old '...Z' stamp: {zs}")
        check(not zf.get("is_stale") and abs((zf.get("age_hours") or 99) - 1) <= TOL_H,
              f"1h-old '...Z' stamp -> live (age {zf.get('age_hours')}h)", f"1h-old '...Z' stamp: {zf}")

        # (5) missing LastUpdated column -> existing contract: unknown age, NOT stale, NOT suppressed
        nocol = load_real(write_odds_dir(eastern_stamp(10), drop_lastupdated=True))
        nmeta = app.get_lines_refresh_meta(nocol)
        check("LastUpdated" not in nocol.columns and not nocol.empty,
              "no-LastUpdated file loads (no column invented)", f"no-LastUpdated file: cols={list(nocol.columns)}")
        check(nmeta.get("is_stale") is False and nmeta.get("age_hours") is None
              and nmeta.get("last_updated") == "Unknown" and nmeta.get("status") == "live",
              "no-LastUpdated -> existing contract: age unknown, is_stale=False, status 'live', 'Unknown'",
              f"no-LastUpdated contract changed: {nmeta}")
        check(bool(app.build_game_market_lookup(nocol)) and football_board_odds_len(nocol) == len(nocol),
              "no-LastUpdated -> existing contract: NOT suppressed (lookup + football odds pass through)",
              "no-LastUpdated -> suppressed (existing contract says unknown age is not suppressed)")

        # (6) tz convention on fixed stamps
        cases = [
            ("2026-11-01 08:29", datetime(2026, 11, 1, 13, 29, tzinfo=timezone.utc)),   # EST (after fall-back)
            ("2026-07-28 09:59", datetime(2026, 7, 28, 13, 59, tzinfo=timezone.utc)),   # EDT
            ("2026-10-26T12:00:00Z", datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)),
            ("2026-10-26T08:00:00-04:00", datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)),
            ("2026-11-01 01:30", datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)),    # ambiguous -> fold 0 (EDT)
            ("not-a-date", None), ("", None), ("nan", None), (None, None),
        ]
        for raw, want in cases:
            got = parse_feed_timestamp_utc(raw)
            check(got == want, f"parse_feed_timestamp_utc({raw!r}) -> {want}",
                  f"parse_feed_timestamp_utc({raw!r}) -> {got}, expected {want}")

        # (7) MUTATION: formatter drops LastUpdated again -> the stale check must FAIL
        def _mutant(df):
            return real_formatter(df).drop(columns=["LastUpdated"], errors="ignore")
        _mutant.__name__ = "_format_game_market_odds_mutant"
        app._format_game_market_odds = _mutant
        try:
            mprob, _ = stale_file_suppressed("mutant")
        finally:
            app._format_game_market_odds = real_formatter
        check(bool(mprob),
              f"mutation (formatter drops LastUpdated) is DETECTED: {len(mprob)} stale-check failure(s)",
              "mutation (formatter drops LastUpdated) NOT detected -- QC does not exercise the real path")
    finally:
        app._format_game_market_odds = real_formatter
        for d in _tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    print()
    print(f"{_results['ok']} ok, {_results['fail']} FAIL")
    return 1 if _results["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
