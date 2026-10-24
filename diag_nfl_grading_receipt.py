"""
Read-only content receipt for data/tracking/NFL_AllPropResults.csv and its Wave consumer
(incident 2026-10-24 Item-5 reconciliation). Resolves the contradiction between the old closure doc
("stale Wk18") and recent prod receipts ("fresh, 2026, Week 6, 16,753 rows") with EVIDENCE, not a claim.

NEVER uses a global max(Week) across seasons: the current season comes from the NFL season resolver
(_nfl_expected_completed_week), and the max graded week is taken WITHIN that current season only. The
board's own data-through / availability / source fingerprint come from the real consumer
(build_nfl_prop_streaks), not a reimplementation.

No network, no fetch, no paid call, no writes. Run on the box that has the data (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 diag_nfl_grading_receipt.py
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

import app

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


def main() -> int:
    print("=" * 78)
    print("NFL_AllPropResults.csv — READ-ONLY CONTENT RECEIPT (Item-5 reconciliation)")
    print("=" * 78)

    # 1-2. path / mtime / size
    print(f"resolved_path   : {PATH}")
    if not PATH.exists():
        print("STATUS          : FILE ABSENT -> surface fails closed (unavailable). This is the "
              "'genuinely missing' branch; keep the Wave unavailable.")
        return 2
    st = PATH.stat()
    print(f"mtime           : {_et(st.st_mtime)}  ({round((datetime.now().timestamp()-st.st_mtime)/3600,2)}h ago)")
    print(f"size_bytes      : {st.st_size}")

    try:
        df = pd.read_csv(PATH, low_memory=False)
    except Exception as exc:
        print(f"STATUS          : UNREADABLE ({type(exc).__name__}: {exc}) -> fails closed.")
        return 2
    print(f"total_rows      : {len(df)}")
    print(f"columns         : {', '.join(map(str, df.columns))}")

    # 4. current season from the RESOLVER (never max)
    try:
        expected_week, expected_season = app._nfl_expected_completed_week()
    except Exception as exc:
        expected_week, expected_season = None, None
        print(f"[WARN] season resolver error: {exc}")
    print(f"resolver_current_season : {expected_season}")
    print(f"resolver_completed_week : {expected_week}")

    # 3. seasons present with row counts
    if "Season" in df.columns:
        seasons = pd.to_numeric(df["Season"], errors="coerce")
        counts = seasons.dropna().astype(int).value_counts().sort_index()
        print("seasons_present :")
        for s, n in counts.items():
            marker = "  <- resolver current" if expected_season and int(s) == int(expected_season) else ""
            print(f"    {int(s)}: {int(n)} rows{marker}")
    else:
        print("seasons_present : (no Season column)")

    # restrict to current season for the per-season facts (NEVER global max)
    cur = df
    if "Season" in df.columns and expected_season:
        cur = df[pd.to_numeric(df["Season"], errors="coerce") == int(expected_season)].copy()
    print(f"current_season_rows : {len(cur)}")

    # 5. current-season max graded week (within current season only)
    if "Week" in cur.columns and len(cur):
        wk = pd.to_numeric(cur["Week"], errors="coerce").dropna()
        print(f"current_season_max_week : {int(wk.max()) if not wk.empty else 'n/a'}  "
              f"(weeks present: {sorted(set(wk.astype(int)))[:25]})")
    else:
        print("current_season_max_week : n/a")

    # 6. latest current-season game date
    date_col = next((c for c in _DATE_COLS if c in cur.columns), None)
    if date_col and len(cur):
        dts = pd.to_datetime(cur[date_col], errors="coerce").dropna()
        print(f"latest_current_game_date : {dts.max() if not dts.empty else 'n/a'} (col {date_col!r})")
    else:
        print(f"latest_current_game_date : n/a (no date column among {_DATE_COLS})")

    # 7. graded / pending / malformed (current season)
    status_col = next((c for c in _STATUS_COLS if c in cur.columns), None)
    rv = pd.to_numeric(cur["ResultValue"], errors="coerce") if "ResultValue" in cur.columns else pd.Series([], dtype=float)
    ident_ok = cur["Player"].astype(str).str.strip().ne("") if "Player" in cur.columns else pd.Series([True] * len(cur))
    graded = int((rv.notna() & ident_ok.reindex(rv.index, fill_value=True)).sum()) if len(rv) else 0
    pending = int((rv.isna() & ident_ok.reindex(rv.index, fill_value=True)).sum()) if len(rv) else 0
    malformed = int((~ident_ok).sum()) if "Player" in cur.columns else 0
    print(f"graded_rows     : {graded}  (finite ResultValue + identity, current season)")
    print(f"pending_rows    : {pending}  (identity present, result not yet in)")
    print(f"malformed_rows  : {malformed}  (blank identity)")
    if status_col:
        vc = cur[status_col].astype(str).str.strip().value_counts().head(8)
        print(f"status_col {status_col!r}: {dict(vc)}")

    # 8. duplicate / conflicting identities (current season)
    key = [c for c in _IDENTITY if c in cur.columns]
    if key and len(cur):
        dmask = cur.duplicated(subset=key, keep=False)
        dups = int(dmask.sum())
        conflicts = 0
        if dups and "ResultValue" in cur.columns:
            for _, g in cur[dmask].groupby(key, dropna=False):
                if pd.to_numeric(g["ResultValue"], errors="coerce").dropna().nunique() > 1:
                    conflicts += 1
        print(f"identity_key    : {key}")
        print(f"duplicate_rows  : {dups}  (same identity key)")
        print(f"conflicting_ids : {conflicts}  (same key, differing ResultValue)")
    else:
        print("identity_key    : (insufficient columns)")

    # 9-11. board data-through / availability / source fingerprint (the REAL consumer)
    try:
        meta = app.build_nfl_prop_streaks(limit=60)
    except Exception as exc:
        print(f"[WARN] build_nfl_prop_streaks error: {exc}")
        meta = {}
    print("-" * 78)
    print(f"board_through_season : {meta.get('through_season')}")
    print(f"board_through_week   : {meta.get('through_week')}")
    print(f"board_through_label  : {meta.get('through_label')!r}")
    print(f"board_expected       : season={meta.get('expected_season')} week={meta.get('expected_week')}")
    print(f"board_available      : {not meta.get('unavailable', False)}  "
          f"(unavailable_reason={meta.get('unavailable_reason')!r}; rows={len(meta.get('rows') or [])}; "
          f"pending={meta.get('pending')}; stale_season={meta.get('stale_season')})")
    print(f"board_source_fingerprint : source_updated={meta.get('source_updated')!r}; "
          f"graded_mtime={_et(st.st_mtime)}")

    print("=" * 78)
    print("RECONCILE: if resolver_current_season=2026 and current_season_max_week≈6 with graded_rows in the")
    print("thousands and board_available=True, the 'stale Wk18' claim is OBSOLETE -> correct the doc. If")
    print("current season rows are absent (board unavailable, current_season_ungraded), the surface stays")
    print("unavailable and THAT becomes the active P0 before any explainer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
