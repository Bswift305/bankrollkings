#!/usr/bin/env python3
"""Refresh the NFL games source (data/historical/nflverse_games.parquet) that feeds the Active ATS
Wave (build_nfl_ats_wave, docs/ats_wave_contract.md). nflverse publishes a single rolling games file
(schedule + results + recorded spread), rewritten as each week finalizes; nothing on prod was
refreshing our copy, so the ATS wave correctly fails closed. This closes that hole -- reversibly.

Source of record (CC BY 4.0, nflverse): Lee Sharpe's nfldata `games.csv`.
    https://github.com/nflverse/nfldata/raw/master/data/games.csv
Only this documented source is used. See docs/nfl_games_refresh_runbook.md.

Safety model:
  * download -> temp file -> VALIDATE -> atomic os.replace of the live parquet. A failed download
    or validation leaves the last valid parquet untouched.
  * a metadata sidecar (<parquet>.meta.json) records the BK fetch time (UTC), upstream URL +
    ETag/Last-Modified, content checksum, current-season row/completed counts and the schema version.
    FRESHNESS is read from the sidecar's successful-fetch time, never filesystem mtime alone.
  * --check-only / --gate separate OPERABILITY failures (permission/read -> nonzero, named) from
    "behind"; an unreadable file is never reported as "no current games".

Idempotent. Run as the application service user (ubuntu on prod). Does NOT touch SU or O/U.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
LIVE_PATH = BASE_DIR / "data" / "historical" / "nflverse_games.parquet"
SOURCE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
SOURCE_LICENSE = "CC BY 4.0 (nflverse / nfldata)"
SCHEMA_VERSION = 1
FRESH_BUDGET_H = 48

REQUIRED_COLS = ["game_id", "season", "week", "gameday", "gametime",
                 "home_team", "away_team", "home_score", "away_score", "result", "spread_line"]

# Week-1 Thursday (ET) per season -- keep in sync with NFL_SEASON_WEEK1_THURSDAY (app.py) and
# NFL_SEASON_WEEK1 (fetch_nfl_player_week.py). Add each new season's opener.
NFL_SEASON_WEEK1 = {2025: date(2025, 9, 4), 2026: date(2026, 9, 10)}


def sidecar_path(live_path=LIVE_PATH) -> Path:
    return Path(str(live_path) + ".meta.json")


def _today_et() -> date:
    try:
        from services.timeutils import to_eastern_date_str
        s = to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        return datetime.now().date()


def current_nfl_season(today: date | None = None) -> int:
    """Explicit active season: NFL season N spans Sep N -> Feb N+1, so Jan/Feb is the prior year."""
    today = today or _today_et()
    return today.year if today.month >= 3 else today.year - 1


def _in_season(today: date | None = None) -> bool:
    """In-season-ish window for the self-gating timer: Aug through early Feb (schedule publishes in
    spring but refreshing matters once games approach). Off-window --gate runs no-op cleanly."""
    today = today or _today_et()
    return today.month in (8, 9, 10, 11, 12, 1, 2)


# --------------------------------------------------------------------------- validation
def _coerce_num(series):
    return pd.to_numeric(series, errors="coerce")


def validate_frame(df, current_season, prev_completed=None, allow_regression=False):
    """Pure validation. Returns (ok: bool, errors: list[str], stats: dict). Never mutates `df`."""
    errors, stats = [], {}
    if df is None or len(df) == 0:
        return False, ["empty frame"], stats
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        return False, [f"missing required columns: {missing}"], stats

    gid = df["game_id"].astype(str).str.strip()
    if (gid == "").any() or gid.isin(["nan", "none", "None"]).any():
        errors.append("blank game_id present")
    if gid.duplicated().any():
        errors.append(f"{int(gid.duplicated().sum())} duplicate game_id rows")

    season = _coerce_num(df["season"])
    cur = df[season == current_season]
    stats["current_season"] = current_season
    stats["current_season_rows"] = int(len(cur))
    if cur.empty:
        errors.append(f"explicit current season {current_season} not present")
        return False, errors, stats

    teams = pd.concat([cur["home_team"].astype(str).str.strip(),
                       cur["away_team"].astype(str).str.strip()]).unique()
    teams = [t for t in teams if t and t.lower() not in ("nan", "none")]
    stats["distinct_teams"] = len(teams)
    if not (32 <= len(teams) <= 36):
        errors.append(f"implausible team universe: {len(teams)} distinct (want 32-36)")

    cur_week = _coerce_num(cur["week"])
    stats["max_week"] = int(cur_week.max()) if cur_week.notna().any() else 0
    if stats["max_week"] < 18:
        errors.append(f"future schedule not retained: max week {stats['max_week']} < 18")

    result = _coerce_num(cur["result"])
    completed_mask = result.notna()
    stats["completed_games"] = int(completed_mask.sum())
    hs, as_ = _coerce_num(cur["home_score"]), _coerce_num(cur["away_score"])
    bad_completed = completed_mask & (hs.isna() | as_.isna())
    if bad_completed.any():
        errors.append(f"{int(bad_completed.sum())} completed rows missing scores")

    # spread: numeric OR explicitly missing (blank/NA). A present-but-nonnumeric value is malformed.
    raw_sp = df["spread_line"]
    sp_num = _coerce_num(raw_sp)
    raw_present = raw_sp.notna() & (raw_sp.astype(str).str.strip() != "")
    malformed_sp = raw_present & sp_num.isna()
    if malformed_sp.any():
        errors.append(f"{int(malformed_sp.sum())} malformed (non-numeric) spread_line values")

    if prev_completed is not None and stats["completed_games"] < prev_completed and not allow_regression:
        errors.append(f"completed-game count regressed {prev_completed} -> {stats['completed_games']} "
                      f"(use --allow-completed-regression to override)")

    stats["schema_version"] = SCHEMA_VERSION
    return (not errors), errors, stats


# --------------------------------------------------------------------------- sidecar
def read_sidecar(side=None):
    side = side or sidecar_path()
    try:
        return json.loads(Path(side).read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_sidecar(meta, side=None):
    side = Path(side or sidecar_path())
    fd, tmp = tempfile.mkstemp(prefix="nflgames_meta_", suffix=".json", dir=str(side.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)
        os.replace(tmp, side)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def sidecar_fetch_epoch(side=None):
    """Successful-fetch time (epoch seconds, UTC) from the sidecar -- the authoritative freshness
    basis. None when absent/unparseable (caller may fall back to mtime, but mtime alone is not
    authoritative)."""
    ft = (read_sidecar(side) or {}).get("fetch_time_utc")
    if not ft:
        return None
    try:
        return datetime.strptime(str(ft).replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


# --------------------------------------------------------------------------- io
def write_atomic_parquet(df, live_path=LIVE_PATH):
    """Write to a temp file in the same dir, then atomically replace. Raises on IO/permission error
    (so the caller reports an OPERABILITY failure); the live file is only ever swapped in whole."""
    live = Path(live_path)
    live.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="nflgames_", suffix=".parquet", dir=str(live.parent))
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, live)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _do_download(url, prev_etag=None, prev_last_modified=None, timeout=60):
    """Return (status, content_bytes|None, etag, last_modified). status: 'ok' | 'unchanged'.
    Raises urllib errors on network failure (the caller turns that into a nonzero exit, live
    untouched)."""
    req = urllib.request.Request(url, headers={"User-Agent": "BankrollKings-games-refresh"})
    if prev_etag:
        req.add_header("If-None-Match", prev_etag)
    if prev_last_modified:
        req.add_header("If-Modified-Since", prev_last_modified)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "ok", resp.read(), resp.headers.get("ETag"), resp.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return "unchanged", None, prev_etag, prev_last_modified
        raise


def inspect_live(live_path=LIVE_PATH, side=None, reader=None):
    """Operability-aware inspection WITHOUT turning an error into data. Returns (status, info):
      'missing'    -> file absent; info = None.
      'ok'         -> readable; info = (rows, stats-ish dict with completed_games/current_season).
      'unreadable' -> exists but cannot be read (permission/corruption); info = the exception.
    `reader` is injectable for tests."""
    live = Path(live_path)
    if not live.exists():
        return "missing", None
    reader = reader or (lambda p: pd.read_parquet(p))
    try:
        df = reader(live)
    except Exception as exc:
        return "unreadable", exc
    season = current_nfl_season()
    cur = df[_coerce_num(df.get("season")) == season]
    return "ok", {"rows": int(len(df)), "current_season": season,
                  "current_season_rows": int(len(cur)),
                  "completed_games": int(_coerce_num(cur.get("result")).notna().sum()) if len(cur) else 0}


# --------------------------------------------------------------------------- check-only
def check_only_result(live_path=LIVE_PATH, side=None, budget_h=FRESH_BUDGET_H, reader=None, now_epoch=None):
    """(exit_code, message). 0 = present + fresh; 2 = missing/stale (behind); 3 = unreadable
    (operability failure). An unreadable live file is NEVER reported as 'no current games'."""
    import time as _t
    side = side or sidecar_path(live_path)
    status, info = inspect_live(live_path, side, reader=reader)
    if status == "unreadable":
        return 3, (f"OPERABILITY: live games parquet exists but cannot be read "
                   f"({type(info).__name__}). Run as the owner (e.g. `sudo -u ubuntu ...`); "
                   f"this is NOT missing data.")
    if status == "missing":
        return 2, "live games parquet is absent (no refresh has succeeded yet)"
    fetch_epoch = sidecar_fetch_epoch(side)
    basis = "sidecar fetch time"
    if fetch_epoch is None:
        try:
            fetch_epoch = os.path.getmtime(live_path)
            basis = "mtime (no sidecar)"
        except OSError as exc:
            return 3, f"OPERABILITY: cannot stat live parquet ({type(exc).__name__})"
    age_h = ((now_epoch or _t.time()) - fetch_epoch) / 3600.0
    cur_rows = info.get("current_season_rows", 0)
    done = info.get("completed_games", 0)
    if cur_rows == 0:
        return 2, f"no rows for current season {info.get('current_season')} yet"
    if age_h > budget_h:
        return 2, (f"source stale: {age_h:.1f}h old > {budget_h}h budget ({basis}); "
                   f"season {info['current_season']} rows {cur_rows}, completed {done}")
    return 0, (f"fresh: {age_h:.1f}h old <= {budget_h}h ({basis}); season {info['current_season']} "
               f"rows {cur_rows}, completed {done}")


# --------------------------------------------------------------------------- main
def _load_new_frame(content_or_source):
    """Parse the downloaded CSV bytes, or read a local --source file (.csv or .parquet) for testing."""
    if isinstance(content_or_source, (bytes, bytearray)):
        return pd.read_csv(io.BytesIO(content_or_source), low_memory=False)
    p = str(content_or_source)
    return pd.read_parquet(p) if p.endswith(".parquet") else pd.read_csv(p, low_memory=False)


def refresh(url=SOURCE_URL, source=None, live_path=LIVE_PATH, allow_regression=False,
            download_fn=_do_download, now_utc=None):
    """Core refresh (importable + testable). Returns (exit_code, message, meta|None).
    Exit codes: 0 ok/unchanged; 3 operability (write/IO); 4 validation; 5 download error."""
    side = sidecar_path(live_path)
    prev = read_sidecar(side)
    now_utc = now_utc or datetime.now(timezone.utc)
    content = None
    etag = prev.get("upstream_etag")
    last_mod = prev.get("upstream_last_modified")

    if source is not None:
        try:
            raw = Path(source).read_bytes()
            new_df = _load_new_frame(source)
            checksum = hashlib.sha256(raw).hexdigest()
        except Exception as exc:
            return 5, f"could not read --source {source}: {type(exc).__name__}: {exc}", None
        status = "ok"
    else:
        try:
            status, content, etag, last_mod = download_fn(url, prev.get("upstream_etag"),
                                                          prev.get("upstream_last_modified"))
        except Exception as exc:
            return 5, f"download failed ({type(exc).__name__}: {exc}); live file untouched", None
        if status == "unchanged":
            # Upstream confirmed current: don't rewrite the parquet, but record that we checked now
            # so freshness reflects the successful contact.
            meta = dict(prev)
            meta["fetch_time_utc"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            meta["upstream_etag"], meta["upstream_last_modified"] = etag, last_mod
            try:
                write_sidecar(meta, side)
            except Exception as exc:
                return 3, f"OPERABILITY: could not write sidecar ({type(exc).__name__})", None
            return 0, "upstream unchanged (304); sidecar fetch time refreshed, parquet untouched", meta
        try:
            new_df = _load_new_frame(content)
            checksum = hashlib.sha256(content).hexdigest()
        except Exception as exc:
            return 4, f"downloaded content did not parse as CSV ({type(exc).__name__}); live untouched", None

    season = current_nfl_season()
    ok, errors, stats = validate_frame(new_df, season, prev_completed=prev.get("completed_games"),
                                       allow_regression=allow_regression)
    if not ok:
        return 4, "validation failed; live file untouched: " + "; ".join(errors), None

    try:
        write_atomic_parquet(new_df, live_path)
    except Exception as exc:
        return 3, f"OPERABILITY: atomic write failed ({type(exc).__name__}); live file untouched", None

    meta = {"schema_version": SCHEMA_VERSION,
            "fetch_time_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "upstream_url": url if source is None else f"(local source: {source})",
            "upstream_etag": etag, "upstream_last_modified": last_mod,
            "content_sha256": checksum, "source_license": SOURCE_LICENSE,
            "current_season": stats.get("current_season"),
            "current_season_rows": stats.get("current_season_rows"),
            "completed_games": stats.get("completed_games"),
            "distinct_teams": stats.get("distinct_teams"), "max_week": stats.get("max_week")}
    try:
        write_sidecar(meta, side)
    except Exception as exc:
        return 3, f"OPERABILITY: parquet replaced but sidecar write failed ({type(exc).__name__})", meta
    return 0, (f"refreshed: season {meta['current_season']} rows {meta['current_season_rows']}, "
               f"completed {meta['completed_games']}, teams {meta['distinct_teams']}"), meta


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the NFL games source (nflverse games.csv).")
    ap.add_argument("--url", default=SOURCE_URL, help="Documented nflverse games.csv URL.")
    ap.add_argument("--source", default=None, help="Local .csv/.parquet instead of downloading (tests).")
    ap.add_argument("--allow-completed-regression", action="store_true",
                    help="Operator override: permit the completed-game count to drop.")
    ap.add_argument("--gate", action="store_true",
                    help="Self-gate to the NFL season window; off-season this no-ops (exit 0).")
    ap.add_argument("--check-only", action="store_true",
                    help="No download: report present+fresh (0), missing/stale (2), or unreadable (3).")
    args = ap.parse_args()

    if args.check_only:
        code, msg = check_only_result()
        print(f"[fetch_nfl_games] check: {msg}")
        return code
    if args.gate and not _in_season():
        print("[fetch_nfl_games] off-season window; nothing to do")
        return 0

    code, msg, _meta = refresh(url=args.url, source=args.source,
                               allow_regression=args.allow_completed_regression)
    print(f"[fetch_nfl_games] {msg}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
