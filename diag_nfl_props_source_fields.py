"""
Read-only Phase-1 source-field confirmation for the NFL capture-precision correction
(incident 2026-10-24, defect #2 forward fix). NO write, NO network, NO paid request.

The capture (capture_nfl_prop_lines.py) reads data/props/NFL_Props.csv. Before adding a three-clock
capture (SourceUpdatedAtUTC / BKCapturedAtUTC / EventCommenceAtUTC) we must confirm what the LIVE feed
actually persists. Code review shows fetch_player_props.build_dataframe writes ordered_columns WITHOUT a
commence/kickoff time or an event id (it keeps LastUpdated = book update time). This probe confirms that on
the live artifact and checks the schedule for any kickoff-time field -- WITHOUT inferring or fabricating.

Reports:
  * NFL_Props.csv: columns, presence of CommenceTime/EventId/LastUpdated, a sanitized sample (no secrets);
  * load_nfl_schedule(): columns + whether any carries an intraday kickoff time (vs a date only);
  * a verdict: whether a tz-aware kickoff is AVAILABLE to the capture today, or must be plumbed from the
    fetcher (provider payload has it) before the capture fix can record EventCommenceAtUTC.

Gate: if kickoff is unavailable, STOP -- do not fabricate it from the schedule without an explicit
reconciliation contract.

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_props_source_fields.py
"""
from __future__ import annotations

import hashlib
import os

import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
PROPS = app.DATA_DIR / "props" / "NFL_Props.csv"
_KICK_HINTS = ("commence", "kickoff", "start", "time", "datetime")


def _sha(p):
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return "n/a"


def _looks_intraday(series: pd.Series) -> bool:
    """True if the column's values carry a time-of-day (not just a date)."""
    s = series.dropna().astype(str).head(200)
    for v in s:
        if any(tok in v for tok in ("T", ":")) and any(ch.isdigit() for ch in v):
            # has a 'T' or ':' with digits -> likely a timestamp, not a bare date
            if len(v) > 10:
                return True
    return False


def main() -> int:
    print("=" * 88)
    print("NFL CAPTURE-PRECISION PHASE-1 SOURCE-FIELD CONFIRMATION (read-only)")
    print("=" * 88)
    # ---- props feed --------------------------------------------------------------------------------
    print(f"PROPS FEED: {PROPS}")
    props_has_commence = props_has_eventid = props_has_lastupdated = False
    if not PROPS.exists():
        print("  ABSENT (no current props feed; off-slate?)")
    else:
        st = os.stat(PROPS)
        print(f"  sha={_sha(PROPS)} size={st.st_size} rows~")
        try:
            df = pd.read_csv(PROPS, low_memory=False)
        except Exception as exc:
            print(f"  UNREADABLE: {exc}"); return 2
        cols = list(df.columns)
        print(f"  rows={len(df)}  columns({len(cols)}): {', '.join(map(str, cols))}")
        commence_cols = [c for c in cols if any(h in str(c).lower() for h in _KICK_HINTS)]
        props_has_commence = any(c for c in cols if "commence" in str(c).lower() or "kickoff" in str(c).lower())
        props_has_eventid = any(str(c).lower() in ("eventid", "event_id", "id") for c in cols)
        props_has_lastupdated = any("lastupdated" in str(c).lower() or "last_update" in str(c).lower() for c in cols)
        print(f"  CommenceTime/kickoff column present : {props_has_commence}  (time-ish cols: {commence_cols})")
        print(f"  EventId column present              : {props_has_eventid}")
        print(f"  LastUpdated (book update time)      : {props_has_lastupdated}")
        for c in commence_cols:
            print(f"    '{c}' intraday-time present: {_looks_intraday(df[c])}  sample={df[c].dropna().astype(str).head(2).tolist()}")
        if props_has_lastupdated:
            lu = next(c for c in cols if "lastupdated" in str(c).lower() or "last_update" in str(c).lower())
            print(f"    '{lu}' intraday-time present: {_looks_intraday(df[lu])}  sample={df[lu].dropna().astype(str).head(2).tolist()}")

    # ---- schedule ----------------------------------------------------------------------------------
    print("-" * 88)
    print("SCHEDULE: load_nfl_schedule()")
    sched_kickoff = False
    try:
        sch = app.load_nfl_schedule()
        cols = list(sch.columns)
        print(f"  rows={len(sch)}  columns({len(cols)}): {', '.join(map(str, cols))}")
        for c in cols:
            if any(h in str(c).lower() for h in _KICK_HINTS):
                intr = _looks_intraday(sch[c])
                print(f"    time-ish col '{c}': intraday={intr}  sample={sch[c].dropna().astype(str).head(2).tolist()}")
                sched_kickoff = sched_kickoff or intr
    except Exception as exc:
        print(f"  schedule unavailable: {exc}")

    # ---- verdict -----------------------------------------------------------------------------------
    print("=" * 88)
    kickoff_available = bool(props_has_commence) or sched_kickoff
    print("VERDICT:")
    print(f"  tz-aware kickoff available to the CAPTURE today: {kickoff_available}")
    if props_has_commence:
        print("  -> props feed already carries a commence/kickoff column; the capture can record "
              "EventCommenceAtUTC directly.")
    elif sched_kickoff:
        print("  -> props feed lacks kickoff, but the SCHEDULE carries an intraday kickoff -> requires an "
              "EXPLICIT reconciliation contract (event-id/team-date join) before use; do not infer silently.")
    else:
        print("  -> kickoff is NOT persisted anywhere the capture reads. STOP: the fetcher "
              "(fetch_player_props.build_dataframe) must first persist CommenceTime (UTC) + EventId into "
              "NFL_Props.csv (the provider payload already has event.commence_time + event.id). Only then "
              "can the capture record EventCommenceAtUTC. No schedule inference without a reconciliation "
              "contract; no fabrication.")
    print(f"  LastUpdated (SourceUpdatedAtUTC candidate) present in props feed: {props_has_lastupdated}")
    print("  BKCapturedAtUTC is always available (record datetime.now(timezone.utc) at capture).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
