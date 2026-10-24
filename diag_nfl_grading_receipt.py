"""
Read-only content receipt for data/tracking/NFL_AllPropResults.csv and its Wave consumer
(incident 2026-10-24 Item-5 reconciliation). Resolves the contradiction between the old closure doc
("stale Wk18") and recent prod receipts ("fresh, 2026, Week 6, ~16,753 rows") with EVIDENCE.

LITERAL read-only (audited + self-proving):
  - No network/provider request. `build_nfl_prop_streaks` + `_load_nfl_all_prop_results`/`_load_cached_csv`
    only read local CSVs and an IN-MEMORY cache (no disk writes; verified in app.py 48017-48177 / 2305+).
  - `append_qc_run_log` is monkeypatched to a no-op here, so even an unexpected caller writes no QC log.
  - Every relevant artifact (the source CSV, the QC run log, and any NFL wave/prop cache/snapshot files)
    is sha256+mtime+size fingerprinted BEFORE and AFTER; the run FAILS (exit 4) if anything changed.
  - Never a global max(Week): current season comes from `_nfl_expected_completed_week`; max graded week is
    taken WITHIN that current season only.

Exit codes: 0 coherent + nothing changed; 2 source absent/unreadable; 3 malformed / internally
contradictory data; 4 the diagnostic itself mutated an artifact (should never happen).

Run on the box with the data (prod/owner), venv python. No fetch, no paid call, no writes.
"""
from __future__ import annotations

import glob
import hashlib
import os
from datetime import datetime, timezone

import pandas as pd

import app

# Belt-and-suspenders: no QC-log write can happen through this diagnostic.
app.append_qc_run_log = lambda *a, **k: None

PATH = app.DATA_DIR / "tracking" / "NFL_AllPropResults.csv"
_DATE_COLS = ("GameDate", "Date", "CommenceDate", "GameDateET", "Kickoff")
_STATUS_COLS = ("OutcomeState", "Result", "Grade", "Outcome", "Status")
_IDENTITY = ("Season", "Week", "Player", "Stat", "Direction", "Line")


def _et(ts_epoch: float) -> str:
    try:
        iso = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat()
        from services.timeutils import to_eastern_datetime_str as _to
        return (_to(iso) + " ET") or iso
    except Exception:
        return str(ts_epoch)


def _relevant_artifacts() -> list[str]:
    """The source + any file the Wave path could conceivably touch (QC log, nfl/wave/prop caches)."""
    files = {str(PATH), str(app.DATA_DIR / "tracking" / "QC_Run_Log.csv")}
    for base in (app.DATA_DIR / "tracking", app.DATA_DIR / "cache"):
        for pat in ("*nfl*wave*", "*nfl*prop*", "*NFL_AllPropResults*", "*hot*hand*", "*streak*"):
            files.update(glob.glob(str(base / pat)))
    return sorted(files)


