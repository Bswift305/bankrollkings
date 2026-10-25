"""
Read-only post-deploy verification + receipts for the NFL capture-precision correction
(incident 2026-10-24, Commits 1-2). NO write, NO network, NO paid request.

Run AFTER the next NORMAL scheduled fetch+capture has run (do not spend credits to populate columns). It
confirms: the props feed now exposes the provider clocks; the archive carries the v2 precision schema and
preserves/classifies legacy rows; observation ids are unique (idempotency proxy); and the Wave is STILL
unavailable (not repointed). Player names are redacted to initials in the sample.

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/verify_nfl_capture_precision.py
"""
from __future__ import annotations

import hashlib
import os
import re
import stat as statmod
from datetime import datetime, timezone

import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
PROPS = app.DATA_DIR / "props" / "NFL_Props.csv"
ARCHIVE = app.DATA_DIR / "tracking" / "NFL_PropLines_Archive.csv"
_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _redact(name):
    t = str(name or "").split()
    return (t[0][:1] + "." + t[-1][:1] + ".") if len(t) >= 2 else "?"


def _vc(series):
    try:
        return dict(series.astype(str).str.strip().replace("", "(blank)").value_counts().head(8))
    except Exception:
        return {}


def main() -> int:
    print("=" * 84)
    print("NFL CAPTURE-PRECISION POST-DEPLOY VERIFICATION (read-only receipts)")
    print("=" * 84)
    # ---- props feed ----
    print(f"PROPS FEED: {PROPS}")
    if not PROPS.exists():
        print("  ABSENT (off-slate or no fetch yet)")
    else:
        df = pd.read_csv(PROPS, low_memory=False)
        for c in ("EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC"):
            present = c in df.columns
            sample = df[c].dropna().astype(str).head(1).tolist() if present else []
            utc_ok = _UTC_Z.match(sample[0]) is not None if (sample and c != "EventId") else ("n/a" if c == "EventId" else False)
            print(f"  {c}: present={present} sample={sample} canonical_utc={utc_ok}")

    # ---- archive ----
    print("-" * 84)
    print(f"ARCHIVE: {ARCHIVE}")
    if not ARCHIVE.exists():
        print("  ABSENT (no capture yet)")
    else:
        st = os.stat(ARCHIVE)
        with open(ARCHIVE, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()[:16]
        print(f"  sha={sha} size={st.st_size} mtime={datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')} perms={statmod.filemode(st.st_mode)}")
        a = pd.read_csv(ARCHIVE, low_memory=False)
        print(f"  rows={len(a)}  columns={len(a.columns)}")
        if "SchemaVersion" in a.columns:
            print(f"  SchemaVersion: {_vc(a['SchemaVersion'])}")
        if "TemporalEligibility" in a.columns:
            print(f"  TemporalEligibility: {_vc(a['TemporalEligibility'])}")
        v2 = a[a.get("SchemaVersion").astype(str) == "nfl_proplines_v2"] if "SchemaVersion" in a.columns else a.iloc[0:0]
        legacy = a[a.get("SchemaVersion").astype(str) == "nfl_proplines_v1"] if "SchemaVersion" in a.columns else a.iloc[0:0]
        print(f"  v2 rows={len(v2)}  legacy v1 rows={len(legacy)}")
        if len(v2) and "ObservationId" in v2.columns:
            dups = int(v2["ObservationId"].duplicated().sum())
            print(f"  v2 ObservationId unique: {dups == 0}  (duplicates={dups})  [idempotency proxy]")
        if len(legacy) and "TemporalEligibility" in legacy.columns:
            lt = set(legacy["TemporalEligibility"].astype(str))
            print(f"  legacy v1 TemporalEligibility values: {sorted(lt)}  "
                  f"(expected only TEMPORAL_PRECISION_INSUFFICIENT)")
        if len(v2):
            cols = [c for c in ("Stat", "Line", "EventCommenceAtUTC", "BKCapturedAtUTC",
                                "TemporalEligibility", "ObservationId") if c in v2.columns]
            r = v2.iloc[0]
            print("  redacted sample v2 observation:")
            print(f"    player={_redact(r.get('Player'))}  " + "  ".join(f"{c}={r.get(c)}" for c in cols))

    # ---- Wave still unavailable ----
    print("-" * 84)
    try:
        meta = app.build_nfl_prop_streaks(limit=5)
        print(f"WAVE: available={not meta.get('unavailable', False)} reason={meta.get('unavailable_reason')!r} "
              f"(expected unavailable -- NOT repointed in this correction)")
    except Exception as exc:
        print(f"WAVE: error {exc}")
    print("=" * 84)
    print("Note: new columns populate only from fetches/captures that ran AFTER the Commit-1/2 deploy; "
          "earlier legacy rows stay TEMPORAL_PRECISION_INSUFFICIENT by design.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
