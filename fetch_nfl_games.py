#!/usr/bin/env python3
"""Refresh the NFL games source that feeds the Active ATS Wave (build_nfl_ats_wave,
docs/ats_wave_contract.md). nflverse publishes a single rolling schedules distribution (schedule +
results + recorded spread); nothing on prod was refreshing our copy, so the ATS wave correctly fails
closed. This closes that hole -- reversibly.

Source of record (CC BY 4.0, nflverse-data): the official `schedules` RELEASE parquet asset, which
`nflreadpy.load_schedules` consumes directly. See docs/nfl_games_refresh_runbook.md + the legal register.
    https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet

Integrity model (one recoverable generation):
  * A published generation is a directory holding BOTH the parquet and its immutable meta.json
    (content fetch time, content sha256 of the stored parquet, upstream ETag/Last-Modified, counts,
    schema version). Generations are built in a temp dir, validated, renamed into place, and then an
    atomic `current.json` pointer swap publishes exactly one generation. A failed download, validation
    or sidecar write leaves the previously published generation active and intact.
  * The pointer carries the generation id, the verified content sha256, and `checked_at_utc` (the last
    time upstream was confirmed current). A 304 refreshes only `checked_at_utc` AFTER re-validating the
    live generation (readable, checksum matches sidecar, current season present) -- a tampered or
    unreadable local file never becomes "fresh" on a 304. `content_fetched_at_utc` (in meta) is kept
    separate; a 304 is not a new content fetch.
  * The consumer verifies the selected parquet's sha256 against the sidecar; missing, corrupt or
    mismatched metadata FAILS CLOSED. There is no filesystem-mtime fallback (use --bootstrap to seed a
    legitimate generation from an existing file).

All times Eastern/UTC explicitly (never host-local). Run as the application service user (ubuntu).
Does NOT touch SU or O/U.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
GAMES_ROOT = BASE_DIR / "data" / "historical" / "nflverse_games"     # generation store
FLAT_MIRROR = BASE_DIR / "data" / "historical" / "nflverse_games.parquet"  # legacy convenience readers
SOURCE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet"
SOURCE_LICENSE = "CC BY 4.0 (nflverse-data)"
SOURCE_ATTRIBUTION = "nflverse (https://github.com/nflverse/nflverse-data), CC BY 4.0"
SCHEMA_VERSION = 2
FRESH_BUDGET_H = 48
KEEP_GENERATIONS = 3
EASTERN = ZoneInfo("America/New_York")

REQUIRED_COLS = ["game_id", "season", "week", "gameday", "gametime",
                 "home_team", "away_team", "home_score", "away_score", "result", "spread_line"]

# Week-1 Thursday (ET) per season -- keep in sync with NFL_SEASON_WEEK1_THURSDAY (app.py) and
# NFL_SEASON_WEEK1 (fetch_nfl_player_week.py). Add each new season's opener.
NFL_SEASON_WEEK1 = {2025: date(2025, 9, 4), 2026: date(2026, 9, 10)}


class GamesSourceError(Exception):
    """The published games generation is missing, unreadable, or fails its checksum/metadata check."""


# --------------------------------------------------------------------------- time (explicit ET)
def _today_et() -> date:
    """Eastern calendar date. Explicit ZoneInfo -- a UTC host must not pick the wrong sports day."""
    return datetime.now(EASTERN).date()


def current_nfl_season(today: date | None = None) -> int:
    """Explicit active season: NFL season N spans Sep N -> Feb N+1, so Jan/Feb is the prior year."""
    today = today or _today_et()
    return today.year if today.month >= 3 else today.year - 1


def _in_season(today: date | None = None) -> bool:
    """In-season window for the self-gating timer: Aug through early Feb. Off-window --gate no-ops."""
    today = today or _today_et()
    return today.month in (8, 9, 10, 11, 12, 1, 2)


def _utc_str(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(s):
    try:
        return datetime.strptime(str(s).replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
    if (completed_mask & (hs.isna() | as_.isna())).any():
        errors.append(f"{int((completed_mask & (hs.isna() | as_.isna())).sum())} completed rows missing scores")

    raw_sp = df["spread_line"]
    raw_present = raw_sp.notna() & (raw_sp.astype(str).str.strip() != "")
    malformed_sp = raw_present & _coerce_num(raw_sp).isna()
    if malformed_sp.any():
        errors.append(f"{int(malformed_sp.sum())} malformed (non-numeric) spread_line values")

    if prev_completed is not None and stats["completed_games"] < prev_completed and not allow_regression:
        errors.append(f"completed-game count regressed {prev_completed} -> {stats['completed_games']} "
                      f"(use --allow-completed-regression to override)")

    stats["schema_version"] = SCHEMA_VERSION
    return (not errors), errors, stats


# --------------------------------------------------------------------------- generation store
def pointer_path(root=GAMES_ROOT) -> Path:
    return Path(root) / "current.json"


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ptr_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def publish_generation(df, content_fetched_at, upstream_url, etag, last_modified, stats,
                       root=GAMES_ROOT, now_utc=None, bootstrap=False):
    """Atomically publish ONE generation: stage parquet + meta in a temp dir, validate the written
    parquet's checksum, rename the dir into place, then swap the current.json pointer. Returns the
    merged meta (pointer + sidecar). Raises on any IO failure (caller reports an operability error);
    the previously published generation stays active until the pointer swap succeeds."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    now_utc = now_utc or datetime.now(timezone.utc)
    staging = Path(tempfile.mkdtemp(prefix=".tmp_gen_", dir=str(root)))
    try:
        pq = staging / "games.parquet"
        df.to_parquet(pq, index=False)
        sha = _sha256_file(pq)
        meta = {"schema_version": SCHEMA_VERSION,
                "content_fetched_at_utc": _utc_str(content_fetched_at),
                "content_sha256": sha, "upstream_url": upstream_url,
                "upstream_etag": etag, "upstream_last_modified": last_modified,
                "source_license": SOURCE_LICENSE, "source_attribution": SOURCE_ATTRIBUTION,
                "bootstrap": bool(bootstrap),
                "current_season": stats.get("current_season"),
                "current_season_rows": stats.get("current_season_rows"),
                "completed_games": stats.get("completed_games"),
                "distinct_teams": stats.get("distinct_teams"), "max_week": stats.get("max_week")}
        (staging / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        gen_name = f"gen_{now_utc.strftime('%Y%m%dT%H%M%SZ')}_{sha[:8]}"
        gen_dir = root / gen_name
        if gen_dir.exists():
            shutil.rmtree(gen_dir, ignore_errors=True)
        os.replace(staging, gen_dir)        # atomic dir publish
        staging = None
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    # Atomic pointer swap = the single moment a new generation becomes live.
    _write_json_atomic(pointer_path(root), {"generation": gen_name, "parquet": "games.parquet",
                                            "content_sha256": sha, "checked_at_utc": _utc_str(now_utc),
                                            "published_at_utc": _utc_str(now_utc)})
    if Path(root) == GAMES_ROOT:           # only the real store mirrors to the legacy flat path
        _mirror_flat(gen_dir / "games.parquet")
    _prune_generations(root)
    return resolve_current(root)


def refresh_checked_at(root=GAMES_ROOT, now_utc=None):
    """Bump ONLY checked_at_utc on the current pointer (a confirmed-current 304). Caller must have
    already validated the live generation. Atomic."""
    ptr = _read_json(pointer_path(root))
    ptr["checked_at_utc"] = _utc_str(now_utc or datetime.now(timezone.utc))
    _write_json_atomic(pointer_path(root), ptr)
    return resolve_current(root)


def resolve_current(root=GAMES_ROOT):
    """Return the live generation as a dict (parquet path + merged meta), VERIFYING the parquet's
    sha256 against both the pointer and the sidecar. Raises GamesSourceError on anything missing,
    unreadable, or mismatched -- the consumer fails closed, never trusting mtime."""
    root = Path(root)
    ptr_file = pointer_path(root)
    if not ptr_file.exists():
        raise GamesSourceError("no current.json pointer (no generation published)")
    try:
        ptr = _read_json(ptr_file)
    except Exception as exc:
        raise GamesSourceError(f"unreadable pointer ({type(exc).__name__})")
    gen = root / str(ptr.get("generation", ""))
    pq = gen / str(ptr.get("parquet", "games.parquet"))
    meta_file = gen / "meta.json"
    if not pq.exists():
        raise GamesSourceError(f"pointer references a missing parquet ({gen.name})")
    if not meta_file.exists():
        raise GamesSourceError(f"missing sidecar metadata ({gen.name}/meta.json)")
    try:
        meta = _read_json(meta_file)
    except Exception as exc:
        raise GamesSourceError(f"corrupt sidecar metadata ({type(exc).__name__})")
    try:
        sha = _sha256_file(pq)
    except Exception as exc:
        raise GamesSourceError(f"unreadable parquet ({type(exc).__name__})")
    if sha != ptr.get("content_sha256") or sha != meta.get("content_sha256"):
        raise GamesSourceError("parquet sha256 does not match the sidecar/pointer (tampered or corrupt)")
    return {"parquet_path": str(pq), "content_sha256": sha,
            "content_fetched_at_utc": meta.get("content_fetched_at_utc"),
            "checked_at_utc": ptr.get("checked_at_utc"), "schema_version": meta.get("schema_version"),
            "current_season": meta.get("current_season"),
            "current_season_rows": meta.get("current_season_rows"),
            "completed_games": meta.get("completed_games"), "bootstrap": meta.get("bootstrap", False),
            "upstream_etag": meta.get("upstream_etag"), "upstream_last_modified": meta.get("upstream_last_modified")}


def verify_current(root=GAMES_ROOT, season=None):
    """resolve_current + confirm the parquet is readable and the current season is actually present.
    Used by the 304 path so a stale/tampered local file never becomes 'fresh'. Raises GamesSourceError."""
    cur = resolve_current(root)
    season = season if season is not None else current_nfl_season()
    try:
        df = pd.read_parquet(cur["parquet_path"])
    except Exception as exc:
        raise GamesSourceError(f"parquet unreadable on verify ({type(exc).__name__})")
    if int((_coerce_num(df.get("season")) == season).sum()) == 0:
        raise GamesSourceError(f"live generation has no rows for current season {season}")
    return cur


def _mirror_flat(gen_parquet):
    """Best-effort legacy mirror: copy the published parquet to the flat path non-ATS readers use.
    Not part of the integrity contract -- the ATS wave reads the generation, not this file."""
    try:
        fd, tmp = tempfile.mkstemp(prefix=".flat_", suffix=".parquet", dir=str(FLAT_MIRROR.parent))
        os.close(fd)
        shutil.copyfile(gen_parquet, tmp)
        os.replace(tmp, FLAT_MIRROR)
    except Exception:
        pass


def _prune_generations(root=GAMES_ROOT, keep=KEEP_GENERATIONS):
    try:
        ptr = _read_json(pointer_path(root)).get("generation")
    except Exception:
        ptr = None
    gens = sorted([p for p in Path(root).glob("gen_*") if p.is_dir()], key=lambda p: p.name)
    for g in gens[:-keep] if len(gens) > keep else []:
        if g.name != ptr:
            shutil.rmtree(g, ignore_errors=True)


# --------------------------------------------------------------------------- freshness / check-only
def freshness(root=GAMES_ROOT, budget_h=FRESH_BUDGET_H, now_epoch=None):
    """(ok, age_hours, checked_at, content_fetched_at, reason). Uses checked_at_utc (last confirmed
    current), NOT mtime. Raises GamesSourceError via resolve_current when the source is unavailable."""
    import time as _t
    cur = resolve_current(root)
    checked = _parse_utc(cur.get("checked_at_utc"))
    if checked is None:
        raise GamesSourceError("sidecar/pointer has no parseable checked_at_utc")
    age_h = ((now_epoch or _t.time()) - checked.timestamp()) / 3600.0
    return (age_h <= budget_h), age_h, cur.get("checked_at_utc"), cur.get("content_fetched_at_utc"), (
        None if age_h <= budget_h else f"source stale: {age_h:.1f}h > {budget_h}h budget")


def check_only_result(root=GAMES_ROOT, budget_h=FRESH_BUDGET_H, now_epoch=None):
    """(exit_code, message). 0 = present + fresh; 2 = missing/stale/behind; 3 = operability failure
    (unreadable/corrupt/checksum-mismatch). An unreadable/invalid store is NEVER 'no current games'."""
    try:
        ok, age_h, checked, fetched, reason = freshness(root, budget_h, now_epoch)
    except GamesSourceError as exc:
        msg = str(exc)
        # a missing pointer is "no refresh yet" (behind, exit 2); corruption/mismatch is operability (3)
        if "no current.json pointer" in msg:
            return 2, "no published generation yet (no refresh has succeeded)"
        return 3, f"OPERABILITY: games source invalid ({msg}). Not 'no games' -- investigate the store."
    if not ok:
        return 2, f"{reason} (checked_at {checked})"
    return 0, f"fresh: {age_h:.1f}h <= {budget_h}h (checked_at {checked}, content_fetched {fetched})"


# --------------------------------------------------------------------------- download + refresh
def _do_download(url, prev_etag=None, prev_last_modified=None, timeout=60):
    """Return (status, content_bytes|None, etag, last_modified). status 'ok' | 'unchanged'. Raises on
    network failure (caller -> nonzero exit, live generation untouched)."""
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


def _load_new_frame(content_or_source):
    """Parse downloaded PARQUET bytes, or read a local --source (.parquet/.csv) for tests."""
    if isinstance(content_or_source, (bytes, bytearray)):
        return pd.read_parquet(io.BytesIO(content_or_source))
    p = str(content_or_source)
    return pd.read_parquet(p) if p.endswith(".parquet") else pd.read_csv(p, low_memory=False)


def refresh(url=SOURCE_URL, source=None, root=GAMES_ROOT, allow_regression=False,
            download_fn=_do_download, now_utc=None):
    """Core refresh. Returns (exit_code, message, meta|None). 0 ok/unchanged; 3 operability (publish);
    4 validation / 304-with-invalid-local; 5 download error. A failure leaves the prior generation live."""
    now_utc = now_utc or datetime.now(timezone.utc)
    season = current_nfl_season()
    try:
        prev = resolve_current(root)
    except GamesSourceError:
        prev = None
    prev_etag = prev.get("upstream_etag") if prev else None
    prev_lastmod = prev.get("upstream_last_modified") if prev else None
    prev_completed = prev.get("completed_games") if prev else None

    if source is not None:
        try:
            df = _load_new_frame(source)
        except Exception as exc:
            return 5, f"could not read --source {source}: {type(exc).__name__}: {exc}", None
        etag = last_mod = None
    else:
        try:
            status, content, etag, last_mod = download_fn(url, prev_etag, prev_lastmod)
        except Exception as exc:
            return 5, f"download failed ({type(exc).__name__}: {exc}); prior generation untouched", None
        if status == "unchanged":
            # 304: validate the LIVE generation before trusting it. Tampered/unreadable -> fail closed.
            try:
                verify_current(root, season)
            except GamesSourceError as exc:
                return 4, f"304 but live generation is invalid ({exc}); not marking fresh", None
            meta = refresh_checked_at(root, now_utc)
            return 0, f"upstream unchanged (304); live generation validated; checked_at refreshed", meta
        try:
            df = _load_new_frame(content)
        except Exception as exc:
            return 4, f"downloaded content did not parse as parquet ({type(exc).__name__}); untouched", None

    ok, errors, stats = validate_frame(df, season, prev_completed=prev_completed, allow_regression=allow_regression)
    if not ok:
        return 4, "validation failed; prior generation untouched: " + "; ".join(errors), None
    try:
        meta = publish_generation(df, now_utc, (url if source is None else f"(local source: {source})"),
                                  etag, last_mod, stats, root=root, now_utc=now_utc)
    except Exception as exc:
        return 3, f"OPERABILITY: publish failed ({type(exc).__name__}); prior generation untouched", None
    return 0, (f"refreshed: season {meta['current_season']} rows {meta['current_season_rows']}, "
               f"completed {meta['completed_games']}"), meta


def bootstrap(existing=FLAT_MIRROR, root=GAMES_ROOT, now_utc=None):
    """One-time: validate an EXISTING flat parquet and publish it as a legitimate first generation +
    sidecar (rather than ever trusting mtime). content_fetched/checked are set from the file's mtime so
    a stale bootstrap stays honestly stale (the board fails closed until a real fetch runs)."""
    existing = Path(existing)
    if not existing.exists():
        return 2, f"no existing file to bootstrap at {existing}", None
    try:
        df = pd.read_parquet(existing)
    except Exception as exc:
        return 3, f"OPERABILITY: cannot read {existing} ({type(exc).__name__})", None
    season = current_nfl_season()
    ok, errors, stats = validate_frame(df, season)
    if not ok:
        return 4, "existing file failed validation; not bootstrapped: " + "; ".join(errors), None
    mtime = datetime.fromtimestamp(os.path.getmtime(existing), timezone.utc)
    meta = publish_generation(df, mtime, f"(bootstrap from {existing})", None, None, stats,
                              root=root, now_utc=now_utc, bootstrap=True)
    # checked_at for a bootstrap = the file's own time (we have NOT confirmed it current upstream).
    ptr = _read_json(pointer_path(root))
    ptr["checked_at_utc"] = _utc_str(mtime)
    _write_json_atomic(pointer_path(root), ptr)
    return 0, f"bootstrapped generation from {existing} (content/checked = file mtime {_utc_str(mtime)})", meta


# --------------------------------------------------------------------------- orchestration (wrapper)
def run_refresh_and_verify(gate=False, url=SOURCE_URL, source=None, allow_regression=False,
                           fetch_fn=None, verify_fn=None, in_season_fn=_in_season):
    """Fetch, then ALWAYS run the ATS synchronization verifier, and PROPAGATE failure: return nonzero
    when the fetch/publication (exit 3/4/5) or the verifier (nonzero) fails. 'behind'/'unchanged'/
    off-season are success. The bash wrapper calls this and exits its code."""
    if gate and not in_season_fn():
        print("[nfl-games] off-season window; nothing to do")
        return 0

    def _default_fetch():
        code, msg, _ = refresh(url=url, source=source, allow_regression=allow_regression)
        print(f"[fetch_nfl_games] {msg}")
        return code

    def _default_verify():
        r = subprocess.run([sys.executable, str(BASE_DIR / "report_nfl_ats_wave_sync.py")])
        return r.returncode

    fetch_rc = (fetch_fn or _default_fetch)()
    verify_rc = (verify_fn or _default_verify)()      # verify even after a fetch failure
    fetch_failed = fetch_rc in (3, 4, 5)
    verify_failed = verify_rc != 0
    if fetch_failed or verify_failed:
        print(f"[nfl-games] FAILURE: fetch_rc={fetch_rc} verify_rc={verify_rc}")
        return fetch_rc if fetch_failed else verify_rc
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the NFL games source (nflverse schedules release).")
    ap.add_argument("--url", default=SOURCE_URL, help="Documented nflverse schedules release parquet.")
    ap.add_argument("--source", default=None, help="Local .parquet/.csv instead of downloading (tests).")
    ap.add_argument("--allow-completed-regression", action="store_true",
                    help="Operator override: permit the completed-game count to drop.")
    ap.add_argument("--gate", action="store_true", help="Self-gate to the NFL season window (no-op off-season).")
    ap.add_argument("--check-only", action="store_true",
                    help="No download: 0 present+fresh, 2 missing/stale, 3 unreadable/corrupt.")
    ap.add_argument("--bootstrap", action="store_true",
                    help="Seed the generation store from the existing flat parquet (no download).")
    ap.add_argument("--run", action="store_true",
                    help="Refresh then verify, propagating failure (for the systemd wrapper).")
    args = ap.parse_args()

    if args.check_only:
        code, msg = check_only_result()
        print(f"[fetch_nfl_games] check: {msg}")
        return code
    if args.bootstrap:
        code, msg, _ = bootstrap()
        print(f"[fetch_nfl_games] bootstrap: {msg}")
        return code
    if args.run:
        return run_refresh_and_verify(gate=args.gate, url=args.url, source=args.source,
                                      allow_regression=args.allow_completed_regression)
    if args.gate and not _in_season():
        print("[fetch_nfl_games] off-season window; nothing to do")
        return 0
    code, msg, _ = refresh(url=args.url, source=args.source,
                           allow_regression=args.allow_completed_regression)
    print(f"[fetch_nfl_games] {msg}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
