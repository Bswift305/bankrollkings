#!/usr/bin/env python3
"""Publish the CFBD college-football slate + CFBD provider lines as CFBD-OWNED artifacts (F7).

CFBD is a CONTEXT source, not a book. It is the sole writer of exactly these artifacts:

  data/schedules/NCAAF_CFBD_Schedule.csv   every upcoming FBS game in the window (lined or not)
  data/odds/NCAAF_CFBD_Lines.csv           one row per (CFBD game, CFBD line provider) -- spread/total
                                           AS THE PROVIDER POSTED THEM. No averaging on disk.
  data/tracking/NCAAF_CFBD_publish.json    generation manifest (written LAST): sha256 + row counts of
                                           both CSVs, window, weeks fetched, per-week request outcome

It NEVER writes the Odds-API-owned files (data/odds/NCAAF_Odds.csv, its data/schedules mirror, or
data/schedules/NCAAF_Schedule.csv); fetch_game_lines.py is their single writer. Before F7 this script
overwrote them with a "CFBD consensus" book and a hard-coded -110 for every spread/total price -- a
price no book offered. There are NO price columns here at all (no SpreadOdds / OverOdds / UnderOdds /
AwayML / HomeML): CFBD gives no executable price, so the honest value is "unavailable", never -110.
Readers show these numbers only on context surfaces, labeled `CFBD consensus — no book price`
(app.load_ncaaf_context_slate); market/play surfaces never read this artifact.

Fail closed: ANY request failure (HTTP error, including a 429 quota/rate-limit) publishes NOTHING,
leaves every existing artifact untouched, prints the reason (429 text stays detectable by
refresh_cfb_data._is_provider_quota_exhausted) and exits non-zero. A clean fetch with zero in-window
FBS games also publishes nothing (no header-only file) and exits 0.

    source .env.local            # needs CFBD_API_KEY
    python fetch_ncaaf_slate_cfbd.py --year 2026 --days 12
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-4))  # fallback: fixed EDT offset

ROOT = pathlib.Path(__file__).resolve().parent
API = "https://api.collegefootballdata.com"
FBS = {"Big Ten", "ACC", "SEC", "Big 12", "Sun Belt", "American Athletic", "American",
       "Mid-American", "Mountain West", "Conference USA", "FBS Independents", "Pac-12"}

SOURCE = "CFBD"
# Contract. Deliberately NO price columns -- see module docstring.
SCHEDULE_COLS = ["Source", "ProviderName", "CfbdGameId", "Date", "Time", "StartDateUTC",
                 "Away", "Home", "AwayConference", "HomeConference", "FetchedAtUTC", "PublishRunId"]
LINES_COLS = ["Source", "ProviderName", "CfbdGameId", "Date", "Time", "StartDateUTC",
              "Away", "Home", "Spread", "Total", "FetchedAtUTC", "PublishRunId"]
FORBIDDEN_PRICE_COLS = ("SpreadOdds", "OverOdds", "UnderOdds", "AwayML", "HomeML", "Book")


class CfbdFetchError(Exception):
    """A CFBD request failed. `quota` is True for an HTTP 429 (quota / rate limit)."""

    def __init__(self, msg, quota=False):
        super().__init__(msg)
        self.quota = quota


def paths(root=None):
    root = pathlib.Path(root or ROOT)
    return {
        "schedule": root / "data" / "schedules" / "NCAAF_CFBD_Schedule.csv",
        "lines": root / "data" / "odds" / "NCAAF_CFBD_Lines.csv",
        "manifest": root / "data" / "tracking" / "NCAAF_CFBD_publish.json",
    }


def _key():
    k = os.environ.get("CFBD_API_KEY")
    if k:
        return k.strip()
    for name in (".env.local", ".env"):   # dev keeps it in .env.local, prod in .env
        envf = ROOT / name
        try:
            if envf.exists():
                for line in envf.read_text().splitlines():
                    if line.strip().startswith("CFBD_API_KEY"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue   # e.g. .env readable only by the service user -> rely on env instead
    raise SystemExit("No CFBD_API_KEY in environment (set it, or run as the service user that can read .env)")


def _get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    return json.load(urllib.request.urlopen(req, timeout=45))


def _request(getter, path, key):
    """One CFBD request. Every failure becomes a CfbdFetchError (never swallowed)."""
    try:
        return getter(f"{API}{path}", key)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise CfbdFetchError(f"CFBD HTTP 429 Too Many Requests (quota / rate limit exceeded) on {path}",
                                 quota=True) from exc
        raise CfbdFetchError(f"CFBD HTTP {exc.code} on {path}") from exc
    except Exception as exc:  # noqa: BLE001 -- network/parse failure is a fetch failure, fail closed
        text = str(exc)
        quota = "429" in text or "too many requests" in text.lower()
        prefix = "CFBD HTTP 429 Too Many Requests (quota / rate limit exceeded)" if quota else "CFBD request failed"
        raise CfbdFetchError(f"{prefix} on {path}: {type(exc).__name__}: {text}", quota=quota) from exc


def _et(start_iso):
    """CFBD startDate (UTC ISO) -> (YYYY-MM-DD, 'HH:MM' 24h) in US/Eastern (aligned with the Odds API feed)."""
    if not start_iso:
        return None, ""
    try:
        dt = datetime.fromisoformat(str(start_iso).replace("Z", "+00:00")).astimezone(ET)
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return str(start_iso)[:10], ""


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def fetch_slate(year, days, key, getter=_get, today=None):
    """Return (schedule_df, lines_df, weeks_meta). Raises CfbdFetchError on ANY request failure, so a
    partial fetch can never be published. Lines are one row per (game, provider) as posted."""
    today = today or datetime.now(ET).date()
    horizon = today + timedelta(days=days)
    t0, t1 = today.strftime("%Y-%m-%d"), horizon.strftime("%Y-%m-%d")
    games, lines_by_id, weeks = [], {}, []
    for wk in range(1, 17):
        gs = _request(getter, f"/games?year={year}&week={wk}&seasonType=regular", key)
        wk_dates = [d for d in (_et(g.get("startDate"))[0] for g in (gs or []) if g.get("startDate")) if d]
        if not wk_dates:
            weeks.append({"week": wk, "games": "ok", "lines": "skipped (no dated games)"})
            continue
        if max(wk_dates) < t0:
            weeks.append({"week": wk, "games": "ok", "lines": "skipped (week in the past)"})
            continue
        if min(wk_dates) > t1:
            weeks.append({"week": wk, "games": "ok", "lines": "skipped (past horizon)"})
            break
        games.extend(gs)
        for L in _request(getter, f"/lines?year={year}&week={wk}&seasonType=regular", key) or []:
            lines_by_id[L.get("id")] = L.get("lines") or []
        weeks.append({"week": wk, "games": "ok", "lines": "ok"})

    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sched_rows, line_rows = [], []
    for g in games:
        date, t = _et(g.get("startDate"))
        if not date or not (t0 <= date <= t1):
            continue
        if g.get("homeConference") not in FBS and g.get("awayConference") not in FBS:
            continue
        base = {"Source": SOURCE, "CfbdGameId": g.get("id"), "Date": date, "Time": t,
                "StartDateUTC": g.get("startDate") or "", "Away": g.get("awayTeam"), "Home": g.get("homeTeam"),
                "FetchedAtUTC": fetched}
        sched_rows.append({**base, "ProviderName": SOURCE,
                           "AwayConference": g.get("awayConference") or "",
                           "HomeConference": g.get("homeConference") or ""})
        for p in lines_by_id.get(g.get("id"), []):
            spread, total = _num(p.get("spread")), _num(p.get("overUnder"))
            if spread is None and total is None:
                continue
            line_rows.append({**base, "ProviderName": str(p.get("provider") or "").strip() or "unknown",
                              "Spread": spread, "Total": total})
    sched = pd.DataFrame(sched_rows)
    lines = pd.DataFrame(line_rows)
    if not sched.empty:
        sched = sched.sort_values(["Date", "Home"]).reset_index(drop=True)
    if not lines.empty:
        lines = lines.sort_values(["Date", "Home", "ProviderName"]).reset_index(drop=True)
    return sched, lines, {"window": [t0, t1], "weeks": weeks, "fetched_at_utc": fetched}


def validate(sched, lines):
    """Contract check on the about-to-publish frames. Returns a list of problems ([] = valid)."""
    errs = []
    for name, df, cols in (("schedule", sched, SCHEDULE_COLS), ("lines", lines, LINES_COLS)):
        if df is None:
            errs.append(f"{name}: missing frame")
            continue
        bad = [c for c in FORBIDDEN_PRICE_COLS if c in df.columns]
        if bad:
            errs.append(f"{name}: carries price/book columns {bad} (CFBD has no executable price)")
        if df.empty:
            continue
        miss = [c for c in cols if c not in df.columns and c != "PublishRunId"]   # stamped at publish
        if miss:
            errs.append(f"{name}: missing columns {miss}")
            continue
        if not (df["Source"] == SOURCE).all():
            errs.append(f"{name}: Source must be '{SOURCE}' on every row")
        if pd.to_numeric(df["CfbdGameId"], errors="coerce").isna().any():
            errs.append(f"{name}: non-integer CfbdGameId")
    if sched is not None and sched.empty:
        errs.append("schedule: zero rows (refusing to publish a header-only file)")
    if lines is not None and not lines.empty and {"CfbdGameId", "ProviderName"}.issubset(lines.columns):
        if lines.duplicated(subset=["CfbdGameId", "ProviderName"]).any():
            errs.append("lines: duplicate (CfbdGameId, ProviderName)")
    return errs


def _sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def publish(sched, lines, meta, root=None):
    """Atomic publish of the CFBD-owned artifacts only (validated temp + os.replace each), manifest LAST."""
    from services.atomic_csv import atomic_write_csv
    out = paths(root)
    run_id = uuid.uuid4().hex[:12]
    sched = sched.assign(PublishRunId=run_id)[SCHEDULE_COLS]
    lines = (lines.assign(PublishRunId=run_id)[LINES_COLS] if not lines.empty
             else pd.DataFrame(columns=LINES_COLS))
    atomic_write_csv(sched, out["schedule"], min_rows=1, required_cols=SCHEDULE_COLS)
    atomic_write_csv(lines, out["lines"], required_cols=LINES_COLS)
    manifest = {
        "source": SOURCE, "publish_run_id": run_id, **meta,
        "artifacts": {k: {"path": out[k].relative_to(pathlib.Path(root or ROOT)).as_posix(),
                          "sha256": _sha256(out[k]), "rows": n}
                      for k, n in (("schedule", len(sched)), ("lines", len(lines)))},
    }
    out["manifest"].parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="NCAAF_CFBD_publish.", suffix=".tmp", dir=str(out["manifest"].parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        os.replace(tmp, out["manifest"])
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return manifest


def run(year, days, key=None, getter=_get, root=None, today=None):
    """Fetch -> validate -> publish. Returns a process exit code; prints the outcome."""
    try:
        sched, lines, meta = fetch_slate(year, days, key if key is not None else _key(), getter=getter,
                                         today=today)
    except CfbdFetchError as exc:
        print(f"[FAIL] CFB game slate: {exc}. Published NOTHING; existing CFBD artifacts untouched.",
              file=sys.stderr)
        return 3 if exc.quota else 2
    if sched.empty:
        print(f"window {meta['window'][0]} .. {meta['window'][1]}: 0 FBS games -- nothing published "
              f"(no header-only file); existing CFBD artifacts untouched.")
        return 0
    errs = validate(sched, lines)
    if errs:
        print("[FAIL] CFB game slate validation: " + "; ".join(errs) + ". Published NOTHING.", file=sys.stderr)
        return 2
    m = publish(sched, lines, meta, root=root)
    print(f"window {meta['window'][0]} .. {meta['window'][1]}")
    print(f"  schedule: {m['artifacts']['schedule']['rows']} games -> {m['artifacts']['schedule']['path']}")
    print(f"  lines:    {m['artifacts']['lines']['rows']} provider rows (no prices) -> {m['artifacts']['lines']['path']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--days", type=int, default=10)
    a = ap.parse_args(argv)
    return run(a.year, a.days)


if __name__ == "__main__":
    raise SystemExit(main())
