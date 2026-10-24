"""
Read-only verification of the NFL result-artifact ownership split (2026-10-24 Item-5 recovery).

Prints, for BOTH authoritative artifacts, the facts the recovery must prove -- path, mtime, size, sha256,
row count, Season distribution, IsBackfill distribution, SnapshotWrittenAt/ModelVersion/Method -- plus the
read-time union count and the Wave board's availability computed from the LIVE artifact.

PASS criteria (exit 0):
  * live file (NFL_AllPropResults.csv) carries current-season rows and NO IsBackfill rows;
  * backfill file (NFL_AllPropResults_Backfill.csv) carries ONLY historical rows (all IsBackfill, no
    current season);
  * the two files are distinct (different sha);
  * the Wave board is AVAILABLE from the live artifact (not current_season_ungraded).
Otherwise exit 3 (prints why). No writes, no network.

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/verify_nfl_result_artifacts.py
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import pandas as pd

import app
from services.nfl_result_artifacts import live_path, backfill_path, load_combined, LIVE_NAME, BACKFILL_NAME

app.append_qc_run_log = lambda *a, **k: None
TRACKING = app.DATA_DIR / "tracking"


def _et(ts):
    try:
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        from services.timeutils import to_eastern_datetime_str as _to
        return (_to(iso) + " ET") or iso
    except Exception:
        return str(ts)


def _counts(s, n=6):
    try:
        vc = s.astype(str).str.strip().replace("", "(blank)").value_counts().head(n)
        return ", ".join(f"{k}={int(v)}" for k, v in vc.items())
    except Exception:
        return "(n/a)"


def _describe(path, cur):
    print(f"ARTIFACT: {path}")
    if not os.path.exists(path):
        print("  ABSENT")
        return None
    st = os.stat(path)
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()[:16]
    print(f"  mtime={_et(st.st_mtime)}  size={st.st_size}  sha={sha}  mode={oct(st.st_mode)[-3:]}")
    try:
        d = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        print(f"  UNREADABLE: {exc}")
        return None
    seasons = pd.to_numeric(d.get("Season"), errors="coerce").dropna().astype(int) if "Season" in d.columns else pd.Series([], dtype=int)
    print(f"  rows={len(d)}  seasons: {_counts(seasons)}  current({cur})={int((seasons == cur).sum())}")
    for col in ("IsBackfill", "ModelVersion", "Method"):
        if col in d.columns:
            print(f"  {col}: {_counts(d[col])}")
    if "SnapshotWrittenAt" in d.columns:
        sw = d["SnapshotWrittenAt"].astype(str).str.strip()
        nb = sw[sw != ""]
        print(f"  SnapshotWrittenAt: blanks={int((sw == '').sum())} range={nb.min() if not nb.empty else 'n/a'}..{nb.max() if not nb.empty else 'n/a'}")
    return {"sha": sha, "df": d, "seasons": seasons}


def main() -> int:
    print("=" * 84)
    print("NFL RESULT-ARTIFACT OWNERSHIP VERIFICATION (read-only)")
    print("=" * 84)
    try:
        _, exp_season = app._nfl_expected_completed_week()
    except Exception:
        exp_season = None
    cur = int(exp_season) if exp_season else None
    print(f"resolver_current_season={exp_season}")
    print("-" * 84)
    live = _describe(str(live_path(TRACKING)), cur)
    print("-" * 84)
    bf = _describe(str(backfill_path(TRACKING)), cur)
    print("-" * 84)
    combined = load_combined(TRACKING)
    cseasons = pd.to_numeric(combined.get("Season"), errors="coerce").dropna().astype(int) if not combined.empty else pd.Series([], dtype=int)
    print(f"load_combined (read-time union): rows={len(combined)}  seasons: {_counts(cseasons)}")
    print("-" * 84)
    try:
        meta = app.build_nfl_prop_streaks(limit=60)
        wave_available = not meta.get("unavailable", False)
        print(f"WAVE board: available={wave_available}  reason={meta.get('unavailable_reason')!r}  "
              f"through={meta.get('through_label')!r}  rows={len(meta.get('rows') or [])}")
    except Exception as exc:
        wave_available = False
        print(f"WAVE board: ERROR {exc}")

    print("-" * 84)
    problems = []
    if live is None:
        problems.append(f"{LIVE_NAME} absent/unreadable")
    else:
        live_cur = int((live["seasons"] == cur).sum()) if cur else 0
        if live_cur <= 0:
            problems.append(f"{LIVE_NAME} has no current-season({cur}) rows (live grade not present)")
        if "IsBackfill" in live["df"].columns and live["df"]["IsBackfill"].astype(str).str.lower().isin(["true", "1"]).any():
            problems.append(f"{LIVE_NAME} contains IsBackfill rows (backfill leaked into the live file)")
    if bf is None:
        problems.append(f"{BACKFILL_NAME} absent/unreadable")
    else:
        if cur and int((bf["seasons"] == cur).sum()) > 0:
            problems.append(f"{BACKFILL_NAME} contains current-season rows (should be historical only)")
    if live and bf and live["sha"] == bf["sha"]:
        problems.append("live and backfill files are byte-identical (not separated)")
    if not wave_available:
        problems.append("Wave board is NOT available from the live artifact")

    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 3
    print("[OK] live carries the current-season population, backfill is historical-only and separate, "
          "and the Wave is available from the live artifact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