def _fingerprint(paths: list[str]) -> dict:
    fp = {}
    for p in paths:
        try:
            st = os.stat(p)
            with open(p, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()[:16]
            fp[p] = (h, st.st_mtime_ns, st.st_size)
        except OSError:
            fp[p] = None  # absent (recorded so a NEW file is also detected as a change)
    return fp


def main() -> int:
    print("=" * 78)
    print("NFL_AllPropResults.csv - READ-ONLY CONTENT RECEIPT (Item-5 reconciliation)")
    print("=" * 78)

    artifacts = _relevant_artifacts()
    fp_before = _fingerprint(artifacts)

    print(f"resolved_path   : {PATH}")
    if not PATH.exists():
        print("STATUS          : FILE ABSENT -> surface fails closed (unavailable). Keep the Wave "
              "unavailable; this is the 'genuinely missing' branch.")
        return 2
    st = PATH.stat()
    age_h = round((datetime.now().timestamp() - st.st_mtime) / 3600, 2)
    print(f"mtime           : {_et(st.st_mtime)}  ({age_h}h ago)")
    print(f"size_bytes      : {st.st_size}")

    try:
        df = pd.read_csv(PATH, low_memory=False)
    except Exception as exc:
        print(f"STATUS          : UNREADABLE ({type(exc).__name__}: {exc}) -> fails closed.")
        return 2
    print(f"total_rows      : {len(df)}")
    print(f"columns         : {', '.join(map(str, df.columns))}")

    try:
        expected_week, expected_season = app._nfl_expected_completed_week()
    except Exception as exc:
        expected_week, expected_season = None, None
        print(f"[WARN] season resolver error: {exc}")
    print(f"resolver_current_season : {expected_season}")
    print(f"resolver_completed_week : {expected_week}")

    if "Season" in df.columns:
        seasons = pd.to_numeric(df["Season"], errors="coerce").dropna().astype(int)
        print("seasons_present :")
        for s, n in seasons.value_counts().sort_index().items():
            mark = "  <- resolver current" if expected_season and int(s) == int(expected_season) else ""
            print(f"    {int(s)}: {int(n)} rows{mark}")
    else:
        print("seasons_present : (no Season column)")

    cur = df
    if "Season" in df.columns and expected_season:
        cur = df[pd.to_numeric(df["Season"], errors="coerce") == int(expected_season)].copy()
    cur_rows = len(cur)
    print(f"current_season_rows : {cur_rows}")

    cur_max_week = None
    if "Week" in cur.columns and cur_rows:
        wk = pd.to_numeric(cur["Week"], errors="coerce").dropna()
        cur_max_week = int(wk.max()) if not wk.empty else None
        print(f"current_season_max_week : {cur_max_week}  (weeks: {sorted(set(wk.astype(int)))[:25]})")
    else:
        print("current_season_max_week : n/a")

    date_col = next((c for c in _DATE_COLS if c in cur.columns), None)
    if date_col and cur_rows:
        dts = pd.to_datetime(cur[date_col], errors="coerce").dropna()
        print(f"latest_current_game_date : {dts.max() if not dts.empty else 'n/a'} (col {date_col!r})")
    else:
        print(f"latest_current_game_date : n/a (no date col among {_DATE_COLS})")

    rv = pd.to_numeric(cur["ResultValue"], errors="coerce") if "ResultValue" in cur.columns else pd.Series([], dtype=float)
    ident_ok = (cur["Player"].astype(str).str.strip().ne("")) if "Player" in cur.columns else pd.Series([True] * cur_rows)
    graded = int((rv.notna() & ident_ok.reindex(rv.index, fill_value=True)).sum()) if len(rv) else 0
    pending = int((rv.isna() & ident_ok.reindex(rv.index, fill_value=True)).sum()) if len(rv) else 0
    malformed = int((~ident_ok).sum()) if "Player" in cur.columns else 0
    print(f"graded_rows     : {graded}")
    print(f"pending_rows    : {pending}")
    print(f"malformed_rows  : {malformed}")
    status_col = next((c for c in _STATUS_COLS if c in cur.columns), None)
    if status_col:
        print(f"status_col {status_col!r}: {dict(cur[status_col].astype(str).str.strip().value_counts().head(8))}")

    key = [c for c in _IDENTITY if c in cur.columns]
    dups = conflicts = 0
    if key and cur_rows:
        dmask = cur.duplicated(subset=key, keep=False)
        dups = int(dmask.sum())
        if dups and "ResultValue" in cur.columns:
            for _, g in cur[dmask].groupby(key, dropna=False):
                if pd.to_numeric(g["ResultValue"], errors="coerce").dropna().nunique() > 1:
                    conflicts += 1
    print(f"identity_key    : {key}")
    print(f"duplicate_rows  : {dups}")
    print(f"conflicting_ids : {conflicts}")

    try:
        meta = app.build_nfl_prop_streaks(limit=60)
    except Exception as exc:
        print(f"[WARN] build_nfl_prop_streaks error: {exc}")
        meta = {}
    board_available = not meta.get("unavailable", False)
    print("-" * 78)
    print(f"board_through_season : {meta.get('through_season')}")
    print(f"board_through_week   : {meta.get('through_week')}")
    print(f"board_through_label  : {meta.get('through_label')!r}")
    print(f"board_expected       : season={meta.get('expected_season')} week={meta.get('expected_week')}")
    print(f"board_available      : {board_available}  (reason={meta.get('unavailable_reason')!r}; "
          f"rows={len(meta.get('rows') or [])}; pending={meta.get('pending')}; stale_season={meta.get('stale_season')})")
    print(f"board_source_fingerprint : source_updated={meta.get('source_updated')!r}; graded_mtime={_et(st.st_mtime)}")

    # ---- read-only proof: nothing changed ----
    fp_after = _fingerprint(artifacts)
    changed = sorted(p for p in artifacts if fp_before.get(p) != fp_after.get(p))
    print("-" * 78)
    print(f"READ-ONLY PROOF : {len(artifacts)} artifact(s) fingerprinted (sha256+mtime_ns+size); "
          f"{'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")

    # ---- contradiction / malformity gate ----
    problems = []
    if changed:
        problems.append(f"diagnostic mutated artifact(s): {changed}")
    if expected_season is None:
        problems.append("season resolver returned None (cannot characterize current season)")
    if malformed > 0:
        problems.append(f"{malformed} malformed rows (blank identity) in current season")
    if conflicts > 0:
        problems.append(f"{conflicts} conflicting identities (same key, differing ResultValue)")
    # internal contradiction: the board and the raw current-season data must agree on availability
    if expected_season is not None:
        raw_has_current = cur_rows > 0 and graded > 0
        if board_available != raw_has_current:
            problems.append(f"board_available={board_available} but current-season graded present={raw_has_current} "
                            "(consumer disagrees with the raw data)")
    print("-" * 78)
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        if changed:
            return 4
        return 3
    print("[OK] coherent receipt; diagnostic changed nothing.")
    print("RECONCILE: resolver_current_season=2026 + current_season_max_week≈6 + graded_rows in the "
          "thousands + board_available=True  => 'stale Wk18' is OBSOLETE (correct the doc, proceed to "
          "Audit #1). Prior-season-only / board unavailable => keep unavailable; that becomes the P0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
